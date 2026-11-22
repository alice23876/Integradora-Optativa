"""Carga por páginas con cursor (para tablas largas: usuarios, pagos, ventas, productos…).

Nunca se pide «todo»: cada llamada trae una página y el botón «Cargar más» pide la siguiente.
Un contador de generaciones descarta respuestas viejas (si el usuario cambió un filtro mientras
llegaba la respuesta anterior).
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import QPushButton

from ..models import Pagina
from .contexto import Contexto
from .widgets import Indicador, mostrar_error


class CargaPaginada:
    def __init__(self, ctx: Contexto, destino, indicador: Indicador, boton_mas: QPushButton,
                 pedir: Callable[[str | None], Pagina], recibir: Callable[[list, bool], None],
                 al_terminar: Callable[[], None] | None = None):
        """pedir(cursor) se ejecuta en segundo plano; recibir(items, es_primera) en el hilo de la interfaz."""
        self.ctx, self.destino, self.indicador, self.boton_mas = ctx, destino, indicador, boton_mas
        self._pedir, self._recibir, self._al_terminar = pedir, recibir, al_terminar
        self._gen = 0
        self._cursor: str | None = None
        self._cargando = False
        self.boton_mas.setVisible(False)
        self.boton_mas.clicked.connect(lambda _=False: self.siguiente())

    @property
    def hay_mas(self) -> bool:
        return self._cursor is not None

    def reiniciar(self) -> None:
        if self._cargando:
            self.indicador.fin()  # la respuesta pendiente quedará descartada por la generación
        self._gen += 1
        self._cursor, self._cargando = None, False
        self._lanzar(None, True)

    def siguiente(self) -> None:
        if self._cargando or self._cursor is None:
            return
        self._lanzar(self._cursor, False)

    def invalidar(self) -> None:
        """Descarta cualquier respuesta en vuelo y deja el botón oculto (p. ej. al cerrar sesión)."""
        if self._cargando:
            self.indicador.fin()
        self._gen += 1
        self._cursor, self._cargando = None, False
        self.boton_mas.setVisible(False)

    def _lanzar(self, cursor: str | None, primera: bool) -> None:
        self._cargando = True
        self.boton_mas.setVisible(False)
        self.indicador.inicio()
        gen = self._gen
        self.ctx.ejecutar(self.destino, lambda: self._pedir(cursor),
                          lambda pag: self._llego(gen, pag, primera), lambda exc: self._fallo(gen, exc))

    def _llego(self, gen: int, pag: Pagina, primera: bool) -> None:
        if gen != self._gen:
            return
        self._cargando = False
        self.indicador.fin()
        self._cursor = pag.siguiente
        self._recibir(pag.items, primera)
        self.boton_mas.setVisible(self._cursor is not None)
        if self._al_terminar:
            self._al_terminar()

    def _fallo(self, gen: int, exc: BaseException) -> None:
        if gen != self._gen:
            return
        self._cargando = False
        self.indicador.fin()
        self.boton_mas.setVisible(self._cursor is not None)
        mostrar_error(self.destino, exc)
