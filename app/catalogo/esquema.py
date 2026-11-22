"""Definición de las 4 tablas de DynamoDB (única fuente de verdad: la usan el script de
creación, las pruebas con moto y la documentación).

Diseño de claves
----------------
categorias         PK id_categoria
productos          PK id_producto
                   GSI gsi_categoria  (id_categoria, fecha_creacion)   → productos por categoría
                   GSI gsi_vendedor   (id_vendedor,  fecha_creacion)   → "mis productos"
                   GSI gsi_busqueda   (bucket_busqueda, titulo_lower)  → búsqueda por prefijo
variantes_producto PK id_variante
                   GSI gsi_producto   (id_producto)                    → variantes de un producto
                   (ítems "SKU#<sku>" = candados de unicidad; no tienen id_producto, por lo que
                    el índice —que es disperso— no los incluye)
resenas            PK id_producto, SK id_usuario  → una reseña por usuario y producto
                   LSI lsi_fecha      (id_producto, fecha_resena)      → más recientes primero

Atributos desnormalizados en `productos` (DynamoDB no tiene JOIN ni agregaciones):
  precio_desde, suma_calificacion, num_resenas, titulo_lower, bucket_busqueda
"""
from __future__ import annotations

import time
from typing import Any

T_CATEGORIAS = "categorias"
T_PRODUCTOS = "productos"
T_VARIANTES = "variantes_producto"
T_RESENAS = "resenas"

# Atributos que forman la clave de cada índice (sirven para reconstruir cursores)
CLAVES_CURSOR = {
    "tabla_productos": ("id_producto",),
    "gsi_categoria": ("id_producto", "id_categoria", "fecha_creacion"),
    "gsi_vendedor": ("id_producto", "id_vendedor", "fecha_creacion"),
    "gsi_busqueda": ("id_producto", "bucket_busqueda", "titulo_lower"),
    "lsi_fecha": ("id_producto", "id_usuario", "fecha_resena"),
}


def _gsi(nombre: str, hash_attr: str, range_attr: str | None = None) -> dict[str, Any]:
    ks = [{"AttributeName": hash_attr, "KeyType": "HASH"}]
    if range_attr:
        ks.append({"AttributeName": range_attr, "KeyType": "RANGE"})
    return {"IndexName": nombre, "KeySchema": ks, "Projection": {"ProjectionType": "ALL"}}


def definiciones(prefijo: str = "") -> list[dict[str, Any]]:
    a = lambda n, t: {"AttributeName": n, "AttributeType": t}  # noqa: E731
    return [
        dict(TableName=f"{prefijo}{T_CATEGORIAS}", BillingMode="PAY_PER_REQUEST",
             KeySchema=[{"AttributeName": "id_categoria", "KeyType": "HASH"}],
             AttributeDefinitions=[a("id_categoria", "S")]),
        dict(TableName=f"{prefijo}{T_PRODUCTOS}", BillingMode="PAY_PER_REQUEST",
             KeySchema=[{"AttributeName": "id_producto", "KeyType": "HASH"}],
             AttributeDefinitions=[a("id_producto", "S"), a("id_categoria", "S"), a("id_vendedor", "N"),
                                   a("fecha_creacion", "S"), a("bucket_busqueda", "S"), a("titulo_lower", "S")],
             GlobalSecondaryIndexes=[_gsi("gsi_categoria", "id_categoria", "fecha_creacion"),
                                     _gsi("gsi_vendedor", "id_vendedor", "fecha_creacion"),
                                     _gsi("gsi_busqueda", "bucket_busqueda", "titulo_lower")]),
        dict(TableName=f"{prefijo}{T_VARIANTES}", BillingMode="PAY_PER_REQUEST",
             KeySchema=[{"AttributeName": "id_variante", "KeyType": "HASH"}],
             AttributeDefinitions=[a("id_variante", "S"), a("id_producto", "S")],
             GlobalSecondaryIndexes=[_gsi("gsi_producto", "id_producto")]),
        dict(TableName=f"{prefijo}{T_RESENAS}", BillingMode="PAY_PER_REQUEST",
             KeySchema=[{"AttributeName": "id_producto", "KeyType": "HASH"},
                        {"AttributeName": "id_usuario", "KeyType": "RANGE"}],
             AttributeDefinitions=[a("id_producto", "S"), a("id_usuario", "N"), a("fecha_resena", "S")],
             LocalSecondaryIndexes=[{"IndexName": "lsi_fecha",
                                     "KeySchema": [{"AttributeName": "id_producto", "KeyType": "HASH"},
                                                   {"AttributeName": "fecha_resena", "KeyType": "RANGE"}],
                                     "Projection": {"ProjectionType": "ALL"}}]),
    ]


def crear_tablas(cliente, prefijo: str = "", esperar: bool = True) -> list[str]:
    """Crea las tablas que no existan. `cliente` es un boto3 client de DynamoDB."""
    existentes: set[str] = set()
    for pagina in cliente.get_paginator("list_tables").paginate():
        existentes.update(pagina["TableNames"])
    creadas = []
    for d in definiciones(prefijo):
        if d["TableName"] in existentes:
            continue
        cliente.create_table(**d)
        creadas.append(d["TableName"])
    if esperar:
        for nombre in creadas:
            cliente.get_waiter("table_exists").wait(TableName=nombre)
            _esperar_indices(cliente, nombre)
    return creadas


def _esperar_indices(cliente, nombre: str, timeout: float = 120) -> None:
    limite = time.time() + timeout
    while time.time() < limite:
        t = cliente.describe_table(TableName=nombre)["Table"]
        if all(g.get("IndexStatus", "ACTIVE") == "ACTIVE" for g in t.get("GlobalSecondaryIndexes", [])):
            return
        time.sleep(1)
