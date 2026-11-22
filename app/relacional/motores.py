"""Creación de motores SQLAlchemy (MySQL en producción, SQLite en demo/pruebas)."""
from __future__ import annotations

import atexit
import shutil
import tempfile
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine

from ..config import Config, ConexionMySQL
from ..errors import ErrorConexion
from .esquema import meta_ops, meta_usuarios


def crear_motor_mysql(con: ConexionMySQL, nombre: str) -> Engine:
    if not con.configurada:
        raise ErrorConexion(
            f"Falta configurar la conexión MySQL «{nombre}». Define MKT_{nombre.upper()}_HOST, "
            f"_USER, _PASSWORD y _DB en tu archivo .env.")
    connect_args = {"connect_timeout": 8, "read_timeout": 20, "write_timeout": 20}
    if con.ssl_ca:
        connect_args["ssl"] = {"ca": con.ssl_ca}
    return create_engine(
        con.url, pool_size=6, max_overflow=6, pool_pre_ping=True, pool_recycle=1800,
        connect_args=connect_args, future=True,
    )


def crear_motor_sqlite(ruta: str | Path) -> Engine:
    motor = create_engine(f"sqlite:///{ruta}", connect_args={"check_same_thread": False, "timeout": 15},
                          future=True)

    @event.listens_for(motor, "connect")
    def _pragmas(conexion, _):  # noqa: ANN001
        cur = conexion.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=15000")
        cur.close()

    return motor


def crear_motores_mysql(cfg: Config) -> tuple[Engine, Engine]:
    return (crear_motor_mysql(cfg.mysql_usuarios, "usuarios"),
            crear_motor_mysql(cfg.mysql_ops, "ops"))


def crear_motores_sqlite_temporales(directorio: str | Path | None = None) -> tuple[Engine, Engine]:
    """Dos archivos SQLite (uno por «base de datos»), con el esquema ya creado."""
    if directorio is None:
        directorio = tempfile.mkdtemp(prefix="mkt_demo_")
        atexit.register(shutil.rmtree, directorio, ignore_errors=True)
    d = Path(directorio)
    m_usuarios = crear_motor_sqlite(d / "usuarios.db")
    m_ops = crear_motor_sqlite(d / "operaciones.db")
    meta_usuarios.create_all(m_usuarios)
    meta_ops.create_all(m_ops)
    return m_usuarios, m_ops
