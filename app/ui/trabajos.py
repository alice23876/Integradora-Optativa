"""Ejecución de llamadas lentas (red, bases de datos) fuera del hilo de la interfaz.

Regla de oro de Qt: la UI solo se toca desde el hilo principal. Por eso cada llamada
al gateway se ejecuta en un hilo del pool y su resultado vuelve por una señal en cola,
que Qt entrega en el hilo principal.
"""
from __future__ import annotations

import itertools
import logging
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot
from shiboken6 import isValid

from ..errors import ErrorMarketplace

log = logging.getLogger(__name__)


class _Senales(QObject):
    listo = Signal(int, object, object)


class _Tarea(QRunnable):
    def __init__(self, id_: int, fn: Callable[[], Any], senales: _Senales):
        super().__init__()
        self.id_, self.fn, self.senales = id_, fn, senales
        self.setAutoDelete(True)

    def run(self) -> None:
        resultado, error = None, None
        try:
            resultado = self.fn()
        except BaseException as exc:  # noqa: BLE001
            error = exc
            if not isinstance(exc, ErrorMarketplace):
                log.exception("Error inesperado en tarea en segundo plano")
        self.senales.listo.emit(self.id_, resultado, error)


class Trabajos(QObject):
    """Debe crearse en el hilo principal."""

    def __init__(self, hilos: int = 6):
        super().__init__()
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(hilos)
        self._senales = _Senales()
        self._senales.listo.connect(self._terminado)
        self._ids = itertools.count(1)
        self._callbacks: dict[int, tuple[Callable | None, Callable | None, QObject | None]] = {}
        self.pendientes = 0

    def ejecutar(self, fn: Callable[[], Any], ok: Callable[[Any], None] | None = None,
                 error: Callable[[BaseException], None] | None = None, destino: QObject | None = None) -> int:
        """`ok`/`error` se invocan en el hilo principal, y solo si `destino` sigue vivo."""
        id_ = next(self._ids)
        self._callbacks[id_] = (ok, error, destino)
        self.pendientes += 1
        self._pool.start(_Tarea(id_, fn, self._senales))
        return id_

    @Slot(int, object, object)
    def _terminado(self, id_: int, resultado: Any, error: BaseException | None) -> None:
        ok, err, destino = self._callbacks.pop(id_, (None, None, None))
        self.pendientes -= 1
        if destino is not None and not isValid(destino):
            return  # la pantalla se cerró mientras esperábamos
        try:
            if error is not None:
                if err:
                    err(error)
                else:
                    log.error("Error sin manejar: %r", error)
            elif ok:
                ok(resultado)
        except RuntimeError:
            log.debug("Widget destruido antes de recibir el resultado", exc_info=True)

    def esperar(self, ms: int = 15000) -> bool:
        return self._pool.waitForDone(ms)
