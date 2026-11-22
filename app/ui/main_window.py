"""Ventana principal: pantalla de carga → inicio de sesión → aplicación (menú lateral según el rol)."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QSettings, QSize, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow, QMenu,
                               QProgressBar, QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from ..config import Config
from ..gateways.base import Gateway
from ..gateways.fabrica import crear_gateway
from . import theme
from .admin import CategoriasPage, PagosPage, PanelAdminPage, UsuariosPage
from .ajustes import AjustesDialog, guardar_ajustes
from .carrito import CarritoPage
from .conexiones import ConexionesPage
from .contexto import Contexto
from .login import LoginPage
from .pagina import PaginaBase
from .pedidos import PedidosPage
from .tienda import TiendaPage
from .trabajos import Trabajos
from .vendedor import MisProductosPage, MisVentasPage
from .widgets import boton, chip, etiqueta, tarjeta

# (clave, texto del menú, fábrica de la página)
Entrada = tuple[str, str, Callable[[Contexto], PaginaBase]]

MENU_POR_ROL: dict[str, list[tuple[str, list[Entrada]]]] = {
    "COMPRADOR": [
        ("COMPRAR", [("tienda", "🛍  Tienda", TiendaPage), ("carrito", "🛒  Mi carrito", CarritoPage),
                     ("pedidos", "📦  Mis pedidos", lambda c: PedidosPage(c, "mis"))]),
    ],
    "VENDEDOR": [
        ("COMPRAR", [("tienda", "🛍  Tienda", TiendaPage), ("carrito", "🛒  Mi carrito", CarritoPage),
                     ("pedidos", "📦  Mis pedidos", lambda c: PedidosPage(c, "mis"))]),
        ("VENDER", [("productos", "🏷  Mis productos", MisProductosPage), ("ventas", "💰  Mis ventas", MisVentasPage)]),
    ],
    "ADMIN": [
        ("EXPLORAR", [("tienda", "🛍  Tienda", TiendaPage)]),
        ("ADMINISTRAR", [("panel", "📊  Panel", PanelAdminPage), ("usuarios", "👥  Usuarios", UsuariosPage),
                         ("categorias", "🗂  Categorías", CategoriasPage),
                         ("pedidos_admin", "📦  Pedidos", lambda c: PedidosPage(c, "admin")),
                         ("pagos", "💳  Pagos", PagosPage)]),
        ("SISTEMA", [("conexiones", "🔌  Conexiones", ConexionesPage)]),
    ],
}


class Shell(QWidget):
    """Encabezado + menú lateral + páginas. Se reconstruye en cada inicio de sesión."""

    cerrar_sesion = Signal()
    abrir_ajustes = Signal()

    def __init__(self, ctx: Contexto, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setObjectName("raiz")
        self._paginas: dict[str, PaginaBase] = {}
        self._fila_de: dict[str, int] = {}
        self._clave_actual: str | None = None
        self._etiqueta_carrito = "🛒  Mi carrito"

        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(0, 0, 0, 0)
        raiz.setSpacing(0)

        # ------------------------------------------------------------------ encabezado
        cab = QFrame()
        cab.setObjectName("cabecera")
        cab.setStyleSheet(f"QFrame#cabecera {{ background:{theme.SURFACE}; border:none; border-bottom:1px solid {theme.BORDER}; }}")
        ch = QHBoxLayout(cab)
        ch.setContentsMargins(20, 10, 20, 10)
        ch.setSpacing(12)
        marca = QLabel("Marketplace")
        marca.setStyleSheet(f"color:{theme.PRIMARY}; font-size:16pt; font-weight:800; background:transparent;")
        ch.addWidget(marca)
        modo = chip(self._texto_modo(), theme.INFO, theme.INFO_SOFT)
        modo.setToolTip("De dónde salen los datos. Se cambia desde «Conexión» en la pantalla de inicio de sesión.")
        ch.addWidget(modo)
        ch.addStretch(1)
        self.btn_carrito = boton("🛒  Carrito (0)", "secondary", lambda: self.ir_a("carrito"))
        self.btn_carrito.setVisible(ctx.puede_comprar)
        ch.addWidget(self.btn_carrito)
        u = ctx.usuario
        self.btn_usuario = QPushButton(f"{u.nombre}  ▾")
        self.btn_usuario.setProperty("variante", "secondary")
        self.btn_usuario.setCursor(Qt.PointingHandCursor)
        menu = QMenu(self.btn_usuario)
        cabecera = QAction(f"{u.nombre_completo}\n{u.correo}", menu)
        cabecera.setEnabled(False)
        menu.addAction(cabecera)
        menu.addAction(QAction(f"Rol: {theme.ETIQUETAS_ESTATUS.get(u.rol, u.rol)}", menu, enabled=False))
        menu.addSeparator()
        menu.addAction("Cerrar sesión", self.cerrar_sesion.emit)
        self.btn_usuario.setMenu(menu)
        ch.addWidget(self.btn_usuario)
        raiz.addWidget(cab)

        # ------------------------------------------------------------------ cuerpo
        cuerpo = QHBoxLayout()
        cuerpo.setSpacing(0)
        self.menu = QListWidget()
        self.menu.setObjectName("sidebar")
        self.menu.setFixedWidth(230)
        self.menu.setFocusPolicy(Qt.NoFocus)
        self.menu.currentItemChanged.connect(self._cambio_menu)
        cuerpo.addWidget(self.menu)
        self.pila = QStackedWidget()
        cuerpo.addWidget(self.pila, 1)
        cont = QWidget()
        cont.setLayout(cuerpo)
        raiz.addWidget(cont, 1)

        self._construir_menu(ctx.rol)
        ctx.carrito_actualizado.connect(self._poner_carrito)
        ctx.navegar.connect(self.ir_a)
        ctx.refrescar_carrito()
        self.ir_a("tienda" if "tienda" in self._paginas else next(iter(self._paginas)))

    def _texto_modo(self) -> str:
        return {"demo": "Modo demostración", "directo": "Conexión directa", "api": "Conectado al backend"}.get(
            self.ctx.cfg.modo, self.ctx.cfg.modo)

    def _construir_menu(self, rol: str) -> None:
        for seccion, entradas in MENU_POR_ROL[rol]:
            cab = QListWidgetItem(seccion)
            cab.setFlags(Qt.NoItemFlags)
            cab.setSizeHint(QSize(190, 34 if self.menu.count() else 26))
            f = QFont(cab.font())
            f.setPointSizeF(8)
            f.setBold(True)
            cab.setFont(f)
            cab.setForeground(QColor(theme.MUTED))
            self.menu.addItem(cab)
            for clave, texto, fabrica in entradas:
                it = QListWidgetItem(texto)
                it.setData(Qt.UserRole, clave)
                it.setSizeHint(QSize(190, 42))
                self.menu.addItem(it)
                self._fila_de[clave] = self.menu.row(it)
                pagina = fabrica(self.ctx)
                self._paginas[clave] = pagina
                self.pila.addWidget(pagina)

    # ------------------------------------------------------------------ navegación
    def ir_a(self, clave: str) -> None:
        if clave not in self._paginas:
            return
        fila = self._fila_de[clave]
        if self.menu.currentRow() != fila:
            self.menu.setCurrentRow(fila)  # dispara _cambio_menu
        else:
            self._mostrar(clave)

    def _cambio_menu(self, actual: QListWidgetItem | None, _) -> None:
        if actual is None:
            return
        clave = actual.data(Qt.UserRole)
        if clave:
            self._mostrar(clave)

    def _mostrar(self, clave: str) -> None:
        pagina = self._paginas[clave]
        self._clave_actual = clave
        self.pila.setCurrentWidget(pagina)
        pagina.al_mostrar()

    def _poner_carrito(self, n: int) -> None:
        self.btn_carrito.setText(f"🛒  Carrito ({n})")
        if "carrito" in self._fila_de:
            self.menu.item(self._fila_de["carrito"]).setText(f"🛒  Mi carrito ({n})" if n else "🛒  Mi carrito")

    def limpiar(self) -> None:
        for p in self._paginas.values():
            p.al_cerrar_sesion()
        try:
            self.ctx.carrito_actualizado.disconnect(self._poner_carrito)
            self.ctx.navegar.disconnect(self.ir_a)
        except (RuntimeError, TypeError):
            pass


class PantallaCarga(QWidget):
    reintentar = Signal()
    cambiar_conexion = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("raiz")
        v = QVBoxLayout(self)
        v.setAlignment(Qt.AlignCenter)
        v.setSpacing(10)
        marca = QLabel("Marketplace")
        marca.setAlignment(Qt.AlignCenter)
        marca.setStyleSheet(f"color:{theme.PRIMARY}; font-size:32pt; font-weight:800;")
        v.addWidget(marca)
        self.texto = etiqueta("Preparando…", "subtitulo", wrap=True)
        self.texto.setAlignment(Qt.AlignCenter)
        self.texto.setMinimumWidth(520)
        v.addWidget(self.texto)
        self.barra = QProgressBar()
        self.barra.setFixedSize(380, 6)
        self.barra.setTextVisible(False)
        self.barra.setStyleSheet(f"QProgressBar {{ background:{theme.BORDER}; border:none; border-radius:3px; max-height:6px; }}"
                                 f"QProgressBar::chunk {{ background:{theme.PRIMARY}; border-radius:3px; }}")
        v.addWidget(self.barra, 0, Qt.AlignHCenter)
        self.error = etiqueta("", "error", wrap=True)
        self.error.setAlignment(Qt.AlignCenter)
        self.error.setMaximumWidth(560)
        v.addWidget(self.error, 0, Qt.AlignHCenter)
        fila = QHBoxLayout()
        fila.setAlignment(Qt.AlignCenter)
        self.btn_reintentar = boton("Reintentar", "primary", self.reintentar.emit)
        self.btn_config = boton("Cambiar conexión", "secondary", self.cambiar_conexion.emit)
        fila.addWidget(self.btn_reintentar)
        fila.addWidget(self.btn_config)
        v.addLayout(fila)
        self.cargando("Preparando…")

    def cargando(self, texto: str, actual: int = 0, total: int = 0) -> None:
        self.error.clear()
        self.texto.setText(texto)
        self.barra.setVisible(True)
        self.barra.setRange(0, total)  # 0,0 = animación indefinida
        self.barra.setValue(actual)
        self.btn_reintentar.setVisible(False)
        self.btn_config.setVisible(False)

    def fallo(self, texto: str) -> None:
        self.texto.setText("No se pudo preparar la aplicación")
        self.error.setText(texto)
        self.barra.setVisible(False)
        self.btn_reintentar.setVisible(True)
        self.btn_config.setVisible(True)


class MainWindow(QMainWindow):
    progreso = Signal(str, int, int)

    def __init__(self, cfg: Config, trabajos: Trabajos, fabrica: Callable[..., Gateway] = crear_gateway):
        super().__init__()
        self.cfg, self.trabajos, self._fabrica = cfg, trabajos, fabrica
        self.ajustes = QSettings("Marketplace", "MarketplaceGUI")
        self.ctx: Contexto | None = None
        self.login: LoginPage | None = None
        self.shell: Shell | None = None
        self._gen_gateway = 0
        self.setWindowTitle("Marketplace")
        self.setMinimumSize(1100, 700)
        self.resize(1380, 860)

        self.pila = QStackedWidget()
        self.setCentralWidget(self.pila)
        self.carga = PantallaCarga()
        self.carga.reintentar.connect(self.iniciar)
        self.carga.cambiar_conexion.connect(self.abrir_ajustes)
        self.pila.addWidget(self.carga)
        self.progreso.connect(self.carga.cargando)

    # ------------------------------------------------------------------ arranque / reconfiguración
    def iniciar(self) -> None:
        self._gen_gateway += 1
        gen = self._gen_gateway
        self._soltar_sesion_ui()
        self.pila.setCurrentWidget(self.carga)
        etiqueta_modo = {"demo": "Generando los datos de demostración…", "directo": "Conectando con las bases de datos…",
                         "api": "Conectando con el backend…"}.get(self.cfg.modo, "Preparando…")
        self.carga.cargando(etiqueta_modo)
        cfg = self.cfg
        self.trabajos.ejecutar(lambda: self._fabrica(cfg, lambda t, a, b: self.progreso.emit(t, a, b)),
                               lambda gw: self._gateway_listo(gen, gw), lambda exc: self._gateway_fallo(gen, exc), self)

    def _soltar_sesion_ui(self) -> None:
        for w in (self.login, self.shell):
            if w is not None:
                self.pila.removeWidget(w)
                w.deleteLater()
        if self.ctx is not None:
            self.ctx.deleteLater()
        self.login = self.shell = self.ctx = None

    def _gateway_fallo(self, gen: int, exc: BaseException) -> None:
        if gen != self._gen_gateway:
            return
        texto = getattr(exc, "mensaje", None) or f"{exc.__class__.__name__}: {exc}"
        self.carga.fallo(texto + "\n\nRevisa tu archivo .env (credenciales y direcciones) o elige otro modo en «Cambiar conexión».")

    def _gateway_listo(self, gen: int, gw: Gateway) -> None:
        if gen != self._gen_gateway:
            return
        self.ctx = Contexto(gw, self.cfg, self.trabajos, self)
        self.ctx.mensaje.connect(lambda t: self.statusBar().showMessage(t, 6000))
        self.ctx.sesion_expirada.connect(self._sesion_expirada)
        self.login = LoginPage(self.ctx)
        self.login.sesion_iniciada.connect(self._sesion_iniciada)
        self.login.abrir_ajustes.connect(self.abrir_ajustes)
        self.pila.addWidget(self.login)
        self.pila.setCurrentWidget(self.login)
        self.statusBar().clearMessage()
        self.login.l_correo.setFocus()

    # ------------------------------------------------------------------ sesión
    def _sesion_iniciada(self) -> None:
        assert self.ctx is not None
        self.shell = Shell(self.ctx)
        self.shell.cerrar_sesion.connect(self.cerrar_sesion)
        self.pila.addWidget(self.shell)
        self.pila.setCurrentWidget(self.shell)
        u = self.ctx.usuario
        self.statusBar().showMessage(f"Hola, {u.nombre}. Sesión iniciada como {theme.ETIQUETAS_ESTATUS.get(u.rol, u.rol).lower()}.", 6000)

    def _volver_al_login(self, mensaje: str = "") -> None:
        if self.shell is not None:
            self.shell.limpiar()
            self.pila.removeWidget(self.shell)
            self.shell.deleteLater()
            self.shell = None
        self.statusBar().clearMessage()
        self.ctx.arbol = None  # type: ignore[union-attr]
        self.ctx.pedido_a_seleccionar = None  # type: ignore[union-attr]
        self.pila.setCurrentWidget(self.login)
        self.login.mostrar(mensaje)

    def cerrar_sesion(self) -> None:
        gw = self.ctx.gw
        self._volver_al_login()
        self.trabajos.ejecutar(gw.logout, None, lambda _: None, self)

    def _sesion_expirada(self) -> None:
        if self.shell is None:
            return
        gw = self.ctx.gw
        self.trabajos.ejecutar(gw.logout, None, lambda _: None, self)
        self._volver_al_login("Tu sesión expiró o ya no es válida. Inicia sesión de nuevo.")

    # ------------------------------------------------------------------ ajustes de conexión
    def abrir_ajustes(self) -> None:
        dlg = AjustesDialog(self.cfg, self.trabajos, self)
        if dlg.exec() != QDialog.Accepted:
            return
        if dlg.modo == self.cfg.modo and dlg.api_url == self.cfg.api_url and self.ctx is not None:
            return
        guardar_ajustes(self.ajustes, dlg.modo, dlg.api_url)
        self.cfg = self.cfg.con(modo=dlg.modo, api_url=dlg.api_url)
        self.iniciar()

    def closeEvent(self, e) -> None:  # noqa: N802
        self.trabajos.esperar(2000)
        super().closeEvent(e)
