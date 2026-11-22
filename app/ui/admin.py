"""Administración: panel de indicadores, usuarios, categorías y pagos."""
from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter
from PySide6.QtWidgets import (QComboBox, QDialog, QFormLayout, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ..categorias import ArbolCategorias
from ..errors import ErrorValidacion
from ..models import ESTATUS_USUARIO, ROLES, Categoria, Estadisticas, Pago, Usuario
from ..util import formato_dinero, slugify
from . import theme
from .contexto import Contexto
from .paginado import CargaPaginada
from .pagina import PaginaBase
from .widgets import (EncabezadoPagina, EstadoVacio, Indicador, boton, celda, celda_estatus, chip, chip_estatus,
                      confirmar, crear_tabla, etiqueta, fecha_corta, mostrar_error, tarjeta)


# --------------------------------------------------------------------------- panel
class Barra(QWidget):
    """Barra horizontal proporcional (0..1)."""

    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self._color, self._valor = QColor(color), 0.0
        self.setFixedHeight(10)
        self.setMinimumWidth(120)

    def poner(self, valor: float) -> None:
        self._valor = max(0.0, min(1.0, valor))
        self.update()

    def paintEvent(self, _):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        r = QRectF(self.rect())
        p.setBrush(QBrush(QColor(theme.GRIS_SOFT)))
        p.drawRoundedRect(r, 5, 5)
        if self._valor > 0:
            p.setBrush(QBrush(self._color))
            p.drawRoundedRect(QRectF(0, 0, max(10.0, r.width() * self._valor), r.height()), 5, 5)


def _kpi(titulo: str, ayuda: str) -> tuple[QWidget, QLabel]:
    t = tarjeta()
    v = QVBoxLayout(t)
    v.setContentsMargins(20, 16, 20, 16)
    v.setSpacing(2)
    v.addWidget(etiqueta(titulo, "muted"))
    valor = etiqueta("—", "precio")
    v.addWidget(valor)
    v.addWidget(etiqueta(ayuda, "muted", wrap=True))
    return t, valor


class PanelAdminPage(PaginaBase):
    def __init__(self, ctx: Contexto, parent=None):
        super().__init__(ctx, parent)
        self._gen = 0
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(24, 20, 24, 16)
        raiz.setSpacing(14)
        enc = EncabezadoPagina("Panel de administración", "Un vistazo a cómo va el marketplace.",
                               "MySQL (usuarios, pagos, pedidos) + DynamoDB")
        enc.acciones.addWidget(boton("Actualizar", al_pulsar=self.al_mostrar))
        raiz.addWidget(enc)
        self.indicador = Indicador()
        raiz.addWidget(self.indicador)

        fila = QHBoxLayout()
        fila.setSpacing(14)
        c1, self.k_ingresos = _kpi("Ingresos aprobados", "Suma de pagos aprobados (sin reembolsos)")
        c2, self.k_productos = _kpi("Productos publicados", "Conteo aproximado de DynamoDB: se refresca cada pocas horas")
        c3, self.k_usuarios = _kpi("Usuarios", "Compradores, vendedores y administradores")
        c4, self.k_pedidos = _kpi("Pedidos", "En cualquier estatus")
        for c in (c1, c2, c3, c4):
            fila.addWidget(c, 1)
        raiz.addLayout(fila)

        cuerpo = QHBoxLayout()
        cuerpo.setSpacing(14)
        self.card_roles = tarjeta()
        self.rejilla_roles = QGridLayout(self.card_roles)
        self.rejilla_roles.setContentsMargins(20, 16, 20, 16)
        self.rejilla_roles.setVerticalSpacing(10)
        self.card_pedidos = tarjeta()
        self.rejilla_pedidos = QGridLayout(self.card_pedidos)
        self.rejilla_pedidos.setContentsMargins(20, 16, 20, 16)
        self.rejilla_pedidos.setVerticalSpacing(10)
        cuerpo.addWidget(self.card_roles, 1)
        cuerpo.addWidget(self.card_pedidos, 1)
        raiz.addLayout(cuerpo)
        raiz.addStretch(1)

    def al_mostrar(self) -> None:
        self._gen += 1
        gen = self._gen
        self.indicador.inicio()
        self.ctx.ejecutar(self, self.ctx.gw.estadisticas, lambda e: self._mostrar(gen, e), lambda x: self._fallo(gen, x))

    def _fallo(self, gen: int, exc: BaseException) -> None:
        if gen == self._gen:
            self.indicador.fin()
            mostrar_error(self, exc)

    @staticmethod
    def _vaciar(rejilla: QGridLayout) -> None:
        while rejilla.count():
            w = rejilla.takeAt(0).widget()
            if w:
                w.deleteLater()

    def _llenar(self, rejilla: QGridLayout, titulo: str, datos: dict[str, int], orden, color) -> None:
        self._vaciar(rejilla)
        rejilla.addWidget(etiqueta(titulo, "h2"), 0, 0, 1, 3)
        total = max(1, sum(datos.values()))
        mayor = max([1, *datos.values()])
        for i, clave in enumerate(orden, 1):
            n = datos.get(clave, 0)
            rejilla.addWidget(chip_estatus(clave), i, 0, Qt.AlignLeft)
            b = Barra(color(clave))
            b.poner(n / mayor)
            rejilla.addWidget(b, i, 1)
            rejilla.addWidget(etiqueta(f"{n:,}  ({n * 100 // total}%)", "muted"), i, 2, Qt.AlignRight)
        rejilla.setColumnStretch(1, 1)
        rejilla.setRowStretch(len(orden) + 1, 1)

    def _mostrar(self, gen: int, e: Estadisticas) -> None:
        if gen != self._gen:
            return
        self.indicador.fin()
        self.k_ingresos.setText(formato_dinero(e.ingresos_aprobados))
        self.k_productos.setText(f"{e.productos_aprox:,}")
        self.k_usuarios.setText(f"{sum(e.usuarios_por_rol.values()):,}")
        self.k_pedidos.setText(f"{sum(e.pedidos_por_estatus.values()):,}")
        self._llenar(self.rejilla_roles, "Usuarios por rol", e.usuarios_por_rol, ROLES,
                     lambda k: theme.ESTATUS_COLORES[k][0])
        self._llenar(self.rejilla_pedidos, "Pedidos por estatus", e.pedidos_por_estatus,
                     ("PENDIENTE", "PAGADO", "ENVIADO", "ENTREGADO", "CANCELADO"), lambda k: theme.ESTATUS_COLORES[k][0])


# --------------------------------------------------------------------------- usuarios
class UsuariosPage(PaginaBase):
    def __init__(self, ctx: Contexto, parent=None):
        super().__init__(ctx, parent)
        self._usuario: Usuario | None = None
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(24, 20, 24, 16)
        raiz.setSpacing(12)
        enc = EncabezadoPagina("Usuarios", "Busca cuentas, cambia el rol de alguien o suspende una cuenta. "
                               "Las contraseñas nunca se muestran: solo existe su hash en la base.", "MySQL #1 (usuarios)")
        raiz.addWidget(enc)

        filtros = QHBoxLayout()
        filtros.setSpacing(8)
        self.q = QLineEdit()
        self.q.setPlaceholderText("Buscar por nombre o correo…")
        self.q.setClearButtonEnabled(True)
        self.q.returnPressed.connect(self._buscar)
        self.f_rol = QComboBox()
        self.f_rol.addItem("Todos los roles", None)
        for r in ROLES:
            self.f_rol.addItem(theme.ETIQUETAS_ESTATUS[r], r)
        self.f_estatus = QComboBox()
        self.f_estatus.addItem("Cualquier estado", None)
        for e in ESTATUS_USUARIO:
            self.f_estatus.addItem(theme.ETIQUETAS_ESTATUS[e], e)
        self.f_rol.currentIndexChanged.connect(lambda _: self._buscar())
        self.f_estatus.currentIndexChanged.connect(lambda _: self._buscar())
        filtros.addWidget(self.q, 1)
        filtros.addWidget(self.f_rol)
        filtros.addWidget(self.f_estatus)
        filtros.addWidget(boton("Buscar", "primary", self._buscar))
        raiz.addLayout(filtros)
        self.indicador = Indicador()
        raiz.addWidget(self.indicador)

        self.tabla = crear_tabla(["ID", "Nombre", "Correo", "Rol", "Estado", "Teléfono", "Registro"],
                                 {0: 60, 1: 200, 3: 120, 4: 110, 5: 130, 6: 130}, estirar=2)
        self.tabla.itemSelectionChanged.connect(self._seleccion)
        raiz.addWidget(self.tabla, 1)

        # ---- panel de acciones sobre la cuenta elegida
        self.panel = tarjeta()
        ph = QHBoxLayout(self.panel)
        ph.setContentsMargins(16, 12, 16, 12)
        ph.setSpacing(10)
        self.sel_texto = etiqueta("Selecciona un usuario para cambiar su rol o suspenderlo.", "muted")
        ph.addWidget(self.sel_texto, 1)
        self.c_rol = QComboBox()
        for r in ROLES:
            self.c_rol.addItem(theme.ETIQUETAS_ESTATUS[r], r)
        ph.addWidget(etiqueta("Rol:", "muted"))
        ph.addWidget(self.c_rol)
        self.btn_rol = boton("Guardar rol", "secondary", self._guardar_rol)
        ph.addWidget(self.btn_rol)
        self.btn_estado = boton("Suspender cuenta", "danger", self._cambiar_estado)
        ph.addWidget(self.btn_estado)
        self.panel.setEnabled(False)
        raiz.addWidget(self.panel)

        pie = QHBoxLayout()
        self.resumen = etiqueta("", "muted")
        pie.addWidget(self.resumen)
        pie.addStretch(1)
        self.btn_mas = boton("Cargar más usuarios")
        pie.addWidget(self.btn_mas)
        raiz.addLayout(pie)
        self.carga = CargaPaginada(ctx, self, self.indicador, self.btn_mas, self._pedir, self._recibir, self._resumen)

    def _pedir(self, cursor):
        rol, est, q = self.f_rol.currentData(), self.f_estatus.currentData(), self.q.text().strip() or None
        return self.ctx.gw.listar_usuarios(rol, est, q, cursor, 40)

    def al_mostrar(self) -> None:
        if self.tabla.rowCount() == 0:
            self.carga.reiniciar()

    def al_cerrar_sesion(self) -> None:
        self.carga.invalidar()
        self.tabla.setRowCount(0)
        self._usuario = None
        self.panel.setEnabled(False)

    def _buscar(self) -> None:
        self.tabla.setRowCount(0)
        self._usuario = None
        self.panel.setEnabled(False)
        self.carga.reiniciar()

    def _recibir(self, items: list[Usuario], primera: bool) -> None:
        for u in items:
            f = self.tabla.rowCount()
            self.tabla.insertRow(f)
            self._poner_fila(f, u)

    def _poner_fila(self, f: int, u: Usuario) -> None:
        self.tabla.setItem(f, 0, celda(str(u.id_usuario), color=theme.MUTED, dato=u))
        self.tabla.setItem(f, 1, celda(u.nombre_completo, negrita=True))
        self.tabla.setItem(f, 2, celda(u.correo))
        self.tabla.setItem(f, 3, celda_estatus(u.rol))
        self.tabla.setItem(f, 4, celda_estatus(u.estatus))
        self.tabla.setItem(f, 5, celda(u.telefono or "—", color=theme.MUTED))
        self.tabla.setItem(f, 6, celda(fecha_corta(u.fecha_registro)))

    def _resumen(self) -> None:
        n = self.tabla.rowCount()
        self.resumen.setText(f"{n} usuario{'s' if n != 1 else ''} cargado{'s' if n != 1 else ''}"
                             + (" · hay más por cargar" if self.carga.hay_mas else ""))

    def _seleccion(self) -> None:
        sel = self.tabla.selectionModel().selectedRows()
        if not sel:
            return
        u: Usuario = self.tabla.item(sel[0].row(), 0).data(Qt.UserRole)
        self._usuario = u
        yo = u.id_usuario == self.ctx.usuario.id_usuario
        self.panel.setEnabled(True)
        self.sel_texto.setText(f"<b>{u.nombre_completo}</b> · {u.correo}" + ("  (esta es tu cuenta)" if yo else ""))
        self.sel_texto.setTextFormat(Qt.RichText)
        self.c_rol.setCurrentIndex(self.c_rol.findData(u.rol))
        self.c_rol.setEnabled(not yo)
        self.btn_rol.setEnabled(not yo)
        self.btn_estado.setEnabled(not yo)
        self.btn_estado.setText("Reactivar cuenta" if u.estatus == "SUSPENDIDO" else "Suspender cuenta")
        self.btn_estado.setProperty("variante", "primary" if u.estatus == "SUSPENDIDO" else "danger")
        self.btn_estado.style().unpolish(self.btn_estado)
        self.btn_estado.style().polish(self.btn_estado)

    def _guardar_rol(self) -> None:
        u = self._usuario
        nuevo = self.c_rol.currentData()
        if not u or nuevo == u.rol:
            return
        if not confirmar(self.window(), "Cambiar rol", f"¿Cambiar a {u.nombre_completo} de {theme.ETIQUETAS_ESTATUS[u.rol].lower()} "
                         f"a {theme.ETIQUETAS_ESTATUS[nuevo].lower()}?"):
            return
        self._actualizar(u, rol=nuevo)

    def _cambiar_estado(self) -> None:
        u = self._usuario
        if not u:
            return
        suspender = u.estatus != "SUSPENDIDO"
        if suspender and not confirmar(self.window(), "Suspender cuenta",
                                       f"{u.nombre_completo} no podrá iniciar sesión hasta que reactives su cuenta. ¿Suspender?",
                                       "Sí, suspender", peligro=True):
            return
        self._actualizar(u, estatus="SUSPENDIDO" if suspender else "ACTIVO")

    def _actualizar(self, u: Usuario, **cambios) -> None:
        self.indicador.inicio()
        self.panel.setEnabled(False)

        def listo(nuevo: Usuario) -> None:
            self.indicador.fin()
            for f in range(self.tabla.rowCount()):
                if self.tabla.item(f, 0).data(Qt.UserRole).id_usuario == nuevo.id_usuario:
                    self.tabla.blockSignals(True)
                    self._poner_fila(f, nuevo)
                    self.tabla.blockSignals(False)
                    self.tabla.selectRow(f)
                    break
            self._usuario = nuevo
            self._seleccion()
            self.panel.setEnabled(True)
            self.ctx.avisar(f"Cuenta de {nuevo.nombre_completo} actualizada")

        def fallo(exc: BaseException) -> None:
            self.indicador.fin()
            self.panel.setEnabled(True)
            mostrar_error(self, exc)

        self.ctx.ejecutar(self, lambda: self.ctx.gw.actualizar_usuario(u.id_usuario, **cambios), listo, fallo)


# --------------------------------------------------------------------------- categorías
class CategoriaDialog(QDialog):
    def __init__(self, ctx: Contexto, arbol: ArbolCategorias, categoria: Categoria | None = None,
                 id_padre: str | None = None, parent=None):
        super().__init__(parent)
        self.ctx, self.categoria = ctx, categoria
        self.guardada: Categoria | None = None
        self._slug_manual = categoria is not None
        self.setWindowTitle("Editar categoría" if categoria else "Nueva categoría")
        self.setModal(True)
        self.setMinimumWidth(480)
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 20, 22, 18)
        v.setSpacing(12)
        v.addWidget(etiqueta("Editar categoría" if categoria else "Nueva categoría", "h2"))
        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)
        self.nombre = QLineEdit()
        self.nombre.setMaxLength(80)
        self.nombre.setPlaceholderText("Ej.: Electrónica")
        self.slug = QLineEdit()
        self.slug.setMaxLength(100)
        self.slug.setPlaceholderText("se genera solo a partir del nombre")
        self.slug.setToolTip("Texto corto para URLs: minúsculas, números y guiones. Debe ser único.")
        self.padre = QComboBox()
        self.padre.addItem("— Ninguna (categoría principal) —", None)
        excluidas = set(arbol.descendientes(categoria.id_categoria)) if categoria else set()
        for c in arbol.ordenadas_por_ruta():
            if c.id_categoria not in excluidas:
                self.padre.addItem(arbol.ruta_texto(c.id_categoria), c.id_categoria)
        self.estatus = QComboBox()
        self.estatus.addItem("Activa (visible en la tienda)", "ACTIVO")
        self.estatus.addItem("Inactiva (oculta)", "INACTIVO")
        form.addRow("Nombre *", self.nombre)
        form.addRow("Slug", self.slug)
        form.addRow("Dentro de", self.padre)
        form.addRow("Estado", self.estatus)
        v.addLayout(form)
        if categoria:
            self.nombre.setText(categoria.nombre)
            self.slug.setText(categoria.slug)
            self.padre.setCurrentIndex(max(0, self.padre.findData(categoria.id_categoria_padre)))
            self.estatus.setCurrentIndex(max(0, self.estatus.findData(categoria.estatus)))
        else:
            if id_padre:
                self.padre.setCurrentIndex(max(0, self.padre.findData(id_padre)))
            self.nombre.textEdited.connect(self._auto_slug)
        self.slug.textEdited.connect(lambda _: setattr(self, "_slug_manual", True))
        self.error = etiqueta("", "error", wrap=True)
        v.addWidget(self.error)
        self.indicador = Indicador()
        v.addWidget(self.indicador)
        fila = QHBoxLayout()
        fila.addStretch(1)
        fila.addWidget(boton("Cancelar", al_pulsar=self.reject))
        self.btn = boton("Guardar", "primary", self._guardar)
        fila.addWidget(self.btn)
        v.addLayout(fila)
        self.nombre.setFocus()

    def _auto_slug(self, texto: str) -> None:
        if not self._slug_manual:
            self.slug.setText(slugify(texto))

    def _guardar(self) -> None:
        self.error.clear()
        nombre = self.nombre.text().strip()
        if len(nombre) < 2:
            self.error.setText("Escribe un nombre de al menos 2 caracteres.")
            return
        slug = slugify(self.slug.text() or nombre)
        if not slug:
            self.error.setText("El slug no es válido: usa letras o números.")
            return
        cat = Categoria(self.categoria.id_categoria if self.categoria else "", nombre, slug,
                        self.padre.currentData(), self.estatus.currentData())
        crear = self.categoria is None
        self.btn.setEnabled(False)
        self.indicador.inicio()
        self.ctx.ejecutar(self, lambda: self.ctx.gw.guardar_categoria(cat, crear=crear), self._listo, self._fallo)

    def _listo(self, cat: Categoria) -> None:
        self.indicador.fin()
        self.guardada = cat
        self.accept()

    def _fallo(self, exc: BaseException) -> None:
        self.indicador.fin()
        self.btn.setEnabled(True)
        self.error.setText(getattr(exc, "mensaje", None) or str(exc))


class CategoriasPage(PaginaBase):
    def __init__(self, ctx: Contexto, parent=None):
        super().__init__(ctx, parent)
        self._arbol: ArbolCategorias | None = None
        self._pendiente: str | None = None
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(24, 20, 24, 16)
        raiz.setSpacing(12)
        enc = EncabezadoPagina("Categorías", "Organiza el catálogo en categorías y subcategorías. Doble clic para editar una.",
                               "DynamoDB (categorias)")
        enc.acciones.addWidget(boton("Actualizar", al_pulsar=lambda: self._cargar(True)))
        enc.acciones.addWidget(boton("+ Subcategoría", "secondary", self._nueva_hija))
        enc.acciones.addWidget(boton("+ Categoría principal", "primary", self._nueva_raiz))
        raiz.addWidget(enc)
        self.indicador = Indicador()
        raiz.addWidget(self.indicador)

        self.arbol_ui = QTreeWidget()
        self.arbol_ui.setHeaderLabels(["Nombre", "Slug", "Estado", "Subcategorías"])
        self.arbol_ui.setColumnWidth(0, 360)
        self.arbol_ui.setColumnWidth(1, 240)
        self.arbol_ui.setColumnWidth(2, 120)
        self.arbol_ui.setUniformRowHeights(True)
        self.arbol_ui.setAlternatingRowColors(False)
        self.arbol_ui.itemDoubleClicked.connect(lambda *_: self._editar())
        self.arbol_ui.setStyleSheet(f"QTreeWidget {{ background:{theme.SURFACE}; border:1px solid {theme.BORDER}; border-radius:10px; }}"
                                    f"QHeaderView::section {{ background:#F7F8FC; color:{theme.MUTED}; border:none; "
                                    f"border-bottom:1px solid {theme.BORDER}; padding:9px 8px; font-weight:700; font-size:9pt; }}")
        raiz.addWidget(self.arbol_ui, 1)

        pie = QHBoxLayout()
        self.resumen = etiqueta("", "muted")
        pie.addWidget(self.resumen)
        pie.addStretch(1)
        pie.addWidget(boton("Editar seleccionada", "secondary", self._editar))
        raiz.addLayout(pie)

    def al_mostrar(self) -> None:
        self._cargar(self._arbol is None)

    def al_cerrar_sesion(self) -> None:
        self._arbol = None
        self.arbol_ui.clear()

    def _cargar(self, forzar: bool) -> None:
        self.indicador.inicio()

        def listo(arbol: ArbolCategorias) -> None:
            self.indicador.fin()
            self._poblar(arbol)

        def fallo(exc: BaseException) -> None:
            self.indicador.fin()
            mostrar_error(self, exc)

        if forzar:
            self.ctx.arbol = None
        if self.ctx.arbol is not None:
            listo(self.ctx.arbol)
            return
        self.ctx.ejecutar(self, self.ctx.gw.listar_categorias,
                          lambda cats: (setattr(self.ctx, "arbol", ArbolCategorias(cats)), listo(self.ctx.arbol)), fallo)

    def _poblar(self, arbol: ArbolCategorias) -> None:
        self._arbol = arbol
        elegida = self._pendiente or self._id_elegido()
        self._pendiente = None
        self.arbol_ui.clear()

        def agregar(padre_item, categorias):
            for c in categorias:
                hijos = arbol.hijos_de(c.id_categoria)
                it = QTreeWidgetItem([c.nombre, c.slug, theme.ETIQUETAS_ESTATUS.get(c.estatus, c.estatus) if c.estatus != "INACTIVO" else "Inactiva",
                                      str(len(hijos)) if hijos else "—"])
                it.setData(0, Qt.UserRole, c.id_categoria)
                if c.estatus != "ACTIVO":
                    for col in range(4):
                        it.setForeground(col, QBrush(QColor(theme.MUTED)))
                it.setForeground(1, QBrush(QColor(theme.MUTED)))
                padre_item.addChild(it) if padre_item else self.arbol_ui.addTopLevelItem(it)
                agregar(it, hijos)

        agregar(None, arbol.raices())
        self.arbol_ui.expandToDepth(0)
        n = len(arbol)
        self.resumen.setText(f"{n} categoría{'s' if n != 1 else ''} · {len(arbol.raices())} principales")
        if elegida:
            self._seleccionar(elegida)

    def _id_elegido(self) -> str | None:
        it = self.arbol_ui.currentItem()
        return it.data(0, Qt.UserRole) if it else None

    def _seleccionar(self, id_categoria: str) -> None:
        pila = [self.arbol_ui.topLevelItem(i) for i in range(self.arbol_ui.topLevelItemCount())]
        while pila:
            it = pila.pop()
            if it.data(0, Qt.UserRole) == id_categoria:
                self.arbol_ui.setCurrentItem(it)
                self.arbol_ui.scrollToItem(it)
                return
            pila.extend(it.child(i) for i in range(it.childCount()))

    def _abrir(self, categoria: Categoria | None, id_padre: str | None) -> None:
        if self._arbol is None:
            return
        dlg = CategoriaDialog(self.ctx, self._arbol, categoria, id_padre, self.window())
        if dlg.exec() == QDialog.Accepted:
            self.ctx.avisar(f"Categoría «{dlg.guardada.nombre}» guardada")
            self._pendiente = dlg.guardada.id_categoria
            self._cargar(True)

    def _nueva_raiz(self) -> None:
        self._abrir(None, None)

    def _nueva_hija(self) -> None:
        elegida = self._id_elegido()
        if not elegida:
            self.ctx.avisar("Primero selecciona la categoría que será la «madre»")
            return
        self._abrir(None, elegida)

    def _editar(self) -> None:
        elegida = self._id_elegido()
        if not elegida or self._arbol is None:
            self.ctx.avisar("Selecciona una categoría de la lista")
            return
        self._abrir(self._arbol.por_id[elegida], None)


# --------------------------------------------------------------------------- pagos
class PagosPage(PaginaBase):
    def __init__(self, ctx: Contexto, parent=None):
        super().__init__(ctx, parent)
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(24, 20, 24, 16)
        raiz.setSpacing(12)
        enc = EncabezadoPagina("Pagos", "Todos los cobros registrados. La aplicación nunca guarda datos de tarjeta: "
                               "solo el método, el monto y la referencia que devuelve la pasarela.", "MySQL #1 (pagos)")
        enc.acciones.addWidget(boton("Actualizar", al_pulsar=lambda: self.carga.reiniciar()))
        raiz.addWidget(enc)
        self.indicador = Indicador()
        raiz.addWidget(self.indicador)
        self.tabla = crear_tabla(["Pago", "Pedido", "Método", "Estatus", "Monto", "Referencia", "Fecha"],
                                 {0: 70, 1: 80, 2: 190, 3: 120, 4: 120, 6: 140}, estirar=5)
        self.tabla.setSelectionMode(self.tabla.SelectionMode.NoSelection)
        raiz.addWidget(self.tabla, 1)
        pie = QHBoxLayout()
        self.resumen = etiqueta("", "muted")
        pie.addWidget(self.resumen)
        pie.addStretch(1)
        self.btn_mas = boton("Cargar más pagos")
        pie.addWidget(self.btn_mas)
        raiz.addLayout(pie)
        self.carga = CargaPaginada(ctx, self, self.indicador, self.btn_mas,
                                   lambda cur: ctx.gw.listar_pagos(cur, 50), self._recibir, self._resumen)

    def al_mostrar(self) -> None:
        self.carga.reiniciar()

    def al_cerrar_sesion(self) -> None:
        self.carga.invalidar()
        self.tabla.setRowCount(0)

    def _recibir(self, items: list[Pago], primera: bool) -> None:
        if primera:
            self.tabla.setRowCount(0)
        for p in items:
            f = self.tabla.rowCount()
            self.tabla.insertRow(f)
            self.tabla.setItem(f, 0, celda(f"#{p.id_pago}", color=theme.MUTED))
            self.tabla.setItem(f, 1, celda(f"#{p.id_pedido}", negrita=True))
            self.tabla.setItem(f, 2, celda(theme.ETIQUETAS_METODO.get(p.metodo_pago, p.metodo_pago)))
            self.tabla.setItem(f, 3, celda_estatus(p.estatus))
            self.tabla.setItem(f, 4, celda(formato_dinero(p.monto), derecha=True, negrita=True, dato=p))
            self.tabla.setItem(f, 5, celda(p.referencia_transaccion or "—", color=theme.MUTED))
            self.tabla.setItem(f, 6, celda(fecha_corta(p.fecha_pago)))

    def _resumen(self) -> None:
        pagos = [self.tabla.item(f, 4).data(Qt.UserRole) for f in range(self.tabla.rowCount())]
        aprobado = sum((p.monto for p in pagos if p.estatus == "APROBADO"), Decimal("0"))
        n = len(pagos)
        self.resumen.setText(f"{n} pago{'s' if n != 1 else ''} cargado{'s' if n != 1 else ''} · "
                             f"aprobados en esta lista: {formato_dinero(aprobado)}"
                             + (" · hay más por cargar" if self.carga.hay_mas else ""))
