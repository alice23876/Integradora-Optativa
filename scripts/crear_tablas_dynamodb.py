#Categroias!/usr/bin/env python
"""Crea en DynamoDB las 4 tablas del catálogo (categorias, productos, variantes_producto, resenas)
con sus índices. Es idempotente: las tablas que ya existen se dejan como están.

    python scripts/crear_tablas_dynamodb.py
    python scripts/crear_tablas_dynamodb.py --endpoint http://localhost:8000      # DynamoDB Local
    python scripts/crear_tablas_dynamodb.py --prefijo dev_ --region us-east-2

Credenciales: las normales de AWS (variables AWS_ACCESS_KEY_ID/…, perfil con AWS_PROFILE, o rol de IAM).
Permisos mínimos: dynamodb:CreateTable, DescribeTable, ListTables.
"""
from _comun import config_desde, parser

import boto3

from app.catalogo.esquema import crear_tablas, definiciones


def main() -> int:
    ap = parser(__doc__)
    ap.add_argument("--region")
    ap.add_argument("--endpoint", help="URL de DynamoDB Local u otro endpoint compatible")
    ap.add_argument("--prefijo", help="prefijo de los nombres de tabla (ej. dev_)")
    ap.add_argument("--solo-mostrar", action="store_true", help="imprime el diseño y sale sin tocar AWS")
    args = ap.parse_args()
    cfg = config_desde(args, aws_region=args.region, dynamo_endpoint=args.endpoint, dynamo_prefijo=args.prefijo)

    if args.solo_mostrar:
        for d in definiciones(cfg.dynamo_prefijo):
            claves = ", ".join(f"{k['AttributeName']} ({k['KeyType']})" for k in d["KeySchema"])
            print(f"\n{d['TableName']}\n  clave: {claves}")
            for g in d.get("GlobalSecondaryIndexes", []):
                print("  GSI", g["IndexName"], "→", ", ".join(k["AttributeName"] for k in g["KeySchema"]))
            for g in d.get("LocalSecondaryIndexes", []):
                print("  LSI", g["IndexName"], "→", ", ".join(k["AttributeName"] for k in g["KeySchema"]))
        return 0

    cliente = boto3.client("dynamodb", region_name=cfg.aws_region, endpoint_url=cfg.dynamo_endpoint)
    destino = cfg.dynamo_endpoint or f"AWS ({cfg.aws_region})"
    print(f"Creando tablas en {destino} con prefijo «{cfg.dynamo_prefijo}»…")
    creadas = crear_tablas(cliente, cfg.dynamo_prefijo)
    if creadas:
        print("Creadas:", ", ".join(creadas))
    else:
        print("Todas las tablas ya existían. No se cambió nada.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
