"""Estado compartido de la sesión de UI: gateway, hilos, categorías y carrito."""
from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QObject, QSettings, Signal

from ..categorias import ArbolCategorias
from ..config import Config
from ..errors import ErrorAutenticacion, ErrorMarketplace
from ..gateways.base import Gateway
from ..models import Usuario
from .trabajos import Trabajos
from .widgets import mostrar_error


class Contexto(QObject):
    carrito_actualizado = Signal(int)
    sesion_expirada = Signal()
    mensaje = Signal(str)
    navegar = Signal(str)

    def __init__(self, gateway: Gateway, cfg: Config, trabajos: Trabajos, parent=None):
        super().__init__(parent)
        self.gw = gateway
        self.cfg = cfg
        self.trabajos = trabajos
        self.arbol: ArbolCategorias | None = None
        self.pedido_a_seleccionar: int | None = None
        self.ajustes = QSettings("Marketplace", "MarketplaceGUI")

    # ------------------------------------------------------------------ usuario
    @property
    def usuario(self) -> Usuario:
        return self.gw.sesion.usuario  # type: ignore[union-attr]

    @property
    def rol(self) -> str:
        return self.usuario.rol

    @property
    def puede_comprar(self) -> bool:
        return self.rol in ("COMPRADOR", "VENDEDOR")

    # ------------------------------------------------------------------ llamadas asíncronas
    def ejecutar(self, destino, fn: Callable[[], Any], ok: Callable[[Any], None] | None = None,
                 error: Callable[[BaseException], None] | None = None) -> int:
        """Ejecuta `fn` (llamada al gateway) en segundo plano. Si `error` no se indica, se muestra
        un cuadro de diálogo estándar; una sesión expirada devuelve al usuario al inicio de sesión."""

        def por_defecto(exc: BaseException) -> None:
            if isinstance(exc, ErrorAutenticacion) and self.gw.sesion is not None:
                self.sesion_expirada.emit()
                return
            mostrar_error(destino if hasattr(destino, "window") else None, exc)

        def con_filtro(exc: BaseException) -> None:
            if isinstance(exc, ErrorAutenticacion) and self.gw.sesion is not None:
                self.sesion_expirada.emit()
                return
            (error or por_defecto)(exc)

        return self.trabajos.ejecutar(fn, ok, con_filtro, destino)

    # ------------------------------------------------------------------ categorías (se cachean)
    def cargar_categorias(self, destino, ok: Callable[[ArbolCategorias], None], forzar: bool = False) -> None:
        if self.arbol is not None and not forzar:
            ok(self.arbol)
            return

        def recibido(cats):
            self.arbol = ArbolCategorias(cats)
            ok(self.arbol)

        self.ejecutar(destino, self.gw.listar_categorias, recibido)

    # ------------------------------------------------------------------ carrito
    def refrescar_carrito(self) -> None:
        if not self.puede_comprar:
            return
        self.ejecutar(self, self.gw.obtener_carrito, lambda c: self.carrito_actualizado.emit(c.num_articulos),
                      lambda exc: None)

    def avisar(self, texto: str) -> None:
        self.mensaje.emit(texto)
