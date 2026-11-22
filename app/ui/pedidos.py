"""Pedidos: «Mis pedidos» (comprador/vendedor como cliente) y «Todos los pedidos» (administrador)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QScrollArea, QSplitter, QStackedLayout, QVBoxLayout,
                               QWidget)

from ..models import ESTATUS_PEDIDO, TRANSICIONES_PEDIDO, Pedido
from ..util import formato_dinero
from . import theme
from .contexto import Contexto
from .pagina import PaginaBase
from .producto_dialog import ResenaDialog
from .widgets import (EncabezadoPagina, EstadoVacio, Indicador, atributos_texto, boton, celda, celda_estatus, chip_estatus,
                      confirmar, crear_tabla, etiqueta, fecha_corta, informar, mostrar_error, tarjeta)

ETIQUETA_ACCION = {"PAGADO": "Marcar como pagado", "ENVIADO": "Marcar como enviado",
                   "ENTREGADO": "Marcar como entregado", "CANCELADO": "Cancelar pedido"}


class PedidosPage(PaginaBase):
    def __init__(self, ctx: Contexto, modo: str = "mis", parent=None):
        super().__init__(ctx, parent)
        self.modo = modo
        self._gen_lista = self._gen_detalle = 0
        self._cursor: str | None = None
        self._hay_mas = False
        self._cargando = False
        self._pedido: Pedido | None = None

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(24, 20, 24, 16)
        raiz.setSpacing(12)
        if modo == "admin":
            enc = EncabezadoPagina("Todos los pedidos", "Supervisa y gestiona los pedidos de toda la plataforma.",
                                   "MySQL (pedidos, pagos) + DynamoDB")
            self.filtro = QComboBox()
            self.filtro.addItem("Todos los estatus", None)
            for e in ESTATUS_PEDIDO:
                self.filtro.addItem(theme.ETIQUETAS_ESTATUS[e], e)
            self.filtro.currentIndexChanged.connect(lambda _: self._cargar(True))
            enc.acciones.addWidget(self.filtro)
        else:
            enc = EncabezadoPagina("Mis pedidos", "Sigue tus compras, cancela un pedido o confirma que lo recibiste. "
                                   "Al recibirlo podrás reseñar cada producto.", "MySQL (pedidos, pagos) + DynamoDB")
            self.filtro = None
        enc.acciones.addWidget(boton("Actualizar", al_pulsar=lambda: self._cargar(True)))
        raiz.addWidget(enc)
        self.indicador = Indicador()
        raiz.addWidget(self.indicador)

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        raiz.addWidget(split, 1)

        # ------------------------------------------------------------- lista
        izq = QWidget()
        iv = QVBoxLayout(izq)
        iv.setContentsMargins(0, 0, 8, 0)
        cols = ["Pedido", "Fecha", "Estatus", "Total"] + (["Comprador"] if modo == "admin" else [])
        anchos = {0: 60, 1: 96, 2: 96, 3: 96, 4: 120} if modo == "admin" else {0: 64, 1: 96, 2: 92, 3: 100}
        self.tabla = crear_tabla(cols, anchos)  # la fecha va sin hora (la hora está en el detalle)
        if modo == "admin":
            self.tabla.setColumnHidden(1, True)  # en la vista de administrador la lista es más angosta; la fecha está en el detalle
        self.tabla.horizontalHeader().setStretchLastSection(True)
        self.tabla.itemSelectionChanged.connect(self._seleccion)
        iv.addWidget(self.tabla, 1)
        self.btn_mas = boton("Cargar más pedidos", "secondary", lambda: self._cargar(False))
        self.btn_mas.setVisible(False)
        iv.addWidget(self.btn_mas)
        split.addWidget(izq)

        # ------------------------------------------------------------- detalle
        der = QWidget()
        self.pila = QStackedLayout(der)
        self.placeholder = EstadoVacio("Selecciona un pedido", "Aquí verás los productos, el pago y las acciones disponibles.")
        self.pila.addWidget(self.placeholder)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.detalle = QWidget()
        self.detalle.setProperty("pagina", True)
        dv = QVBoxLayout(self.detalle)
        dv.setContentsMargins(8, 0, 0, 0)
        dv.setSpacing(12)
        scroll.setWidget(self.detalle)
        self.pila.addWidget(scroll)

        cab = tarjeta()
        cv = QVBoxLayout(cab)
        cv.setContentsMargins(18, 14, 18, 14)
        cv.setSpacing(4)
        fila = QHBoxLayout()
        self.d_titulo = etiqueta("", "h2")
        fila.addWidget(self.d_titulo)
        self.d_chip_caja = QHBoxLayout()
        fila.addLayout(self.d_chip_caja)
        fila.addStretch(1)
        self.d_total = etiqueta("", "precio")
        fila.addWidget(self.d_total)
        cv.addLayout(fila)
        self.d_fecha = etiqueta("", "muted")
        self.d_comprador = etiqueta("", "muted")
        self.d_direccion = etiqueta("", wrap=True)
        for w in (self.d_fecha, self.d_comprador, self.d_direccion):
            cv.addWidget(w)
        dv.addWidget(cab)

        cl = tarjeta()
        clv = QVBoxLayout(cl)
        clv.setContentsMargins(14, 12, 14, 14)
        clv.addWidget(etiqueta("Productos", "h2"))
        self.t_lineas = crear_tabla(["Producto", "Cant.", "Precio", "Subtotal", ""], {1: 50, 2: 95, 3: 100, 4: 112},
                                    estirar=0, filas_altas=56)
        self.t_lineas.setSelectionMode(self.t_lineas.SelectionMode.NoSelection)
        clv.addWidget(self.t_lineas)
        dv.addWidget(cl)

        self.card_pagos = tarjeta()
        pv = QVBoxLayout(self.card_pagos)
        pv.setContentsMargins(14, 12, 14, 14)
        pv.addWidget(etiqueta("Pagos", "h2"))
        self.t_pagos = crear_tabla(["Método", "Estatus", "Monto", "Referencia", "Fecha"], {0: 160, 1: 95, 2: 100, 4: 135},
                                   estirar=3)
        self.t_pagos.setSelectionMode(self.t_pagos.SelectionMode.NoSelection)
        pv.addWidget(self.t_pagos)
        dv.addWidget(self.card_pagos)

        self.acciones = QHBoxLayout()
        self.acciones.setSpacing(8)
        dv.addLayout(self.acciones)
        dv.addStretch(1)
        split.addWidget(der)
        if modo == "mis":
            split.setSizes([430, 840])
        else:  # la lista no baja de 410 px (si no, se recorta); el detalle recibe el resto
            izq.setMinimumWidth(410)
            split.setSizes([440, 820])
        for t in (self.t_lineas, self.t_pagos):  # altura exacta: sin barras de desplazamiento internas
            t.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            t.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    # ------------------------------------------------------------------ lista
    def al_mostrar(self) -> None:
        self._cargar(True)

    def al_cerrar_sesion(self) -> None:
        self.tabla.setRowCount(0)
        self.pila.setCurrentIndex(0)
        self._pedido = None

    def _cargar(self, reiniciar: bool) -> None:
        if reiniciar:
            self._gen_lista += 1
            self._cursor, self._cargando = None, False
            seleccion = self._pedido.id_pedido if self._pedido else self.ctx.pedido_a_seleccionar
            self._reseleccionar = seleccion
            self.tabla.setRowCount(0)
        if self._cargando or (not reiniciar and not self._hay_mas):
            return
        self._cargando = True
        self.btn_mas.setVisible(False)
        self.indicador.inicio()
        gen, cursor = self._gen_lista, self._cursor
        estatus = self.filtro.currentData() if self.filtro else None
        if self.modo == "admin":
            fn = lambda: self.ctx.gw.listar_pedidos_admin(estatus, cursor, 30)  # noqa: E731
        else:
            fn = lambda: self.ctx.gw.listar_mis_pedidos(cursor, 30)  # noqa: E731
        self.ctx.ejecutar(self, fn, lambda pag: self._lista(gen, pag), lambda exc: self._fallo_lista(gen, exc))

    def _fallo_lista(self, gen: int, exc: BaseException) -> None:
        if gen != self._gen_lista:
            return
        self._cargando = False
        self.indicador.fin()
        mostrar_error(self, exc)

    def _lista(self, gen: int, pag) -> None:
        if gen != self._gen_lista:
            return
        self._cargando = False
        self.indicador.fin()
        self.tabla.blockSignals(True)
        for p in pag.items:
            self._poner_fila(self.tabla.rowCount(), p, insertar=True)
        self.tabla.blockSignals(False)
        self._cursor, self._hay_mas = pag.siguiente, pag.siguiente is not None
        self.btn_mas.setVisible(self._hay_mas)
        if self.tabla.rowCount() == 0:
            self.placeholder.poner("Aún no hay pedidos", "Cuando compres algo, aparecerá aquí." if self.modo == "mis" else "")
            self.pila.setCurrentIndex(0)
            return
        objetivo = getattr(self, "_reseleccionar", None)
        if objetivo is not None:
            for fila in range(self.tabla.rowCount()):
                if self.tabla.item(fila, 0).data(Qt.UserRole).id_pedido == objetivo:
                    self.tabla.selectRow(fila)
                    break
            else:
                if self._hay_mas:
                    self._cargar(False)
            self._reseleccionar = None
            self.ctx.pedido_a_seleccionar = None

    def _poner_fila(self, fila: int, p: Pedido, insertar: bool = False) -> None:
        if insertar:
            self.tabla.insertRow(fila)
        self.tabla.setItem(fila, 0, celda(f"#{p.id_pedido}", negrita=True, dato=p))
        self.tabla.setItem(fila, 1, celda(fecha_corta(p.fecha_pedido, con_hora=False)))
        self.tabla.setItem(fila, 2, celda_estatus(p.estatus))
        self.tabla.setItem(fila, 3, celda(formato_dinero(p.monto_total), derecha=True))
        if self.modo == "admin":
            self.tabla.setItem(fila, 4, celda(p.nombre_comprador or f"Usuario {p.id_comprador}"))

    # ------------------------------------------------------------------ detalle
    def _seleccion(self) -> None:
        filas = self.tabla.selectionModel().selectedRows()
        if not filas:
            return
        id_pedido = self.tabla.item(filas[0].row(), 0).data(Qt.UserRole).id_pedido
        self._gen_detalle += 1
        gen = self._gen_detalle
        self.indicador.inicio()
        self.ctx.ejecutar(self, lambda: self.ctx.gw.obtener_pedido(id_pedido),
                          lambda p: self._mostrar(gen, p), lambda e: self._fallo_detalle(gen, e))

    def _fallo_detalle(self, gen: int, exc: BaseException) -> None:
        if gen == self._gen_detalle:
            self.indicador.fin()
            mostrar_error(self, exc)

    def _mostrar(self, gen: int, p: Pedido) -> None:
        if gen != self._gen_detalle:
            return
        self.indicador.fin()
        self._pedido = p
        self.pila.setCurrentIndex(1)
        self.d_titulo.setText(f"Pedido #{p.id_pedido}")
        while self.d_chip_caja.count():
            w = self.d_chip_caja.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.d_chip_caja.addWidget(chip_estatus(p.estatus))
        self.d_total.setText(formato_dinero(p.monto_total))
        self.d_fecha.setText(f"Realizado el {fecha_corta(p.fecha_pedido)}")
        self.d_comprador.setText(f"Comprador: {p.nombre_comprador}" if p.nombre_comprador else "")
        self.d_comprador.setVisible(bool(p.nombre_comprador))
        self.d_direccion.setText(f"Envío a: {p.direccion_envio}")

        es_dueno = p.id_comprador == self.ctx.usuario.id_usuario
        puede_resenar = es_dueno and p.estatus == "ENTREGADO"
        self.t_lineas.setColumnHidden(4, not puede_resenar)  # la columna de «Reseñar» solo existe cuando se usa
        self.t_lineas.setRowCount(0)
        for l in p.lineas:
            fila = self.t_lineas.rowCount()
            self.t_lineas.insertRow(fila)
            self.t_lineas.setItem(fila, 0, celda(f"{l.titulo}\n{atributos_texto(l.atributos)}  ·  {l.sku}", dato=l.id_producto))
            self.t_lineas.setItem(fila, 1, celda(str(l.cantidad), derecha=True))
            self.t_lineas.setItem(fila, 2, celda(formato_dinero(l.precio_unitario), derecha=True))
            self.t_lineas.setItem(fila, 3, celda(formato_dinero(l.subtotal), derecha=True, negrita=True))
            if puede_resenar and l.id_producto:
                cont = QWidget()
                h = QHBoxLayout(cont)
                h.setContentsMargins(4, 10, 8, 10)
                h.addWidget(boton("Reseñar", "secondary", lambda lin=l: self._resenar(lin)))
                self.t_lineas.setCellWidget(fila, 4, cont)
            self.t_lineas.setRowHeight(fila, 58)
        self.t_lineas.setFixedHeight(46 + 58 * max(1, len(p.lineas)))

        self.card_pagos.setVisible(bool(p.pagos))
        self.t_pagos.setRowCount(0)
        for pg in p.pagos:
            fila = self.t_pagos.rowCount()
            self.t_pagos.insertRow(fila)
            self.t_pagos.setItem(fila, 0, celda(theme.ETIQUETAS_METODO.get(pg.metodo_pago, pg.metodo_pago)))
            self.t_pagos.setItem(fila, 1, celda_estatus(pg.estatus))
            self.t_pagos.setItem(fila, 2, celda(formato_dinero(pg.monto), derecha=True))
            self.t_pagos.setItem(fila, 3, celda(pg.referencia_transaccion or "—", color=theme.MUTED))
            self.t_pagos.setItem(fila, 4, celda(fecha_corta(pg.fecha_pago)))
        self.t_pagos.setFixedHeight(46 + 38 * max(1, len(p.pagos)))
        self._armar_acciones(p, es_dueno)

        # refleja el estatus actual en la lista sin recargarla
        for fila in range(self.tabla.rowCount()):
            if self.tabla.item(fila, 0).data(Qt.UserRole).id_pedido == p.id_pedido:
                p.nombre_comprador = p.nombre_comprador or self.tabla.item(fila, 0).data(Qt.UserRole).nombre_comprador
                self.tabla.blockSignals(True)
                self._poner_fila(fila, p)
                self.tabla.blockSignals(False)

    def _armar_acciones(self, p: Pedido, es_dueno: bool) -> None:
        while self.acciones.count():
            w = self.acciones.takeAt(0).widget()
            if w:
                w.deleteLater()
        rol = self.ctx.usuario.rol
        if rol == "ADMIN" and self.modo == "admin":
            for nuevo in TRANSICIONES_PEDIDO.get(p.estatus, ()):
                peligro = nuevo == "CANCELADO"
                self.acciones.addWidget(boton(ETIQUETA_ACCION[nuevo], "danger" if peligro else "primary" if nuevo != "PAGADO" else "secondary",
                                              lambda n=nuevo: self._cambiar(p, n)))
        elif es_dueno:
            if p.estatus in ("PENDIENTE", "PAGADO"):
                self.acciones.addWidget(boton("Cancelar pedido", "danger", lambda: self._cambiar(p, "CANCELADO")))
            if p.estatus == "ENVIADO":
                self.acciones.addWidget(boton("Confirmar que ya lo recibí", "primary", lambda: self._cambiar(p, "ENTREGADO")))
        self.acciones.addStretch(1)

    def _cambiar(self, p: Pedido, nuevo: str) -> None:
        if nuevo == "CANCELADO":
            extra = " Se reembolsará el pago y los productos volverán al inventario." if p.estatus == "PAGADO" else ""
            if not confirmar(self.window(), "Cancelar pedido", f"¿Cancelar el pedido #{p.id_pedido}?{extra} Esta acción no se puede deshacer.",
                             "Sí, cancelar pedido", peligro=True):
                return
        elif nuevo == "ENTREGADO" and p.id_comprador == self.ctx.usuario.id_usuario:
            if not confirmar(self.window(), "Confirmar recepción", "¿Ya recibiste todos los productos de este pedido?", "Sí, ya lo recibí"):
                return
        self.indicador.inicio()
        self.ctx.ejecutar(self, lambda: self.ctx.gw.cambiar_estatus_pedido(p.id_pedido, nuevo),
                          lambda ped: self._cambiado(ped), self._fallo_cambio)

    def _cambiado(self, ped: Pedido) -> None:
        self.indicador.fin()
        self._gen_detalle += 1
        self._mostrar(self._gen_detalle, ped)
        self.ctx.avisar(f"Pedido #{ped.id_pedido}: ahora está {theme.ETIQUETAS_ESTATUS.get(ped.estatus, ped.estatus).lower()}")

    def _fallo_cambio(self, exc: BaseException) -> None:
        self.indicador.fin()
        mostrar_error(self, exc)
        self._seleccion()  # recarga el detalle por si el estado cambió en otro lado

    def _resenar(self, linea) -> None:
        def listo(e):
            if not e.puede:
                informar(self.window(), "Reseña", e.motivo)
                return
            dlg = ResenaDialog(self.ctx, linea.id_producto, linea.titulo, self.window())
            if dlg.exec() == QDialog.Accepted:
                self.ctx.avisar("¡Gracias por tu reseña!")

        self.ctx.ejecutar(self, lambda: self.ctx.gw.elegibilidad_resena(linea.id_producto), listo)
