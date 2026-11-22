"""Diálogo de conexión: elegir el modo (demo / directo / API) y probarlo antes de guardar."""
from __future__ import annotations

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtWidgets import (QButtonGroup, QDialog, QHBoxLayout, QLineEdit, QRadioButton, QVBoxLayout)

from ..config import MODOS, Config
from ..models import EstadoConexion
from . import theme
from .trabajos import Trabajos
from .widgets import Indicador, boton, etiqueta, fijar_alturas_de_texto, tarjeta

NOMBRES_MODO = {"demo": "Demostración", "directo": "Directo a las bases de datos", "api": "Mi backend (API)"}
AYUDA_MODO = {
    "demo": "Datos de ejemplo en tu computadora (17,000 productos). No necesita AWS ni MySQL: ideal para conocer la aplicación.",
    "directo": "Se conecta a DynamoDB y a las 2 bases MySQL con las credenciales de tu archivo .env.",
    "api": "Habla con tu backend Python por HTTP (el que construiremos después).",
}


def _sangrado(w) -> QHBoxLayout:
    """El texto largo va con sangría usando un espacio (los márgenes de un QLabel con saltos de línea miden mal)."""
    fila = QHBoxLayout()
    fila.setContentsMargins(0, 0, 0, 0)
    fila.addSpacing(26)
    fila.addWidget(w, 1)
    return fila


def guardar_ajustes(ajustes: QSettings, modo: str, api_url: str) -> None:
    ajustes.setValue("modo", modo)
    ajustes.setValue("api_url", api_url)
    ajustes.sync()


def leer_ajustes(ajustes: QSettings) -> dict:
    return {"modo": ajustes.value("modo", None, str), "api_url": ajustes.value("api_url", None, str)}


def probar_config(cfg: Config) -> list[EstadoConexion]:
    """Se ejecuta en segundo plano. No inicia sesión: solo comprueba que los servicios responden."""
    if cfg.modo == "demo":
        return [EstadoConexion("Modo demostración", "memoria", True,
                               f"{cfg.demo_productos:,} productos de ejemplo; no usa AWS ni MySQL", 0.0)]
    if cfg.modo == "api":
        from ..gateways.api import GatewayApi
        return GatewayApi(cfg.api_url, cfg.api_timeout).estado_conexiones()
    from ..gateways.fabrica import crear_gateway_directo
    return crear_gateway_directo(cfg).estado_conexiones()


class AjustesDialog(QDialog):
    def __init__(self, cfg: Config, trabajos: Trabajos, parent=None):
        super().__init__(parent)
        self.cfg, self.trabajos = cfg, trabajos
        self.modo = cfg.modo
        self.api_url = cfg.api_url
        self.setWindowTitle("Conexión")
        self.setModal(True)
        self.setFixedWidth(680)
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 22, 24, 18)
        v.setSpacing(12)
        v.addWidget(etiqueta("¿De dónde salen los datos?", "titulo"))
        v.addWidget(etiqueta("Elige cómo se conecta la aplicación. Puedes cambiarlo cuando quieras; "
                             "al guardar se pedirá iniciar sesión de nuevo.", "subtitulo", wrap=True))

        self.grupo = QButtonGroup(self)
        self._radios: dict[str, QRadioButton] = {}
        for m in MODOS:
            caja = tarjeta()
            cv = QVBoxLayout(caja)
            cv.setContentsMargins(16, 12, 16, 12)
            cv.setSpacing(2)
            r = QRadioButton(NOMBRES_MODO[m])
            r.setStyleSheet("font-weight:700; font-size:11pt;")
            r.setChecked(m == cfg.modo)
            r.toggled.connect(self._cambio_modo)
            self.grupo.addButton(r)
            self._radios[m] = r
            cv.addWidget(r)
            cv.addLayout(_sangrado(etiqueta(AYUDA_MODO[m], "muted", wrap=True)))
            if m == "api":
                fila = QHBoxLayout()
                fila.setContentsMargins(26, 6, 0, 0)
                self.url = QLineEdit(cfg.api_url)
                self.url.setPlaceholderText("http://localhost:8000")
                fila.addWidget(etiqueta("Dirección del backend:", "muted"))
                fila.addWidget(self.url, 1)
                cv.addLayout(fila)
            if m == "directo":
                n = etiqueta("Las credenciales se leen del archivo <b>.env</b> o de tu perfil de AWS (nunca se guardan aquí). Úsalo solo en desarrollo.", "muted", wrap=True)
                cv.addLayout(_sangrado(n))
            v.addWidget(caja)

        self.resultado = etiqueta("", wrap=True)
        self.resultado.setTextFormat(Qt.RichText)
        v.addWidget(self.resultado)
        self.indicador = Indicador()
        v.addWidget(self.indicador)
        fila = QHBoxLayout()
        self.btn_probar = boton("Probar conexión", "secondary", self._probar)
        fila.addWidget(self.btn_probar)
        fila.addStretch(1)
        fila.addWidget(boton("Cancelar", al_pulsar=self.reject))
        fila.addWidget(boton("Guardar y usar", "primary", self._guardar))
        v.addLayout(fila)
        self._cambio_modo()

    def showEvent(self, e) -> None:  # noqa: N802
        super().showEvent(e)
        QTimer.singleShot(0, self._medir)  # ya con el ancho real, para que los textos largos midan bien

    def _medir(self) -> None:
        fijar_alturas_de_texto(self)
        self.layout().invalidate()
        self.adjustSize()

    def _modo_elegido(self) -> str:
        return next(m for m, r in self._radios.items() if r.isChecked())

    def _cambio_modo(self, *_):
        if hasattr(self, "url") and "api" in self._radios:
            self.url.setEnabled(self._radios["api"].isChecked())

    def _cfg_elegida(self) -> Config:
        return self.cfg.con(modo=self._modo_elegido(), api_url=self.url.text().strip().rstrip("/") or self.cfg.api_url)

    def _probar(self) -> None:
        cfg = self._cfg_elegida()
        self.resultado.setText("")
        self.btn_probar.setEnabled(False)
        self.indicador.inicio()

        def listo(estados: list[EstadoConexion]) -> None:
            self.indicador.fin()
            self.btn_probar.setEnabled(True)
            lineas = []
            for e in estados:
                color, marca = (theme.OK, "✔") if e.ok else (theme.DANGER, "✘")
                ms = f" · {e.latencia_ms:.0f} ms" if e.latencia_ms is not None else ""
                detalle = (e.detalle or "")[:160]
                lineas.append(f"<span style='color:{color}'><b>{marca} {e.nombre}</b></span>{ms}"
                              f"<br><span style='color:{theme.MUTED}'>{detalle}</span>")
            self.resultado.setText("<br>".join(lineas))
            QTimer.singleShot(0, self._medir)

        def fallo(exc: BaseException) -> None:
            self.indicador.fin()
            self.btn_probar.setEnabled(True)
            texto = getattr(exc, "mensaje", None) or f"{exc.__class__.__name__}: {exc}"
            self.resultado.setText(f"<span style='color:{theme.DANGER}'><b>✘ No se pudo conectar</b></span><br>"
                                   f"<span style='color:{theme.MUTED}'>{texto[:300]}</span>")
            QTimer.singleShot(0, self._medir)

        self.trabajos.ejecutar(lambda: probar_config(cfg), listo, fallo, self)

    def _guardar(self) -> None:
        cfg = self._cfg_elegida()
        self.modo, self.api_url = cfg.modo, cfg.api_url
        self.accept()
