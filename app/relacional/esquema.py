"""Esquema de las dos bases MySQL.

  Base A (mkt_usuarios):   usuarios, pagos
  Base B (mkt_operaciones): carritos, detalle_carrito, pedidos, detalle_pedido

Reglas que NO se pueden expresar como FOREIGN KEY porque cruzan bases de datos
(las valida la capa de acceso):
  * pagos.id_pedido              → pedidos (base B)
  * carritos.id_usuario          → usuarios (base A)
  * pedidos.id_comprador         → usuarios (base A)
  * detalle_pedido.id_vendedor   → usuarios (base A)
  * detalle_carrito/detalle_pedido.id_variante → variantes_producto (DynamoDB)
"""
from __future__ import annotations

import warnings

from sqlalchemy import (BigInteger, CheckConstraint, Column, DateTime, ForeignKey, Index,
                        Integer, MetaData, Numeric, String, Table, Text, UniqueConstraint, text)

from ..util import a_naive_utc, utcnow

# SQLite (solo demo/pruebas) no tiene DECIMAL nativo; MySQL sí. El aviso no aplica a producción.
warnings.filterwarnings("ignore", message=".*does \\*not\\* support Decimal.*")

_CONVENCION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

ID = BigInteger().with_variant(Integer, "sqlite")  # autoincrement también en SQLite
_MYSQL = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4"}


def _ahora():
    return a_naive_utc(utcnow())


# =============================================================================== BASE A
meta_usuarios = MetaData(naming_convention=_CONVENCION)

usuarios = Table(
    "usuarios", meta_usuarios,
    Column("id_usuario", ID, primary_key=True, autoincrement=True),
    Column("correo", String(255), nullable=False),
    Column("contrasena_hash", String(255), nullable=False),
    Column("rol", String(20), nullable=False, server_default="COMPRADOR"),
    Column("nombre", String(100), nullable=False),
    Column("apellido", String(100), nullable=False),
    Column("telefono", String(30)),
    Column("estatus", String(20), nullable=False, server_default="ACTIVO"),
    Column("fecha_registro", DateTime, nullable=False, default=_ahora, server_default=text("CURRENT_TIMESTAMP")),
    UniqueConstraint("correo", name="uq_usuarios_correo"),
    CheckConstraint("rol IN ('COMPRADOR','VENDEDOR','ADMIN')", name="rol"),
    CheckConstraint("estatus IN ('ACTIVO','SUSPENDIDO')", name="estatus"),
    Index("ix_usuarios_rol_id", "rol", "id_usuario"),
    **_MYSQL,
)

pagos = Table(
    "pagos", meta_usuarios,
    Column("id_pago", ID, primary_key=True, autoincrement=True),
    Column("id_pedido", ID, nullable=False),  # → pedidos (base B): sin FK
    Column("metodo_pago", String(30), nullable=False),
    Column("estatus", String(20), nullable=False),
    Column("monto", Numeric(12, 2), nullable=False),
    Column("referencia_transaccion", String(100)),
    Column("fecha_pago", DateTime, nullable=False, default=_ahora, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint("estatus IN ('APROBADO','RECHAZADO','REEMBOLSADO')", name="estatus"),
    CheckConstraint("monto >= 0", name="monto"),
    Index("ix_pagos_id_pedido", "id_pedido"),
    **_MYSQL,
)

# =============================================================================== BASE B
meta_ops = MetaData(naming_convention=_CONVENCION)

carritos = Table(
    "carritos", meta_ops,
    Column("id_carrito", ID, primary_key=True, autoincrement=True),
    Column("id_usuario", ID, nullable=False),  # → usuarios (base A): sin FK
    Column("estatus", String(20), nullable=False, server_default="ACTIVO"),
    Column("fecha_creacion", DateTime, nullable=False, default=_ahora, server_default=text("CURRENT_TIMESTAMP")),
    Column("fecha_actualizacion", DateTime, nullable=False, default=_ahora, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint("estatus IN ('ACTIVO','CONVERTIDO','ABANDONADO')", name="estatus"),
    Index("ix_carritos_usuario_estatus", "id_usuario", "estatus"),
    **_MYSQL,
)

detalle_carrito = Table(
    "detalle_carrito", meta_ops,
    Column("id_detalle_carrito", ID, primary_key=True, autoincrement=True),
    Column("id_carrito", ID, ForeignKey("carritos.id_carrito", ondelete="CASCADE"), nullable=False),
    Column("id_variante", String(36), nullable=False),  # → variantes_producto (DynamoDB)
    Column("cantidad", Integer, nullable=False),
    UniqueConstraint("id_carrito", "id_variante", name="uq_detalle_carrito_variante"),
    CheckConstraint("cantidad > 0", name="cantidad"),
    **_MYSQL,
)

pedidos = Table(
    "pedidos", meta_ops,
    Column("id_pedido", ID, primary_key=True, autoincrement=True),
    Column("id_comprador", ID, nullable=False),  # → usuarios (base A): sin FK
    Column("estatus", String(20), nullable=False, server_default="PENDIENTE"),
    Column("monto_total", Numeric(12, 2), nullable=False),
    Column("direccion_envio", String(500), nullable=False),
    Column("fecha_pedido", DateTime, nullable=False, default=_ahora, server_default=text("CURRENT_TIMESTAMP")),
    CheckConstraint("estatus IN ('PENDIENTE','PAGADO','ENVIADO','ENTREGADO','CANCELADO')", name="estatus"),
    CheckConstraint("monto_total >= 0", name="monto_total"),
    Index("ix_pedidos_comprador_id", "id_comprador", "id_pedido"),
    Index("ix_pedidos_estatus_id", "estatus", "id_pedido"),
    **_MYSQL,
)

detalle_pedido = Table(
    "detalle_pedido", meta_ops,
    Column("id_detalle_pedido", ID, primary_key=True, autoincrement=True),
    Column("id_pedido", ID, ForeignKey("pedidos.id_pedido", ondelete="CASCADE"), nullable=False),
    Column("id_variante", String(36), nullable=False),  # → variantes_producto (DynamoDB)
    Column("id_vendedor", ID, nullable=False),          # → usuarios (base A): sin FK
    Column("precio_unitario", Numeric(12, 2), nullable=False),  # congelado al comprar
    Column("cantidad", Integer, nullable=False),
    Column("subtotal", Numeric(12, 2), nullable=False),
    CheckConstraint("cantidad > 0", name="cantidad"),
    Index("ix_detalle_pedido_pedido", "id_pedido"),
    Index("ix_detalle_pedido_vendedor_id", "id_vendedor", "id_detalle_pedido"),
    Index("ix_detalle_pedido_variante", "id_variante"),
    **_MYSQL,
)

BASE_USUARIOS = "mkt_usuarios"
BASE_OPERACIONES = "mkt_operaciones"
