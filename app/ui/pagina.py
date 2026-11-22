"""Clase base de las pantallas que se muestran en el área principal."""
from __future__ import annotations

from PySide6.QtWidgets import QWidget

from .contexto import Contexto


class PaginaBase(QWidget):
    def __init__(self, ctx: Contexto, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setProperty("pagina", True)
        self._visible_antes = False

    def al_mostrar(self) -> None:
        """El shell lo llama cada vez que el usuario entra a esta pantalla (refresca datos)."""

    def al_cerrar_sesion(self) -> None:
        """Libera datos de la sesión anterior."""
