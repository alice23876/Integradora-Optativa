#!/usr/bin/env python
"""Puebla las bases REALES con datos de ejemplo: 17,000 productos (con variantes), categorías,
cuentas de prueba, y unos pedidos con pagos y reseñas.

    python scripts/sembrar_datos.py                      # 17,000 productos
    python scripts/sembrar_datos.py --productos 20000
    python scripts/sembrar_datos.py --sin-pedidos        # solo catálogo y cuentas

Qué hace, en orden (todo es idempotente: puedes repetirlo):
  1. crea las tablas de DynamoDB que falten
  2. crea las tablas MySQL que falten (las bases de datos deben existir; ver crear_esquema_mysql.py)
  3. crea las cuentas de demostración (admin@demo.com / Admin1234, vendedor1@demo.com / Vende1234,
     comprador@demo.com / Compra1234 …)  ⚠ cámbialas o bórralas si la base no es de pruebas
  4. inserta categorías, productos y variantes (los ids son deterministas: repetirlo sobrescribe, no duplica)
  5. crea algunos pedidos/pagos/reseñas (solo si todavía no hay pedidos)
"""
import time

from _comun import barra, config_desde, parser

import boto3

from app.catalogo.dynamo import CatalogoDynamo
from app.catalogo.esquema import crear_tablas
from app.demo_data import sembrar_demo
from app.gateways.directo import GatewayDirecto
from app.relacional.almacen import AlmacenSql
from app.relacional.esquema import meta_ops, meta_usuarios
from app.relacional.motores import crear_motores_mysql


def main() -> int:
    ap = parser(__doc__)
    ap.add_argument("--productos", type=int, default=17_000)
    ap.add_argument("--sin-pedidos", action="store_true")
    ap.add_argument("--semilla", type=int, default=7, help="cambia la semilla para generar otro catálogo")
    ap.add_argument("--sí", "--si", dest="si", action="store_true", help="no pedir confirmación")
    args = ap.parse_args()
    cfg = config_desde(args)

    destino = cfg.dynamo_endpoint or f"AWS DynamoDB ({cfg.aws_region})"
    print(f"Destino del catálogo : {destino}  (prefijo «{cfg.dynamo_prefijo}»)")
    for etiqueta, c in (("MySQL usuarios", cfg.mysql_usuarios), ("MySQL operaciones", cfg.mysql_ops)):
        if not c.configurada:
            print(f"✘ Falta configurar {etiqueta} en el .env (ver .env.example).")
            return 1
        u = c.url if not isinstance(c.url, str) else c.url.split("@")[-1]
        print(f"{etiqueta:<21}: {getattr(u, 'host', u)}/{getattr(u, 'database', '')}")
    if not args.si and input(f"\nSe escribirán ~{args.productos:,} productos y cuentas de prueba. ¿Continuar? [s/N] ").lower() not in ("s", "si", "sí", "y"):
        print("Cancelado.")
        return 0

    t0 = time.time()
    print("\n1/4 Tablas de DynamoDB…")
    cliente = boto3.client("dynamodb", region_name=cfg.aws_region, endpoint_url=cfg.dynamo_endpoint)
    crear_tablas(cliente, cfg.dynamo_prefijo)

    print("2/4 Tablas de MySQL…")
    motor_usuarios, motor_ops = crear_motores_mysql(cfg)
    meta_usuarios.create_all(motor_usuarios)
    meta_ops.create_all(motor_ops)

    gw = GatewayDirecto(CatalogoDynamo(cfg.aws_region, cfg.dynamo_prefijo, cfg.dynamo_endpoint),
                        AlmacenSql(motor_usuarios, motor_ops), bcrypt_rounds=cfg.bcrypt_rounds, etiqueta="siembra")

    con_pedidos = not args.sin_pedidos
    if con_pedidos and sum(gw.sql.contar_pedidos_por_estatus().values()) > 0:
        print("   (ya hay pedidos: no se crean pedidos de ejemplo para no duplicarlos)")
        con_pedidos = False

    print("3/4 Cuentas, catálogo y pedidos de ejemplo…")
    sembrar_demo(gw, args.productos, barra, rounds=cfg.bcrypt_rounds, semilla=args.semilla, con_pedidos=con_pedidos)

    print("4/4 Verificando…")
    for e in gw.estado_conexiones():
        print(f"   {'✔' if e.ok else '✘'} {e.nombre}  {e.detalle}")
    print(f"\nListo en {time.time() - t0:,.0f} s. Abre la app con:  python main.py --modo directo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
