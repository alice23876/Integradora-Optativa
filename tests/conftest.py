"""Fixture `mundo`: el mismo escenario sobre 3 backends distintos.

  memoria → GatewayDirecto + catálogo en memoria + SQLite
  dynamo  → GatewayDirecto + DynamoDB simulado con moto + SQLite
  api     → GatewayApi (HTTP falso) → GatewayDirecto con catálogo en memoria
  mysql   → catálogo en memoria + las 2 bases en un servidor MySQL/MariaDB REAL (solo si defines
            MKT_TEST_MYSQL, p. ej. «mysql+pymysql://root@127.0.0.1:3307»; usa/limpia las bases
            mkt_test_usuarios y mkt_test_ops, así que apúntalo a un servidor de pruebas)

Si un test pasa en todos, la interfaz se comporta igual con cualquiera.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import pytest
import requests

os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

from app.catalogo.dynamo import CatalogoDynamo  # noqa: E402
from app.catalogo.esquema import crear_tablas  # noqa: E402
from app.catalogo.memoria import CatalogoMemoria  # noqa: E402
from app.demo_data import CUENTAS_DEMO, sembrar_demo  # noqa: E402
from app.gateways.api import GatewayApi  # noqa: E402
from app.gateways.directo import GatewayDirecto  # noqa: E402
from app.models import Producto, Variante  # noqa: E402
from app.relacional.almacen import AlmacenSql  # noqa: E402
from app.relacional.esquema import meta_ops, meta_usuarios  # noqa: E402
from app.relacional.motores import crear_motores_sqlite_temporales  # noqa: E402

from .fake_api import FakeApi  # noqa: E402

N_PRODUCTOS = 150
PASSWORDS = {c.correo: c.password for c in CUENTAS_DEMO}


@dataclass
class Mundo:
    gw: object                 # interfaz bajo prueba (Gateway)
    nucleo: GatewayDirecto     # puerta trasera para manipular datos
    productos: list[Producto]
    tipo: str
    http: FakeApi | None = None
    _pedidos_creados: list = field(default_factory=list)

    def entrar(self, correo: str):
        self.gw.logout()
        return self.gw.login(correo, PASSWORDS[correo])

    # ---------- ayudas para escoger datos del catálogo sembrado
    @property
    def cat(self):
        return self.nucleo.catalogo

    def vendedor_id(self, correo: str) -> int:
        return self.nucleo.sql.usuario_con_hash_por_correo(correo)[0].id_usuario

    def variante_con_stock(self, minimo: int = 5, no_vendedor: int | None = None, excluir: set[str] | None = None):
        for p in self.productos:
            if no_vendedor is not None and p.id_vendedor == no_vendedor:
                continue
            if excluir and p.id_producto in excluir:
                continue
            for v in p.variantes:
                if v.cantidad_stock >= minimo:
                    return p, v
        raise AssertionError("No hay variante con stock suficiente en el escenario")


def _sembrar(nucleo: GatewayDirecto) -> list[Producto]:
    capturado: list[Producto] = []
    original = nucleo.catalogo.insertar_masivo

    def espia(categorias, productos, *a, **k):
        capturado.extend(productos)
        return original(categorias, productos, *a, **k)

    nucleo.catalogo.insertar_masivo = espia  # type: ignore[method-assign]
    sembrar_demo(nucleo, N_PRODUCTOS, rounds=4, con_pedidos=False)
    nucleo.catalogo.insertar_masivo = original  # type: ignore[method-assign]
    return capturado


def _motores_mysql(base_url: str):
    from sqlalchemy import create_engine

    motores = []
    for nombre, meta in (("mkt_test_usuarios", meta_usuarios), ("mkt_test_ops", meta_ops)):
        m = create_engine(f"{base_url}/{nombre}?charset=utf8mb4", pool_size=6, max_overflow=6, pool_pre_ping=True)
        meta.drop_all(m)
        meta.create_all(m)
        motores.append(m)
    return motores


_PARAMS = ["memoria", "dynamo", "api"] + (["mysql"] if os.environ.get("MKT_TEST_MYSQL") else [])


@pytest.fixture(params=_PARAMS)
def mundo(request):
    tipo = request.param
    mock = None
    if tipo == "dynamo":
        from moto import mock_aws
        import boto3

        mock = mock_aws()
        mock.start()
        crear_tablas(boto3.client("dynamodb", region_name="us-east-1"), "t_")
        catalogo = CatalogoDynamo("us-east-1", "t_")
    else:
        catalogo = CatalogoMemoria()
    if tipo == "mysql":
        m_usuarios, m_ops = _motores_mysql(os.environ["MKT_TEST_MYSQL"])
    else:
        m_usuarios, m_ops = crear_motores_sqlite_temporales()
    nucleo = GatewayDirecto(catalogo, AlmacenSql(m_usuarios, m_ops), bcrypt_rounds=4, etiqueta=tipo)
    productos = _sembrar(nucleo)
    http = None
    gw = nucleo
    if tipo == "api":
        http = FakeApi(nucleo)
        sesion_http = requests.Session()
        sesion_http.mount("http://", http)
        gw = GatewayApi("http://backend.test", http=sesion_http)
    try:
        yield Mundo(gw=gw, nucleo=nucleo, productos=productos, tipo=tipo, http=http)
    finally:
        if mock:
            mock.stop()
