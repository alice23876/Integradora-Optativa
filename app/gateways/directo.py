"""Gateway «directo»: orquesta las tres bases de datos desde Python.

Este archivo es, en la práctica, el **diseño de referencia del backend**: contiene las
reglas de negocio que cruzan bases de datos (no existen JOIN ni transacciones entre
DynamoDB y los dos MySQL):

  * checkout  → saga: reservar stock (DynamoDB, atómico) → crear pedido (MySQL B, transacción)
                → registrar pago (MySQL A). Si un paso falla, se compensa el anterior.
  * reseñas   → solo quien recibió el producto (MySQL B) puede reseñar (DynamoDB).
  * pedidos   → líneas enriquecidas con título/SKU (DynamoDB) tras leerlas de MySQL B.

⚠ En producción esta clase debe vivir en el servidor, NO en la app de escritorio:
un cliente con credenciales de MySQL/AWS es un riesgo de seguridad (cualquiera podría
extraerlas). El modo directo es para desarrollo y herramientas internas.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from decimal import Decimal

import bcrypt

from ..catalogo.base import CatalogoBase
from ..categorias import ArbolCategorias
from ..errors import (ErrorAutenticacion, ErrorConflicto, ErrorMarketplace, ErrorNoEncontrado, ErrorPago,
                      ErrorPermiso, ErrorStock, ErrorValidacion)
from ..models import (METODOS_PAGO, ROLES, TRANSICIONES_PEDIDO, Carrito, Categoria, DatosProducto,
                      DatosRegistro, Elegibilidad, EstadoConexion, Estadisticas, FiltroProductos,
                      LineaCarrito, LineaVenta, Pago, Pagina, Pedido, Producto, ProductoResumen,
                      Resena, Sesion, Usuario)
from ..pagos import Pasarela, PasarelaSimulada
from ..relacional.almacen import AlmacenSql
from ..util import dinero, normalizar, nuevo_id, slugify
from .base import Gateway

log = logging.getLogger(__name__)

_RE_CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
_RE_SKU = re.compile(r"^[A-Z0-9][A-Z0-9._-]{1,39}$")
_HASH_FALSO = bcrypt.hashpw(b"contrasena-falsa", bcrypt.gensalt(4))  # igualar tiempos si el correo no existe
MAX_PRECIO = Decimal("10000000")


def nombre_publico(u: Usuario) -> str:
    """Nombre que se muestra a otros usuarios: «María G.»"""
    return f"{u.nombre} {u.apellido[:1]}.".strip()


class GatewayDirecto(Gateway):
    def __init__(self, catalogo: CatalogoBase, sql: AlmacenSql, *, bcrypt_rounds: int = 12,
                 pasarela: Pasarela | None = None, etiqueta: str = "directo"):
        self.catalogo = catalogo
        self.sql = sql
        self.modo = etiqueta
        self._rounds = bcrypt_rounds
        self.pasarela: Pasarela = pasarela or PasarelaSimulada()
        self._usuario: Usuario | None = None
        self._arbol_cache: tuple[float, ArbolCategorias] | None = None
        self._lock = threading.Lock()

    # =================================================================== sesión
    @property
    def sesion(self) -> Sesion | None:
        return Sesion(self._usuario) if self._usuario else None

    def _requerir_sesion(self) -> Usuario:
        if not self._usuario:
            raise ErrorAutenticacion("Inicia sesión para continuar.")
        return self._usuario

    def _requerir_rol(self, *roles: str) -> Usuario:
        u = self._requerir_sesion()
        if u.rol not in roles:
            raise ErrorPermiso("Tu rol no tiene permiso para esta acción.")
        return u

    def login(self, correo: str, password: str) -> Sesion:
        correo = (correo or "").strip().lower()
        if not correo or not password:
            raise ErrorValidacion("Escribe tu correo y tu contraseña.")
        encontrado = self.sql.usuario_con_hash_por_correo(correo)
        pw = password.encode("utf-8")
        if len(pw) > 72:
            pw = b""  # bcrypt no admite más de 72 bytes: nunca coincidirá
        hash_guardado = encontrado[1].encode() if encontrado else _HASH_FALSO
        coincide = bool(pw) and bcrypt.checkpw(pw, hash_guardado)
        if not encontrado or not coincide:
            raise ErrorAutenticacion("Correo o contraseña incorrectos.")
        usuario = encontrado[0]
        if usuario.estatus != "ACTIVO":
            raise ErrorAutenticacion("Tu cuenta está suspendida. Contacta al administrador.")
        self._usuario = usuario
        return Sesion(usuario)

    def registrar(self, datos: DatosRegistro) -> Sesion:
        correo = (datos.correo or "").strip().lower()
        if not _RE_CORREO.match(correo):
            raise ErrorValidacion("Escribe un correo válido.")
        if datos.rol not in ("COMPRADOR", "VENDEDOR"):
            raise ErrorValidacion("Solo puedes registrarte como comprador o vendedor.")
        pw = datos.password or ""
        if len(pw) < 8 or not re.search(r"[A-Za-z]", pw) or not re.search(r"\d", pw):
            raise ErrorValidacion("La contraseña debe tener al menos 8 caracteres, con letras y números.")
        if len(pw.encode("utf-8")) > 72:
            raise ErrorValidacion("La contraseña es demasiado larga (máximo 72 bytes).")
        nombre, apellido = (datos.nombre or "").strip(), (datos.apellido or "").strip()
        if not nombre or not apellido:
            raise ErrorValidacion("Escribe tu nombre y apellido.")
        telefono = (datos.telefono or "").strip() or None
        if telefono and len(telefono) > 30:
            raise ErrorValidacion("El teléfono es demasiado largo.")
        hash_pw = bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt(self._rounds)).decode()
        usuario = self.sql.crear_usuario(correo=correo, contrasena_hash=hash_pw, rol=datos.rol,
                                         nombre=nombre, apellido=apellido, telefono=telefono)
        self._usuario = usuario
        return Sesion(usuario)

    def logout(self) -> None:
        self._usuario = None

    # =================================================================== categorías
    def _arbol(self, forzar: bool = False) -> ArbolCategorias:
        with self._lock:
            ahora = time.monotonic()
            if forzar or self._arbol_cache is None or ahora - self._arbol_cache[0] > 60:
                self._arbol_cache = (ahora, ArbolCategorias(self.catalogo.listar_categorias()))
            return self._arbol_cache[1]

    def listar_categorias(self) -> list[Categoria]:
        self._requerir_sesion()
        return list(self._arbol().por_id.values())

    def guardar_categoria(self, categoria: Categoria, *, crear: bool) -> Categoria:
        self._requerir_rol("ADMIN")
        nombre = (categoria.nombre or "").strip()
        if not 2 <= len(nombre) <= 80:
            raise ErrorValidacion("El nombre de la categoría debe tener entre 2 y 80 caracteres.")
        slug = slugify(categoria.slug or nombre)
        if not slug:
            raise ErrorValidacion("El slug no es válido.")
        if categoria.estatus not in ("ACTIVO", "INACTIVO"):
            raise ErrorValidacion("Estatus no válido.")
        arbol = self._arbol(forzar=True)
        padre = categoria.id_categoria_padre or None
        if padre and padre not in arbol.por_id:
            raise ErrorValidacion("La categoría padre no existe.")
        id_cat = categoria.id_categoria or nuevo_id()
        if not crear:
            if id_cat not in arbol.por_id:
                raise ErrorNoEncontrado("La categoría no existe.")
            if padre and padre in arbol.descendientes(id_cat):
                raise ErrorValidacion("Una categoría no puede colgar de sí misma ni de sus subcategorías.")
        resultado = self.catalogo.guardar_categoria(
            Categoria(id_cat, nombre, slug, padre, categoria.estatus), crear=crear)
        self._arbol(forzar=True)
        return resultado

    # =================================================================== catálogo
    def listar_productos(self, filtro: FiltroProductos | None = None, cursor: str | None = None,
                         limite: int = 24) -> Pagina[ProductoResumen]:
        self._requerir_sesion()
        f = filtro or FiltroProductos()
        ids_categoria = self._arbol().descendientes(f.id_categoria) if f.id_categoria else None
        return self.catalogo.listar_productos(
            ids_categoria=ids_categoria, q=normalizar(f.q) or None, en_cualquier_parte=f.en_cualquier_parte,
            solo_activos=True, cursor=cursor, limite=min(max(limite, 1), 100))

    def obtener_producto(self, id_producto: str) -> Producto:
        u = self._requerir_sesion()
        p = self.catalogo.obtener_producto(id_producto)
        if not p:
            raise ErrorNoEncontrado("El producto no existe o ya no está disponible.")
        es_dueno = u.rol == "ADMIN" or u.id_usuario == p.id_vendedor
        if not es_dueno:
            if p.estatus != "ACTIVO":
                raise ErrorNoEncontrado("El producto no existe o ya no está disponible.")
            p.variantes = [v for v in p.variantes if v.estatus == "ACTIVO"]
        p.ruta_categoria = [c.nombre for c in self._arbol().ruta(p.id_categoria)]
        vendedor = self.sql.usuario_por_id(p.id_vendedor)
        p.nombre_vendedor = nombre_publico(vendedor) if vendedor else None
        return p

    def listar_resenas(self, id_producto: str, cursor: str | None = None, limite: int = 10) -> Pagina[Resena]:
        self._requerir_sesion()
        return self.catalogo.listar_resenas(id_producto, cursor=cursor, limite=min(max(limite, 1), 50))

    def elegibilidad_resena(self, id_producto: str) -> Elegibilidad:
        u = self._requerir_sesion()
        if u.rol == "ADMIN":
            return Elegibilidad(False, "Los administradores no escriben reseñas.")
        p = self.catalogo.obtener_productos([id_producto]).get(id_producto)
        if not p:
            raise ErrorNoEncontrado("El producto no existe.")
        if p.id_vendedor == u.id_usuario:
            return Elegibilidad(False, "No puedes reseñar tu propio producto.")
        if self.catalogo.obtener_resena(id_producto, u.id_usuario):
            return Elegibilidad(False, "Ya reseñaste este producto.")
        ids_variante = [v.id_variante for v in self.catalogo.variantes_de_producto(id_producto)]
        if not self.sql.comprador_recibio_variantes(u.id_usuario, ids_variante):
            return Elegibilidad(False, "Solo puedes reseñar productos de pedidos que ya recibiste (ENTREGADO).")
        return Elegibilidad(True)

    def crear_resena(self, id_producto: str, calificacion: int, comentario: str) -> Resena:
        u = self._requerir_sesion()
        if not 1 <= int(calificacion) <= 5:
            raise ErrorValidacion("La calificación debe ser de 1 a 5 estrellas.")
        comentario = (comentario or "").strip()
        if len(comentario) > 1000:
            raise ErrorValidacion("El comentario no puede pasar de 1,000 caracteres.")
        elegible = self.elegibilidad_resena(id_producto)
        if not elegible.puede:
            raise ErrorPermiso(elegible.motivo)
        return self.catalogo.crear_resena(Resena(
            id_resena=nuevo_id(), id_producto=id_producto, id_usuario=u.id_usuario,
            calificacion=int(calificacion), comentario=comentario, nombre_usuario=nombre_publico(u)))

    # =================================================================== carrito
    def _requerir_comprador(self) -> Usuario:
        return self._requerir_rol("COMPRADOR", "VENDEDOR")

    def _armar_carrito(self, id_carrito: int) -> Carrito:
        filas = self.sql.lineas_carrito(id_carrito)
        variantes = self.catalogo.obtener_variantes([f["id_variante"] for f in filas])
        productos = self.catalogo.obtener_productos({v.id_producto for v in variantes.values()})
        lineas = []
        for f in filas:
            v = variantes.get(f["id_variante"])
            p = productos.get(v.id_producto) if v else None
            linea = LineaCarrito(id_detalle_carrito=int(f["id_detalle_carrito"]), id_variante=f["id_variante"],
                                 cantidad=int(f["cantidad"]))
            if v and p:
                linea.id_producto, linea.titulo, linea.sku = p.id_producto, p.titulo, v.sku
                linea.atributos, linea.precio_unitario = v.atributos, v.precio
                linea.stock_disponible = v.cantidad_stock
                linea.disponible = v.estatus == "ACTIVO" and p.estatus == "ACTIVO" and v.cantidad_stock > 0
            lineas.append(linea)
        return Carrito(id_carrito=id_carrito, lineas=lineas)

    def obtener_carrito(self) -> Carrito:
        u = self._requerir_comprador()
        return self._armar_carrito(self.sql.carrito_activo(u.id_usuario, crear=True))  # type: ignore[arg-type]

    def agregar_al_carrito(self, id_variante: str, cantidad: int) -> Carrito:
        u = self._requerir_comprador()
        if not 1 <= int(cantidad) <= 99:
            raise ErrorValidacion("La cantidad debe estar entre 1 y 99.")
        v = self.catalogo.obtener_variantes([id_variante]).get(id_variante)
        p = self.catalogo.obtener_productos([v.id_producto]).get(v.id_producto) if v else None
        if not v or not p or v.estatus != "ACTIVO" or p.estatus != "ACTIVO":
            raise ErrorNoEncontrado("Esta presentación ya no está disponible.")
        if p.id_vendedor == u.id_usuario:
            raise ErrorValidacion("No puedes comprar tus propios productos.")
        id_carrito = self.sql.carrito_activo(u.id_usuario, crear=True)
        ya_tiene = self.sql.cantidad_en_carrito(id_carrito, id_variante)  # type: ignore[arg-type]
        if ya_tiene + int(cantidad) > v.cantidad_stock:
            raise ErrorStock(f"Solo hay {v.cantidad_stock} disponibles (ya tienes {ya_tiene} en tu carrito).")
        self.sql.agregar_linea(id_carrito, id_variante, int(cantidad))  # type: ignore[arg-type]
        return self._armar_carrito(id_carrito)  # type: ignore[arg-type]

    def cambiar_cantidad(self, id_detalle_carrito: int, cantidad: int) -> Carrito:
        u = self._requerir_comprador()
        id_carrito = self.sql.carrito_activo(u.id_usuario, crear=True)
        if int(cantidad) <= 0:
            return self.quitar_del_carrito(id_detalle_carrito)
        if int(cantidad) > 99:
            raise ErrorValidacion("La cantidad máxima por producto es 99.")
        fila = next((f for f in self.sql.lineas_carrito(id_carrito) if f["id_detalle_carrito"] == id_detalle_carrito), None)  # type: ignore[arg-type]
        if not fila:
            raise ErrorNoEncontrado("Esa línea ya no está en tu carrito.")
        v = self.catalogo.obtener_variantes([fila["id_variante"]]).get(fila["id_variante"])
        if not v or v.estatus != "ACTIVO":
            raise ErrorNoEncontrado("Esta presentación ya no está disponible.")
        if int(cantidad) > v.cantidad_stock:
            raise ErrorStock(f"Solo hay {v.cantidad_stock} disponibles.")
        self.sql.fijar_cantidad(id_carrito, id_detalle_carrito, int(cantidad))  # type: ignore[arg-type]
        return self._armar_carrito(id_carrito)  # type: ignore[arg-type]

    def quitar_del_carrito(self, id_detalle_carrito: int) -> Carrito:
        u = self._requerir_comprador()
        id_carrito = self.sql.carrito_activo(u.id_usuario, crear=True)
        self.sql.quitar_linea(id_carrito, id_detalle_carrito)  # type: ignore[arg-type]
        return self._armar_carrito(id_carrito)  # type: ignore[arg-type]

    # =================================================================== checkout (saga)
    def checkout(self, direccion_envio: str, metodo_pago: str) -> Pedido:
        u = self._requerir_comprador()
        direccion = (direccion_envio or "").strip()
        if len(direccion) < 10:
            raise ErrorValidacion("Escribe una dirección de envío completa (calle, número, colonia, ciudad, C.P.).")
        if len(direccion) > 500:
            raise ErrorValidacion("La dirección es demasiado larga.")
        if metodo_pago not in METODOS_PAGO:
            raise ErrorValidacion("Elige un método de pago válido.")

        id_carrito = self.sql.carrito_activo(u.id_usuario, crear=False)
        filas = self.sql.lineas_carrito(id_carrito) if id_carrito else []
        if not filas:
            raise ErrorValidacion("Tu carrito está vacío.")

        # 1) Validar contra el catálogo (precio y existencias actuales)
        variantes = self.catalogo.obtener_variantes([f["id_variante"] for f in filas])
        productos = self.catalogo.obtener_productos({v.id_producto for v in variantes.values()})
        problemas: list[str] = []
        congeladas: list[dict] = []
        for f in filas:
            v = variantes.get(f["id_variante"])
            p = productos.get(v.id_producto) if v else None
            if not v or not p or v.estatus != "ACTIVO" or p.estatus != "ACTIVO":
                problemas.append(f"Un producto de tu carrito ya no está disponible ({p.titulo if p else f['id_variante'][:8]}).")
                continue
            if p.id_vendedor == u.id_usuario:
                problemas.append(f"«{p.titulo}» es tuyo: no puedes comprarlo.")
                continue
            if v.cantidad_stock < f["cantidad"]:
                problemas.append(f"«{p.titulo}» ({v.sku}): solo quedan {v.cantidad_stock}, pediste {f['cantidad']}.")
                continue
            congeladas.append({"id_variante": v.id_variante, "id_vendedor": p.id_vendedor,
                               "precio_unitario": v.precio, "cantidad": int(f["cantidad"])})
        if problemas:
            raise ErrorStock("Revisa tu carrito antes de pagar.", detalles=problemas)

        # 2) Reservar existencias (atómico en DynamoDB: todo o nada)
        items = [(c["id_variante"], c["cantidad"]) for c in congeladas]
        try:
            self.catalogo.reservar_stock(items)
        except ErrorStock as exc:
            nombres = self._nombres_variantes(exc.ids_afectados)
            raise ErrorStock("Alguien se llevó las últimas piezas mientras comprabas.",
                             detalles=[f"Sin existencias suficientes: {n}" for n in nombres],
                             ids_afectados=exc.ids_afectados) from exc

        # 3) Crear pedido + líneas y convertir el carrito (transacción en MySQL B)
        try:
            pedido = self.sql.crear_pedido(u.id_usuario, direccion, congeladas, id_carrito)  # type: ignore[arg-type]
        except Exception:
            self._liberar_seguro(items, "crear_pedido falló")
            raise

        # 4) Cobrar y registrar el pago (MySQL A)
        try:
            resultado = self.pasarela.cobrar(pedido.id_pedido, pedido.monto_total, metodo_pago)
            self.sql.registrar_pago(id_pedido=pedido.id_pedido, metodo_pago=metodo_pago,
                                    estatus=resultado.estatus, monto=pedido.monto_total,
                                    referencia=resultado.referencia)
            if resultado.estatus != "APROBADO":
                self._cancelar(pedido.id_pedido, ("PENDIENTE",))
                raise ErrorPago("El pago fue rechazado. No se te cobró nada; tu stock fue liberado.")
            self.sql.cambiar_estatus(pedido.id_pedido, ("PENDIENTE",), "PAGADO")
        except ErrorMarketplace:
            raise
        except Exception:
            log.exception("Fallo al registrar el pago del pedido %s: se cancela", pedido.id_pedido)
            try:
                self._cancelar(pedido.id_pedido, ("PENDIENTE", "PAGADO"))
            except Exception:  # noqa: BLE001
                log.exception("¡Compensación incompleta del pedido %s! Requiere revisión manual", pedido.id_pedido)
            raise
        return self.obtener_pedido(pedido.id_pedido)

    def _nombres_variantes(self, ids: list[str]) -> list[str]:
        variantes = self.catalogo.obtener_variantes(ids)
        productos = self.catalogo.obtener_productos({v.id_producto for v in variantes.values()})
        return [f"{productos[v.id_producto].titulo} ({v.sku})" if v.id_producto in productos else v.sku
                for v in variantes.values()] or ids

    def _liberar_seguro(self, items: list[tuple[str, int]], motivo: str) -> None:
        try:
            self.catalogo.liberar_stock(items)
        except Exception:  # noqa: BLE001
            log.exception("STOCK HUÉRFANO (%s): no se pudo devolver %s", motivo, items)

    def _cancelar(self, id_pedido: int, desde: tuple[str, ...]) -> None:
        """Cancela, reembolsa y devuelve existencias UNA sola vez (UPDATE condicional)."""
        if not self.sql.cambiar_estatus(id_pedido, desde, "CANCELADO"):
            raise ErrorConflicto("El pedido ya cambió de estado. Actualiza la pantalla.")
        self.sql.reembolsar_pagos(id_pedido)
        lineas = self.sql.lineas_de_pedido(id_pedido)
        self._liberar_seguro([(l.id_variante, l.cantidad) for l in lineas], f"cancelar pedido {id_pedido}")

    # =================================================================== pedidos
    def _enriquecer(self, lineas: list) -> None:
        """Añade título/SKU/atributos (DynamoDB) a líneas leídas de MySQL."""
        if not lineas:
            return
        variantes = self.catalogo.obtener_variantes({l.id_variante for l in lineas})
        productos = self.catalogo.obtener_productos({v.id_producto for v in variantes.values()})
        for l in lineas:
            v = variantes.get(l.id_variante)
            if not v:
                continue
            l.sku, l.atributos = v.sku, v.atributos
            if hasattr(l, "id_producto"):
                l.id_producto = v.id_producto
            if v.id_producto in productos:
                l.titulo = productos[v.id_producto].titulo

    def _con_nombres_comprador(self, pedidos: list[Pedido]) -> None:
        nombres = self.sql.usuarios_por_ids({p.id_comprador for p in pedidos})
        for p in pedidos:
            u = nombres.get(p.id_comprador)
            p.nombre_comprador = u.nombre_completo if u else None

    def listar_mis_pedidos(self, cursor: str | None = None, limite: int = 20) -> Pagina[Pedido]:
        u = self._requerir_comprador()
        return self.sql.listar_pedidos(id_comprador=u.id_usuario, estatus=None, cursor=cursor,
                                       limite=min(max(limite, 1), 100))

    def listar_pedidos_admin(self, estatus: str | None = None, cursor: str | None = None,
                             limite: int = 30) -> Pagina[Pedido]:
        self._requerir_rol("ADMIN")
        pagina = self.sql.listar_pedidos(id_comprador=None, estatus=estatus or None, cursor=cursor,
                                         limite=min(max(limite, 1), 100))
        self._con_nombres_comprador(pagina.items)
        return pagina

    def obtener_pedido(self, id_pedido: int) -> Pedido:
        u = self._requerir_sesion()
        p = self.sql.pedido_por_id(id_pedido)
        if not p:
            raise ErrorNoEncontrado("El pedido no existe.")
        es_admin, es_dueno = u.rol == "ADMIN", p.id_comprador == u.id_usuario
        es_vendedor = u.rol == "VENDEDOR" and any(l.id_vendedor == u.id_usuario for l in p.lineas)
        if not (es_admin or es_dueno or es_vendedor):
            raise ErrorNoEncontrado("El pedido no existe.")  # no revelamos que existe
        if not (es_admin or es_dueno):
            p.lineas = [l for l in p.lineas if l.id_vendedor == u.id_usuario]  # el vendedor solo ve lo suyo
        self._enriquecer(p.lineas)
        if es_admin or es_dueno:
            p.pagos = self.sql.pagos_de_pedido(id_pedido)
        if not es_dueno:
            self._con_nombres_comprador([p])
        return p

    def cambiar_estatus_pedido(self, id_pedido: int, nuevo_estatus: str) -> Pedido:
        u = self._requerir_sesion()
        p = self.sql.pedido_por_id(id_pedido, con_lineas=False)
        if not p:
            raise ErrorNoEncontrado("El pedido no existe.")
        actual = p.estatus
        if nuevo_estatus not in TRANSICIONES_PEDIDO.get(actual, ()):
            raise ErrorConflicto(f"Un pedido {actual} no puede pasar a {nuevo_estatus}.")
        par = (actual, nuevo_estatus)
        if u.rol == "ADMIN":
            permitido = True
        elif p.id_comprador == u.id_usuario:
            permitido = par in {("PENDIENTE", "CANCELADO"), ("PAGADO", "CANCELADO"), ("ENVIADO", "ENTREGADO")}
        elif u.rol == "VENDEDOR" and par == ("PAGADO", "ENVIADO"):
            vendedores = self.sql.vendedores_de_pedido(id_pedido)
            if vendedores == {u.id_usuario}:
                permitido = True
            elif u.id_usuario in vendedores:
                # el esquema guarda UN estatus por pedido (no por línea): con varios vendedores lo decide el administrador
                raise ErrorPermiso("Este pedido incluye productos de otros vendedores, así que solo el administrador "
                                   "puede marcarlo como enviado.")
            else:
                permitido = False
        else:
            permitido = False
        if not permitido:
            raise ErrorPermiso("No tienes permiso para hacer este cambio de estatus.")

        if nuevo_estatus == "CANCELADO":
            self._cancelar(id_pedido, (actual,))
        else:
            if not self.sql.cambiar_estatus(id_pedido, (actual,), nuevo_estatus):
                raise ErrorConflicto("El pedido cambió de estado mientras lo editabas. Actualiza la pantalla.")
            if par == ("PENDIENTE", "PAGADO"):  # un pedido PAGADO siempre debe tener un pago aprobado
                self.sql.registrar_pago(id_pedido=id_pedido, metodo_pago="TRANSFERENCIA", estatus="APROBADO",
                                        monto=p.monto_total, referencia=f"MANUAL-ADMIN-{u.id_usuario}")
        return self.obtener_pedido(id_pedido)

    def listar_pagos(self, cursor: str | None = None, limite: int = 30) -> Pagina[Pago]:
        self._requerir_rol("ADMIN")
        return self.sql.listar_pagos(cursor=cursor, limite=min(max(limite, 1), 100))

    # =================================================================== vendedor
    def listar_mis_productos(self, cursor: str | None = None, limite: int = 30) -> Pagina[ProductoResumen]:
        u = self._requerir_rol("VENDEDOR")
        return self.catalogo.listar_productos(id_vendedor=u.id_usuario, solo_activos=False, cursor=cursor,
                                              limite=min(max(limite, 1), 100))

    def listar_mis_ventas(self, cursor: str | None = None, limite: int = 30) -> Pagina[LineaVenta]:
        u = self._requerir_rol("VENDEDOR")
        pagina = self.sql.listar_ventas(u.id_usuario, cursor=cursor, limite=min(max(limite, 1), 100))
        self._enriquecer(pagina.items)
        return pagina

    def _validar_producto(self, d: DatosProducto, *, nuevo: bool) -> None:
        if not 3 <= len((d.titulo or "").strip()) <= 150:
            raise ErrorValidacion("El título debe tener entre 3 y 150 caracteres.")
        if len(d.descripcion or "") > 4000:
            raise ErrorValidacion("La descripción no puede pasar de 4,000 caracteres.")
        if len(d.marca or "") > 80:
            raise ErrorValidacion("La marca no puede pasar de 80 caracteres.")
        if d.estatus not in ("ACTIVO", "INACTIVO"):
            raise ErrorValidacion("Estatus no válido.")
        cat = self._arbol(forzar=True).por_id.get(d.id_categoria)
        if not cat or cat.estatus != "ACTIVO":
            raise ErrorValidacion("Elige una categoría válida.")
        if nuevo and not d.variantes:
            raise ErrorValidacion("Agrega al menos una variante (precio y existencias).")
        vistos: set[str] = set()
        for v in d.variantes:
            if v.id_variante is None:
                sku = (v.sku or "").strip().upper()
                if not _RE_SKU.match(sku):
                    raise ErrorValidacion(f"SKU «{v.sku}» no válido: usa letras, números, punto, guion (2-40 caracteres).")
                if sku in vistos:
                    raise ErrorValidacion(f"El SKU «{sku}» está repetido en este producto.")
                vistos.add(sku)
            precio = dinero(v.precio)
            if not Decimal("0.01") <= precio <= MAX_PRECIO:
                raise ErrorValidacion(f"El precio de «{v.sku}» debe estar entre $0.01 y $10,000,000.")
            if not 0 <= int(v.cantidad_stock) <= 1_000_000:
                raise ErrorValidacion(f"Las existencias de «{v.sku}» no son válidas.")
            if v.estatus not in ("ACTIVO", "INACTIVO"):
                raise ErrorValidacion("Estatus de variante no válido.")
            for k, val in v.atributos.items():
                if not k.strip() or not str(val).strip() or len(k) > 40 or len(str(val)) > 80:
                    raise ErrorValidacion(f"Atributos no válidos en «{v.sku}» (ej.: Talla=M, Color=Azul).")

    def guardar_producto(self, datos: DatosProducto, id_producto: str | None = None) -> Producto:
        u = self._requerir_rol("VENDEDOR", "ADMIN")
        self._validar_producto(datos, nuevo=id_producto is None)
        campos = {"titulo": datos.titulo.strip(), "descripcion": (datos.descripcion or "").strip(),
                  "marca": (datos.marca or "").strip(), "id_categoria": datos.id_categoria,
                  "estatus": datos.estatus}
        if id_producto is None:
            if u.rol != "VENDEDOR":
                raise ErrorPermiso("Solo los vendedores publican productos.")
            nuevo_prod = nuevo_id()
            self.catalogo.crear_producto(id_producto=nuevo_prod, id_vendedor=u.id_usuario, **campos)
            try:
                for v in datos.variantes:
                    self.catalogo.crear_variante(
                        id_variante=nuevo_id(), id_producto=nuevo_prod, sku=v.sku.strip().upper(),
                        precio=dinero(v.precio), cantidad_stock=int(v.cantidad_stock),
                        atributos={k.strip(): str(x).strip() for k, x in v.atributos.items()}, estatus=v.estatus)
            except Exception:
                self.catalogo.eliminar_producto_fisico(nuevo_prod)  # compensación: no dejar huérfanos
                raise
            return self.obtener_producto(nuevo_prod)

        actual = self.catalogo.obtener_producto(id_producto)
        if not actual:
            raise ErrorNoEncontrado("El producto no existe.")
        if u.rol != "ADMIN" and actual.id_vendedor != u.id_usuario:
            raise ErrorPermiso("Este producto no es tuyo.")
        existentes = {v.id_variante for v in actual.variantes}
        for v in datos.variantes:
            if v.id_variante and v.id_variante not in existentes:
                raise ErrorNoEncontrado("Una de las variantes no pertenece a este producto.")
        self.catalogo.actualizar_producto(id_producto, campos)
        for v in datos.variantes:
            atributos = {k.strip(): str(x).strip() for k, x in v.atributos.items()}
            if v.id_variante:
                self.catalogo.actualizar_variante(v.id_variante, precio=dinero(v.precio),
                                                  cantidad_stock=int(v.cantidad_stock), atributos=atributos,
                                                  estatus=v.estatus)
            else:
                self.catalogo.crear_variante(id_variante=nuevo_id(), id_producto=id_producto,
                                             sku=v.sku.strip().upper(), precio=dinero(v.precio),
                                             cantidad_stock=int(v.cantidad_stock), atributos=atributos,
                                             estatus=v.estatus)
        return self.obtener_producto(id_producto)

    # =================================================================== administración
    def listar_usuarios(self, rol: str | None = None, estatus: str | None = None, q: str | None = None,
                        cursor: str | None = None, limite: int = 30) -> Pagina[Usuario]:
        self._requerir_rol("ADMIN")
        return self.sql.listar_usuarios(rol=rol or None, estatus=estatus or None, q=(q or "").strip() or None,
                                        cursor=cursor, limite=min(max(limite, 1), 100))

    def actualizar_usuario(self, id_usuario: int, rol: str | None = None, estatus: str | None = None) -> Usuario:
        admin = self._requerir_rol("ADMIN")
        if rol and rol not in ROLES:
            raise ErrorValidacion("Rol no válido.")
        if estatus and estatus not in ("ACTIVO", "SUSPENDIDO"):
            raise ErrorValidacion("Estatus no válido.")
        if id_usuario == admin.id_usuario and ((rol and rol != "ADMIN") or (estatus and estatus != "ACTIVO")):
            raise ErrorValidacion("No puedes quitarte tu propio acceso de administrador.")
        return self.sql.actualizar_usuario(id_usuario, rol=rol, estatus=estatus)

    def estadisticas(self) -> Estadisticas:
        self._requerir_rol("ADMIN")
        return Estadisticas(
            usuarios_por_rol=self.sql.contar_usuarios_por_rol(),
            pedidos_por_estatus=self.sql.contar_pedidos_por_estatus(),
            ingresos_aprobados=self.sql.ingresos_aprobados(),
            productos_aprox=self.catalogo.contar_productos_aprox())

    # =================================================================== diagnóstico
    def estado_conexiones(self) -> list[EstadoConexion]:
        return self.catalogo.salud() + self.sql.salud()
