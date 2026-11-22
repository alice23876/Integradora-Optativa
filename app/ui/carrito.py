"""Carrito de compras y confirmación del pedido (checkout)."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QPlainTextEdit, QSpinBox, QStackedLayout, QVBoxLayout,
                               QWidget)

from ..models import METODOS_PAGO, Carrito, Pedido
from ..util import formato_dinero
from . import theme
from .contexto import Contexto
from .pagina import PaginaBase
from .widgets import (EncabezadoPagina, EstadoVacio, Indicador, SelectorCantidad, atributos_texto, boton, celda, crear_tabla, etiqueta,
                      informar, linea_separadora, mostrar_error, tarjeta)


class CheckoutDialog(QDialog):
    def __init__(self, ctx: Contexto, carrito: Carrito, parent=None):
        super().__init__(parent)
        self.ctx, self.carrito = ctx, carrito
        self.pedido: Pedido | None = None
        self.setWindowTitle("Confirmar pedido")
        self.setModal(True)
        self.setMinimumWidth(560)
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 18)
        v.setSpacing(10)
        v.addWidget(etiqueta("Confirmar pedido", "h2"))

        resumen = tarjeta()
        rv = QVBoxLayout(resumen)
        rv.setContentsMargins(16, 12, 16, 12)
        rv.setSpacing(4)
        disponibles = [l for l in carrito.lineas if l.disponible]
        for l in disponibles[:5]:
            fila = QHBoxLayout()
            fila.addWidget(etiqueta(f"{l.cantidad} × {l.titulo}"), 1)
            fila.addWidget(etiqueta(formato_dinero(l.subtotal)))
            rv.addLayout(fila)
        if len(disponibles) > 5:
            rv.addWidget(etiqueta(f"… y {len(disponibles) - 5} producto(s) más", "muted"))
        rv.addWidget(linea_separadora())
        total = QHBoxLayout()
        total.addWidget(etiqueta("Total a pagar", "h2"), 1)
        t = etiqueta(formato_dinero(carrito.total), "precio")
        total.addWidget(t)
        rv.addLayout(total)
        v.addWidget(resumen)

        v.addWidget(etiqueta("Dirección de envío", "muted"))
        self.direccion = QPlainTextEdit()
        self.direccion.setPlaceholderText("Calle y número, colonia, ciudad, estado y código postal")
        self.direccion.setFixedHeight(84)
        guardada = ctx.ajustes.value(f"direccion/{ctx.usuario.id_usuario}", "")
        self.direccion.setPlainText(str(guardada or ""))
        v.addWidget(self.direccion)

        v.addWidget(etiqueta("Método de pago", "muted"))
        self.metodo = QComboBox()
        for m in METODOS_PAGO:
            self.metodo.addItem(theme.ETIQUETAS_METODO.get(m, m), m)
        v.addWidget(self.metodo)

        nota = etiqueta("Por seguridad esta aplicación nunca captura datos de tarjeta. El cobro lo procesa el servidor con la "
                        "pasarela de pagos; en modo demostración el pago se simula y siempre se aprueba.", "muted", wrap=True)
        nota.setStyleSheet("font-size:9pt;")
        v.addWidget(nota)
        self.error = etiqueta("", "error", wrap=True)
        v.addWidget(self.error)
        self.indicador = Indicador()
        v.addWidget(self.indicador)
        fila = QHBoxLayout()
        fila.addStretch(1)
        fila.addWidget(boton("Volver al carrito", al_pulsar=self.reject))
        self.btn = boton(f"Pagar {formato_dinero(carrito.total)}", "primary", self._confirmar)
        fila.addWidget(self.btn)
        v.addLayout(fila)

    def _confirmar(self) -> None:
        self.error.clear()
        direccion, metodo = self.direccion.toPlainText().strip(), self.metodo.currentData()
        self.btn.setEnabled(False)
        self.btn.setText("Procesando…")
        self.indicador.inicio()
        self.ctx.ejecutar(self, lambda: self.ctx.gw.checkout(direccion, metodo), self._listo, self._fallo)

    def _listo(self, pedido: Pedido) -> None:
        self.indicador.fin()
        self.ctx.ajustes.setValue(f"direccion/{self.ctx.usuario.id_usuario}", pedido.direccion_envio)
        self.pedido = pedido
        self.accept()

    def _fallo(self, exc: BaseException) -> None:
        self.indicador.fin()
        self.btn.setEnabled(True)
        self.btn.setText(f"Pagar {formato_dinero(self.carrito.total)}")
        detalles = getattr(exc, "detalles", [])
        self.error.setText(str(exc) + ("\n" + "\n".join(f"• {d}" for d in detalles) if detalles else ""))
        if getattr(exc, "codigo", "") in ("stock_insuficiente", "pago"):
            self.ctx.refrescar_carrito()


class CarritoPage(PaginaBase):
    def __init__(self, ctx: Contexto, parent=None):
        super().__init__(ctx, parent)
        self._carrito: Carrito | None = None
        self._pend: dict[int, int] = {}
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(450)
        self._timer.timeout.connect(self._aplicar_pendientes)

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(24, 20, 24, 16)
        raiz.setSpacing(12)
        raiz.addWidget(EncabezadoPagina(
            "Mi carrito", "Cambia las cantidades o quita productos. El precio y las existencias se confirman de nuevo al pagar.",
            "MySQL (carritos) + DynamoDB (precios y existencias)"))
        self.indicador = Indicador()
        raiz.addWidget(self.indicador)

        cont = QWidget()
        self.pila = QStackedLayout(cont)
        raiz.addWidget(cont, 1)

        lleno = QWidget()
        lv = QVBoxLayout(lleno)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(12)
        self.tabla = crear_tabla(["Producto", "Precio", "Cantidad", "Subtotal", ""], {1: 110, 2: 170, 3: 120, 4: 100},
                                 estirar=0, filas_altas=64)
        self.tabla.setSelectionMode(self.tabla.SelectionMode.NoSelection)
        self.tabla.cellDoubleClicked.connect(self._ver_producto)
        lv.addWidget(self.tabla, 1)

        pie = tarjeta()
        pv = QHBoxLayout(pie)
        pv.setContentsMargins(18, 14, 18, 14)
        self.articulos = etiqueta("", "muted")
        pv.addWidget(self.articulos)
        self.aviso = etiqueta("", "error")
        pv.addWidget(self.aviso, 1)
        pv.addWidget(etiqueta("Total", "muted"))
        self.total = etiqueta("$0.00", "precio")
        pv.addWidget(self.total)
        pv.addWidget(boton("Seguir comprando", al_pulsar=lambda: self.ctx.navegar.emit("tienda")))
        self.btn_pagar = boton("Finalizar compra", "primary", self._pagar)
        pv.addWidget(self.btn_pagar)
        lv.addWidget(pie)
        self.pila.addWidget(lleno)

        self.vacio = QWidget()
        vv = QVBoxLayout(self.vacio)
        vv.setAlignment(Qt.AlignCenter)
        vv.addWidget(EstadoVacio("Tu carrito está vacío", "Explora la tienda y agrega productos: aparecerán aquí."))
        vv.addWidget(boton("Ir a la tienda", "primary", lambda: self.ctx.navegar.emit("tienda")), 0, Qt.AlignHCenter)
        self.pila.addWidget(self.vacio)

    # ------------------------------------------------------------------ carga
    def al_mostrar(self) -> None:
        self._cargar()

    def al_cerrar_sesion(self) -> None:
        self._carrito = None
        self.tabla.setRowCount(0)

    def _cargar(self) -> None:
        self.indicador.inicio()
        self.ctx.ejecutar(self, self.ctx.gw.obtener_carrito, self._mostrar, self._fallo)

    def _fallo(self, exc: BaseException) -> None:
        self.indicador.fin()
        mostrar_error(self, exc)

    def _mostrar(self, carrito: Carrito) -> None:
        if self.indicador.isVisible():
            self.indicador.fin()
        self._carrito = carrito
        self.ctx.carrito_actualizado.emit(carrito.num_articulos)
        self.tabla.blockSignals(True)
        self.tabla.setRowCount(0)
        for l in carrito.lineas:
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)
            sin_stock = (not l.disponible) or l.cantidad > l.stock_disponible
            texto = f"{l.titulo}\n{atributos_texto(l.atributos)}  ·  {l.sku}"
            if not l.disponible:
                texto += "\nYa no está disponible"
            elif l.cantidad > l.stock_disponible:
                texto += f"\nSolo quedan {l.stock_disponible}"
            self.tabla.setItem(fila, 0, celda(texto, color=theme.DANGER if sin_stock else None, dato=l.id_producto))
            self.tabla.setItem(fila, 1, celda(formato_dinero(l.precio_unitario), derecha=True))
            spin = SelectorCantidad()
            spin.setRange(1, max(1, min(99, l.stock_disponible)))
            spin.setValue(min(l.cantidad, spin.maximum()))
            spin.setEnabled(l.disponible)
            spin.valueChanged.connect(lambda val, i=l.id_detalle_carrito: self._cantidad(i, val))
            cont = QWidget()
            ch = QHBoxLayout(cont)
            ch.setContentsMargins(8, 0, 8, 0)
            ch.addWidget(spin)
            self.tabla.setCellWidget(fila, 2, cont)
            self.tabla.setItem(fila, 3, celda(formato_dinero(l.subtotal) if l.disponible else "—", derecha=True, negrita=True))
            quitar = boton("Quitar", "danger", lambda i=l.id_detalle_carrito: self._quitar(i))
            c2 = QWidget()
            h2 = QHBoxLayout(c2)
            h2.setContentsMargins(4, 12, 8, 12)
            h2.addWidget(quitar)
            self.tabla.setCellWidget(fila, 4, c2)
            self.tabla.setRowHeight(fila, 70)
        self.tabla.blockSignals(False)
        self.articulos.setText(f"{carrito.num_articulos} artículo(s)")
        self.total.setText(formato_dinero(carrito.total))
        self.aviso.setText("Revisa los productos marcados en rojo antes de pagar." if carrito.hay_problemas else "")
        self.btn_pagar.setEnabled(bool(carrito.lineas) and not carrito.hay_problemas)
        self.pila.setCurrentIndex(0 if carrito.lineas else 1)

    # ------------------------------------------------------------------ acciones
    def _cantidad(self, id_detalle: int, valor: int) -> None:
        self._pend[id_detalle] = valor
        self.btn_pagar.setEnabled(False)
        self._timer.start()

    def _aplicar_pendientes(self) -> None:
        pend, self._pend = dict(self._pend), {}
        if not pend:
            return

        def tarea():
            carrito = None
            for id_det, qty in pend.items():
                carrito = self.ctx.gw.cambiar_cantidad(id_det, qty)
            return carrito

        self.indicador.inicio()
        self.ctx.ejecutar(self, tarea, self._mostrar, self._fallo_cambio)

    def _fallo_cambio(self, exc: BaseException) -> None:
        self.indicador.fin()
        mostrar_error(self, exc)
        self._cargar()

    def _quitar(self, id_detalle: int) -> None:
        self._pend.pop(id_detalle, None)
        self.indicador.inicio()
        self.ctx.ejecutar(self, lambda: self.ctx.gw.quitar_del_carrito(id_detalle), self._mostrar, self._fallo_cambio)

    def _ver_producto(self, fila: int, _col: int) -> None:
        item = self.tabla.item(fila, 0)
        if item and item.data(Qt.UserRole):
            from .producto_dialog import abrir_producto
            abrir_producto(self.ctx, item.data(Qt.UserRole), self.window())
            self._cargar()

    def _pagar(self) -> None:
        if not self._carrito or not self._carrito.lineas:
            return
        dlg = CheckoutDialog(self.ctx, self._carrito, self.window())
        if dlg.exec() == QDialog.Accepted and dlg.pedido:
            p = dlg.pedido
            self.ctx.carrito_actualizado.emit(0)
            self.ctx.pedido_a_seleccionar = p.id_pedido
            informar(self.window(), "¡Pedido realizado!",
                     f"Tu pedido #{p.id_pedido} por {formato_dinero(p.monto_total)} quedó {theme.ETIQUETAS_ESTATUS.get(p.estatus, p.estatus).lower()}.",
                     "Puedes seguirlo en «Mis pedidos». Cuando lo recibas, podrás reseñar tus productos.")
            self.ctx.navegar.emit("pedidos")
        else:
            self._cargar()
