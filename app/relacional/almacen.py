"""Acceso a las dos bases MySQL (usuarios/pagos y carritos/pedidos).

* Paginación por *keyset* (WHERE id < último ORDER BY id DESC), no OFFSET: costo
  constante aunque haya millones de pedidos.
* Ninguna consulta cruza bases de datos. Si hace falta unir datos (p. ej. nombre
  del comprador en un pedido) lo hace la capa superior con una consulta por lotes.
"""
from __future__ import annotations

import time
from decimal import Decimal
from typing import Any, Iterable

from sqlalchemy import and_, func, insert, or_, select, text, update
from sqlalchemy.engine import Engine, RowMapping
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError

from ..errors import ErrorConexion, ErrorConflicto, ErrorNoEncontrado
from ..models import (EstadoConexion, LineaPedido, LineaVenta, Pago, Pagina, Pedido, Usuario)
from ..util import a_naive_utc, a_utc, codificar_cursor, decodificar_cursor, dinero, utcnow
from . import esquema as e

MAX_LINEAS_CARRITO = 50


def _ahora():
    return a_naive_utc(utcnow())


def _escapar_like(texto: str) -> str:
    return texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class AlmacenSql:
    def __init__(self, motor_usuarios: Engine, motor_ops: Engine):
        self.usuarios_db = motor_usuarios
        self.ops_db = motor_ops

    # ------------------------------------------------------------------ utilidades
    @staticmethod
    def _envolver(exc: Exception) -> Exception:
        if isinstance(exc, (OperationalError, DBAPIError)) and not isinstance(exc, IntegrityError):
            return ErrorConexion(f"No se pudo consultar MySQL: {str(exc.orig) if getattr(exc, 'orig', None) else exc}")
        return exc

    def _pagina(self, filas: list[RowMapping], limite: int, convertir, clave: str) -> Pagina:
        hay_mas = len(filas) > limite
        filas = filas[:limite]
        siguiente = codificar_cursor({"id": filas[-1][clave]}) if hay_mas and filas else None
        return Pagina([convertir(f) for f in filas], siguiente)

    @staticmethod
    def _id_cursor(cursor: str | None) -> int | None:
        d = decodificar_cursor(cursor)
        return int(d["id"]) if d and "id" in d else None

    # ================================================================== USUARIOS (base A)
    @staticmethod
    def _usuario(f: RowMapping) -> Usuario:
        return Usuario(
            id_usuario=int(f["id_usuario"]), correo=f["correo"], rol=f["rol"], nombre=f["nombre"],
            apellido=f["apellido"], telefono=f["telefono"], estatus=f["estatus"],
            fecha_registro=a_utc(f["fecha_registro"]))

    def crear_usuario(self, *, correo: str, contrasena_hash: str, rol: str, nombre: str,
                      apellido: str, telefono: str | None) -> Usuario:
        try:
            with self.usuarios_db.begin() as cx:
                r = cx.execute(insert(e.usuarios).values(
                    correo=correo, contrasena_hash=contrasena_hash, rol=rol, nombre=nombre,
                    apellido=apellido, telefono=telefono, estatus="ACTIVO"))
                id_usuario = r.inserted_primary_key[0]
        except IntegrityError as exc:
            raise ErrorConflicto("Ya existe una cuenta con ese correo.") from exc
        except Exception as exc:  # noqa: BLE001
            raise self._envolver(exc)
        return self.usuario_por_id(id_usuario)  # type: ignore[return-value]

    def usuario_con_hash_por_correo(self, correo: str) -> tuple[Usuario, str] | None:
        try:
            with self.usuarios_db.connect() as cx:
                f = cx.execute(select(e.usuarios).where(e.usuarios.c.correo == correo)).mappings().first()
        except Exception as exc:  # noqa: BLE001
            raise self._envolver(exc)
        return (self._usuario(f), f["contrasena_hash"]) if f else None

    def usuario_por_id(self, id_usuario: int) -> Usuario | None:
        return self.usuarios_por_ids([id_usuario]).get(id_usuario)

    def usuarios_por_ids(self, ids: Iterable[int]) -> dict[int, Usuario]:
        ids = list({int(i) for i in ids})
        if not ids:
            return {}
        try:
            with self.usuarios_db.connect() as cx:
                filas = cx.execute(select(e.usuarios).where(e.usuarios.c.id_usuario.in_(ids))).mappings().all()
        except Exception as exc:  # noqa: BLE001
            raise self._envolver(exc)
        return {int(f["id_usuario"]): self._usuario(f) for f in filas}

    def listar_usuarios(self, *, rol: str | None, estatus: str | None, q: str | None,
                        cursor: str | None, limite: int) -> Pagina[Usuario]:
        c = e.usuarios.c
        cond = []
        if rol:
            cond.append(c.rol == rol)
        if estatus:
            cond.append(c.estatus == estatus)
        if q:
            patron = _escapar_like(q.strip().lower()) + "%"  # prefijo → puede usar índice
            cond.append(or_(func.lower(c.correo).like(patron, escape="\\"),
                            func.lower(c.nombre).like(patron, escape="\\"),
                            func.lower(c.apellido).like(patron, escape="\\")))
        ultimo = self._id_cursor(cursor)
        if ultimo is not None:
            cond.append(c.id_usuario < ultimo)
        consulta = select(e.usuarios).where(and_(*cond)).order_by(c.id_usuario.desc()).limit(limite + 1)
        try:
            with self.usuarios_db.connect() as cx:
                filas = cx.execute(consulta).mappings().all()
        except Exception as exc:  # noqa: BLE001
            raise self._envolver(exc)
        return self._pagina(filas, limite, self._usuario, "id_usuario")

    def actualizar_usuario(self, id_usuario: int, *, rol: str | None, estatus: str | None) -> Usuario:
        valores = {k: v for k, v in (("rol", rol), ("estatus", estatus)) if v}
        if valores:
            try:
                with self.usuarios_db.begin() as cx:
                    r = cx.execute(update(e.usuarios).where(e.usuarios.c.id_usuario == id_usuario).values(**valores))
                    if r.rowcount == 0:
                        raise ErrorNoEncontrado("El usuario no existe.")
            except ErrorNoEncontrado:
                raise
            except Exception as exc:  # noqa: BLE001
                raise self._envolver(exc)
        u = self.usuario_por_id(id_usuario)
        if not u:
            raise ErrorNoEncontrado("El usuario no existe.")
        return u

    def contar_usuarios_por_rol(self) -> dict[str, int]:
        c = e.usuarios.c
        try:
            with self.usuarios_db.connect() as cx:
                filas = cx.execute(select(c.rol, func.count()).group_by(c.rol)).all()
        except Exception as exc:  # noqa: BLE001
            raise self._envolver(exc)
        return {r: int(n) for r, n in filas}

    # ================================================================== PAGOS (base A)
    @staticmethod
    def _pago(f: RowMapping) -> Pago:
        return Pago(
            id_pago=int(f["id_pago"]), id_pedido=int(f["id_pedido"]), metodo_pago=f["metodo_pago"],
            estatus=f["estatus"], monto=dinero(f["monto"]), referencia_transaccion=f["referencia_transaccion"],
            fecha_pago=a_utc(f["fecha_pago"]))

    def registrar_pago(self, *, id_pedido: int, metodo_pago: str, estatus: str, monto: Decimal,
                       referencia: str | None) -> Pago:
        try:
            with self.usuarios_db.begin() as cx:
                r = cx.execute(insert(e.pagos).values(
                    id_pedido=id_pedido, metodo_pago=metodo_pago, estatus=estatus,
                    monto=dinero(monto), referencia_transaccion=referencia))
                id_pago = r.inserted_primary_key[0]
                f = cx.execute(select(e.pagos).where(e.pagos.c.id_pago == id_pago)).mappings().one()
        except Exception as exc:  # noqa: BLE001
            raise self._envolver(exc)
        return self._pago(f)

    def pagos_de_pedido(self, id_pedido: int) -> list[Pago]:
        try:
            with self.usuarios_db.connect() as cx:
                filas = cx.execute(select(e.pagos).where(e.pagos.c.id_pedido == id_pedido)
                                   .order_by(e.pagos.c.id_pago)).mappings().all()
        except Exception as exc:  # noqa: BLE001
            raise self._envolver(exc)
        return [self._pago(f) for f in filas]

    def reembolsar_pagos(self, id_pedido: int) -> int:
        try:
            with self.usuarios_db.begin() as cx:
                r = cx.execute(update(e.pagos).where(e.pagos.c.id_pedido == id_pedido,
                                                      e.pagos.c.estatus == "APROBADO")
                               .values(estatus="REEMBOLSADO"))
                return r.rowcount
        except Exception as exc:  # noqa: BLE001
            raise self._envolver(exc)

    def listar_pagos(self, *, cursor: str | None, limite: int) -> Pagina[Pago]:
        c = e.pagos.c
        ultimo = self._id_cursor(cursor)
        consulta = select(e.pagos)
        if ultimo is not None:
            consulta = consulta.where(c.id_pago < ultimo)
        consulta = consulta.order_by(c.id_pago.desc()).limit(limite + 1)
        try:
            with self.usuarios_db.connect() as cx:
                filas = cx.execute(consulta).mappings().all()
        except Exception as exc:  # noqa: BLE001
            raise self._envolver(exc)
        return self._pagina(filas, limite, self._pago, "id_pago")

    def ingresos_aprobados(self) -> Decimal:
        try:
            with self.usuarios_db.connect() as cx:
                total = cx.execute(select(func.coalesce(func.sum(e.pagos.c.monto), 0))
                                   .where(e.pagos.c.estatus == "APROBADO")).scalar_one()
        except Exception as exc:  # noqa: BLE001
            raise self._envolver(exc)
        return dinero(total)

    # ================================================================== CARRITO (base B)
    def carrito_activo(self, id_usuario: int, *, crear: bool) -> int | None:
        c = e.carritos.c
        try:
            with self.ops_db.begin() as cx:
                id_carrito = cx.execute(
                    select(c.id_carrito).where(c.id_usuario == id_usuario, c.estatus == "ACTIVO")
                    .order_by(c.id_carrito.desc()).limit(1)).scalar()
                if id_carrito is None and crear:
                    id_carrito = cx.execute(insert(e.carritos).values(
                        id_usuario=id_usuario, estatus="ACTIVO")).inserted_primary_key[0]
        except Exception as exc:  # noqa: BLE001
            raise self._envolver(exc)
        return int(id_carrito) if id_carrito is not None else None

    def lineas_carrito(self, id_carrito: int) -> list[dict[str, Any]]:
        d = e.detalle_carrito.c
        try:
            with self.ops_db.connect() as cx:
                filas = cx.execute(select(e.detalle_carrito).where(d.id_carrito == id_carrito)
                                   .order_by(d.id_detalle_carrito)).mappings().all()
        except Exception as exc:  # noqa: BLE001
            raise self._envolver(exc)
        return [dict(f) for f in filas]

    def agregar_linea(self, id_carrito: int, id_variante: str, cantidad: int) -> None:
        d = e.detalle_carrito.c
        try:
            with self.ops_db.begin() as cx:
                existente = cx.execute(select(d.id_detalle_carrito, d.cantidad).where(
                    d.id_carrito == id_carrito, d.id_variante == id_variante)).first()
                if existente:
                    cx.execute(update(e.detalle_carrito).where(d.id_detalle_carrito == existente[0])
                               .values(cantidad=existente[1] + cantidad))
                else:
                    n = cx.execute(select(func.count()).where(d.id_carrito == id_carrito)).scalar_one()
                    if n >= MAX_LINEAS_CARRITO:
                        raise ErrorConflicto(f"El carrito admite máximo {MAX_LINEAS_CARRITO} productos distintos.")
                    cx.execute(insert(e.detalle_carrito).values(
                        id_carrito=id_carrito, id_variante=id_variante, cantidad=cantidad))
                cx.execute(update(e.carritos).where(e.carritos.c.id_carrito == id_carrito)
                           .values(fecha_actualizacion=_ahora()))
        except ErrorConflicto:
            raise
        except Exception as exc:  # noqa: BLE001
            raise self._envolver(exc)

    def cantidad_en_carrito(self, id_carrito: int, id_variante: str) -> int:
        d = e.detalle_carrito.c
        try:
            with self.ops_db.connect() as cx:
                return int(cx.execute(select(func.coalesce(func.sum(d.cantidad), 0)).where(
                    d.id_carrito == id_carrito, d.id_variante == id_variante)).scalar_one())
        except Exception as exc:  # noqa: BLE001
            raise self._envolver(exc)

    def fijar_cantidad(self, id_carrito: int, id_detalle: int, cantidad: int) -> None:
        d = e.detalle_carrito.c
        try:
            with self.ops_db.begin() as cx:
                r = cx.execute(update(e.detalle_carrito).where(
                    d.id_detalle_carrito == id_detalle, d.id_carrito == id_carrito).values(cantidad=cantidad))
                if r.rowcount == 0:
                    raise ErrorNoEncontrado("Esa línea ya no está en tu carrito.")
                cx.execute(update(e.carritos).where(e.carritos.c.id_carrito == id_carrito)
                           .values(fecha_actualizacion=_ahora()))
        except ErrorNoEncontrado:
            raise
        except Exception as exc:  # noqa: BLE001
            raise self._envolver(exc)

    def quitar_linea(self, id_carrito: int, id_detalle: int) -> None:
        d = e.detalle_carrito.c
        try:
            with self.ops_db.begin() as cx:
                cx.execute(e.detalle_carrito.delete().where(
                    d.id_detalle_carrito == id_detalle, d.id_carrito == id_carrito))
                cx.execute(update(e.carritos).where(e.carritos.c.id_carrito == id_carrito)
                           .values(fecha_actualizacion=_ahora()))
        except Exception as exc:  # noqa: BLE001
            raise self._envolver(exc)

    # ================================================================== PEDIDOS (base B)
    @staticmethod
    def _pedido(f: RowMapping) -> Pedido:
        return Pedido(
            id_pedido=int(f["id_pedido"]), id_comprador=int(f["id_comprador"]), estatus=f["estatus"],
            monto_total=dinero(f["monto_total"]), direccion_envio=f["direccion_envio"],
            fecha_pedido=a_utc(f["fecha_pedido"]))

    @staticmethod
    def _linea_pedido(f: RowMapping) -> LineaPedido:
        return LineaPedido(
            id_detalle_pedido=int(f["id_detalle_pedido"]), id_pedido=int(f["id_pedido"]),
            id_variante=f["id_variante"], id_vendedor=int(f["id_vendedor"]),
            precio_unitario=dinero(f["precio_unitario"]), cantidad=int(f["cantidad"]),
            subtotal=dinero(f["subtotal"]))

    def crear_pedido(self, id_comprador: int, direccion: str, lineas: list[dict[str, Any]],
                     id_carrito: int) -> Pedido:
        """Una sola transacción en la base B: convierte el carrito, crea el pedido y sus líneas.
        El UPDATE condicional del carrito evita pedidos duplicados por doble clic."""
        total = sum((dinero(l["precio_unitario"]) * l["cantidad"] for l in lineas), Decimal("0"))
        try:
            with self.ops_db.begin() as cx:
                r = cx.execute(update(e.carritos).where(
                    e.carritos.c.id_carrito == id_carrito, e.carritos.c.id_usuario == id_comprador,
                    e.carritos.c.estatus == "ACTIVO").values(estatus="CONVERTIDO", fecha_actualizacion=_ahora()))
                if r.rowcount != 1:
                    raise ErrorConflicto("Este carrito ya fue procesado.")
                id_pedido = cx.execute(insert(e.pedidos).values(
                    id_comprador=id_comprador, estatus="PENDIENTE", monto_total=total,
                    direccion_envio=direccion)).inserted_primary_key[0]
                cx.execute(insert(e.detalle_pedido), [{
                    "id_pedido": id_pedido, "id_variante": l["id_variante"], "id_vendedor": l["id_vendedor"],
                    "precio_unitario": dinero(l["precio_unitario"]), "cantidad": l["cantidad"],
                    "subtotal": dinero(l["precio_unitario"]) * l["cantidad"]} for l in lineas])
        except ErrorConflicto:
            raise
        except Exception as exc:  # noqa: BLE001
            raise self._envolver(exc)
        return self.pedido_por_id(id_pedido, con_lineas=True)  # type: ignore[return-value]

    def pedido_por_id(self, id_pedido: int, *, con_lineas: bool = True) -> Pedido | None:
        try:
            with self.ops_db.connect() as cx:
                f = cx.execute(select(e.pedidos).where(e.pedidos.c.id_pedido == id_pedido)).mappings().first()
                if not f:
                    return None
                pedido = self._pedido(f)
                if con_lineas:
                    pedido.lineas = self.lineas_de_pedido(id_pedido, cx=cx)
        except Exception as exc:  # noqa: BLE001
            raise self._envolver(exc)
        return pedido

    def lineas_de_pedido(self, id_pedido: int, cx=None) -> list[LineaPedido]:
        consulta = select(e.detalle_pedido).where(e.detalle_pedido.c.id_pedido == id_pedido) \
            .order_by(e.detalle_pedido.c.id_detalle_pedido)
        if cx is not None:
            return [self._linea_pedido(f) for f in cx.execute(consulta).mappings().all()]
        try:
            with self.ops_db.connect() as cx2:
                return [self._linea_pedido(f) for f in cx2.execute(consulta).mappings().all()]
        except Exception as exc:  # noqa: BLE001
            raise self._envolver(exc)

    def listar_pedidos(self, *, id_comprador: int | None, estatus: str | None, cursor: str | None,
                       limite: int) -> Pagina[Pedido]:
        c = e.pedidos.c
        cond = []
        if id_comprador is not None:
            cond.append(c.id_comprador == id_comprador)
        if estatus:
            cond.append(c.estatus == estatus)
        ultimo = self._id_cursor(cursor)
        if ultimo is not None:
            cond.append(c.id_pedido < ultimo)
        consulta = select(e.pedidos).where(and_(*cond)).order_by(c.id_pedido.desc()).limit(limite + 1)
        try:
            with self.ops_db.connect() as cx:
                filas = cx.execute(consulta).mappings().all()
        except Exception as exc:  # noqa: BLE001
            raise self._envolver(exc)
        return self._pagina(filas, limite, self._pedido, "id_pedido")

    def cambiar_estatus(self, id_pedido: int, desde: Iterable[str], hacia: str) -> bool:
        """UPDATE condicional: devuelve True solo si ESTA llamada hizo la transición.
        Garantiza que efectos secundarios (devolver stock, reembolsar) ocurran una sola vez."""
        try:
            with self.ops_db.begin() as cx:
                r = cx.execute(update(e.pedidos).where(
                    e.pedidos.c.id_pedido == id_pedido, e.pedidos.c.estatus.in_(list(desde)))
                    .values(estatus=hacia))
                return r.rowcount == 1
        except Exception as exc:  # noqa: BLE001
            raise self._envolver(exc)

    def vendedores_de_pedido(self, id_pedido: int) -> set[int]:
        try:
            with self.ops_db.connect() as cx:
                filas = cx.execute(select(e.detalle_pedido.c.id_vendedor).where(
                    e.detalle_pedido.c.id_pedido == id_pedido).distinct()).all()
        except Exception as exc:  # noqa: BLE001
            raise self._envolver(exc)
        return {int(f[0]) for f in filas}

    def listar_ventas(self, id_vendedor: int, *, cursor: str | None, limite: int) -> Pagina[LineaVenta]:
        d, p = e.detalle_pedido.c, e.pedidos.c
        cond = [d.id_vendedor == id_vendedor]
        ultimo = self._id_cursor(cursor)
        if ultimo is not None:
            cond.append(d.id_detalle_pedido < ultimo)
        consulta = (select(e.detalle_pedido, p.estatus.label("estatus_pedido"), p.fecha_pedido)
                    .join(e.pedidos, e.pedidos.c.id_pedido == d.id_pedido)
                    .where(and_(*cond)).order_by(d.id_detalle_pedido.desc()).limit(limite + 1))
        try:
            with self.ops_db.connect() as cx:
                filas = cx.execute(consulta).mappings().all()
        except Exception as exc:  # noqa: BLE001
            raise self._envolver(exc)

        def conv(f: RowMapping) -> LineaVenta:
            return LineaVenta(
                id_detalle_pedido=int(f["id_detalle_pedido"]), id_pedido=int(f["id_pedido"]),
                id_variante=f["id_variante"], precio_unitario=dinero(f["precio_unitario"]),
                cantidad=int(f["cantidad"]), subtotal=dinero(f["subtotal"]),
                estatus_pedido=f["estatus_pedido"], fecha_pedido=a_utc(f["fecha_pedido"]))

        return self._pagina(filas, limite, conv, "id_detalle_pedido")

    def comprador_recibio_variantes(self, id_comprador: int, ids_variante: list[str]) -> bool:
        """¿Tiene el usuario algún pedido ENTREGADO que incluya alguna de estas variantes?"""
        if not ids_variante:
            return False
        d, p = e.detalle_pedido.c, e.pedidos.c
        consulta = (select(d.id_detalle_pedido).join(e.pedidos, e.pedidos.c.id_pedido == d.id_pedido)
                    .where(p.id_comprador == id_comprador, p.estatus == "ENTREGADO",
                           d.id_variante.in_(ids_variante)).limit(1))
        try:
            with self.ops_db.connect() as cx:
                return cx.execute(consulta).first() is not None
        except Exception as exc:  # noqa: BLE001
            raise self._envolver(exc)

    def contar_pedidos_por_estatus(self) -> dict[str, int]:
        try:
            with self.ops_db.connect() as cx:
                filas = cx.execute(select(e.pedidos.c.estatus, func.count()).group_by(e.pedidos.c.estatus)).all()
        except Exception as exc:  # noqa: BLE001
            raise self._envolver(exc)
        return {s: int(n) for s, n in filas}

    # ================================================================== salud
    def salud(self) -> list[EstadoConexion]:
        resultado = []
        for nombre, motor, contiene in (
            ("MySQL · usuarios y pagos", self.usuarios_db, "usuarios, pagos"),
            ("MySQL · carritos y pedidos", self.ops_db, "carritos, detalle_carrito, pedidos, detalle_pedido"),
        ):
            t0 = time.perf_counter()
            try:
                with motor.connect() as cx:
                    cx.execute(text("SELECT 1"))
                ms = (time.perf_counter() - t0) * 1000
                resultado.append(EstadoConexion(nombre, "SQL", True, motor.url.render_as_string(hide_password=True),
                                                round(ms, 1), contiene))
            except Exception as exc:  # noqa: BLE001
                resultado.append(EstadoConexion(nombre, "SQL", False, str(getattr(exc, "orig", exc))[:200],
                                                None, contiene))
        return resultado
