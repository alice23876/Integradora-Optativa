"""Pantalla de entrada: explicación didáctica a la izquierda; iniciar sesión / crear cuenta a la derecha."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QFormLayout, QFrame, QHBoxLayout, QLineEdit, QStackedWidget, QTabBar,
                               QVBoxLayout, QWidget)

from ..demo_data import CUENTAS_DEMO
from ..models import DatosRegistro, Sesion
from . import theme
from .contexto import Contexto
from .widgets import Indicador, boton, chip, etiqueta

_BLANCO = "color:white; background:transparent;"


class _PilaAjustada(QStackedWidget):
    """Mide lo que mide la página visible (un QStackedWidget normal usa la más alta de todas)."""

    def sizeHint(self):  # noqa: N802
        w = self.currentWidget()
        return w.sizeHint() if w else super().sizeHint()

    def minimumSizeHint(self):  # noqa: N802
        w = self.currentWidget()
        return w.minimumSizeHint() if w else super().minimumSizeHint()


class Pestanas(QWidget):
    """Pestañas con la altura de la página activa."""

    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.barra = QTabBar()
        self.barra.setDrawBase(True)
        self.barra.setExpanding(False)
        self.pila = _PilaAjustada()
        v.addWidget(self.barra)
        v.addWidget(self.pila)
        self.barra.currentChanged.connect(self._cambio)

    def addTab(self, w: QWidget, texto: str) -> None:  # noqa: N802
        self.pila.addWidget(w)
        self.barra.addTab(texto)

    def setCurrentIndex(self, i: int) -> None:  # noqa: N802
        self.barra.setCurrentIndex(i)

    def _cambio(self, i: int) -> None:
        self.pila.setCurrentIndex(i)
        self.pila.updateGeometry()
        self.updateGeometry()


class PanelIzquierdo(QFrame):
    """Presentación: qué es la app y cómo se reparten los datos (sin tecnicismos de más)."""

    def __init__(self, modo: str, parent=None):
        super().__init__(parent)
        self.setObjectName("panelLogin")
        self.setStyleSheet(f"#panelLogin {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {theme.PRIMARY_DARK}, stop:1 {theme.PURPLE});"
                           " border: none; }")
        v = QVBoxLayout(self)
        v.setContentsMargins(44, 44, 44, 36)
        v.setSpacing(14)
        marca = etiqueta("Marketplace", "")
        marca.setStyleSheet(_BLANCO + "font-size:30pt; font-weight:800;")
        v.addWidget(marca)
        lema = etiqueta("Compra y vende entre miles de productos, sin complicaciones.", "", wrap=True)
        lema.setStyleSheet(_BLANCO + "font-size:13pt;")
        v.addWidget(lema)
        v.addSpacing(18)
        pasos = [
            ("1", "Explora", "Busca entre más de 17,000 productos por categoría o por nombre."),
            ("2", "Elige una variante", "Cada producto tiene tallas, colores o capacidades con su propio precio y existencias."),
            ("3", "Compra con seguridad", "Tu pedido reserva el inventario, registra el pago y se puede seguir hasta la entrega."),
            ("4", "Opina", "Cuando recibes un producto puedes dejar una reseña."),
        ]
        for n, t, d in pasos:
            fila = QHBoxLayout()
            fila.setSpacing(12)
            bola = etiqueta(n, "")
            bola.setAlignment(Qt.AlignCenter)
            bola.setFixedSize(30, 30)
            bola.setStyleSheet("color:white; background:rgba(255,255,255,0.22); border-radius:15px; font-weight:800;")
            fila.addWidget(bola, 0, Qt.AlignTop)
            col = QVBoxLayout()
            col.setSpacing(0)
            t1 = etiqueta(t, "")
            t1.setStyleSheet(_BLANCO + "font-weight:700; font-size:11pt;")
            t2 = etiqueta(d, "", wrap=True)
            t2.setStyleSheet("color:rgba(255,255,255,0.82); background:transparent;")
            col.addWidget(t1)
            col.addWidget(t2)
            fila.addLayout(col, 1)
            v.addLayout(fila)
        v.addStretch(1)
        self.modo = etiqueta("", "", wrap=True)
        self.modo.setStyleSheet("color:rgba(255,255,255,0.85); background:rgba(255,255,255,0.12); border-radius:10px; padding:10px 12px;")
        v.addWidget(self.modo)
        self.poner_modo(modo)

    def poner_modo(self, modo: str) -> None:
        textos = {"demo": "Modo demostración · datos de ejemplo en tu computadora; no necesita internet ni bases de datos.",
                  "directo": "Modo directo · conectado a DynamoDB (catálogo) y a dos bases MySQL (usuarios y operaciones).",
                  "api": "Modo API · conectado a tu backend Python, que a su vez usa DynamoDB y MySQL."}
        self.modo.setText(textos.get(modo, modo))


class LoginPage(QWidget):
    sesion_iniciada = Signal()
    abrir_ajustes = Signal()

    def __init__(self, ctx: Contexto, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setObjectName("raiz")
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        self.izq = PanelIzquierdo(ctx.cfg.modo)
        self.izq.setMinimumWidth(380)
        self.izq.setMaximumWidth(520)
        h.addWidget(self.izq, 4)

        der = QWidget()
        der.setProperty("pagina", True)
        dv = QVBoxLayout(der)
        dv.setContentsMargins(0, 0, 0, 14)
        dv.addStretch(1)
        centro = QHBoxLayout()
        centro.addStretch(1)
        self.caja = QFrame()
        self.caja.setProperty("card", True)
        self.caja.setFixedWidth(430)
        cv = QVBoxLayout(self.caja)
        cv.setContentsMargins(28, 24, 28, 24)
        cv.setSpacing(10)
        cv.addWidget(etiqueta("Bienvenido", "titulo"))
        cv.addWidget(etiqueta("Inicia sesión o crea tu cuenta para continuar.", "subtitulo", wrap=True))
        self.tabs = Pestanas()
        self.tabs.addTab(self._form_login(), "Iniciar sesión")
        self.tabs.addTab(self._form_registro(), "Crear cuenta")
        cv.addWidget(self.tabs)
        self.error = etiqueta("", "error", wrap=True)
        cv.addWidget(self.error)
        self.indicador = Indicador()
        cv.addWidget(self.indicador)
        centro.addWidget(self.caja)
        centro.addStretch(1)
        dv.addLayout(centro)
        self.demo = QWidget()
        self._armar_demo()
        dv.addSpacing(10)
        dv.addWidget(self.demo, 0, Qt.AlignHCenter)
        dv.addStretch(1)
        pie = QHBoxLayout()
        pie.setContentsMargins(18, 0, 18, 0)
        pie.addStretch(1)
        pie.addWidget(boton("⚙  Conexión", "link", self.abrir_ajustes.emit, "Cambiar de dónde salen los datos"))
        dv.addLayout(pie)
        h.addWidget(der, 6)
        self.refrescar_modo()

    # ------------------------------------------------------------------ formularios
    def _form_login(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        f.setContentsMargins(0, 14, 0, 4)
        f.setVerticalSpacing(10)
        f.setLabelAlignment(Qt.AlignLeft)
        self.l_correo = QLineEdit()
        self.l_correo.setPlaceholderText("tu@correo.com")
        self.l_pass = QLineEdit()
        self.l_pass.setEchoMode(QLineEdit.Password)
        self.l_pass.setPlaceholderText("Tu contraseña")
        self.l_correo.returnPressed.connect(self.l_pass.setFocus)
        self.l_pass.returnPressed.connect(self._entrar)
        f.addRow(etiqueta("Correo", "muted"))
        f.addRow(self.l_correo)
        f.addRow(etiqueta("Contraseña", "muted"))
        f.addRow(self.l_pass)
        self.btn_entrar = boton("Entrar", "primary", self._entrar)
        self.btn_entrar.setMinimumHeight(40)
        f.addRow(self.btn_entrar)
        return w

    def _form_registro(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        f.setContentsMargins(0, 14, 0, 4)
        f.setVerticalSpacing(8)
        self.r_nombre, self.r_apellido = QLineEdit(), QLineEdit()
        self.r_correo, self.r_tel = QLineEdit(), QLineEdit()
        self.r_pass, self.r_pass2 = QLineEdit(), QLineEdit()
        self.r_nombre.setPlaceholderText("Nombre")
        self.r_apellido.setPlaceholderText("Apellido")
        self.r_correo.setPlaceholderText("tu@correo.com")
        self.r_tel.setPlaceholderText("Teléfono (opcional)")
        for e, t in ((self.r_pass, "Contraseña (8+ caracteres, letras y números)"), (self.r_pass2, "Repite la contraseña")):
            e.setEchoMode(QLineEdit.Password)
            e.setPlaceholderText(t)
        self.r_rol = QComboBox()
        self.r_rol.addItem("Quiero comprar", "COMPRADOR")
        self.r_rol.addItem("Quiero vender (también puedo comprar)", "VENDEDOR")
        nombres = QHBoxLayout()
        nombres.addWidget(self.r_nombre)
        nombres.addWidget(self.r_apellido)
        f.addRow(nombres)
        for e in (self.r_correo, self.r_tel, self.r_pass, self.r_pass2, self.r_rol):
            f.addRow(e)
        self.r_pass2.returnPressed.connect(self._registrar)
        self.btn_registrar = boton("Crear mi cuenta", "primary", self._registrar)
        self.btn_registrar.setMinimumHeight(40)
        f.addRow(self.btn_registrar)
        return w

    def _armar_demo(self) -> None:
        v = QVBoxLayout(self.demo)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        t = etiqueta("Cuentas de demostración — un clic para entrar", "muted")
        t.setAlignment(Qt.AlignCenter)
        v.addWidget(t)
        fila = QHBoxLayout()
        fila.setSpacing(8)
        elegidas = {}
        for c in CUENTAS_DEMO:
            elegidas.setdefault(c.rol, c)
        nombres = {"ADMIN": "Administrador", "VENDEDOR": "Vendedor", "COMPRADOR": "Comprador"}
        for rol in ("COMPRADOR", "VENDEDOR", "ADMIN"):
            c = elegidas[rol]
            fila.addWidget(boton(nombres[rol], "chip", lambda c=c: self._entrar_demo(c.correo, c.password),
                                 f"{c.correo}  /  {c.password}"))
        v.addLayout(fila)

    def refrescar_modo(self) -> None:
        self.izq.poner_modo(self.ctx.cfg.modo)
        self.demo.setVisible(self.ctx.cfg.modo == "demo")

    # ------------------------------------------------------------------ acciones
    def _ocupado(self, si: bool) -> None:
        for b in (self.btn_entrar, self.btn_registrar):
            b.setEnabled(not si)
        self.demo.setEnabled(not si)
        self.indicador.inicio() if si else self.indicador.fin()

    def _entrar_demo(self, correo: str, password: str) -> None:
        self.tabs.setCurrentIndex(0)
        self.l_correo.setText(correo)
        self.l_pass.setText(password)
        self._entrar()

    def _entrar(self) -> None:
        correo, pw = self.l_correo.text().strip(), self.l_pass.text()
        if not correo or not pw:
            self.error.setText("Escribe tu correo y tu contraseña.")
            return
        self._lanzar(lambda: self.ctx.gw.login(correo, pw))

    def _registrar(self) -> None:
        if self.r_pass.text() != self.r_pass2.text():
            self.error.setText("Las contraseñas no coinciden.")
            return
        datos = DatosRegistro(correo=self.r_correo.text().strip(), password=self.r_pass.text(),
                              nombre=self.r_nombre.text().strip(), apellido=self.r_apellido.text().strip(),
                              telefono=self.r_tel.text().strip() or None, rol=self.r_rol.currentData())
        self._lanzar(lambda: self.ctx.gw.registrar(datos))

    def _lanzar(self, fn) -> None:
        self.error.clear()
        self._ocupado(True)

        def listo(_: Sesion) -> None:
            self._ocupado(False)
            self.limpiar()
            self.sesion_iniciada.emit()

        def fallo(exc: BaseException) -> None:
            self._ocupado(False)
            self.l_pass.clear()
            texto = getattr(exc, "mensaje", None) or f"{exc.__class__.__name__}: {exc}"
            detalles = getattr(exc, "detalles", None) or []
            if getattr(exc, "codigo", "") == "conexion":
                texto += "\nPuedes revisar o cambiar la conexión con el botón «Conexión» (abajo a la derecha)."
            self.error.setText(texto + ("\n" + "\n".join(f"• {d}" for d in detalles) if detalles else ""))

        self.ctx.trabajos.ejecutar(fn, listo, fallo, self)

    def limpiar(self) -> None:
        for e in (self.l_pass, self.r_pass, self.r_pass2):
            e.clear()
        self.error.clear()

    def mostrar(self, mensaje: str = "") -> None:
        self.limpiar()
        self.l_correo.clear()
        self.tabs.setCurrentIndex(0)
        self.error.setText(mensaje)
        self.l_correo.setFocus()
