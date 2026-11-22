"""Tienda: categorías + búsqueda + cuadrícula de productos con carga incremental.

Para soportar 17,000+ productos NO se cargan todos: se piden de 24 en 24 (cursor opaco de
DynamoDB) cuando el usuario se acerca al final del scroll. La vista es un QListView con
un modelo + delegado que solo pinta lo visible, así que añadir miles de tarjetas no cuesta.
"""
from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QEvent, QModelIndex, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QLineEdit, QListView, QStackedLayout, QStyle,
                               QStyledItemDelegate, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ..categorias import ArbolCategorias
from ..models import FiltroProductos, ProductoResumen
from ..util import formato_dinero
from . import theme
from .pagina import PaginaBase
from .producto_dialog import abrir_producto
from .widgets import (EncabezadoPagina, EstadoVacio, Indicador, boton, dibujar_tile, estrellas, etiqueta,
                      iniciales, partir_en_lineas, tarjeta)

TAM_PAGINA = 24
ANCHO_TARJETA, ALTO_TARJETA = 212, 286


class ModeloProductos(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[ProductoResumen] = []

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._items)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        p = self._items[index.row()]
        if role == Qt.UserRole:
            return p
        if role in (Qt.DisplayRole, Qt.ToolTipRole):
            return p.titulo
        return None

    def limpiar(self) -> None:
        self.beginResetModel()
        self._items = []
        self.endResetModel()

    def agregar(self, nuevos: list[ProductoResumen]) -> None:
        if not nuevos:
            return
        n = len(self._items)
        self.beginInsertRows(QModelIndex(), n, n + len(nuevos) - 1)
        self._items.extend(nuevos)
        self.endInsertRows()


class TarjetaDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        return QSize(ANCHO_TARJETA, ALTO_TARJETA)

    def paint(self, p: QPainter, option, index) -> None:
        r: ProductoResumen = index.data(Qt.UserRole)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        ancho_card = ANCHO_TARJETA - 12  # la tarjeta mide siempre lo mismo; la celda puede ser más ancha y la centra
        rect = QRectF(option.rect.center().x() - ancho_card / 2, option.rect.top() + 6, ancho_card, ALTO_TARJETA - 12)
        activo = bool(option.state & (QStyle.State_MouseOver | QStyle.State_Selected))
        ruta = QPainterPath()
        ruta.addRoundedRect(rect, 14, 14)
        p.fillPath(ruta, QColor(theme.SURFACE))
        p.setPen(QPen(QColor(theme.PRIMARY if activo else theme.BORDER), 2 if activo else 1))
        p.drawPath(ruta)

        tile = QRectF(rect.left() + 10, rect.top() + 10, rect.width() - 20, 128)
        dibujar_tile(p, tile, f"{r.id_categoria}{r.marca}", iniciales(r.titulo), 10)

        base = QFont(p.font())
        x, ancho, y = int(rect.left() + 12), int(rect.width() - 24), tile.bottom() + 8

        f_titulo = QFont(base)
        f_titulo.setBold(True)
        f_titulo.setPointSizeF(10.5)
        p.setFont(f_titulo)
        p.setPen(QColor(theme.TEXT))
        fm = QFontMetrics(f_titulo)
        for linea in partir_en_lineas(fm, r.titulo, ancho, 2):
            p.drawText(x, int(y + fm.ascent()), linea)
            y += fm.height()
        y += 2

        f_chico = QFont(base)
        f_chico.setPointSizeF(9)
        p.setFont(f_chico)
        p.setPen(QColor(theme.MUTED))
        fm2 = QFontMetrics(f_chico)
        p.drawText(x, int(y + fm2.ascent()), fm2.elidedText(r.marca or " ", Qt.ElideRight, ancho))
        y += fm2.height() + 4

        f_precio = QFont(base)
        f_precio.setBold(True)
        f_precio.setPointSizeF(13)
        p.setFont(f_precio)
        fm3 = QFontMetrics(f_precio)
        if r.precio_desde is not None:
            p.setPen(QColor(theme.PRIMARY))
            p.drawText(x, int(y + fm3.ascent()), formato_dinero(r.precio_desde))
        else:
            p.setPen(QColor(theme.MUTED))
            p.drawText(x, int(y + fm3.ascent()), "Sin disponibilidad")
        y += fm3.height() + 2

        p.setFont(f_chico)
        p.setPen(QColor("#D97706" if r.calificacion_promedio else theme.MUTED))
        p.drawText(x, int(y + fm2.ascent()), estrellas(r.calificacion_promedio, r.num_resenas))
        p.restore()


class TiendaPage(PaginaBase):
    def __init__(self, ctx, parent=None):
        super().__init__(ctx, parent)
        self._gen = 0
        self._cursor: str | None = None
        self._hay_mas = True
        self._cargando = False
        self._cat: str | None = None
        self._arbol: ArbolCategorias | None = None
        self._iniciada = False

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(24, 20, 24, 16)
        raiz.setSpacing(12)
        raiz.addWidget(EncabezadoPagina(
            "Tienda", "Explora el catálogo por categoría o busca por nombre. Los productos se cargan poco a poco mientras te desplazas.",
            "DynamoDB"))

        cuerpo = QHBoxLayout()
        cuerpo.setSpacing(16)
        raiz.addLayout(cuerpo, 1)

        # ------------------------------------------------------------- categorías
        lateral = tarjeta()
        lateral.setFixedWidth(240)
        lv = QVBoxLayout(lateral)
        lv.setContentsMargins(12, 14, 12, 12)
        lv.addWidget(etiqueta("Categorías", "h2"))
        self.arbol_ui = QTreeWidget()
        self.arbol_ui.setHeaderHidden(True)
        self.arbol_ui.setIndentation(16)
        self.arbol_ui.itemSelectionChanged.connect(self._categoria_elegida)
        lv.addWidget(self.arbol_ui, 1)
        cuerpo.addWidget(lateral)

        # ------------------------------------------------------------- resultados
        der = QVBoxLayout()
        der.setSpacing(10)
        cuerpo.addLayout(der, 1)

        busca = QHBoxLayout()
        busca.setSpacing(8)
        self.q = QLineEdit()
        self.q.setPlaceholderText("Buscar productos…  (ej. camisa, laptop, audífonos)")
        self.q.setClearButtonEnabled(True)
        self.q.returnPressed.connect(self._buscar)
        busca.addWidget(self.q, 1)
        busca.addWidget(boton("Buscar", "primary", self._buscar))
        busca.addWidget(boton("Limpiar", "secondary", self._limpiar))
        der.addLayout(busca)

        opciones = QHBoxLayout()
        self.cualquier = QCheckBox("Buscar en cualquier parte del nombre (más lento)")
        self.cualquier.setToolTip(
            "Por defecto, sin categoría, se buscan nombres que EMPIEZAN con tu texto: es instantáneo porque usa un índice de DynamoDB.\n"
            "Esta casilla recorre el catálogo con un filtro: encuentra más, pero tarda más.\n"
            "Si eliges una categoría, la búsqueda ya es en cualquier parte del nombre dentro de esa categoría.")
        self.cualquier.toggled.connect(lambda _: self.q.text().strip() and self._buscar())
        opciones.addWidget(self.cualquier)
        opciones.addStretch(1)
        self.resumen = etiqueta("", "muted")
        opciones.addWidget(self.resumen)
        der.addLayout(opciones)

        self.indicador = Indicador()
        der.addWidget(self.indicador)

        self.modelo = ModeloProductos(self)
        self.vista = QListView()
        self.vista.setModel(self.modelo)
        self.vista.setItemDelegate(TarjetaDelegate(self.vista))
        self.vista.setViewMode(QListView.IconMode)
        self.vista.setResizeMode(QListView.Adjust)
        self.vista.setMovement(QListView.Static)
        self.vista.setWrapping(True)
        self.vista.setUniformItemSizes(True)
        self.vista.setGridSize(QSize(ANCHO_TARJETA, ALTO_TARJETA))
        self.vista.setSelectionMode(QListView.SingleSelection)
        self.vista.setVerticalScrollMode(QListView.ScrollPerPixel)
        self.vista.setMouseTracking(True)
        self.vista.setFrameShape(QListView.NoFrame)
        self.vista.setEditTriggers(QListView.NoEditTriggers)
        self.vista.activated.connect(self._abrir)
        self.vista.verticalScrollBar().valueChanged.connect(self._scroll)
        self.vista.viewport().installEventFilter(self)  # reparte el ancho sobrante entre las columnas

        self.vacio = EstadoVacio("No encontramos productos",
                                 "Prueba con otra palabra, quita la categoría o marca «Buscar en cualquier parte del nombre».")
        pila_w = QWidget()
        self.pila = QStackedLayout(pila_w)
        self.pila.addWidget(self.vista)
        self.pila.addWidget(self.vacio)
        der.addWidget(pila_w, 1)

        pie = QHBoxLayout()
        pie.addStretch(1)
        self.btn_mas = boton("Cargar más productos", "secondary", self._cargar_mas)
        self.btn_mas.setVisible(False)
        pie.addWidget(self.btn_mas)
        pie.addStretch(1)
        der.addLayout(pie)

    def eventFilter(self, obj, ev) -> bool:  # noqa: N802
        if obj is self.vista.viewport() and ev.type() == QEvent.Resize:
            ancho = ev.size().width() - 8  # margen: IconMode envuelve antes si la fila llena justo el ancho
            columnas = max(1, ancho // ANCHO_TARJETA)
            celda = ancho // columnas
            if celda != self.vista.gridSize().width():
                self.vista.setGridSize(QSize(celda, ALTO_TARJETA))
        return super().eventFilter(obj, ev)

    # ------------------------------------------------------------------ ciclo de vida
    def al_mostrar(self) -> None:
        if self._arbol is None or self.ctx.arbol is not self._arbol:  # el admin pudo cambiar las categorías
            self.ctx.cargar_categorias(self, self._poblar_arbol)
        if not self._iniciada:
            self._iniciada = True
            self._nueva_busqueda()

    def al_cerrar_sesion(self) -> None:
        self._iniciada = False
        self._arbol = None
        self.modelo.limpiar()
        self.arbol_ui.clear()
        self._cat = None
        self.q.clear()

    # ------------------------------------------------------------------ categorías
    def _poblar_arbol(self, arbol: ArbolCategorias) -> None:
        self._arbol = arbol
        self.arbol_ui.blockSignals(True)
        self.arbol_ui.clear()
        todas = QTreeWidgetItem(["Todas las categorías"])
        todas.setData(0, Qt.UserRole, None)
        f = todas.font(0)
        f.setBold(True)
        todas.setFont(0, f)
        self.arbol_ui.addTopLevelItem(todas)

        def agregar(padre_item, categorias):
            for c in categorias:
                if c.estatus != "ACTIVO":
                    continue
                it = QTreeWidgetItem([c.nombre])
                it.setData(0, Qt.UserRole, c.id_categoria)
                padre_item.addChild(it) if padre_item else self.arbol_ui.addTopLevelItem(it)
                agregar(it, arbol.hijos_de(c.id_categoria))

        agregar(None, arbol.raices())
        self.arbol_ui.setCurrentItem(todas)
        self.arbol_ui.blockSignals(False)

    def _categoria_elegida(self) -> None:
        items = self.arbol_ui.selectedItems()
        nueva = items[0].data(0, Qt.UserRole) if items else None
        if nueva != self._cat:
            self._cat = nueva
            self._nueva_busqueda()

    # ------------------------------------------------------------------ búsqueda / carga
    def _filtro(self) -> FiltroProductos:
        return FiltroProductos(q=self.q.text().strip() or None, id_categoria=self._cat,
                               en_cualquier_parte=self.cualquier.isChecked())

    def _buscar(self) -> None:
        self._nueva_busqueda()

    def _limpiar(self) -> None:
        self.q.clear()
        self.cualquier.setChecked(False)
        self.arbol_ui.setCurrentItem(self.arbol_ui.topLevelItem(0))
        self._cat = None
        self._nueva_busqueda()

    def _nueva_busqueda(self) -> None:
        self._gen += 1
        if self._cargando:
            self.indicador.fin()
        self._cargando = False
        self._cursor, self._hay_mas = None, True
        self.modelo.limpiar()
        self.pila.setCurrentWidget(self.vista)
        self.vista.verticalScrollBar().setValue(0)
        self._cargar_mas()

    def _cargar_mas(self) -> None:
        if self._cargando or not self._hay_mas:
            return
        self._cargando = True
        self.btn_mas.setVisible(False)
        self.indicador.inicio()
        gen, filtro, cursor = self._gen, self._filtro(), self._cursor
        self.ctx.ejecutar(self, lambda: self.ctx.gw.listar_productos(filtro, cursor, TAM_PAGINA),
                          lambda pag: self._recibido(gen, pag), lambda exc: self._fallo(gen, exc))

    def _recibido(self, gen: int, pag) -> None:
        if gen != self._gen:
            return
        self._cargando = False
        self.indicador.fin()
        self.modelo.agregar(pag.items)
        self._cursor, self._hay_mas = pag.siguiente, pag.siguiente is not None
        n = self.modelo.rowCount()
        if n == 0 and not self._hay_mas:
            self.pila.setCurrentWidget(self.vacio)
        self._texto_resumen()
        if not pag.items and self._hay_mas:      # página vacía pero con cursor: seguir buscando
            self._cargar_mas()
            return
        self.btn_mas.setVisible(self._hay_mas)
        QTimer.singleShot(0, self._rellenar)

    def _fallo(self, gen: int, exc: BaseException) -> None:
        if gen != self._gen:
            return
        self._cargando = False
        self.indicador.fin()
        self.btn_mas.setVisible(self._hay_mas)
        from .widgets import mostrar_error
        mostrar_error(self, exc)

    def _texto_resumen(self) -> None:
        n = self.modelo.rowCount()
        donde = f" en «{self._arbol.ruta_texto(self._cat)}»" if self._arbol and self._cat else ""
        mas = " · desplázate para ver más" if self._hay_mas and n else ""
        self.resumen.setText(f"{n:,} productos cargados{donde}{mas}" if n else "")

    def _scroll(self, valor: int) -> None:
        if self.vista.verticalScrollBar().maximum() - valor < 500:
            self._cargar_mas()

    def _rellenar(self) -> None:
        """Si la ventana es tan grande que no hay scroll, sigue pidiendo hasta llenarla."""
        if self._hay_mas and not self._cargando and self.vista.verticalScrollBar().maximum() == 0 \
                and 0 < self.modelo.rowCount() < 240:
            self._cargar_mas()

    def _abrir(self, index: QModelIndex) -> None:
        p: ProductoResumen = index.data(Qt.UserRole)
        abrir_producto(self.ctx, p.id_producto, self.window())
