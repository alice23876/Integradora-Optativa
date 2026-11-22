#!/usr/bin/env python
"""Crea las tablas de las 2 bases MySQL (idempotente) y, si lo pides, las bases de datos.

    Base A (usuarios, pagos)                                   → variables MKT_USUARIOS_*
    Base B (carritos, detalle_carrito, pedidos, detalle_pedido) → variables MKT_OPS_*

    python scripts/crear_esquema_mysql.py                    # las bases ya existen
    python scripts/crear_esquema_mysql.py --crear-bases      # además hace CREATE DATABASE IF NOT EXISTS

Si prefieres revisar el SQL antes de ejecutarlo: python scripts/exportar_ddl.py
"""
from _comun import config_desde, parser

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy import create_engine

from app.relacional.esquema import meta_ops, meta_usuarios
from app.relacional.motores import crear_motor_mysql


def crear_base_si_falta(conexion) -> None:
    url = make_url(conexion.url) if isinstance(conexion.url, str) else conexion.url
    base = url.database
    motor = create_engine(url._replace(database=None))  # (url.set(database=None) ignora los None)
    with motor.begin() as cx:
        cx.execute(text(f"CREATE DATABASE IF NOT EXISTS `{base}` CHARACTER SET utf8mb4"))
    motor.dispose()
    print(f"  base «{base}» lista")


def main() -> int:
    ap = parser(__doc__)
    ap.add_argument("--crear-bases", action="store_true", help="ejecuta CREATE DATABASE IF NOT EXISTS (requiere ese permiso)")
    args = ap.parse_args()
    cfg = config_desde(args)

    for nombre, conexion, meta in (("usuarios", cfg.mysql_usuarios, meta_usuarios), ("ops", cfg.mysql_ops, meta_ops)):
        print(f"Base «{nombre}»:")
        if args.crear_bases and conexion.configurada:
            crear_base_si_falta(conexion)
        motor = crear_motor_mysql(conexion, nombre)
        meta.create_all(motor)
        print("  tablas:", ", ".join(meta.tables))
        motor.dispose()
    print("Listo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
