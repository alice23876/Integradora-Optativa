"""Pruebas de la interfaz con Qt «offscreen» (sin pantalla): se maneja la ventana como lo haría una persona.

Usan el modo demo con pocos productos para que sean rápidas. Cualquier excepción que ocurra dentro de
un slot de Qt (que normalmente solo se imprime) hace fallar la prueba.
"""
from __future__ import annotations

import os
import sys
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QSettings, QTimer, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from app.config import Config  # noqa: E402
from app.ui.carrito import CheckoutDialog  # noqa: E402
from app.ui.main_window import MENU_POR_ROL, MainWindow  # noqa: E402
from app.ui.theme import aplicar_tema  # noqa: E402
from app.ui.trabajos import Trabajos  # noqa: E402
from app.ui.vendedor import ProductoEditorDialog, texto_a_atributos  # noqa: E402
from app.errors import ErrorValidacion  # noqa: E402


# --------------------------------------------------------------------------- utilidades
def bombear(app, ms: int = 30) -> None:
    """Procesa eventos de Qt un rato (con sleep: así el hilo de trabajo recibe el GIL)."""
    fin = time.time() + ms / 1000
    while time.time() < fin:
        app.processEvents()
        time.sleep(0.004)


def esperar(app, condicion, ms: int = 15000) -> bool:
    fin = time.time() + ms / 1000
    while time.time() < fin:
        app.processEvents()
        if condicion():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    aplicar_tema(app)
    return app


@pytest.fixture
def ventana(qapp, tmp_path, monkeypatch):
    QSettings.setDefaultFormat(QSettings.IniFormat)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    errores: list = []
    monkeypatch.setattr(sys, "excepthook", lambda t, v, tb: errores.append(f"{t.__name__}: {v}"))
    w = MainWindow(Config(modo="demo", demo_productos=400), Trabajos())
    w.resize(1280, 800)
    w.show()
    w.iniciar()
    assert esperar(qapp, lambda: w.login is not None, 60000), "la app no llegó a la pantalla de inicio de sesión"
    yield w
    bombear(qapp, 100)
    w.close()
    assert not errores, f"excepciones dentro de Qt: {errores}"


def entrar(qapp, w, correo: str, password: str):
    w.login.l_correo.setText(correo)
    w.login.l_pass.setText(password)
    w.login._entrar()
    assert esperar(qapp, lambda: w.shell is not None), w.login.error.text()


def reposo(qapp, w) -> None:
    """Espera a que no quede ninguna llamada pendiente al gateway."""
    assert esperar(qapp, lambda: w.trabajos.pendientes == 0, 20000), "quedaron llamadas sin terminar"
    bombear(qapp, 80)


@pytest.fixture
def modales(qapp):
    """Cierra solos los cuadros de mensaje (aceptando) y guarda lo que dijeron."""
    visto: list[str] = []

    def vigilar():
        m = QApplication.activeModalWidget()
        if isinstance(m, QMessageBox):
            visto.append(m.text())
            for b in m.buttons():
                if m.buttonRole(b) == QMessageBox.AcceptRole:
                    b.click()
                    return
            m.buttons()[0].click()

    t = QTimer()
    t.timeout.connect(vigilar)
    t.start(60)
    yield visto
    t.stop()


# --------------------------------------------------------------------------- pruebas
@pytest.mark.parametrize("correo,password,rol", [
    ("comprador@demo.com", "Compra1234", "COMPRADOR"),
    ("vendedor1@demo.com", "Vende1234", "VENDEDOR"),
    ("admin@demo.com", "Admin1234", "ADMIN"),
])
def test_cada_rol_ve_su_menu_y_todas_las_pantallas_cargan(qapp, ventana, correo, password, rol):
    entrar(qapp, ventana, correo, password)
    claves = [c for _, entradas in MENU_POR_ROL[rol] for c, _, _ in entradas]
    assert list(ventana.shell._paginas) == claves
    for clave in claves:
        ventana.shell.ir_a(clave)
        reposo(qapp, ventana)
        assert ventana.shell.pila.currentWidget() is ventana.shell._paginas[clave]
    # el administrador no compra: no tiene carrito
    assert ventana.shell.btn_carrito.isVisibleTo(ventana.shell) == (rol != "ADMIN")


def test_login_incorrecto_y_registro_validado(qapp, ventana):
    l = ventana.login
    l.l_correo.setText("admin@demo.com")
    l.l_pass.setText("incorrecta")
    l._entrar()
    assert esperar(qapp, lambda: l.error.text() != "" and l.btn_entrar.isEnabled())
    assert "incorrectos" in l.error.text()
    assert ventana.shell is None

    l.tabs.setCurrentIndex(1)
    l.r_pass.setText("abc12345")
    l.r_pass2.setText("distinta1")
    l._registrar()
    assert "no coinciden" in l.error.text()

    for e, v in ((l.r_nombre, "Luis"), (l.r_apellido, "Prueba"), (l.r_correo, "luis@prueba.com"),
                 (l.r_pass, "Secreta123"), (l.r_pass2, "Secreta123")):
        e.setText(v)
    l.r_rol.setCurrentIndex(l.r_rol.findData("VENDEDOR"))
    l._registrar()
    assert esperar(qapp, lambda: ventana.shell is not None), l.error.text()
    assert ventana.ctx.rol == "VENDEDOR"


def test_tienda_busca_pagina_y_filtra_por_categoria(qapp, ventana):
    entrar(qapp, ventana, "comprador@demo.com", "Compra1234")
    t = ventana.shell._paginas["tienda"]
    assert esperar(qapp, lambda: t.modelo.rowCount() > 0)
    assert t.modelo.rowCount() <= 24  # nunca se baja el catálogo completo
    sb = t.vista.verticalScrollBar()
    antes = t.modelo.rowCount()
    sb.setValue(sb.maximum())
    assert esperar(qapp, lambda: t.modelo.rowCount() > antes), "el scroll no cargó más productos"

    t.q.setText("zzzzzz")
    t._buscar()
    assert esperar(qapp, lambda: not t._cargando and t.pila.currentWidget() is t.vacio)

    t._limpiar()
    assert esperar(qapp, lambda: not t._cargando and t.modelo.rowCount() > 0)
    raiz = t.arbol_ui.topLevelItem(1)
    t.arbol_ui.setCurrentItem(raiz.child(0) if raiz.childCount() else raiz)
    assert esperar(qapp, lambda: not t._cargando and t.modelo.rowCount() > 0)
    assert "›" in t.resumen.text() or "«" in t.resumen.text()


def test_compra_completa_desde_el_carrito(qapp, ventana, modales):
    entrar(qapp, ventana, "comprador@demo.com", "Compra1234")
    ctx, shell = ventana.ctx, ventana.shell
    t = shell._paginas["tienda"]
    assert esperar(qapp, lambda: t.modelo.rowCount() >= 2)
    stock = {}
    for i in (0, 1):
        r = t.modelo.index(i).data(Qt.UserRole)
        v = next(v for v in ctx.gw.obtener_producto(r.id_producto).variantes if v.cantidad_stock >= 2)
        stock[v.id_variante] = (r.id_producto, v.cantidad_stock)
        ctx.gw.agregar_al_carrito(v.id_variante, 2)
    shell.ir_a("carrito")
    cp = shell._paginas["carrito"]
    assert esperar(qapp, lambda: cp.tabla.rowCount() == 2 and cp.btn_pagar.isEnabled())

    def rellenar():
        d = QApplication.activeModalWidget()
        if isinstance(d, CheckoutDialog) and d.btn.isEnabled():
            d.direccion.setPlainText("Av. Morelos 45, Col. Centro, Cuernavaca, Morelos, 62000")
            d.btn.click()

    timer = QTimer()
    timer.timeout.connect(rellenar)
    timer.start(60)
    cp._pagar()
    timer.stop()
    assert any("Tu pedido" in m for m in modales), modales
    assert shell._clave_actual == "pedidos"
    pe = shell._paginas["pedidos"]
    assert esperar(qapp, lambda: pe._pedido is not None and pe._pedido.estatus == "PAGADO")
    assert pe._pedido.monto_total > 0
    assert ctx.gw.obtener_carrito().lineas == []
    for id_var, (id_prod, antes) in stock.items():  # el inventario bajó 2 en cada variante
        despues = next(v for v in ctx.gw.obtener_producto(id_prod).variantes if v.id_variante == id_var)
        assert despues.cantidad_stock == antes - 2


def test_vendedor_publica_edita_y_ve_ventas(qapp, ventana, modales):
    entrar(qapp, ventana, "vendedor1@demo.com", "Vende1234")
    ctx = ventana.ctx
    ed = ProductoEditorDialog(ctx, None, ventana)
    ed.show()
    assert esperar(qapp, lambda: ed.categoria.count() > 1)
    ed.titulo.setText("Mochila de prueba UI")
    ed.categoria.setCurrentIndex(3)
    f1 = ed._filas[0]
    f1.sku.setText("mochi-ui-1")
    f1.atributos.setText("Color=Azul; Tamaño=Grande")
    ed._agregar_fila()
    f2 = ed._filas[1]
    f2.sku.setText("mochi-ui-2")
    f2.atributos.setText("Color Rojo")  # mal escrito
    ed._guardar()
    assert "Color Rojo" in ed.error.text()
    f2.atributos.setText("Color=Rojo")
    f2.precio.setValue(349.5)
    f2.stock.setValue(7)
    ed._guardar()
    assert esperar(qapp, lambda: ed.guardado is not None), ed.error.text()
    assert {v.sku for v in ed.guardado.variantes} == {"MOCHI-UI-1", "MOCHI-UI-2"}
    id_producto = ed.guardado.id_producto
    ed.close()

    # SKU repetido: la base lo rechaza y el formulario lo explica
    ed2 = ProductoEditorDialog(ctx, None, ventana)
    ed2.show()
    assert esperar(qapp, lambda: ed2.categoria.count() > 1)
    ed2.titulo.setText("Otra mochila")
    ed2.categoria.setCurrentIndex(3)
    ed2._filas[0].sku.setText("MOCHI-UI-1")
    ed2._guardar()
    assert esperar(qapp, lambda: ed2.error.text() != "")
    assert "ya existe" in ed2.error.text()
    ed2.close()

    # edición: cambia precio y existencias de la primera variante; el SKU no es editable
    prod = ctx.gw.obtener_producto(id_producto)
    ed3 = ProductoEditorDialog(ctx, prod, ventana)
    ed3.show()
    assert esperar(qapp, lambda: ed3.titulo.text() != "")
    assert all(f.sku.isReadOnly() for f in ed3._filas)
    ed3._filas[0].precio.setValue(999.99)
    ed3._filas[0].stock.setValue(5)
    ed3._guardar()
    assert esperar(qapp, lambda: ed3.guardado is not None), ed3.error.text()
    primera = next(v for v in ed3.guardado.variantes if v.sku == "MOCHI-UI-1")
    assert (str(primera.precio), primera.cantidad_stock) == ("999.99", 5)
    ed3.close()

    ventana.shell.ir_a("productos")
    mp = ventana.shell._paginas["productos"]
    assert esperar(qapp, lambda: mp.tabla.rowCount() > 0)
    assert any("Mochila de prueba UI" in mp.tabla.item(f, 0).text() for f in range(mp.tabla.rowCount()))
    ventana.shell.ir_a("ventas")
    reposo(qapp, ventana)


def test_texto_a_atributos():
    assert texto_a_atributos("Talla=M; Color=Azul") == {"Talla": "M", "Color": "Azul"}
    assert texto_a_atributos("") == {}
    with pytest.raises(ErrorValidacion):
        texto_a_atributos("Talla M")


def test_admin_suspende_usuarios_y_crea_categorias(qapp, ventana, modales):
    entrar(qapp, ventana, "admin@demo.com", "Admin1234")
    ctx, shell = ventana.ctx, ventana.shell
    shell.ir_a("panel")
    pn = shell._paginas["panel"]
    assert esperar(qapp, lambda: pn.k_usuarios.text() != "—")
    assert pn.k_productos.text() == "400"

    shell.ir_a("usuarios")
    us = shell._paginas["usuarios"]
    assert esperar(qapp, lambda: us.tabla.rowCount() > 0)
    us.q.setText("comprador2")
    us._buscar()
    assert esperar(qapp, lambda: us.tabla.rowCount() == 1)
    us.tabla.selectRow(0)
    us._cambiar_estado()
    assert esperar(qapp, lambda: us._usuario.estatus == "SUSPENDIDO")
    assert any("Suspender" in m or "iniciar sesión" in m for m in modales)
    us.q.setText("admin@")  # la propia cuenta no se puede suspender ni degradar
    us._buscar()
    assert esperar(qapp, lambda: us.tabla.rowCount() >= 1)
    us.tabla.selectRow(0)
    bombear(qapp, 100)
    assert not us.btn_estado.isEnabled() and not us.btn_rol.isEnabled()

    shell.ir_a("categorias")
    ct = shell._paginas["categorias"]
    assert esperar(qapp, lambda: ct.arbol_ui.topLevelItemCount() > 0)
    from app.ui.admin import CategoriaDialog
    d = CategoriaDialog(ctx, ctx.arbol, None, None, ventana)
    d.show()
    d.nombre.setText("Mascotas y más")
    d._auto_slug("Mascotas y más")
    assert d.slug.text() == "mascotas-y-mas"
    d._guardar()
    assert esperar(qapp, lambda: d.guardada is not None), d.error.text()
    nueva = d.guardada.id_categoria
    d.close()
    ctx.arbol = None
    ct._cargar(True)
    assert esperar(qapp, lambda: ctx.arbol is not None and nueva in ctx.arbol.por_id)
    # al editar la categoría nueva, sus descendientes no se ofrecen como «madre» (evita ciclos)
    d2 = CategoriaDialog(ctx, ctx.arbol, ctx.arbol.por_id[nueva], None, ventana)
    assert all("Mascotas y más" not in d2.padre.itemText(i) for i in range(d2.padre.count()))
    d2.close()

    for clave in ("pedidos_admin", "pagos", "conexiones"):
        shell.ir_a(clave)
        reposo(qapp, ventana)
    assert shell._paginas["conexiones"].tabla.rowCount() == 3


def test_cerrar_sesion_y_sesion_expirada_vuelven_al_login(qapp, ventana):
    entrar(qapp, ventana, "comprador@demo.com", "Compra1234")
    ventana.shell.cerrar_sesion.emit()
    bombear(qapp, 200)
    assert ventana.shell is None and ventana.pila.currentWidget() is ventana.login
    assert ventana.login.l_pass.text() == ""

    entrar(qapp, ventana, "comprador@demo.com", "Compra1234")
    ventana.ctx.gw.logout()          # el servidor «olvida» la sesión
    ventana.ctx.sesion_expirada.emit()
    bombear(qapp, 200)
    assert ventana.shell is None
    assert "sesión" in ventana.login.error.text()
