#!/usr/bin/env python
"""Comprueba, sin abrir la interfaz, que DynamoDB y las 2 bases MySQL (o tu backend) responden.

    python scripts/probar_conexiones.py                 # usa MKT_MODO del .env (directo por defecto aquí)
    python scripts/probar_conexiones.py --modo api
"""
from _comun import config_desde, parser

from app.ui.ajustes import probar_config  # no abre ventanas: solo reutiliza la comprobación


def main() -> int:
    ap = parser(__doc__)
    ap.add_argument("--modo", choices=("directo", "api"), default="directo")
    args = ap.parse_args()
    cfg = config_desde(args, modo=args.modo)
    try:
        estados = probar_config(cfg)
    except Exception as exc:  # noqa: BLE001
        print("✘", getattr(exc, "mensaje", None) or exc)
        return 1
    for e in estados:
        ms = f"{e.latencia_ms:.0f} ms" if e.latencia_ms is not None else "—"
        print(f"{'✔' if e.ok else '✘'} {e.nombre:<34} {ms:>8}   {e.detalle}")
    return 0 if all(e.ok for e in estados) else 1


if __name__ == "__main__":
    raise SystemExit(main())
