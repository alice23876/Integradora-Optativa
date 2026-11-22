"""Piezas reutilizables de interfaz."""
from __future__ import annotations

import zlib
from typing import Callable

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
                               QProgressBar, QPushButton, QSizePolicy, QSpinBox, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from ..errors import ErrorMarketplace, ErrorStock
from ..models import Producto, ProductoResumen
from . import theme


# --------------------------------------------------------------------------- botones y etiquetas
def boton(texto: str, variante: str = "secondary", al_pulsar: Callable | None = None, tooltip: str = "") -> QPushButton:
    b = QPushButton(texto)
    b.setProperty("variante", variante)
    b.setCursor(Qt.PointingHandCursor)
    if tooltip:
        b.setToolTip(tooltip)
    if al_pulsar:
        b.clicked.connect(lambda _=False: al_pulsar())
    return b


def etiqueta(texto: str = "", rol: str = "", wrap: bool = False, selectable: bool = False) -> QLabel:
    lb = QLabel(texto)
    if rol:
        lb.setProperty("rol", rol)
    lb.setWordWrap(wrap)
    if selectable:
        lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return lb


def chip(texto: str, fg: str = theme.PRIMARY, bg: str = theme.PRIMARY_SOFT) -> QLabel:
    lb = QLabel(texto)
    lb.setAlignment(Qt.AlignCenter)
    lb.setStyleSheet(f"background:{bg}; color:{fg}; border-radius:10px; padding:3px 10px; font-weight:700; font-size:8.5pt;")
    lb.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
    return lb


def chip_estatus(estatus: str) -> QLabel:
    fg, bg = theme.ESTATUS_COLORES.get(estatus, (theme.MUTED, theme.GRIS_SOFT))
    return chip(theme.ETIQUETAS_ESTATUS.get(estatus, estatus), fg, bg)


def tarjeta() -> QFrame:
    f = QFrame()
    f.setProperty("card", True)
    return f


def estrellas(promedio: float | None, n: int = 0) -> str:
    if not promedio:
        return "Sin reseñas"
    llenas = int(round(promedio))
    return f"{'★' * llenas}{'☆' * (5 - llenas)}  {promedio:.1f} ({n})"


def estrellas_fijas(nota: int) -> str:
    return "★" * nota + "☆" * (5 - nota)


class SelectorCantidad(QWidget):
    """[ − ]  3  [ + ]: más claro que las flechitas diminutas de un QSpinBox."""

    valueChanged = Signal(int)  # noqa: N815

    def __init__(self, minimo: int = 1, maximo: int = 99, parent=None):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        self._menos = boton("−", "secondary")
        self._mas = boton("+", "secondary")
        for b in (self._menos, self._mas):
            b.setFixedSize(32, 34)
            b.setStyleSheet("padding:0; font-size:12pt;")
        self._spin = QSpinBox()
        self._spin.setAlignment(Qt.AlignCenter)
        self._spin.setFixedWidth(56)
        self._spin.setStyleSheet("padding:6px 2px;")
        self._spin.setRange(minimo, maximo)
        self._menos.clicked.connect(lambda: self._spin.setValue(self._spin.value() - 1))
        self._mas.clicked.connect(lambda: self._spin.setValue(self._spin.value() + 1))
        self._spin.valueChanged.connect(self._cambio)
        h.addWidget(self._menos)
        h.addWidget(self._spin)
        h.addWidget(self._mas)
        self._cambio(self._spin.value(), emitir=False)

    def _cambio(self, v: int, emitir: bool = True) -> None:
        self._menos.setEnabled(self.isEnabled() and v > self._spin.minimum())
        self._mas.setEnabled(self.isEnabled() and v < self._spin.maximum())
        if emitir:
            self.valueChanged.emit(v)

    def setRange(self, minimo: int, maximo: int) -> None:  # noqa: N802
        self._spin.setRange(minimo, maximo)
        self._cambio(self._spin.value(), emitir=False)

    def setValue(self, v: int) -> None:  # noqa: N802
        self._spin.setValue(v)
        self._cambio(self._spin.value(), emitir=False)

    def value(self) -> int:
        return self._spin.value()

    def maximum(self) -> int:
        return self._spin.maximum()

    def setEnabled(self, si: bool) -> None:  # noqa: N802
        super().setEnabled(si)
        self._cambio(self._spin.value(), emitir=False)


# --------------------------------------------------------------------------- encabezado de página
class EncabezadoPagina(QWidget):
    """Título + explicación + «de dónde salen los datos» (didáctico)."""

    def __init__(self, titulo: str, subtitulo: str = "", origen: str = "", parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)
        fila = QHBoxLayout()
        fila.setSpacing(10)
        self.titulo = etiqueta(titulo, "titulo")
        fila.addWidget(self.titulo)
        if origen:
            c = chip(f"Datos: {origen}", theme.INFO, theme.INFO_SOFT)
            c.setToolTip("Base de datos de la que sale la información de esta pantalla")
            fila.addWidget(c, 0, Qt.AlignBottom)
        fila.addStretch(1)
        self.acciones = QHBoxLayout()
        self.acciones.setSpacing(8)
        fila.addLayout(self.acciones)
        v.addLayout(fila)
        if subtitulo:
            v.addWidget(etiqueta(subtitulo, "subtitulo", wrap=True))


class Indicador(QProgressBar):
    """Barra fina de «cargando…» que no ocupa espacio cuando no hay actividad."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setRange(0, 0)
        self.setTextVisible(False)
        self.setFixedHeight(3)
        self._n = 0
        self.setVisible(False)

    def inicio(self) -> None:
        self._n += 1
        self.setVisible(True)

    def fin(self) -> None:
        self._n = max(0, self._n - 1)
        if self._n == 0:
            self.setVisible(False)


class EstadoVacio(QWidget):
    def __init__(self, titulo: str, texto: str = "", parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setAlignment(Qt.AlignCenter)
        self.t = etiqueta(titulo, "h2")
        self.t.setAlignment(Qt.AlignCenter)
        self.d = etiqueta(texto, "muted", wrap=True)
        self.d.setAlignment(Qt.AlignCenter)
        self.d.setMaximumWidth(460)
        v.addWidget(self.t)
        v.addWidget(self.d, 0, Qt.AlignHCenter)

    def poner(self, titulo: str, texto: str = "") -> None:
        self.t.setText(titulo)
        self.d.setText(texto)


# --------------------------------------------------------------------------- tablas
def crear_tabla(columnas: list[str], anchos: dict[int, int] | None = None, estirar: int | None = None,
                filas_altas: int = 0) -> QTableWidget:
    t = QTableWidget(0, len(columnas))
    t.setHorizontalHeaderLabels(columnas)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setSelectionMode(QAbstractItemView.SingleSelection)
    t.setAlternatingRowColors(True)
    t.setShowGrid(False)
    t.verticalHeader().setVisible(False)
    t.verticalHeader().setDefaultSectionSize(filas_altas or 38)
    t.setFocusPolicy(Qt.StrongFocus)
    t.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
    t.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
    h = t.horizontalHeader()
    h.setHighlightSections(False)
    h.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    for i in range(len(columnas)):
        h.setSectionResizeMode(i, QHeaderView.Interactive)
    if estirar is not None:
        h.setSectionResizeMode(estirar, QHeaderView.Stretch)
    for col, ancho in (anchos or {}).items():
        t.setColumnWidth(col, ancho)
    return t


def celda(texto: str = "", *, derecha: bool = False, color: str | None = None, negrita: bool = False,
          dato=None, tooltip: str = "") -> QTableWidgetItem:
    it = QTableWidgetItem(texto)
    it.setTextAlignment((Qt.AlignRight if derecha else Qt.AlignLeft) | Qt.AlignVCenter)
    if color:
        it.setForeground(QColor(color))
    if negrita:
        f = it.font()
        f.setBold(True)
        it.setFont(f)
    if dato is not None:
        it.setData(Qt.UserRole, dato)
    if tooltip:
        it.setToolTip(tooltip)
    return it


def celda_estatus(estatus: str) -> QTableWidgetItem:
    fg, _ = theme.ESTATUS_COLORES.get(estatus, (theme.MUTED, theme.GRIS_SOFT))
    return celda(theme.ETIQUETAS_ESTATUS.get(estatus, estatus), color=fg, negrita=True, dato=estatus)


def fecha_corta(dt, con_hora: bool = True) -> str:
    if not dt:
        return "—"
    return dt.astimezone().strftime("%d/%m/%Y %H:%M" if con_hora else "%d/%m/%Y")


def atributos_texto(atributos: dict[str, str]) -> str:
    return " · ".join(f"{k}: {v}" for k, v in atributos.items()) or "Única"


# --------------------------------------------------------------------------- mensajes
def mostrar_error(parent, exc: BaseException) -> None:
    if isinstance(exc, ErrorMarketplace):
        caja = QMessageBox(QMessageBox.Warning, "No se pudo completar", exc.mensaje, QMessageBox.Ok, parent)
        if exc.detalles:
            caja.setInformativeText("\n".join(f"• {d}" for d in exc.detalles))
        if exc.codigo == "conexion":
            caja.setIcon(QMessageBox.Critical)
            caja.setWindowTitle("Problema de conexión")
    else:
        caja = QMessageBox(QMessageBox.Critical, "Error inesperado",
                           "Ocurrió un error inesperado. Si se repite, avisa al equipo técnico.", QMessageBox.Ok, parent)
        caja.setInformativeText(f"{exc.__class__.__name__}: {exc}")
    caja.exec()


def informar(parent, titulo: str, texto: str, detalle: str = "") -> None:
    caja = QMessageBox(QMessageBox.Information, titulo, texto, QMessageBox.Ok, parent)
    if detalle:
        caja.setInformativeText(detalle)
    caja.exec()


def confirmar(parent, titulo: str, texto: str, si: str = "Sí, continuar", peligro: bool = False) -> bool:
    caja = QMessageBox(QMessageBox.Question, titulo, texto, QMessageBox.NoButton, parent)
    b_si = caja.addButton(si, QMessageBox.AcceptRole)
    caja.addButton("Cancelar", QMessageBox.RejectRole)
    if peligro:
        b_si.setProperty("variante", "danger")
    caja.exec()
    return caja.clickedButton() is b_si


# --------------------------------------------------------------------------- «foto» del producto (sin imágenes en el esquema)
def tono(semilla: str) -> int:
    return zlib.crc32(semilla.encode()) % 360


def iniciales(titulo: str) -> str:
    palabras = [p for p in titulo.replace("-", " ").split() if p[:1].isalpha()]
    return "".join(p[0] for p in palabras[:2]).upper() or "?"


def dibujar_tile(p: QPainter, rect: QRectF, semilla: str, texto: str, radio: float = 10) -> None:
    h = tono(semilla)
    g = QLinearGradient(rect.topLeft(), rect.bottomRight())
    g.setColorAt(0, QColor.fromHsl(h, 150, 150))
    g.setColorAt(1, QColor.fromHsl((h + 35) % 360, 170, 105))
    ruta = QPainterPath()
    ruta.addRoundedRect(rect, radio, radio)
    p.fillPath(ruta, QBrush(g))
    f = QFont(p.font())
    f.setPixelSize(int(rect.height() * 0.38))
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor(255, 255, 255, 215))
    p.drawText(rect, Qt.AlignCenter, texto)


class TileProducto(QWidget):
    def __init__(self, tam: int = 240, parent=None):
        super().__init__(parent)
        self.setFixedSize(tam, tam)
        self._semilla, self._texto = "x", "?"

    def poner(self, p: ProductoResumen | Producto) -> None:
        self._semilla, self._texto = f"{p.id_categoria}{p.marca}", iniciales(p.titulo)
        self.update()

    def paintEvent(self, _):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dibujar_tile(p, QRectF(self.rect()).adjusted(1, 1, -1, -1), self._semilla, self._texto, 16)


def partir_en_lineas(fm: QFontMetrics, texto: str, ancho: int, max_lineas: int = 2) -> list[str]:
    palabras, lineas, actual = texto.split(), [], ""
    for i, pal in enumerate(palabras):
        prueba = f"{actual} {pal}".strip()
        if fm.horizontalAdvance(prueba) <= ancho:
            actual = prueba
        else:
            if actual:
                lineas.append(actual)
            actual = pal
            if len(lineas) == max_lineas - 1:
                actual = " ".join(palabras[i:])
                break
    lineas.append(actual)
    lineas = lineas[:max_lineas]
    lineas[-1] = fm.elidedText(lineas[-1], Qt.ElideRight, ancho)
    return lineas


def fijar_alturas_de_texto(raiz: QWidget) -> None:
    """Qt a veces reparte menos alto del necesario a los QLabel con saltos de línea; con el ancho real ya conocido
    se les fija su alto mínimo exacto."""
    for lb in raiz.findChildren(QLabel):
        if lb.wordWrap() and lb.width() > 0:
            lb.setMinimumHeight(lb.heightForWidth(lb.width()))


def linea_separadora() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setStyleSheet(f"color:{theme.BORDER}; background:{theme.BORDER}; max-height:1px; border:none;")
    return f
