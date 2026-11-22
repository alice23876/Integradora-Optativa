"""Panel del vendedor: «Mis productos» (alta y edición con variantes) y «Mis ventas»."""
from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLineEdit, QPlainTextEdit,
                               QSpinBox, QVBoxLayout, QWidget)

from ..errors import ErrorValidacion
from ..models import DatosProducto, DatosVariante, Producto, ProductoResumen
from ..util import formato_dinero
from . import theme
from .contexto import Contexto
from .paginado import CargaPaginada
from .pagina import PaginaBase
from .widgets import (EncabezadoPagina, EstadoVacio, Indicador, atributos_texto, boton, celda, celda_estatus,
                      confirmar, crear_tabla, etiqueta, estrellas, fecha_corta, mostrar_error, tarjeta)

ETIQUETAS_PUBLICACION = {"ACTIVO": "Publicado", "INACTIVO": "Pausado"}


# --------------------------------------------------------------------------- utilidades de formulario
def atributos_a_texto(atributos: dict[str, str]) -> str:
    return "; ".join(f"{k}={v}" for k, v in atributos.items())


def texto_a_atributos(texto: str) -> dict[str, str]:
    """«Talla=M; Color=Azul» → {'Talla': 'M', 'Color': 'Azul'}. Lanza ErrorValidacion si hay un formato roto."""
    resultado: dict[str, str] = {}
    for trozo in (t.strip() for t in texto.replace("\n", ";").split(";")):
        if not trozo:
            continue
        clave, sep, valor = trozo.partition("=")
        if not sep or not clave.strip() or not valor.strip():
            raise ErrorValidacion(f"No entiendo «{trozo}». Escribe los atributos así: Talla=M; Color=Azul")
        resultado[clave.strip()] = valor.strip()
    return resultado


class FilaVariante:
    """Los controles de una fila de la tabla de variantes."""

    def __init__(self, existente_id: str | None = None):
        self.id_variante = existente_id
        self.sku = QLineEdit()
        self.sku.setPlaceholderText("Ej.: CAM-AZUL-M")
        self.sku.setMaxLength(40)
        self.precio = QDoubleSpinBox()
        self.precio.setRange(0.01, 10_000_000)
        self.precio.setDecimals(2)
        self.precio.setPrefix("$ ")
        self.precio.setGroupSeparatorShown(True)
        self.precio.setValue(100)
        self.precio.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.stock = QSpinBox()
        self.stock.setRange(0, 1_000_000)
        self.stock.setGroupSeparatorShown(True)
        self.stock.setValue(10)
        self.stock.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.atributos = QLineEdit()
        self.atributos.setPlaceholderText("Talla=M; Color=Azul")
        self.estatus = QComboBox()
        for clave, texto in ETIQUETAS_PUBLICACION.items():
            self.estatus.addItem(texto, clave)

    def cargar(self, v) -> None:
        self.sku.setText(v.sku)
        self.sku.setReadOnly(True)  # el SKU es la identidad de la variante: no se cambia
        self.sku.setToolTip("El SKU no se puede cambiar. Si te equivocaste, pausa esta variante y crea otra.")
        self.sku.setStyleSheet(f"background:{theme.GRIS_SOFT}; color:{theme.MUTED};")
        self.precio.setValue(float(v.precio))
        self.stock.setValue(int(v.cantidad_stock))
        self.atributos.setText(atributos_a_texto(v.atributos))
        self.estatus.setCurrentIndex(max(0, self.estatus.findData(v.estatus)))

    def a_datos(self) -> DatosVariante:
        return DatosVariante(sku=self.sku.text().strip().upper(), precio=Decimal(f"{self.precio.value():.2f}"),
                             cantidad_stock=self.stock.value(), atributos=texto_a_atributos(self.atributos.text()),
                             estatus=self.estatus.currentData(), id_variante=self.id_variante)


class ProductoEditorDialog(QDialog):
    """Alta / edición de un producto con sus variantes (talla, color… cada una con su SKU, precio y existencias)."""

    def __init__(self, ctx: Contexto, producto: Producto | None, parent=None):
        super().__init__(parent)
        self.ctx, self.producto = ctx, producto
        self.guardado: Producto | None = None
        self._filas: list[FilaVariante] = []
        self.setWindowTitle("Editar producto" if producto else "Nuevo producto")
        self.setModal(True)
        self.resize(1020, 760)

        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 18)
        v.setSpacing(12)
        v.addWidget(etiqueta("Editar producto" if producto else "Publicar un producto nuevo", "titulo"))
        v.addWidget(etiqueta(
            "Un producto tiene una o varias variantes. Cada variante es algo que se puede comprar: tiene su propio SKU "
            "(código único), precio y existencias. Ejemplo: la misma playera en talla M azul y talla L roja.",
            "subtitulo", wrap=True))

        datos = tarjeta()
        form = QFormLayout(datos)
        form.setContentsMargins(18, 16, 18, 16)
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(10)
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self.titulo = QLineEdit()
        self.titulo.setMaxLength(150)
        self.titulo.setPlaceholderText("Ej.: Playera de algodón orgánico")
        self.marca = QLineEdit()
        self.marca.setMaxLength(80)
        self.categoria = QComboBox()
        self.categoria.setMaxVisibleItems(18)
        self.estatus = QComboBox()
        for clave, texto in ETIQUETAS_PUBLICACION.items():
            self.estatus.addItem(texto + (" (visible en la tienda)" if clave == "ACTIVO" else " (oculto para los compradores)"), clave)
        self.descripcion = QPlainTextEdit()
        self.descripcion.setPlaceholderText("Materiales, medidas, qué incluye, cuidados…")
        self.descripcion.setFixedHeight(96)
        form.addRow("Título *", self.titulo)
        form.addRow("Marca", self.marca)
        form.addRow("Categoría *", self.categoria)
        form.addRow("Estado", self.estatus)
        form.addRow("Descripción", self.descripcion)
        v.addWidget(datos)

        # --------------------------------------------------------------- variantes
        cab = QHBoxLayout()
        cab.addWidget(etiqueta("Variantes", "h2"))
        cab.addStretch(1)
        cab.addWidget(boton("+ Agregar variante", "secondary", self._agregar_fila))
        self.btn_quitar = boton("Quitar la variante nueva seleccionada", "link", self._quitar_fila)
        cab.addWidget(self.btn_quitar)
        v.addLayout(cab)
        self.tabla = crear_tabla(["SKU", "Precio", "Existencias", "Atributos", "Estado"],
                                 {0: 190, 1: 140, 2: 120, 4: 150}, estirar=3, filas_altas=50)
        self.tabla.setSelectionBehavior(self.tabla.SelectionBehavior.SelectRows)
        v.addWidget(self.tabla, 1)
        v.addWidget(etiqueta("Los atributos se escriben como «Nombre=Valor» separados por punto y coma. "
                             "Las variantes ya guardadas no se borran: pásalas a «Pausado» para ocultarlas.", "muted", wrap=True))

        self.error = etiqueta("", "error", wrap=True)
        v.addWidget(self.error)
        self.indicador = Indicador()
        v.addWidget(self.indicador)
        pie = QHBoxLayout()
        pie.addStretch(1)
        pie.addWidget(boton("Cancelar", al_pulsar=self.reject))
        self.btn_guardar = boton("Guardar cambios" if producto else "Publicar producto", "primary", self._guardar)
        pie.addWidget(self.btn_guardar)
        v.addLayout(pie)

        self.ctx.cargar_categorias(self, self._poblar)

    # ------------------------------------------------------------------ carga inicial
    def _poblar(self, arbol) -> None:
        self.categoria.clear()
        self.categoria.addItem("— Elige una categoría —", None)
        for c in arbol.ordenadas_por_ruta():
            if c.estatus == "ACTIVO":
                self.categoria.addItem(arbol.ruta_texto(c.id_categoria), c.id_categoria)
        p = self.producto
        if p:
            self.titulo.setText(p.titulo)
            self.marca.setText(p.marca)
            self.descripcion.setPlainText(p.descripcion)
            self.estatus.setCurrentIndex(max(0, self.estatus.findData(p.estatus)))
            i = self.categoria.findData(p.id_categoria)
            if i < 0:  # categoría desactivada después de publicar el producto: se conserva visible
                self.categoria.addItem(f"{arbol.ruta_texto(p.id_categoria)} (categoría inactiva)", p.id_categoria)
                i = self.categoria.count() - 1
            self.categoria.setCurrentIndex(i)
            for var in p.variantes:
                self._agregar_fila(var)
        else:
            self._agregar_fila()

    def _agregar_fila(self, variante=None) -> None:
        fila = FilaVariante(variante.id_variante if variante is not None else None)
        if variante is not None:
            fila.cargar(variante)
        i = self.tabla.rowCount()
        self.tabla.insertRow(i)
        for col, w in enumerate((fila.sku, fila.precio, fila.stock, fila.atributos, fila.estatus)):
            self.tabla.setCellWidget(i, col, w)
        self.tabla.setRowHeight(i, 50)
        self._filas.append(fila)
        self.tabla.selectRow(i)
        if variante is None:
            fila.sku.setFocus()

    def _quitar_fila(self) -> None:
        sel = self.tabla.selectionModel().selectedRows()
        if not sel:
            return
        i = sel[0].row()
        if self._filas[i].id_variante:
            self.error.setText("Esa variante ya existe: no se borra, cámbiala a «Pausado».")
            return
        if len(self._filas) == 1 and self.producto is None:
            self.error.setText("Un producto necesita al menos una variante.")
            return
        self.error.clear()
        self._filas.pop(i)
        self.tabla.removeRow(i)

    # ------------------------------------------------------------------ guardar
    def _recolectar(self) -> DatosProducto:
        if not self.categoria.currentData():
            raise ErrorValidacion("Elige una categoría.")
        variantes = []
        for n, f in enumerate(self._filas, 1):
            try:
                variantes.append(f.a_datos())
            except ErrorValidacion as e:
                raise ErrorValidacion(f"Variante {n}: {e.mensaje}") from None
        return DatosProducto(titulo=self.titulo.text().strip(), id_categoria=self.categoria.currentData(),
                             descripcion=self.descripcion.toPlainText().strip(), marca=self.marca.text().strip(),
                             estatus=self.estatus.currentData(), variantes=variantes)

    def _guardar(self) -> None:
        self.error.clear()
        try:
            datos = self._recolectar()
        except ErrorValidacion as e:
            self.error.setText(e.mensaje)
            return
        self.btn_guardar.setEnabled(False)
        self.indicador.inicio()
        id_producto = self.producto.id_producto if self.producto else None
        self.ctx.ejecutar(self, lambda: self.ctx.gw.guardar_producto(datos, id_producto), self._listo, self._fallo)

    def _listo(self, producto: Producto) -> None:
        self.indicador.fin()
        self.guardado = producto
        self.accept()

    def _fallo(self, exc: BaseException) -> None:
        self.indicador.fin()
        self.btn_guardar.setEnabled(True)
        texto = getattr(exc, "mensaje", None) or str(exc)
        detalles = getattr(exc, "detalles", None)
        self.error.setText(texto + ("\n" + "\n".join(f"• {d}" for d in detalles) if detalles else ""))


# --------------------------------------------------------------------------- Mis productos
class MisProductosPage(PaginaBase):
    def __init__(self, ctx: Contexto, parent=None):
        super().__init__(ctx, parent)
        self._arbol = None
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(24, 20, 24, 16)
        raiz.setSpacing(12)
        enc = EncabezadoPagina("Mis productos", "Publica productos, ajusta precios y existencias o pausa lo que no quieras vender. "
                               "Doble clic en una fila para editarla.", "DynamoDB (productos, variantes_producto)")
        enc.acciones.addWidget(boton("Actualizar", al_pulsar=lambda: self.carga.reiniciar()))
        enc.acciones.addWidget(boton("+ Nuevo producto", "primary", self._nuevo))
        raiz.addWidget(enc)
        self.indicador = Indicador()
        raiz.addWidget(self.indicador)

        self.tabla = crear_tabla(["Producto", "Categoría", "Estado", "Desde", "Calificación", "Publicado"],
                                 {1: 170, 2: 90, 3: 100, 4: 140, 5: 100}, estirar=0, filas_altas=44)
        self.tabla.doubleClicked.connect(lambda _: self._editar())
        raiz.addWidget(self.tabla, 1)
        self.vacio = EstadoVacio("Todavía no publicas productos", "Pulsa «+ Nuevo producto» para crear el primero.")
        raiz.addWidget(self.vacio)
        self.vacio.setVisible(False)

        pie = QHBoxLayout()
        self.resumen = etiqueta("", "muted")
        pie.addWidget(self.resumen)
        pie.addStretch(1)
        self.btn_mas = boton("Cargar más productos")
        pie.addWidget(self.btn_mas)
        self.btn_editar = boton("Editar seleccionado", "secondary", self._editar)
        pie.addWidget(self.btn_editar)
        raiz.addLayout(pie)
        self.carga = CargaPaginada(ctx, self, self.indicador, self.btn_mas,
                                   lambda cur: ctx.gw.listar_mis_productos(cur, 40), self._recibir, self._resumen)

    def al_mostrar(self) -> None:
        self.ctx.cargar_categorias(self, self._con_arbol)

    def _con_arbol(self, arbol) -> None:
        self._arbol = arbol
        self.carga.reiniciar()

    def al_cerrar_sesion(self) -> None:
        self.carga.invalidar()
        self.tabla.setRowCount(0)
        self._arbol = None

    def _recibir(self, items: list[ProductoResumen], primera: bool) -> None:
        if primera:
            self.tabla.setRowCount(0)
        for p in items:
            f = self.tabla.rowCount()
            self.tabla.insertRow(f)
            self.tabla.setItem(f, 0, celda(p.titulo, negrita=True, dato=p.id_producto, tooltip=p.titulo))
            self.tabla.setItem(f, 1, celda(self._arbol.nombre(p.id_categoria) if self._arbol else "—", color=theme.MUTED))
            item = celda(ETIQUETAS_PUBLICACION.get(p.estatus, p.estatus), negrita=True,
                         color=theme.OK if p.estatus == "ACTIVO" else theme.MUTED, dato=p.estatus)
            self.tabla.setItem(f, 2, item)
            self.tabla.setItem(f, 3, celda(formato_dinero(p.precio_desde) if p.precio_desde else "—", derecha=True))
            self.tabla.setItem(f, 4, celda(estrellas(p.calificacion_promedio, p.num_resenas), color=theme.WARN))
            self.tabla.setItem(f, 5, celda(fecha_corta(p.fecha_creacion, con_hora=False)))
        self.vacio.setVisible(self.tabla.rowCount() == 0)
        self.tabla.setVisible(self.tabla.rowCount() > 0)

    def _resumen(self) -> None:
        n = self.tabla.rowCount()
        self.resumen.setText(f"{n} producto{'s' if n != 1 else ''} cargado{'s' if n != 1 else ''}"
                             + (" · hay más por cargar" if self.carga.hay_mas else ""))
        self.btn_editar.setEnabled(n > 0)

    def _nuevo(self) -> None:
        dlg = ProductoEditorDialog(self.ctx, None, self.window())
        if dlg.exec() == QDialog.Accepted:
            self.ctx.avisar(f"Producto «{dlg.guardado.titulo}» publicado")
            self.carga.reiniciar()

    def _editar(self) -> None:
        sel = self.tabla.selectionModel().selectedRows()
        if not sel:
            self.ctx.avisar("Selecciona un producto de la lista")
            return
        id_producto = self.tabla.item(sel[0].row(), 0).data(Qt.UserRole)
        self.indicador.inicio()

        def listo(prod: Producto) -> None:
            self.indicador.fin()
            dlg = ProductoEditorDialog(self.ctx, prod, self.window())
            if dlg.exec() == QDialog.Accepted:
                self.ctx.avisar(f"Producto «{dlg.guardado.titulo}» actualizado")
                self.carga.reiniciar()

        def fallo(exc: BaseException) -> None:
            self.indicador.fin()
            mostrar_error(self, exc)

        self.ctx.ejecutar(self, lambda: self.ctx.gw.obtener_producto(id_producto), listo, fallo)


# --------------------------------------------------------------------------- Mis ventas
class MisVentasPage(PaginaBase):
    def __init__(self, ctx: Contexto, parent=None):
        super().__init__(ctx, parent)
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(24, 20, 24, 16)
        raiz.setSpacing(12)
        enc = EncabezadoPagina("Mis ventas", "Los productos tuyos que se han comprado. Cuando un pedido está pagado, "
                               "prepáralo y márcalo como enviado.", "MySQL (detalle_pedido, pedidos) + DynamoDB")
        enc.acciones.addWidget(boton("Actualizar", al_pulsar=lambda: self.carga.reiniciar()))
        raiz.addWidget(enc)
        self.indicador = Indicador()
        raiz.addWidget(self.indicador)

        self.tabla = crear_tabla(["Pedido", "Fecha", "Producto", "Cant.", "Precio", "Subtotal", "Estatus", ""],
                                 {0: 80, 1: 140, 3: 56, 4: 100, 5: 110, 6: 110, 7: 210}, estirar=2, filas_altas=56)
        self.tabla.setSelectionMode(self.tabla.SelectionMode.NoSelection)
        raiz.addWidget(self.tabla, 1)
        self.vacio = EstadoVacio("Aún no tienes ventas", "Cuando alguien compre uno de tus productos aparecerá aquí.")
        raiz.addWidget(self.vacio)
        self.vacio.setVisible(False)

        pie = QHBoxLayout()
        self.resumen = etiqueta("", "muted")
        pie.addWidget(self.resumen)
        pie.addStretch(1)
        self.btn_mas = boton("Cargar más ventas")
        pie.addWidget(self.btn_mas)
        raiz.addLayout(pie)
        self.carga = CargaPaginada(ctx, self, self.indicador, self.btn_mas,
                                   lambda cur: ctx.gw.listar_mis_ventas(cur, 40), self._recibir, self._resumen)

    def al_mostrar(self) -> None:
        self.carga.reiniciar()

    def al_cerrar_sesion(self) -> None:
        self.carga.invalidar()
        self.tabla.setRowCount(0)

    def _recibir(self, items, primera: bool) -> None:
        if primera:
            self.tabla.setRowCount(0)
        for l in items:
            f = self.tabla.rowCount()
            self.tabla.insertRow(f)
            self.tabla.setItem(f, 0, celda(f"#{l.id_pedido}", negrita=True, dato=l.id_pedido))
            self.tabla.setItem(f, 1, celda(fecha_corta(l.fecha_pedido)))
            self.tabla.setItem(f, 2, celda(f"{l.titulo}\n{atributos_texto(l.atributos)}  ·  {l.sku}"))
            self.tabla.setItem(f, 3, celda(str(l.cantidad), derecha=True))
            self.tabla.setItem(f, 4, celda(formato_dinero(l.precio_unitario), derecha=True))
            self.tabla.setItem(f, 5, celda(formato_dinero(l.subtotal), derecha=True, negrita=True, dato=l))
            self.tabla.setItem(f, 6, celda_estatus(l.estatus_pedido))
            if l.estatus_pedido == "PAGADO":
                cont = QWidget()
                h = QHBoxLayout(cont)
                h.setContentsMargins(4, 10, 8, 10)
                h.addWidget(boton("Marcar como enviado", "primary", lambda pid=l.id_pedido: self._enviar(pid)))
                self.tabla.setCellWidget(f, 7, cont)

    def _resumen(self) -> None:
        validas = [self.tabla.item(f, 5).data(Qt.UserRole) for f in range(self.tabla.rowCount())]
        validas = [l for l in validas if l and l.estatus_pedido != "CANCELADO"]
        total = sum((l.subtotal for l in validas), Decimal("0"))
        n = self.tabla.rowCount()
        self.vacio.setVisible(n == 0)
        self.tabla.setVisible(n > 0)
        self.resumen.setText(f"{n} línea{'s' if n != 1 else ''} cargada{'s' if n != 1 else ''} · "
                             f"vendido (sin cancelados): {formato_dinero(total)}"
                             + (" · hay más por cargar" if self.carga.hay_mas else ""))

    def _enviar(self, id_pedido: int) -> None:
        if not confirmar(self.window(), "Marcar como enviado",
                         f"¿Ya enviaste el pedido #{id_pedido}? El comprador verá que va en camino.", "Sí, ya lo envié"):
            return
        self.indicador.inicio()

        def listo(_):
            self.indicador.fin()
            self.ctx.avisar(f"Pedido #{id_pedido} marcado como enviado")
            self.carga.reiniciar()

        def fallo(exc):
            self.indicador.fin()
            mostrar_error(self, exc)

        self.ctx.ejecutar(self, lambda: self.ctx.gw.cambiar_estatus_pedido(id_pedido, "ENVIADO"), listo, fallo)
