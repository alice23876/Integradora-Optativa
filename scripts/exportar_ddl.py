#!/usr/bin/env python
"""Genera el SQL (DDL) de MySQL a partir del esquema de la aplicación, para que lo revises o lo
ejecutes con tu propia herramienta (MySQL Workbench, Flyway, RDS Query Editor…).

    python scripts/exportar_ddl.py            # escribe sql/mysql_usuarios_pagos.sql y sql/mysql_operaciones.sql
"""
from _comun import RAIZ

from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.relacional.esquema import BASE_OPERACIONES, BASE_USUARIOS, meta_ops, meta_usuarios


def ddl(meta) -> str:
    d = mysql.dialect()
    partes = []
    for tabla in meta.sorted_tables:
        partes.append(str(CreateTable(tabla).compile(dialect=d)).strip() + ";")
        for ix in sorted(tabla.indexes, key=lambda i: i.name):
            partes.append(str(CreateIndex(ix).compile(dialect=d)).strip() + ";")
    return "\n\n".join(partes)


def escribir(nombre_archivo: str, base: str, titulo: str, meta) -> None:
    cuerpo = (f"-- {titulo}\n-- Generado por scripts/exportar_ddl.py a partir de app/relacional/esquema.py. No lo edites a mano.\n"
              f"-- Requiere MySQL 8.0.16+ (las restricciones CHECK se aplican desde esa versión).\n\n"
              f"CREATE DATABASE IF NOT EXISTS `{base}` CHARACTER SET utf8mb4;\nUSE `{base}`;\n\n"
              f"{ddl(meta)}\n")
    destino = RAIZ / "sql" / nombre_archivo
    destino.parent.mkdir(exist_ok=True)
    destino.write_text(cuerpo, encoding="utf-8")
    print("escrito", destino.relative_to(RAIZ))


if __name__ == "__main__":
    escribir("mysql_usuarios_pagos.sql", BASE_USUARIOS, "Base A: usuarios y pagos", meta_usuarios)
    escribir("mysql_operaciones.sql", BASE_OPERACIONES, "Base B: carritos, detalle_carrito, pedidos y detalle_pedido", meta_ops)
