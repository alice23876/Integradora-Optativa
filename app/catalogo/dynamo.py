"""Catálogo sobre DynamoDB (boto3).

Reglas de oro que sigue este módulo:
  * NUNCA se hace Scan completo: todo es Query por índice o Scan con `Limit` paginado.
  * Los cursores son el LastEvaluatedKey codificado (el cliente no ve la estructura).
  * Operaciones multi-ítem (stock de varias variantes, reseña + promedio, SKU único)
    usan TransactWriteItems → todo o nada.
  * Un cliente boto3 *resource* por hilo (los resources no son thread-safe y la UI
    ejecuta las consultas en un pool de hilos).
"""
from __future__ import annotations

import functools
import logging
import threading
import time
from collections import defaultdict
from decimal import Decimal
from typing import Any, Callable, Iterable

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError

from ..errors import (ErrorConexion, ErrorConflicto, ErrorMarketplace, ErrorNoEncontrado, ErrorStock)
from ..models import (Categoria, EstadoConexion, Pagina, Producto, ProductoResumen, Resena, Variante)
from ..util import (a_iso, bucket_busqueda, codificar_cursor, de_iso, decodificar_cursor, normalizar, utcnow)
from .base import CatalogoBase
from .esquema import CLAVES_CURSOR, T_CATEGORIAS, T_PRODUCTOS, T_RESENAS, T_VARIANTES

log = logging.getLogger(__name__)

MAX_EVALUADOS = 3000          # tope de ítems leídos por petición cuando el filtro descarta mucho
MAX_TRANSACCION = 100         # límite de DynamoDB por TransactWriteItems


# =============================================================================== conversiones
def _entero(v: Any, defecto: int = 0) -> int:
    return int(v) if v is not None else defecto


def _decimal(v: Any) -> Decimal | None:
    return None if v is None else Decimal(str(v))


def _limpiar(item: dict[str, Any]) -> dict[str, Any]:
    """Python → DynamoDB: descarta None y cadenas vacías, floats → Decimal."""
    salida: dict[str, Any] = {}
    for k, v in item.items():
        if v is None or v == "":
            continue
        salida[k] = Decimal(str(v)) if isinstance(v, float) else v
    return salida


def _combinar(*condiciones):
    resultado = None
    for c in condiciones:
        if c is not None:
            resultado = c if resultado is None else resultado & c
    return resultado


def _resumen(i: dict[str, Any]) -> ProductoResumen:
    n = _entero(i.get("num_resenas"))
    suma = float(i.get("suma_calificacion", 0))
    return ProductoResumen(
        id_producto=i["id_producto"], titulo=i["titulo"], id_categoria=i["id_categoria"],
        id_vendedor=_entero(i["id_vendedor"]), marca=i.get("marca", ""), estatus=i.get("estatus", "ACTIVO"),
        fecha_creacion=de_iso(i.get("fecha_creacion")), precio_desde=_decimal(i.get("precio_desde")),
        calificacion_promedio=round(suma / n, 2) if n else None, num_resenas=n)


def _variante(i: dict[str, Any]) -> Variante:
    return Variante(
        id_variante=i["id_variante"], id_producto=i["id_producto"], sku=i["sku"],
        precio=Decimal(str(i["precio"])), cantidad_stock=_entero(i.get("cantidad_stock")),
        atributos={str(k): str(v) for k, v in (i.get("atributos") or {}).items()},
        estatus=i.get("estatus", "ACTIVO"))


def _resena(i: dict[str, Any]) -> Resena:
    return Resena(
        id_resena=i.get("id_resena", ""), id_producto=i["id_producto"], id_usuario=_entero(i["id_usuario"]),
        calificacion=_entero(i["calificacion"]), comentario=i.get("comentario", ""),
        nombre_usuario=i.get("nombre_usuario", ""), fecha_resena=de_iso(i.get("fecha_resena")))


def _item_producto(p: Producto) -> dict[str, Any]:
    tl = normalizar(p.titulo)
    return _limpiar({
        "id_producto": p.id_producto, "id_vendedor": int(p.id_vendedor), "id_categoria": p.id_categoria,
        "titulo": p.titulo, "titulo_lower": tl, "bucket_busqueda": bucket_busqueda(tl),
        "descripcion": p.descripcion, "marca": p.marca, "estatus": p.estatus,
        "fecha_creacion": a_iso(p.fecha_creacion or utcnow()), "precio_desde": p.precio_desde,
        "suma_calificacion": 0, "num_resenas": 0})


def _item_variante(v: Variante) -> dict[str, Any]:
    return _limpiar({
        "id_variante": v.id_variante, "id_producto": v.id_producto, "sku": v.sku, "precio": v.precio,
        "cantidad_stock": int(v.cantidad_stock), "atributos": dict(v.atributos), "estatus": v.estatus})


# =============================================================================== traducción de errores
def _desde_client_error(exc: ClientError) -> ErrorMarketplace:
    codigo = exc.response.get("Error", {}).get("Code", "")
    mensaje = exc.response.get("Error", {}).get("Message", str(exc))
    if codigo == "ResourceNotFoundException":
        return ErrorConexion("Falta una tabla o índice de DynamoDB. Ejecuta scripts/crear_tablas_dynamodb.py "
                             f"(detalle: {mensaje})")
    if codigo in {"AccessDeniedException", "UnrecognizedClientException", "InvalidSignatureException",
                  "ExpiredTokenException", "ExpiredToken", "InvalidClientTokenId", "UnauthorizedOperation"}:
        return ErrorConexion(f"AWS rechazó las credenciales o permisos ({codigo}). Revisa tu perfil/rol de IAM.")
    if codigo in {"ProvisionedThroughputExceededException", "ThrottlingException", "RequestLimitExceeded"}:
        return ErrorConexion("DynamoDB está limitando las peticiones. Intenta de nuevo en unos segundos.")
    return ErrorConexion(f"Error de DynamoDB ({codigo}): {mensaje}")


def _traducir(fn: Callable) -> Callable:
    @functools.wraps(fn)
    def envoltura(self, *args, **kwargs):
        try:
            return fn(self, *args, **kwargs)
        except ErrorMarketplace:
            raise
        except ClientError as exc:
            raise _desde_client_error(exc) from exc
        except BotoCoreError as exc:
            raise ErrorConexion(f"No se pudo conectar con DynamoDB: {exc}") from exc

    return envoltura


# =============================================================================== catálogo
class CatalogoDynamo(CatalogoBase):
    def __init__(self, region: str = "us-east-1", prefijo: str = "", endpoint: str | None = None):
        self._region = region
        self._endpoint = endpoint
        self._local = threading.local()
        self.t_categorias = f"{prefijo}{T_CATEGORIAS}"
        self.t_productos = f"{prefijo}{T_PRODUCTOS}"
        self.t_variantes = f"{prefijo}{T_VARIANTES}"
        self.t_resenas = f"{prefijo}{T_RESENAS}"

    # ------------------------------------------------------------------ infraestructura
    @property
    def _db(self):
        db = getattr(self._local, "db", None)
        if db is None:
            sesion = boto3.session.Session(region_name=self._region)
            db = sesion.resource(
                "dynamodb", endpoint_url=self._endpoint,
                config=BotoConfig(retries={"max_attempts": 6, "mode": "standard"}, connect_timeout=5,
                                  read_timeout=15, max_pool_connections=20))
            self._local.db = db
        return db

    def _t(self, nombre: str):
        return self._db.Table(nombre)

    @property
    def _cliente(self):
        return self._db.meta.client

    def _leer(self, tabla: str, *, indice: str | None = None, clave=None, filtro=None, adelante: bool = True,
              limite: int, inicio: dict | None = None, claves_cursor: tuple[str, ...],
              sobrelectura: int = 0, max_evaluados: int = MAX_EVALUADOS) -> tuple[list[dict], dict | None]:
        """Lee hasta `limite` ítems que pasen el filtro. Devuelve (ítems, última_clave|None).
        `última_clave` != None ⇒ aún puede haber más resultados."""
        t = self._t(tabla)
        items: list[dict] = []
        evaluados = 0
        start = inicio
        while True:
            faltan = limite - len(items)
            params: dict[str, Any] = {"Limit": max(faltan, sobrelectura) if filtro is not None else faltan}
            if indice:
                params["IndexName"] = indice
            if clave is not None:
                params["KeyConditionExpression"] = clave
            if filtro is not None:
                params["FilterExpression"] = filtro
            if not adelante:
                params["ScanIndexForward"] = False
            if start:
                params["ExclusiveStartKey"] = start
            resp = t.query(**params) if clave is not None else t.scan(**params)
            obtenidos = resp.get("Items", [])
            evaluados += resp.get("ScannedCount", len(obtenidos))
            lek = resp.get("LastEvaluatedKey")
            if len(obtenidos) > faltan:           # sobrelectura: nos quedamos solo con lo necesario
                obtenidos = obtenidos[:faltan]
                items += obtenidos
                ultimo = obtenidos[-1]
                return items, {k: ultimo[k] for k in claves_cursor}
            items += obtenidos
            if not lek:
                return items, None
            start = lek
            if len(items) >= limite or evaluados >= max_evaluados:
                return items, lek

    def _batch_get(self, tabla: str, atributo_clave: str, ids: Iterable[str]) -> list[dict]:
        ids = list({i for i in ids})
        resultado: list[dict] = []
        for k in range(0, len(ids), 100):
            pendientes = {tabla: {"Keys": [{atributo_clave: i} for i in ids[k:k + 100]]}}
            intentos = 0
            while pendientes and intentos < 8:
                resp = self._db.batch_get_item(RequestItems=pendientes)
                resultado += resp.get("Responses", {}).get(tabla, [])
                pendientes = resp.get("UnprocessedKeys") or {}
                if pendientes:
                    intentos += 1
                    time.sleep(0.05 * 2 ** intentos)
        return resultado

    # ------------------------------------------------------------------ categorías
    def listar_categorias(self) -> list[Categoria]:
        items, start = [], None
        t = self._t(self.t_categorias)
        while True:
            resp = t.scan(**({"ExclusiveStartKey": start} if start else {}))
            items += resp.get("Items", [])
            start = resp.get("LastEvaluatedKey")
            if not start:
                break
        return [Categoria(id_categoria=i["id_categoria"], nombre=i["nombre"], slug=i["slug"],
                          id_categoria_padre=i.get("id_categoria_padre"), estatus=i.get("estatus", "ACTIVO"))
                for i in items]

    def guardar_categoria(self, categoria: Categoria, *, crear: bool) -> Categoria:
        # El slug debe ser único. La tabla es pequeña, así que se verifica leyéndola completa.
        for c in self.listar_categorias():
            if c.slug == categoria.slug and c.id_categoria != categoria.id_categoria:
                raise ErrorConflicto(f"Ya existe una categoría con el slug «{categoria.slug}».")
        item = _limpiar({"id_categoria": categoria.id_categoria, "id_categoria_padre": categoria.id_categoria_padre,
                         "nombre": categoria.nombre, "slug": categoria.slug, "estatus": categoria.estatus})
        condicion = "attribute_not_exists(id_categoria)" if crear else "attribute_exists(id_categoria)"
        try:
            self._t(self.t_categorias).put_item(Item=item, ConditionExpression=condicion)
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise (ErrorConflicto("La categoría ya existe.") if crear
                       else ErrorNoEncontrado("La categoría no existe.")) from exc
            raise
        return categoria

    # ------------------------------------------------------------------ productos
    def listar_productos(self, *, ids_categoria=None, q=None, en_cualquier_parte=False, id_vendedor=None,
                         solo_activos=True, cursor=None, limite=24) -> Pagina[ProductoResumen]:
        cur = decodificar_cursor(cursor) or {}
        q = normalizar(q) or None
        activo = Attr("estatus").eq("ACTIVO") if solo_activos else None

        def pagina(items, lek) -> Pagina[ProductoResumen]:
            return Pagina([_resumen(i) for i in items], codificar_cursor({"k": lek}) if lek else None)

        if id_vendedor is not None:
            items, lek = self._leer(self.t_productos, indice="gsi_vendedor",
                                    clave=Key("id_vendedor").eq(int(id_vendedor)), filtro=activo, adelante=False,
                                    limite=limite, inicio=cur.get("k"), claves_cursor=CLAVES_CURSOR["gsi_vendedor"])
            return pagina(items, lek)

        if ids_categoria:
            filtro = _combinar(activo, Attr("titulo_lower").contains(q) if q else None)
            pos, clave_actual = int(cur.get("c", 0)), cur.get("k")
            items: list[dict] = []
            while pos < len(ids_categoria) and len(items) < limite:
                lote, lek = self._leer(
                    self.t_productos, indice="gsi_categoria", clave=Key("id_categoria").eq(ids_categoria[pos]),
                    filtro=filtro, adelante=False, limite=limite - len(items), inicio=clave_actual,
                    claves_cursor=CLAVES_CURSOR["gsi_categoria"], sobrelectura=200 if q else 0)
                items += lote
                if lek is None:
                    pos, clave_actual = pos + 1, None   # categoría agotada → siguiente
                else:
                    clave_actual = lek                   # página llena o tope de lectura
                    break
            hay_mas = pos < len(ids_categoria)
            return Pagina([_resumen(i) for i in items],
                          codificar_cursor({"c": pos, "k": clave_actual}) if hay_mas else None)

        if q and not en_cualquier_parte:
            clave = Key("bucket_busqueda").eq(bucket_busqueda(q)) & Key("titulo_lower").begins_with(q)
            items, lek = self._leer(self.t_productos, indice="gsi_busqueda", clave=clave, filtro=activo,
                                    limite=limite, inicio=cur.get("k"), claves_cursor=CLAVES_CURSOR["gsi_busqueda"])
            return pagina(items, lek)

        filtro = _combinar(activo, Attr("titulo_lower").contains(q) if q else None)
        items, lek = self._leer(self.t_productos, filtro=filtro, limite=limite, inicio=cur.get("k"),
                                claves_cursor=CLAVES_CURSOR["tabla_productos"],
                                sobrelectura=500 if q else 0)
        return pagina(items, lek)

    def obtener_producto(self, id_producto: str) -> Producto | None:
        item = self._t(self.t_productos).get_item(Key={"id_producto": id_producto}).get("Item")
        if not item:
            return None
        base = _resumen(item)
        return Producto(**{**base.__dict__}, descripcion=item.get("descripcion", ""),
                        variantes=self.variantes_de_producto(id_producto))

    def obtener_productos(self, ids: Iterable[str]) -> dict[str, ProductoResumen]:
        return {i["id_producto"]: _resumen(i) for i in self._batch_get(self.t_productos, "id_producto", ids)}

    def crear_producto(self, *, id_producto, id_vendedor, id_categoria, titulo, descripcion, marca,
                       estatus="ACTIVO") -> Producto:
        p = Producto(id_producto=id_producto, titulo=titulo, id_categoria=id_categoria,
                     id_vendedor=int(id_vendedor), marca=marca, estatus=estatus, fecha_creacion=utcnow(),
                     descripcion=descripcion)
        try:
            self._t(self.t_productos).put_item(Item=_item_producto(p),
                                               ConditionExpression="attribute_not_exists(id_producto)")
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ErrorConflicto("El producto ya existe.") from exc
            raise
        return p

    def actualizar_producto(self, id_producto: str, campos: dict) -> Producto:
        permitidos = {"titulo", "descripcion", "marca", "id_categoria", "estatus"}
        valores = {k: v for k, v in campos.items() if k in permitidos}
        if "titulo" in valores:
            tl = normalizar(valores["titulo"])
            valores["titulo_lower"], valores["bucket_busqueda"] = tl, bucket_busqueda(tl)
        if valores:
            sets, nombres, vals = [], {}, {}
            for n, (k, v) in enumerate(valores.items()):
                nombres[f"#n{n}"], vals[f":v{n}"] = k, v
                sets.append(f"#n{n} = :v{n}")
            try:
                self._t(self.t_productos).update_item(
                    Key={"id_producto": id_producto}, UpdateExpression="SET " + ", ".join(sets),
                    ExpressionAttributeNames=nombres, ExpressionAttributeValues=vals,
                    ConditionExpression="attribute_exists(id_producto)")
            except ClientError as exc:
                if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                    raise ErrorNoEncontrado("El producto no existe.") from exc
                raise
        p = self.obtener_producto(id_producto)
        if not p:
            raise ErrorNoEncontrado("El producto no existe.")
        return p

    def eliminar_producto_fisico(self, id_producto: str) -> None:
        variantes = self.variantes_de_producto(id_producto)
        with self._t(self.t_variantes).batch_writer() as lote:
            for v in variantes:
                lote.delete_item(Key={"id_variante": v.id_variante})
                lote.delete_item(Key={"id_variante": f"SKU#{v.sku}"})
        self._t(self.t_productos).delete_item(Key={"id_producto": id_producto})

    # ------------------------------------------------------------------ variantes
    def obtener_variantes(self, ids: Iterable[str]) -> dict[str, Variante]:
        return {i["id_variante"]: _variante(i) for i in self._batch_get(self.t_variantes, "id_variante", ids)
                if "id_producto" in i}

    def variantes_de_producto(self, id_producto: str) -> list[Variante]:
        t = self._t(self.t_variantes)
        items, start = [], None
        while True:
            params: dict[str, Any] = {"IndexName": "gsi_producto", "KeyConditionExpression": Key("id_producto").eq(id_producto)}
            if start:
                params["ExclusiveStartKey"] = start
            resp = t.query(**params)
            items += resp.get("Items", [])
            start = resp.get("LastEvaluatedKey")
            if not start:
                break
        return sorted((_variante(i) for i in items), key=lambda v: v.sku)

    def _recalcular_precio_desde(self, id_producto: str) -> None:
        precios = [v.precio for v in self.variantes_de_producto(id_producto) if v.estatus == "ACTIVO"]
        t = self._t(self.t_productos)
        try:
            if precios:
                t.update_item(Key={"id_producto": id_producto}, UpdateExpression="SET precio_desde = :p",
                              ConditionExpression="attribute_exists(id_producto)",
                              ExpressionAttributeValues={":p": min(precios)})
            else:
                t.update_item(Key={"id_producto": id_producto}, UpdateExpression="REMOVE precio_desde",
                              ConditionExpression="attribute_exists(id_producto)")
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise

    def crear_variante(self, *, id_variante, id_producto, sku, precio, cantidad_stock, atributos,
                       estatus="ACTIVO") -> Variante:
        v = Variante(id_variante, id_producto, sku, Decimal(str(precio)), int(cantidad_stock), dict(atributos), estatus)
        try:
            self._cliente.transact_write_items(TransactItems=[
                {"Put": {"TableName": self.t_variantes, "Item": _item_variante(v),
                         "ConditionExpression": "attribute_not_exists(id_variante)"}},
                # Candado de unicidad del SKU (ver catalogo/esquema.py)
                {"Put": {"TableName": self.t_variantes,
                         "Item": {"id_variante": f"SKU#{sku}", "id_variante_ref": id_variante},
                         "ConditionExpression": "attribute_not_exists(id_variante)"}},
            ])
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "TransactionCanceledException":
                raise ErrorConflicto(f"El SKU «{sku}» ya existe en el catálogo.") from exc
            raise
        self._recalcular_precio_desde(id_producto)
        return v

    def actualizar_variante(self, id_variante, *, precio=None, cantidad_stock=None, atributos=None,
                            estatus=None) -> Variante:
        campos = {"precio": precio, "cantidad_stock": cantidad_stock, "atributos": atributos, "estatus": estatus}
        sets, nombres, vals = [], {}, {}
        for n, (k, v) in enumerate((k, v) for k, v in campos.items() if v is not None):
            nombres[f"#n{n}"] = k
            vals[f":v{n}"] = Decimal(str(v)) if k == "precio" else v
            sets.append(f"#n{n} = :v{n}")
        if not sets:
            variantes = self.obtener_variantes([id_variante])
            if id_variante not in variantes:
                raise ErrorNoEncontrado("La variante no existe.")
            return variantes[id_variante]
        try:
            resp = self._t(self.t_variantes).update_item(
                Key={"id_variante": id_variante}, UpdateExpression="SET " + ", ".join(sets),
                ExpressionAttributeNames=nombres, ExpressionAttributeValues=vals,
                ConditionExpression="attribute_exists(id_producto)", ReturnValues="ALL_NEW")
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ErrorNoEncontrado("La variante no existe.") from exc
            raise
        v = _variante(resp["Attributes"])
        if precio is not None or estatus is not None:
            self._recalcular_precio_desde(v.id_producto)
        return v

    # ------------------------------------------------------------------ existencias
    def reservar_stock(self, items: list[tuple[str, int]]) -> None:
        agregado: dict[str, int] = defaultdict(int)
        for vid, q in items:
            agregado[vid] += int(q)
        ids = list(agregado)
        descontados: list[tuple[str, int]] = []   # grupos ya confirmados (por si un grupo posterior falla)
        for k in range(0, len(ids), MAX_TRANSACCION):
            grupo = ids[k:k + MAX_TRANSACCION]
            acciones = [{"Update": {
                "TableName": self.t_variantes, "Key": {"id_variante": vid},
                "UpdateExpression": "SET cantidad_stock = cantidad_stock - :q",
                "ConditionExpression": "attribute_exists(id_producto) AND #e = :act AND cantidad_stock >= :q",
                "ExpressionAttributeNames": {"#e": "estatus"},
                "ExpressionAttributeValues": {":q": agregado[vid], ":act": "ACTIVO"}}} for vid in grupo]
            try:
                self._cliente.transact_write_items(TransactItems=acciones)
            except Exception as exc:  # noqa: BLE001
                if descontados:
                    self.liberar_stock(descontados)   # todo o nada también entre grupos
                if isinstance(exc, ClientError) and exc.response["Error"]["Code"] == "TransactionCanceledException":
                    razones = exc.response.get("CancellationReasons") or []
                    fallan = [vid for vid, r in zip(grupo, razones) if r.get("Code") == "ConditionalCheckFailed"]
                    raise ErrorStock("Sin existencias suficientes.", ids_afectados=fallan or grupo) from exc
                raise
            descontados += [(vid, agregado[vid]) for vid in grupo]

    def liberar_stock(self, items: list[tuple[str, int]]) -> None:
        agregado: dict[str, int] = defaultdict(int)
        for vid, q in items:
            agregado[vid] += int(q)
        ids = list(agregado)
        for k in range(0, len(ids), MAX_TRANSACCION):
            self._cliente.transact_write_items(TransactItems=[{"Update": {
                "TableName": self.t_variantes, "Key": {"id_variante": vid},
                "UpdateExpression": "ADD cantidad_stock :q",
                "ConditionExpression": "attribute_exists(id_producto)",
                "ExpressionAttributeValues": {":q": agregado[vid]}}} for vid in ids[k:k + MAX_TRANSACCION]])

    # ------------------------------------------------------------------ reseñas
    def listar_resenas(self, id_producto, *, cursor, limite) -> Pagina[Resena]:
        cur = decodificar_cursor(cursor) or {}
        items, lek = self._leer(self.t_resenas, indice="lsi_fecha", clave=Key("id_producto").eq(id_producto),
                                adelante=False, limite=limite, inicio=cur.get("k"),
                                claves_cursor=CLAVES_CURSOR["lsi_fecha"])
        return Pagina([_resena(i) for i in items], codificar_cursor({"k": lek}) if lek else None)

    def obtener_resena(self, id_producto: str, id_usuario: int) -> Resena | None:
        item = self._t(self.t_resenas).get_item(
            Key={"id_producto": id_producto, "id_usuario": int(id_usuario)}).get("Item")
        return _resena(item) if item else None

    def crear_resena(self, resena: Resena) -> Resena:
        if resena.fecha_resena is None:
            resena.fecha_resena = utcnow()
        item = _limpiar({"id_producto": resena.id_producto, "id_usuario": int(resena.id_usuario),
                         "id_resena": resena.id_resena, "calificacion": int(resena.calificacion),
                         "comentario": resena.comentario, "nombre_usuario": resena.nombre_usuario,
                         "fecha_resena": a_iso(resena.fecha_resena)})
        try:
            self._cliente.transact_write_items(TransactItems=[
                {"Put": {"TableName": self.t_resenas, "Item": item,
                         "ConditionExpression": "attribute_not_exists(id_producto)"}},
                {"Update": {"TableName": self.t_productos, "Key": {"id_producto": resena.id_producto},
                            "UpdateExpression": "ADD num_resenas :uno, suma_calificacion :c",
                            "ConditionExpression": "attribute_exists(id_producto)",
                            "ExpressionAttributeValues": {":uno": 1, ":c": int(resena.calificacion)}}},
            ])
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "TransactionCanceledException":
                razones = exc.response.get("CancellationReasons") or []
                if len(razones) > 1 and razones[1].get("Code") == "ConditionalCheckFailed":
                    raise ErrorNoEncontrado("El producto no existe.") from exc
                raise ErrorConflicto("Ya reseñaste este producto.") from exc
            raise
        return resena

    # ------------------------------------------------------------------ operación
    def salud(self) -> list[EstadoConexion]:
        t0 = time.perf_counter()
        nombres = [self.t_productos, self.t_categorias, self.t_variantes, self.t_resenas]
        faltan, detalles = [], []
        try:
            for n in nombres:
                try:
                    d = self._cliente.describe_table(TableName=n)["Table"]
                    detalles.append(f"{n}≈{int(d.get('ItemCount', 0)):,}")
                except ClientError as exc:
                    if exc.response["Error"]["Code"] == "ResourceNotFoundException":
                        faltan.append(n)
                    else:
                        raise
        except (ClientError, BotoCoreError) as exc:
            return [EstadoConexion("DynamoDB", "NoSQL", False, str(exc)[:200], None,
                                   "productos, categorias, variantes_producto, resenas")]
        ms = round((time.perf_counter() - t0) * 1000, 1)
        region = f"{self._region}" + (f" · {self._endpoint}" if self._endpoint else "")
        if faltan:
            return [EstadoConexion("DynamoDB", "NoSQL", False,
                                   f"Faltan tablas: {', '.join(faltan)} → ejecuta scripts/crear_tablas_dynamodb.py",
                                   ms, "productos, categorias, variantes_producto, resenas")]
        return [EstadoConexion("DynamoDB", "NoSQL", True, f"{region} · " + ", ".join(detalles), ms,
                               "productos, categorias, variantes_producto, resenas")]

    def contar_productos_aprox(self) -> int:
        """ItemCount lo actualiza DynamoDB cada ~6 horas: es solo una aproximación."""
        return int(self._cliente.describe_table(TableName=self.t_productos)["Table"].get("ItemCount", 0))

    def insertar_masivo(self, categorias: list[Categoria], productos: list[Producto], progreso=None) -> None:
        with self._t(self.t_categorias).batch_writer() as lote:
            for c in categorias:
                lote.put_item(Item=_limpiar({"id_categoria": c.id_categoria, "id_categoria_padre": c.id_categoria_padre,
                                             "nombre": c.nombre, "slug": c.slug, "estatus": c.estatus}))
        total = len(productos)
        with self._t(self.t_productos).batch_writer() as lp, self._t(self.t_variantes).batch_writer() as lv:
            for n, p in enumerate(productos, 1):
                lp.put_item(Item=_item_producto(p))
                for v in p.variantes:
                    lv.put_item(Item=_item_variante(v))
                    lv.put_item(Item={"id_variante": f"SKU#{v.sku}", "id_variante_ref": v.id_variante})
                if progreso and n % 500 == 0:
                    progreso(n, total)
        if progreso:
            progreso(total, total)


for _nombre, _fn in list(vars(CatalogoDynamo).items()):
    if callable(_fn) and not _nombre.startswith("_"):
        setattr(CatalogoDynamo, _nombre, _traducir(_fn))
