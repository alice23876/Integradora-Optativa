"""Configuración. Prioridad: ajustes guardados desde la UI > variables de entorno / .env > valores por defecto.

Los secretos (contraseñas de MySQL, credenciales AWS) NUNCA se guardan desde la UI:
se leen del entorno / .env / perfil de AWS.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, replace

from dotenv import load_dotenv
from sqlalchemy.engine import URL

MODOS = ("demo", "directo", "api")
DESCRIPCION_MODOS = {
    "demo": "Demostración: datos de ejemplo en memoria (17,000 productos). No necesita AWS ni MySQL.",
    "directo": "Directo: se conecta a DynamoDB y a las 2 bases MySQL con las credenciales del .env.",
    "api": "API: habla con tu backend Python por HTTP (el que construiremos después).",
}


@dataclass
class ConexionMySQL:
    url: URL | str | None = None
    ssl_ca: str | None = None

    @property
    def configurada(self) -> bool:
        return self.url is not None


@dataclass
class Config:
    modo: str = "demo"
    api_url: str = "http://localhost:8000"
    api_timeout: float = 15.0
    aws_region: str = "us-east-1"
    dynamo_endpoint: str | None = None      # p. ej. http://localhost:8000 (DynamoDB Local)
    dynamo_prefijo: str = ""                # p. ej. "mkt_" → mkt_productos
    mysql_usuarios: ConexionMySQL = field(default_factory=ConexionMySQL)
    mysql_ops: ConexionMySQL = field(default_factory=ConexionMySQL)
    bcrypt_rounds: int = 12
    demo_productos: int = 17_000
    tamano_pagina: int = 24

    def con(self, **cambios) -> "Config":
        return replace(self, **cambios)


def _mysql_desde_entorno(prefijo: str) -> ConexionMySQL:
    """MKT_<PREFIJO>_URL (URL completa de SQLAlchemy) o por partes:
    MKT_<PREFIJO>_HOST / _PORT / _DB / _USER / _PASSWORD / _SSL_CA"""
    env = os.environ
    url_completa = env.get(f"MKT_{prefijo}_URL")
    ssl_ca = env.get(f"MKT_{prefijo}_SSL_CA") or None
    if url_completa:
        return ConexionMySQL(url_completa, ssl_ca)
    host = env.get(f"MKT_{prefijo}_HOST")
    if not host:
        return ConexionMySQL(None, ssl_ca)
    url = URL.create(
        "mysql+pymysql",
        username=env.get(f"MKT_{prefijo}_USER", "root"),
        password=env.get(f"MKT_{prefijo}_PASSWORD") or None,
        host=host,
        port=int(env.get(f"MKT_{prefijo}_PORT", "3306")),
        database=env.get(f"MKT_{prefijo}_DB", f"mkt_{prefijo.lower()}"),
        query={"charset": "utf8mb4"},
    )
    return ConexionMySQL(url, ssl_ca)


def cargar_config(archivo_env: str | None = None, sobrescribir: dict | None = None) -> Config:
    load_dotenv(archivo_env, override=False)
    env = os.environ
    cfg = Config(
        modo=env.get("MKT_MODO", "demo").lower(),
        api_url=env.get("MKT_API_URL", "http://localhost:8000").rstrip("/"),
        api_timeout=float(env.get("MKT_API_TIMEOUT", "15")),
        aws_region=env.get("AWS_REGION") or env.get("AWS_DEFAULT_REGION") or "us-east-1",
        dynamo_endpoint=env.get("MKT_DYNAMO_ENDPOINT") or None,
        dynamo_prefijo=env.get("MKT_DYNAMO_PREFIJO", ""),
        mysql_usuarios=_mysql_desde_entorno("USUARIOS"),
        mysql_ops=_mysql_desde_entorno("OPS"),
        bcrypt_rounds=int(env.get("MKT_BCRYPT_ROUNDS", "12")),
        demo_productos=int(env.get("MKT_DEMO_PRODUCTOS", "17000")),
        tamano_pagina=int(env.get("MKT_TAMANO_PAGINA", "24")),
    )
    if sobrescribir:
        validos = {k: v for k, v in sobrescribir.items() if v not in (None, "")}
        cfg = cfg.con(**validos)
    if cfg.modo not in MODOS:
        cfg = cfg.con(modo="demo")
    return cfg
