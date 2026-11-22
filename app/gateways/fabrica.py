"""Construye el gateway según el modo configurado (demo | directo | api)."""
from __future__ import annotations

from typing import Callable

from ..config import Config
from ..demo_data import sembrar_demo
from .api import GatewayApi
from .base import Gateway
from .directo import GatewayDirecto

Progreso = Callable[[str, int, int], None]


def crear_gateway_demo(cfg: Config, progreso: Progreso | None = None) -> GatewayDirecto:
    from ..catalogo.memoria import CatalogoMemoria
    from ..relacional.almacen import AlmacenSql
    from ..relacional.motores import crear_motores_sqlite_temporales

    motor_usuarios, motor_ops = crear_motores_sqlite_temporales()
    gw = GatewayDirecto(CatalogoMemoria(), AlmacenSql(motor_usuarios, motor_ops), bcrypt_rounds=4, etiqueta="demo")
    sembrar_demo(gw, cfg.demo_productos, progreso, rounds=4)
    return gw


def crear_gateway_directo(cfg: Config) -> GatewayDirecto:
    from ..catalogo.dynamo import CatalogoDynamo
    from ..relacional.almacen import AlmacenSql
    from ..relacional.motores import crear_motores_mysql

    motor_usuarios, motor_ops = crear_motores_mysql(cfg)
    catalogo = CatalogoDynamo(cfg.aws_region, cfg.dynamo_prefijo, cfg.dynamo_endpoint)
    return GatewayDirecto(catalogo, AlmacenSql(motor_usuarios, motor_ops), bcrypt_rounds=cfg.bcrypt_rounds,
                          etiqueta="directo")


def crear_gateway(cfg: Config, progreso: Progreso | None = None) -> Gateway:
    if cfg.modo == "api":
        return GatewayApi(cfg.api_url, cfg.api_timeout)
    if cfg.modo == "directo":
        return crear_gateway_directo(cfg)
    return crear_gateway_demo(cfg, progreso)
