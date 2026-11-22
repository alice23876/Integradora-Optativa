"""Detalle de producto: variantes, compra y reseñas."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QScrollArea, QSpinBox,
                               QVBoxLayout, QWidget, QComboBox, QDialogButtonBox)

from ..models import Producto, Resena, Variante
from ..util import formato_dinero
from . import theme
from .contexto import Contexto
from .widgets import (Indicador, SelectorCantidad, TileProducto, atributos_texto, boton, celda, chip_estatus, crear_tabla, estrellas,
                      estrellas_fijas, etiqueta, fecha_corta, mostrar_error, tarjeta)


class ResenaDialog(QDialog):
    """Escribir una reseña. El backend verifica que el usuario haya recibido el producto."""

    def __init__(self, ctx: Contexto, id_producto: str, titulo: str, parent=None):
        super().__init__(parent)
        self.ctx, self.id_producto = ctx, id_producto
        self.resena: Resena | None = None
        self.setWindowTitle("Escribir reseña")
        self.setModal(True)
        self.setMinimumWidth(460)
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 20, 22, 18)
        v.setSpacing(12)
        v.addWidget(etiqueta("Tu opinión ayuda a otros compradores", "h2"))
        v.addWidget(etiqueta(titulo, "muted", wrap=True))
        self.nota = QComboBox()
        for n in (5, 4, 3, 2, 1):
            self.nota.addItem(f"{estrellas_fijas(n)}   {['', 'Malo', 'Regular', 'Bueno', 'Muy bueno', 'Excelente'][n]}", n)
        v.addWidget(etiqueta("Calificación", "muted"))
        v.addWidget(self.nota)
        v.addWidget(etiqueta("Comentario (opcional)", "muted"))
        self.texto = QPlainTextEdit()
        self.texto.setPlaceholderText("¿Qué te pareció la calidad, el envío y la atención del vendedor?")
        self.texto.setFixedHeight(110)
        self.texto.textChanged.connect(self._contar)
        v.addWidget(self.texto)
        self.contador = etiqueta("0 / 1000", "muted")
        self.contador.setAlignment(Qt.AlignRight)
        v.addWidget(self.contador)
        self.error = etiqueta("", "error", wrap=True)
        v.addWidget(self.error)
        self.indicador = Indicador()
        v.addWidget(self.indicador)
        fila = QHBoxLayout()
        fila.addStretch(1)
        fila.addWidget(boton("Cancelar", al_pulsar=self.reject))
        self.btn = boton("Publicar reseña", "primary", self._enviar)
        fila.addWidget(self.btn)
        v.addLayout(fila)

    def _contar(self) -> None:
        n = len(self.texto.toPlainText())
        self.contador.setText(f"{n} / 1000")
        self.contador.setProperty("rol", "error" if n > 1000 else "muted")
        self.contador.style().unpolish(self.contador)
        self.contador.style().polish(self.contador)

    def _enviar(self) -> None:
        self.error.clear()
        self.btn.setEnabled(False)
        self.indicador.inicio()
        nota, texto = self.nota.currentData(), self.texto.toPlainText()
        self.ctx.ejecutar(self, lambda: self.ctx.gw.crear_resena(self.id_producto, nota, texto),
                          self._listo, self._fallo)

    def _listo(self, resena: Resena) -> None:
        self.indicador.fin()
        self.resena = resena
        self.accept()

    def _fallo(self, exc: BaseException) -> None:
        self.indicador.fin()
        self.btn.setEnabled(True)
        self.error.setText(str(exc))


class ProductoDialog(QDialog):
    def __init__(self, ctx: Contexto, id_producto: str, parent=None):
        super().__init__(parent)
        self.ctx, self.id_producto = ctx, id_producto
        self.producto: Producto | None = None
        self._variante: Variante | None = None
        self._cursor_resenas: str | None = None
        self._puede_resenar = False
        self.setWindowTitle("Detalle del producto")
        self.setModal(True)
        self.resize(1000, 760)

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)
        self.indicador = Indicador()
        raiz.addWidget(self.indicador)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        raiz.addWidget(scroll)
        contenido = QWidget()
        contenido.setProperty("pagina", True)
        scroll.setWidget(contenido)
        v = QVBoxLayout(contenido)
        v.setContentsMargins(24, 20, 24, 24)
        v.setSpacing(16)

        # ----------------------------------------------------------- cabecera: foto + datos
        top = tarjeta()
        h = QHBoxLayout(top)
        h.setContentsMargins(20, 20, 20, 20)
        h.setSpacing(22)
        self.tile = TileProducto(250)
        h.addWidget(self.tile, 0, Qt.AlignTop)
        info = QVBoxLayout()
        info.setSpacing(6)
        self.ruta = etiqueta("", "muted")
        self.titulo = etiqueta("Cargando…", "h2", wrap=True)
        self.titulo.setStyleSheet("font-size:17pt;")
        self.meta = etiqueta("", "muted")
        self.estrellas = etiqueta("")
        self.estrellas.setStyleSheet("color:#D97706; font-weight:600;")
        self.descripcion = etiqueta("", wrap=True)
        for w in (self.ruta, self.titulo, self.meta, self.estrellas, self.descripcion):
            info.addWidget(w)
        info.addSpacing(6)
        info.addWidget(etiqueta("Elige una presentación", "h2"))
        self.tabla = crear_tabla(["Presentación", "SKU", "Precio", "Disponibles"], {1: 130, 2: 100, 3: 100}, estirar=0)
        self.tabla.setFixedHeight(190)
        self.tabla.itemSelectionChanged.connect(self._variante_elegida)
        info.addWidget(self.tabla)
        compra = QHBoxLayout()
        compra.setSpacing(10)
        self.precio = etiqueta("", "precio")
        compra.addWidget(self.precio)
        compra.addStretch(1)
        compra.addWidget(etiqueta("Cantidad", "muted"))
        self.cantidad = SelectorCantidad(1, 1)
        compra.addWidget(self.cantidad)
        self.btn_agregar = boton("Agregar al carrito", "primary", self._agregar)
        compra.addWidget(self.btn_agregar)
        info.addLayout(compra)
        self.aviso = etiqueta("", "muted", wrap=True)
        info.addWidget(self.aviso)
        info.addStretch(1)
        h.addLayout(info, 1)
        v.addWidget(top)

        # ----------------------------------------------------------- reseñas
        self.card_resenas = tarjeta()
        rv = QVBoxLayout(self.card_resenas)
        rv.setContentsMargins(20, 16, 20, 16)
        rv.setSpacing(8)
        cab = QHBoxLayout()
        self.titulo_resenas = etiqueta("Reseñas", "h2")
        cab.addWidget(self.titulo_resenas)
        cab.addStretch(1)
        self.btn_resena = boton("Escribir reseña", "secondary", self._escribir_resena)
        self.btn_resena.setEnabled(False)
        cab.addWidget(self.btn_resena)
        rv.addLayout(cab)
        self.motivo = etiqueta("", "muted", wrap=True)
        rv.addWidget(self.motivo)
        self.lista_resenas = QVBoxLayout()
        self.lista_resenas.setSpacing(0)
        rv.addLayout(self.lista_resenas)
        self.sin_resenas = etiqueta("Este producto aún no tiene reseñas.", "muted")
        rv.addWidget(self.sin_resenas)
        self.btn_mas = boton("Ver más reseñas", "link", self._pedir_resenas)
        self.btn_mas.setVisible(False)
        rv.addWidget(self.btn_mas, 0, Qt.AlignLeft)
        v.addWidget(self.card_resenas)
        v.addStretch(1)

        self._cargar()

    # ------------------------------------------------------------------ carga
    def _cargar(self) -> None:
        self.indicador.inicio()
        self.ctx.ejecutar(self, lambda: self.ctx.gw.obtener_producto(self.id_producto), self._producto, self._fallo_carga)

    def _fallo_carga(self, exc: BaseException) -> None:
        self.indicador.fin()
        mostrar_error(self, exc)
        self.reject()

    def _producto(self, p: Producto) -> None:
        self.indicador.fin()
        self.producto = p
        self.tile.poner(p)
        self.setWindowTitle(p.titulo)
        self.ruta.setText(" › ".join(p.ruta_categoria))
        self.titulo.setText(p.titulo)
        partes = [f"Marca {p.marca}" if p.marca else "", f"Vendido por {p.nombre_vendedor}" if p.nombre_vendedor else ""]
        self.meta.setText("  ·  ".join(x for x in partes if x))
        self.estrellas.setText(estrellas(p.calificacion_promedio, p.num_resenas))
        self.descripcion.setText(p.descripcion or "Sin descripción.")
        self.titulo_resenas.setText(f"Reseñas ({p.num_resenas})" if p.num_resenas else "Reseñas")

        previa = self._variante.id_variante if self._variante else None
        self.tabla.setRowCount(0)
        for v in p.variantes:
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)
            gris = theme.MUTED if v.estatus != "ACTIVO" else None
            self.tabla.setItem(fila, 0, celda(atributos_texto(v.atributos) + ("  (pausada)" if v.estatus != "ACTIVO" else ""),
                                              color=gris, dato=v))
            self.tabla.setItem(fila, 1, celda(v.sku, color=theme.MUTED))
            self.tabla.setItem(fila, 2, celda(formato_dinero(v.precio), derecha=True, negrita=True))
            agotada = v.cantidad_stock <= 0
            self.tabla.setItem(fila, 3, celda("Agotado" if agotada else str(v.cantidad_stock), derecha=True,
                                              color=theme.DANGER if agotada else None))
        elegir = next((i for i, v in enumerate(p.variantes) if v.id_variante == previa), None)
        if elegir is None:
            elegir = next((i for i, v in enumerate(p.variantes) if v.estatus == "ACTIVO" and v.cantidad_stock > 0), 0)
        if p.variantes:
            self.tabla.selectRow(elegir)
        else:
            self._variante = None
            self._actualizar_compra()

        self._cursor_resenas = None
        self._limpiar_resenas()
        self._pedir_resenas()
        self._pedir_elegibilidad()

    # ------------------------------------------------------------------ compra
    def _variante_elegida(self) -> None:
        filas = self.tabla.selectionModel().selectedRows()
        self._variante = self.tabla.item(filas[0].row(), 0).data(Qt.UserRole) if filas else None
        self._actualizar_compra()

    def _actualizar_compra(self) -> None:
        v, p = self._variante, self.producto
        self.precio.setText(formato_dinero(v.precio) if v else "—")
        motivo = ""
        if not v:
            motivo = "Este producto no tiene presentaciones disponibles."
        elif not self.ctx.puede_comprar:
            motivo = "Los administradores no realizan compras."
        elif p and p.id_vendedor == self.ctx.usuario.id_usuario:
            motivo = "Este producto es tuyo: lo editas desde «Mis productos»."
        elif v.estatus != "ACTIVO":
            motivo = "Esta presentación está pausada."
        elif v.cantidad_stock <= 0:
            motivo = "Esta presentación está agotada."
        self.cantidad.setRange(1, max(1, min(99, v.cantidad_stock if v else 1)))
        self.cantidad.setEnabled(not motivo)
        self.btn_agregar.setEnabled(not motivo)
        self.aviso.setText(motivo)
        self.aviso.setProperty("rol", "muted")

    def _agregar(self) -> None:
        v = self._variante
        if not v:
            return
        cantidad = self.cantidad.value()
        self.btn_agregar.setEnabled(False)
        self.indicador.inicio()
        self.ctx.ejecutar(self, lambda: self.ctx.gw.agregar_al_carrito(v.id_variante, cantidad),
                          self._agregado, self._fallo_agregar)

    def _agregado(self, carrito) -> None:
        self.indicador.fin()
        self.ctx.carrito_actualizado.emit(carrito.num_articulos)
        self.aviso.setProperty("rol", "ok")
        self.aviso.style().unpolish(self.aviso)
        self.aviso.style().polish(self.aviso)
        self.aviso.setText(f"Agregado al carrito. Tienes {carrito.num_articulos} artículo(s).")
        self.btn_agregar.setEnabled(True)
        self.ctx.avisar("Producto agregado al carrito")

    def _fallo_agregar(self, exc: BaseException) -> None:
        self.indicador.fin()
        self.btn_agregar.setEnabled(True)
        mostrar_error(self, exc)
        self._cargar()  # refresca existencias

    # ------------------------------------------------------------------ reseñas
    def _limpiar_resenas(self) -> None:
        while self.lista_resenas.count():
            w = self.lista_resenas.takeAt(0).widget()
            if w:
                w.deleteLater()

    def _pedir_resenas(self) -> None:
        self.btn_mas.setEnabled(False)
        cursor = self._cursor_resenas
        self.ctx.ejecutar(self, lambda: self.ctx.gw.listar_resenas(self.id_producto, cursor, 5), self._resenas, lambda e: None)

    def _resenas(self, pag) -> None:
        for r in pag.items:
            self.lista_resenas.addWidget(self._tarjeta_resena(r))
        self._cursor_resenas = pag.siguiente
        self.btn_mas.setVisible(bool(pag.siguiente))
        self.btn_mas.setEnabled(True)
        self.sin_resenas.setVisible(self.lista_resenas.count() == 0)

    @staticmethod
    def _tarjeta_resena(r: Resena) -> QWidget:
        f = QFrame()
        f.setStyleSheet(f"QFrame {{ border: none; border-bottom: 1px solid {theme.BORDER}; background: transparent; }} QLabel {{ border: none; }}")
        v = QVBoxLayout(f)
        v.setContentsMargins(0, 10, 0, 10)
        v.setSpacing(2)
        cab = QHBoxLayout()
        est = QLabel(estrellas_fijas(r.calificacion))
        est.setStyleSheet("color:#D97706; font-size:11pt;")
        cab.addWidget(est)
        cab.addWidget(etiqueta(f"{r.nombre_usuario or 'Cliente'}  ·  {fecha_corta(r.fecha_resena)}", "muted"))
        cab.addStretch(1)
        v.addLayout(cab)
        if r.comentario:
            v.addWidget(etiqueta(r.comentario, wrap=True))
        return f

    def _pedir_elegibilidad(self) -> None:
        self.btn_resena.setEnabled(False)

        def listo(e):
            self._puede_resenar = e.puede
            self.btn_resena.setEnabled(e.puede)
            self.motivo.setText("" if e.puede else e.motivo)

        self.ctx.ejecutar(self, lambda: self.ctx.gw.elegibilidad_resena(self.id_producto), listo, lambda e: None)

    def _escribir_resena(self) -> None:
        if not self.producto:
            return
        dlg = ResenaDialog(self.ctx, self.id_producto, self.producto.titulo, self)
        if dlg.exec() == QDialog.Accepted:
            self.ctx.avisar("¡Gracias por tu reseña!")
            self._cargar()


def abrir_producto(ctx: Contexto, id_producto: str, parent=None) -> None:
    ProductoDialog(ctx, id_producto, parent).exec()
