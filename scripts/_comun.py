"""Utilidades compartidas por los scripts (permiten ejecutarlos desde cualquier carpeta)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from app.config import Config, cargar_config  # noqa: E402


def parser(descripcion: str) -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=descripcion)
    ap.add_argument("--env", help="ruta de un archivo .env (por defecto, el de la carpeta actual)")
    return ap


def config_desde(args, **extra) -> Config:
    return cargar_config(args.env, {k: v for k, v in extra.items() if v not in (None, "")})


def barra(texto: str, actual: int, total: int) -> None:
    """Progreso de una sola línea en la terminal."""
    if total:
        pct = actual * 100 // total
        print(f"\r  {texto:<40} {actual:>7,}/{total:<7,} {pct:>3}%", end="", flush=True)
        if actual >= total:
            print()
    else:
        print(f"  {texto}")
