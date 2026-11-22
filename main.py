"""Punto de entrada.

    python main.py                  # modo demo (por defecto): no necesita AWS ni MySQL
    python main.py --modo directo   # DynamoDB + 2 MySQL con las credenciales del .env
    python main.py --modo api       # tu backend Python (MKT_API_URL)
"""
from __future__ import annotations

import argparse
import logging
import sys

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from app.config import MODOS, cargar_config
from app.ui.ajustes import leer_ajustes
from app.ui.main_window import MainWindow
from app.ui.theme import aplicar_tema
from app.ui.trabajos import Trabajos


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Marketplace — interfaz gráfica")
    ap.add_argument("--modo", choices=MODOS, help="demo | directo | api (por defecto: el último usado o MKT_MODO)")
    ap.add_argument("--env", help="ruta de un archivo .env distinto")
    ap.add_argument("--productos", type=int, help="cantidad de productos de ejemplo en modo demo (por defecto 17000)")
    ap.add_argument("--verbose", action="store_true")
    args, resto = ap.parse_known_args(argv if argv is not None else sys.argv[1:])
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    app = QApplication([sys.argv[0], *resto])
    app.setApplicationName("Marketplace")
    app.setOrganizationName("Marketplace")
    aplicar_tema(app)

    # Prioridad: línea de comandos > ajustes guardados desde la interfaz > .env / variables de entorno > valores por defecto
    guardados = leer_ajustes(QSettings("Marketplace", "MarketplaceGUI"))
    sobrescribir = {k: v for k, v in guardados.items() if v}
    if args.modo:
        sobrescribir["modo"] = args.modo
    if args.productos:
        sobrescribir["demo_productos"] = args.productos
    cfg = cargar_config(args.env, sobrescribir)

    trabajos = Trabajos()
    ventana = MainWindow(cfg, trabajos)
    ventana.show()
    ventana.iniciar()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
