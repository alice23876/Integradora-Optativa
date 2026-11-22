"""Catálogo en memoria (modo demo). Replica la semántica de CatalogoDynamo."""
from __future__ import annotations

import bisect
import threading
from collections import defaultdict
from decimal import Decimal
from typing import Iterable

from ..errors import ErrorConflicto, ErrorNoEncontrado, ErrorStock
from ..models import (Categoria, EstadoConexion, Pagina, Producto, ProductoResumen, Resena, Variante)
from ..util import a_iso, codificar_cursor, decodificar_cursor, normalizar, utcnow
from .base import CatalogoBase


class CatalogoMemoria(CatalogoBase):
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._categorias: dict[str, Categoria] = {}
        self._prod: dict[str, dict] = {}                  # id_producto → registro
        self._var: dict[str, Variante] = {}
        self._var_de_prod: dict[str, list[str]] = defaultdict(list)
        self._skus: set[str] = set()
        self._resenas: dict[tuple[str, int], Resena] = {}
        self._resenas_de_prod: dict[str, list[tuple[str, int]]] = defaultdict(list)
        # índices ordenados (equivalen a los GSI de DynamoDB)
        self._por_cat: dict[str, list[tuple[str, str]]] = defaultdict(list)   # (fecha_iso, id)
        self._por_vend: dict[int, list[tuple[str, str]]] = defaultdict(list)
        self._titulos: list[tuple[str, str]] = []                              # (titulo_lower, id)
        self._orden: list[str] = []                                            # feed (inserción)

    # ------------------------------------------------------------------ conversión
    def _resumen(self, r: dict) -> ProductoResumen:
        n = r["num_resenas"]
        return ProductoResumen(
            id_producto=r["id_producto"], titulo=r["titulo"], id_categoria=r["id_categoria"],
            id_vendedor=r["id_vendedor"], marca=r["marca"], estatus=r["estatus"],
            fecha_creacion=r["fecha_creacion"], precio_desde=r["precio_desde"],
            calificacion_promedio=round(r["suma_calificacion"] / n, 2) if n else None, num_resenas=n)

    def _recalcular_precio(self, id_producto: str) -> None:
        precios = [self._var[v].precio for v in self._var_de_prod[id_producto]
                   if self._var[v].estatus == "ACTIVO"]
        self._prod[id_producto]["precio_desde"] = min(precios) if precios else None

    # ------------------------------------------------------------------ categorías
    def listar_categorias(self) -> list[Categoria]:
        with self._lock:
            return list(self._categorias.values())

    def guardar_categoria(self, categoria: Categoria, *, crear: bool) -> Categoria:
        with self._lock:
            for c in self._categorias.values():
                if c.slug == categoria.slug and c.id_categoria != categoria.id_categoria:
                    raise ErrorConflicto(f"Ya existe una categoría con el slug «{categoria.slug}».")
            if crear and categoria.id_categoria in self._categorias:
                raise ErrorConflicto("La categoría ya existe.")
            if not crear and categoria.id_categoria not in self._categorias:
                raise ErrorNoEncontrado("La categoría no existe.")
            self._categorias[categoria.id_categoria] = categoria
            return categoria

    # ------------------------------------------------------------------ productos
    def _indexar(self, r: dict) -> None:
        clave = (a_iso(r["fecha_creacion"]), r["id_producto"])
        bisect.insort(self._por_cat[r["id_categoria"]], clave)
        bisect.insort(self._por_vend[r["id_vendedor"]], clave)
        bisect.insort(self._titulos, (r["titulo_lower"], r["id_producto"]))

    def _desindexar(self, r: dict) -> None:
        clave = (a_iso(r["fecha_creacion"]), r["id_producto"])
        for lista, k in ((self._por_cat[r["id_categoria"]], clave), (self._por_vend[r["id_vendedor"]], clave),
                         (self._titulos, (r["titulo_lower"], r["id_producto"]))):
            i = bisect.bisect_left(lista, k)
            if i < len(lista) and lista[i] == k:
                del lista[i]

    def listar_productos(self, *, ids_categoria=None, q=None, en_cualquier_parte=False, id_vendedor=None,
                         solo_activos=True, cursor=None, limite=24) -> Pagina[ProductoResumen]:
        q = normalizar(q) or None
        desplazamiento = int((decodificar_cursor(cursor) or {}).get("o", 0))
        with self._lock:
            if id_vendedor is not None:
                ids = [i for _, i in reversed(self._por_vend.get(id_vendedor, []))]
            elif ids_categoria:
                ids = [i for c in ids_categoria for _, i in reversed(self._por_cat.get(c, []))]
                if q:
                    ids = [i for i in ids if q in self._prod[i]["titulo_lower"]]
            elif q and not en_cualquier_parte:
                inicio = bisect.bisect_left(self._titulos, (q, ""))
                ids = []
                for tl, i in self._titulos[inicio:]:
                    if not tl.startswith(q):
                        break
                    ids.append(i)
            elif q:
                ids = [i for i in self._orden if q in self._prod[i]["titulo_lower"]]
            else:
                ids = self._orden
            if solo_activos:
                ids = [i for i in ids if self._prod[i]["estatus"] == "ACTIVO"]
            pagina = ids[desplazamiento:desplazamiento + limite]
            hay_mas = len(ids) > desplazamiento + limite
            return Pagina([self._resumen(self._prod[i]) for i in pagina],
                          codificar_cursor({"o": desplazamiento + limite}) if hay_mas else None)

    def obtener_producto(self, id_producto: str) -> Producto | None:
        with self._lock:
            r = self._prod.get(id_producto)
            if not r:
                return None
            base = self._resumen(r)
            return Producto(**{**base.__dict__}, descripcion=r["descripcion"],
                            variantes=self.variantes_de_producto(id_producto))

    def obtener_productos(self, ids: Iterable[str]) -> dict[str, ProductoResumen]:
        with self._lock:
            return {i: self._resumen(self._prod[i]) for i in set(ids) if i in self._prod}

    def crear_producto(self, *, id_producto, id_vendedor, id_categoria, titulo, descripcion, marca,
                       estatus="ACTIVO") -> Producto:
        with self._lock:
            if id_producto in self._prod:
                raise ErrorConflicto("El producto ya existe.")
            r = dict(id_producto=id_producto, id_vendedor=int(id_vendedor), id_categoria=id_categoria,
                     titulo=titulo, titulo_lower=normalizar(titulo), descripcion=descripcion, marca=marca,
                     estatus=estatus, fecha_creacion=utcnow(), precio_desde=None, suma_calificacion=0,
                     num_resenas=0)
            self._prod[id_producto] = r
            self._orden.append(id_producto)
            self._indexar(r)
            return self.obtener_producto(id_producto)  # type: ignore[return-value]

    def actualizar_producto(self, id_producto: str, campos: dict) -> Producto:
        permitidos = {"titulo", "descripcion", "marca", "id_categoria", "estatus"}
        with self._lock:
            r = self._prod.get(id_producto)
            if not r:
                raise ErrorNoEncontrado("El producto no existe.")
            self._desindexar(r)
            for k, v in campos.items():
                if k in permitidos:
                    r[k] = v
            r["titulo_lower"] = normalizar(r["titulo"])
            self._indexar(r)
            return self.obtener_producto(id_producto)  # type: ignore[return-value]

    def eliminar_producto_fisico(self, id_producto: str) -> None:
        with self._lock:
            r = self._prod.pop(id_producto, None)
            if r:
                self._desindexar(r)
                self._orden.remove(id_producto)
            for v in self._var_de_prod.pop(id_producto, []):
                var = self._var.pop(v, None)
                if var:
                    self._skus.discard(var.sku)

    # ------------------------------------------------------------------ variantes
    def obtener_variantes(self, ids: Iterable[str]) -> dict[str, Variante]:
        with self._lock:
            return {i: self._copiar(self._var[i]) for i in set(ids) if i in self._var}

    @staticmethod
    def _copiar(v: Variante) -> Variante:
        return Variante(**{**v.__dict__, "atributos": dict(v.atributos)})

    def variantes_de_producto(self, id_producto: str) -> list[Variante]:
        with self._lock:
            return sorted((self._copiar(self._var[i]) for i in self._var_de_prod.get(id_producto, [])),
                          key=lambda v: v.sku)

    def crear_variante(self, *, id_variante, id_producto, sku, precio, cantidad_stock, atributos,
                       estatus="ACTIVO") -> Variante:
        with self._lock:
            if id_producto not in self._prod:
                raise ErrorNoEncontrado("El producto no existe.")
            if sku in self._skus:
                raise ErrorConflicto(f"El SKU «{sku}» ya existe.")
            v = Variante(id_variante, id_producto, sku, Decimal(str(precio)), int(cantidad_stock),
                         dict(atributos), estatus)
            self._var[id_variante] = v
            self._var_de_prod[id_producto].append(id_variante)
            self._skus.add(sku)
            self._recalcular_precio(id_producto)
            return self._copiar(v)

    def actualizar_variante(self, id_variante, *, precio=None, cantidad_stock=None, atributos=None,
                            estatus=None) -> Variante:
        with self._lock:
            v = self._var.get(id_variante)
            if not v:
                raise ErrorNoEncontrado("La variante no existe.")
            if precio is not None:
                v.precio = Decimal(str(precio))
            if cantidad_stock is not None:
                v.cantidad_stock = int(cantidad_stock)
            if atributos is not None:
                v.atributos = dict(atributos)
            if estatus is not None:
                v.estatus = estatus
            self._recalcular_precio(v.id_producto)
            return self._copiar(v)

    # ------------------------------------------------------------------ existencias
    def reservar_stock(self, items: list[tuple[str, int]]) -> None:
        agregado: dict[str, int] = defaultdict(int)
        for vid, q in items:
            agregado[vid] += q
        with self._lock:
            fallan = [vid for vid, q in agregado.items()
                      if vid not in self._var or self._var[vid].estatus != "ACTIVO"
                      or self._var[vid].cantidad_stock < q]
            if fallan:
                raise ErrorStock("Sin existencias suficientes.", ids_afectados=fallan)
            for vid, q in agregado.items():
                self._var[vid].cantidad_stock -= q

    def liberar_stock(self, items: list[tuple[str, int]]) -> None:
        with self._lock:
            for vid, q in items:
                if vid in self._var:
                    self._var[vid].cantidad_stock += q

    # ------------------------------------------------------------------ reseñas
    def listar_resenas(self, id_producto, *, cursor, limite) -> Pagina[Resena]:
        desplazamiento = int((decodificar_cursor(cursor) or {}).get("o", 0))
        with self._lock:
            claves = sorted(self._resenas_de_prod.get(id_producto, []),
                            key=lambda k: self._resenas[k].fecha_resena, reverse=True)
            pag = [self._resenas[k] for k in claves[desplazamiento:desplazamiento + limite]]
            hay_mas = len(claves) > desplazamiento + limite
            return Pagina(pag, codificar_cursor({"o": desplazamiento + limite}) if hay_mas else None)

    def obtener_resena(self, id_producto: str, id_usuario: int) -> Resena | None:
        with self._lock:
            return self._resenas.get((id_producto, int(id_usuario)))

    def crear_resena(self, resena: Resena) -> Resena:
        clave = (resena.id_producto, int(resena.id_usuario))
        with self._lock:
            if resena.id_producto not in self._prod:
                raise ErrorNoEncontrado("El producto no existe.")
            if clave in self._resenas:
                raise ErrorConflicto("Ya reseñaste este producto.")
            if resena.fecha_resena is None:
                resena.fecha_resena = utcnow()
            self._resenas[clave] = resena
            self._resenas_de_prod[resena.id_producto].append(clave)
            r = self._prod[resena.id_producto]
            r["num_resenas"] += 1
            r["suma_calificacion"] += resena.calificacion
            return resena

    # ------------------------------------------------------------------ operación
    def salud(self) -> list[EstadoConexion]:
        return [EstadoConexion("Catálogo en memoria (demo)", "NoSQL", True,
                               f"{len(self._prod):,} productos · {len(self._var):,} variantes",
                               0.0, "productos, categorias, variantes_producto, resenas")]

    def contar_productos_aprox(self) -> int:
        return len(self._prod)

    def insertar_masivo(self, categorias: list[Categoria], productos: list[Producto], progreso=None) -> None:
        with self._lock:
            for c in categorias:
                self._categorias[c.id_categoria] = c
            for p in productos:
                r = dict(id_producto=p.id_producto, id_vendedor=int(p.id_vendedor), id_categoria=p.id_categoria,
                         titulo=p.titulo, titulo_lower=normalizar(p.titulo), descripcion=p.descripcion,
                         marca=p.marca, estatus=p.estatus, fecha_creacion=p.fecha_creacion or utcnow(),
                         precio_desde=p.precio_desde, suma_calificacion=0, num_resenas=0)
                self._prod[p.id_producto] = r
                self._orden.append(p.id_producto)
                for v in p.variantes:
                    self._var[v.id_variante] = self._copiar(v)
                    self._var_de_prod[p.id_producto].append(v.id_variante)
                    self._skus.add(v.sku)
            # índices ordenados: se construyen una sola vez (mucho más rápido que insort uno a uno)
            self._por_cat.clear(), self._por_vend.clear()
            for r in self._prod.values():
                clave = (a_iso(r["fecha_creacion"]), r["id_producto"])
                self._por_cat[r["id_categoria"]].append(clave)
                self._por_vend[r["id_vendedor"]].append(clave)
            for lista in list(self._por_cat.values()) + list(self._por_vend.values()):
                lista.sort()
            self._titulos = sorted((r["titulo_lower"], r["id_producto"]) for r in self._prod.values())
