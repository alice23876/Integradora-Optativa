"""Conexiones: estado de las bases de datos y mapa didáctico de dónde vive cada tabla."""
from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from ..config import DESCRIPCION_MODOS
from ..models import EstadoConexion
from . import theme
from .contexto import Contexto
from .pagina import PaginaBase
from .widgets import (EncabezadoPagina, Indicador, boton, celda, chip, crear_tabla, etiqueta, mostrar_error, tarjeta)

MAPA = [
    ("DynamoDB", "NoSQL · catálogo", theme.INFO, theme.INFO_SOFT, [
        ("productos", "Título, marca, categoría y vendedor. Se lee por página, nunca completo."),
        ("variantes_producto", "SKU, precio, existencias y atributos (talla, color…)."),
        ("categorias", "Árbol de categorías (pocas filas: se guarda en memoria)."),
        ("resenas", "Calificaciones y comentarios, una por usuario y producto."),
    ]),
    ("MySQL #1 · usuarios", "SQL · identidad y dinero", theme.OK, theme.OK_SOFT, [
        ("usuarios", "Cuentas y roles. La contraseña se guarda solo como hash bcrypt."),
        ("pagos", "Método, monto y referencia de la pasarela. Nunca datos de tarjeta."),
    ]),
    ("MySQL #2 · operaciones", "SQL · compras", theme.PURPLE, theme.PURPLE_SOFT, [
        ("carritos", "Un carrito ACTIVO por comprador."),
        ("detalle_carrito", "Variantes y cantidades dentro del carrito."),
        ("pedidos", "Estatus, total y dirección de envío."),
        ("detalle_pedido", "Precio congelado al comprar, cantidad y vendedor de cada línea."),
    ]),
]


class ConexionesPage(PaginaBase):
    def __init__(self, ctx: Contexto, parent=None):
        super().__init__(ctx, parent)
        self._gen = 0
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        marco = QVBoxLayout(self)
        marco.setContentsMargins(0, 0, 0, 0)
        marco.addWidget(scroll)
        cont = QWidget()
        cont.setProperty("pagina", True)
        scroll.setWidget(cont)
        raiz = QVBoxLayout(cont)
        raiz.setContentsMargins(24, 20, 24, 20)
        raiz.setSpacing(14)

        enc = EncabezadoPagina("Conexiones", "Comprueba que las bases de datos responden y entiende dónde se guarda cada cosa.")
        enc.acciones.addWidget(boton("Probar conexiones", "primary", self.al_mostrar))
        raiz.addWidget(enc)
        self.indicador = Indicador()
        raiz.addWidget(self.indicador)

        self.modo = etiqueta("", wrap=True)
        raiz.addWidget(self.modo)

        card = tarjeta()
        cv = QVBoxLayout(card)
        cv.setContentsMargins(14, 12, 14, 14)
        cv.addWidget(etiqueta("Estado en vivo", "h2"))
        self.tabla = crear_tabla(["", "Servicio", "Tipo", "Respuesta", "Contiene", "Detalle"],
                                 {0: 40, 1: 230, 2: 70, 3: 100, 4: 300}, estirar=5, filas_altas=44)
        self.tabla.setSelectionMode(self.tabla.SelectionMode.NoSelection)
        cv.addWidget(self.tabla)
        raiz.addWidget(card)

        raiz.addWidget(etiqueta("¿Dónde vive cada tabla?", "h2"))
        cols = QHBoxLayout()
        cols.setSpacing(14)
        for titulo, subtitulo, fg, bg, tablas in MAPA:
            c = tarjeta()
            v = QVBoxLayout(c)
            v.setContentsMargins(18, 16, 18, 16)
            v.setSpacing(8)
            v.addWidget(chip(subtitulo, fg, bg))
            v.addWidget(etiqueta(titulo, "h2"))
            for nombre, para_que in tablas:
                t = etiqueta(f"<b>{nombre}</b><br><span style='color:{theme.MUTED}'>{para_que}</span>", wrap=True)
                v.addWidget(t)
            v.addStretch(1)
            cols.addWidget(c, 1)
        raiz.addLayout(cols)
        nota = tarjeta()
        nv = QVBoxLayout(nota)
        nv.setContentsMargins(18, 14, 18, 14)
        nv.addWidget(etiqueta(
            "<b>Una compra cruza varias bases.</b> Entre bases distintas no existe JOIN ni llave foránea, así que la "
            "aplicación valida y une los datos por id (por ejemplo, <i>detalle_pedido.id_variante</i> apunta a DynamoDB). "
            "Al pagar se reserva el inventario, se crea el pedido, se cobra y, si algo falla, se deshace lo anterior.",
            wrap=True))
        raiz.addWidget(nota)
        raiz.addStretch(1)

    def al_mostrar(self) -> None:
        self._gen += 1
        gen = self._gen
        self.modo.setText(f"<b>Modo actual: {self.ctx.cfg.modo}</b> — {DESCRIPCION_MODOS.get(self.ctx.cfg.modo, '')}")
        self.indicador.inicio()

        def listo(estados):
            if gen == self._gen:
                self.indicador.fin()
                self._poblar(estados)

        def fallo(exc):
            if gen == self._gen:
                self.indicador.fin()
                mostrar_error(self, exc)

        self.ctx.ejecutar(self, self.ctx.gw.estado_conexiones, listo, fallo)

    def _poblar(self, estados: list[EstadoConexion]) -> None:
        self.tabla.setRowCount(0)
        for e in estados:
            f = self.tabla.rowCount()
            self.tabla.insertRow(f)
            self.tabla.setItem(f, 0, celda("●" if e.ok else "✕", color=theme.OK if e.ok else theme.DANGER, negrita=True))
            self.tabla.setItem(f, 1, celda(e.nombre, negrita=True))
            self.tabla.setItem(f, 2, celda(e.tipo, color=theme.MUTED))
            self.tabla.setItem(f, 3, celda(f"{e.latencia_ms:.0f} ms" if e.latencia_ms is not None else "—", derecha=True))
            self.tabla.setItem(f, 4, celda(e.contiene or "—", color=theme.MUTED, tooltip=e.contiene))
            self.tabla.setItem(f, 5, celda(e.detalle or ("Conectado" if e.ok else "Sin respuesta"),
                                           color=theme.TEXT if e.ok else theme.DANGER, tooltip=e.detalle))
