"""Pruebas de contrato: se ejecutan idénticas contra memoria, DynamoDB (moto) y la API HTTP falsa."""
from __future__ import annotations

import threading
from decimal import Decimal

import pytest

from app.categorias import ArbolCategorias
from app.demo_data import CUENTAS_DEMO
from app.errors import (ErrorAutenticacion, ErrorConflicto, ErrorNoEncontrado, ErrorPago, ErrorPermiso,
                        ErrorStock, ErrorValidacion)
from app.gateways.directo import GatewayDirecto
from app.models import (Categoria, DatosProducto, DatosRegistro, DatosVariante, FiltroProductos)
from app.pagos import PasarelaSimulada
from app.util import normalizar

from .conftest import N_PRODUCTOS

DIRECCION = "Calle Falsa 123, Col. Centro, Ciudad de México, C.P. 06000"


# --------------------------------------------------------------------------- ayudas
def recorrer(fn, limite=7, max_paginas=600):
    items, cursor, n = [], None, 0
    while True:
        pag = fn(cursor, limite)
        items += pag.items
        n += 1
        assert n < max_paginas, "paginación infinita"
        if not pag.siguiente:
            return items
        cursor = pag.siguiente


def correo_de(mundo, id_usuario: int) -> str:
    for c in CUENTAS_DEMO:
        if mundo.vendedor_id(c.correo) == id_usuario:
            return c.correo
    raise AssertionError(id_usuario)


def comprar(mundo, v, cantidad=1, correo="comprador@demo.com", metodo="TARJETA"):
    mundo.entrar(correo)
    mundo.gw.agregar_al_carrito(v.id_variante, cantidad)
    return mundo.gw.checkout(DIRECCION, metodo)


def entregar(mundo, pedido, vendedor_correo, comprador="comprador@demo.com"):
    mundo.entrar(vendedor_correo)
    mundo.gw.cambiar_estatus_pedido(pedido.id_pedido, "ENVIADO")
    mundo.entrar(comprador)
    return mundo.gw.cambiar_estatus_pedido(pedido.id_pedido, "ENTREGADO")


def stock_actual(mundo, v) -> int:
    return mundo.cat.obtener_variantes([v.id_variante])[v.id_variante].cantidad_stock


# --------------------------------------------------------------------------- sesión
def test_requiere_sesion(mundo):
    with pytest.raises(ErrorAutenticacion):
        mundo.gw.listar_productos(None, None, 5)
    with pytest.raises(ErrorAutenticacion):
        mundo.gw.obtener_carrito()


def test_login_correcto_e_incorrecto(mundo):
    gw = mundo.gw
    with pytest.raises(ErrorAutenticacion):
        gw.login("comprador@demo.com", "incorrecta1")
    with pytest.raises(ErrorAutenticacion):
        gw.login("nadie@demo.com", "Compra1234")
    with pytest.raises(ErrorValidacion if mundo.tipo != "api" else (ErrorValidacion, ErrorAutenticacion)):
        gw.login("", "")
    s = gw.login("COMPRADOR@demo.com ", "Compra1234")  # el correo se normaliza
    assert s.usuario.rol == "COMPRADOR" and s.usuario.nombre == "Diego"
    assert gw.sesion.usuario.correo == "comprador@demo.com"
    gw.logout()
    assert gw.sesion is None


def test_registro(mundo):
    gw = mundo.gw
    nuevo = DatosRegistro("nuevo@demo.com", "Clave1234", "Nora", "Pérez", "5512345678", "VENDEDOR")
    assert gw.registrar(nuevo).usuario.rol == "VENDEDOR"
    gw.logout()
    with pytest.raises(ErrorConflicto):
        gw.registrar(nuevo)
    with pytest.raises(ErrorValidacion):
        gw.registrar(DatosRegistro("otro@demo.com", "corta", "A", "B"))
    with pytest.raises(ErrorValidacion):
        gw.registrar(DatosRegistro("otro@demo.com", "Clave1234", "A", "B", None, "ADMIN"))  # nadie se hace admin solo
    with pytest.raises(ErrorValidacion):
        gw.registrar(DatosRegistro("no-es-correo", "Clave1234", "A", "B"))
    gw.logout()
    assert gw.login("nuevo@demo.com", "Clave1234").usuario.apellido == "Pérez"


def test_cuenta_suspendida_no_entra(mundo):
    mundo.entrar("admin@demo.com")
    objetivo = mundo.vendedor_id("comprador2@demo.com")
    mundo.gw.actualizar_usuario(objetivo, estatus="SUSPENDIDO")
    with pytest.raises(ErrorAutenticacion):
        mundo.entrar("comprador2@demo.com")
    mundo.entrar("admin@demo.com")
    mundo.gw.actualizar_usuario(objetivo, estatus="ACTIVO")
    assert mundo.entrar("comprador2@demo.com").usuario.estatus == "ACTIVO"


# --------------------------------------------------------------------------- catálogo
def test_categorias(mundo):
    mundo.entrar("comprador@demo.com")
    nombres = {c.nombre for c in mundo.gw.listar_categorias()}
    assert {"Ropa", "Hombre", "Camisas", "Electrónica", "Libros"} <= nombres


def test_feed_pagina_todo_sin_duplicados_ni_faltantes(mundo):
    mundo.entrar("comprador@demo.com")
    items = recorrer(lambda c, l: mundo.gw.listar_productos(None, c, l), limite=17)
    ids = [p.id_producto for p in items]
    assert len(ids) == len(set(ids)) == N_PRODUCTOS
    assert all(p.precio_desde is not None for p in items)


def test_categoria_incluye_subcategorias(mundo):
    mundo.entrar("comprador@demo.com")
    arbol = ArbolCategorias(mundo.gw.listar_categorias())
    for id_cat in ("cat_ropa", "cat_hombre", "cat_camisas", "cat_electronica"):
        validas = set(arbol.descendientes(id_cat))
        esperado = {p.id_producto for p in mundo.productos if p.id_categoria in validas}
        assert esperado, id_cat
        items = recorrer(lambda c, l: mundo.gw.listar_productos(FiltroProductos(id_categoria=id_cat), c, l), limite=5)
        ids = [p.id_producto for p in items]
        assert len(ids) == len(set(ids)), f"duplicados en {id_cat}"
        assert set(ids) == esperado, id_cat


def test_orden_mas_recientes_primero_en_categoria_hoja(mundo):
    """Dentro de una categoría hoja: más reciente primero. (En una categoría padre los resultados
    salen agrupados por subcategoría, cada grupo ordenado así: no se mezclan particiones del índice.)"""
    mundo.entrar("comprador@demo.com")
    conteo: dict[str, int] = {}
    for p in mundo.productos:
        conteo[p.id_categoria] = conteo.get(p.id_categoria, 0) + 1
    hoja = max(conteo, key=conteo.get)
    items = recorrer(lambda c, l: mundo.gw.listar_productos(FiltroProductos(id_categoria=hoja), c, l), limite=2)
    fechas = [p.fecha_creacion for p in items]
    assert len(fechas) == conteo[hoja] >= 3 and fechas == sorted(fechas, reverse=True)


def test_busqueda_por_prefijo_ignora_acentos_y_mayusculas(mundo):
    mundo.entrar("comprador@demo.com")
    for q in ("camisa", "AUDIFONOS", "Audífonos", "libro"):
        esperado = {p.id_producto for p in mundo.productos if normalizar(p.titulo).startswith(normalizar(q))}
        assert esperado, q
        items = recorrer(lambda c, l: mundo.gw.listar_productos(FiltroProductos(q=q), c, l), limite=3)
        assert {p.id_producto for p in items} == esperado, q
    assert recorrer(lambda c, l: mundo.gw.listar_productos(FiltroProductos(q="zzzz-no-existe"), c, l)) == []


def test_busqueda_en_cualquier_parte_y_dentro_de_categoria(mundo):
    mundo.entrar("comprador@demo.com")
    esperado = {p.id_producto for p in mundo.productos if "slim" in normalizar(p.titulo)}
    assert esperado
    items = recorrer(lambda c, l: mundo.gw.listar_productos(FiltroProductos(q="slim", en_cualquier_parte=True), c, l), 2)
    assert {p.id_producto for p in items} == esperado and len(items) == len(esperado)

    arbol = ArbolCategorias(mundo.gw.listar_categorias())
    validas = set(arbol.descendientes("cat_ropa"))
    esperado = {p.id_producto for p in mundo.productos if p.id_categoria in validas and "premium" in normalizar(p.titulo)}
    assert esperado
    items = recorrer(lambda c, l: mundo.gw.listar_productos(FiltroProductos(q="premium", id_categoria="cat_ropa"), c, l), 2)
    assert {p.id_producto for p in items} == esperado and len(items) == len(esperado)


def test_cursor_invalido(mundo):
    mundo.entrar("comprador@demo.com")
    with pytest.raises(ErrorValidacion):
        mundo.gw.listar_productos(None, "###no-es-cursor###", 5)


def test_detalle_de_producto(mundo):
    mundo.entrar("comprador@demo.com")
    p, _ = mundo.variante_con_stock(1)
    d = mundo.gw.obtener_producto(p.id_producto)
    assert d.titulo == p.titulo and d.descripcion == p.descripcion
    assert {v.sku for v in d.variantes} == {v.sku for v in p.variantes}
    assert d.precio_desde == min(v.precio for v in p.variantes)
    assert d.ruta_categoria and d.nombre_vendedor and d.nombre_vendedor.endswith(".")
    with pytest.raises(ErrorNoEncontrado):
        mundo.gw.obtener_producto("f" * 32)


# --------------------------------------------------------------------------- carrito
def test_carrito_agrega_suma_cambia_y_quita(mundo):
    mundo.entrar("comprador@demo.com")
    gw = mundo.gw
    _, v = mundo.variante_con_stock(5)
    c = gw.agregar_al_carrito(v.id_variante, 2)
    assert len(c.lineas) == 1 and c.lineas[0].cantidad == 2 and c.total == v.precio * 2
    c = gw.agregar_al_carrito(v.id_variante, 1)
    assert len(c.lineas) == 1 and c.lineas[0].cantidad == 3  # misma variante → se suma
    linea = c.lineas[0]
    assert linea.sku == v.sku and linea.disponible and linea.stock_disponible == v.cantidad_stock
    c = gw.cambiar_cantidad(linea.id_detalle_carrito, 1)
    assert c.lineas[0].cantidad == 1
    with pytest.raises(ErrorStock):
        gw.cambiar_cantidad(linea.id_detalle_carrito, v.cantidad_stock + 1)
    with pytest.raises(ErrorStock):
        gw.agregar_al_carrito(v.id_variante, v.cantidad_stock)  # ya hay 1 en el carrito
    with pytest.raises(ErrorValidacion):
        gw.agregar_al_carrito(v.id_variante, 0)
    assert gw.quitar_del_carrito(linea.id_detalle_carrito).lineas == []


def test_no_puedes_comprar_tus_productos_ni_el_admin_compra(mundo):
    mundo.entrar("vendedor1@demo.com")
    mio = next(p for p in mundo.productos if p.id_vendedor == mundo.vendedor_id("vendedor1@demo.com"))
    with pytest.raises(ErrorValidacion):
        mundo.gw.agregar_al_carrito(mio.variantes[0].id_variante, 1)
    mundo.entrar("admin@demo.com")
    with pytest.raises(ErrorPermiso):
        mundo.gw.obtener_carrito()


# --------------------------------------------------------------------------- checkout
def test_checkout_completo(mundo):
    gw = mundo.gw
    p1, v1 = mundo.variante_con_stock(5)
    p2, v2 = mundo.variante_con_stock(5, excluir={p1.id_producto})
    mundo.entrar("comprador@demo.com")
    gw.agregar_al_carrito(v1.id_variante, 2)
    gw.agregar_al_carrito(v2.id_variante, 1)
    pedido = gw.checkout(DIRECCION, "TARJETA")

    total = v1.precio * 2 + v2.precio
    assert pedido.estatus == "PAGADO" and pedido.monto_total == total
    assert [l.cantidad for l in pedido.lineas] == [2, 1]
    assert {l.titulo for l in pedido.lineas} == {p1.titulo, p2.titulo}          # título viene de DynamoDB
    assert pedido.lineas[0].subtotal == v1.precio * 2
    assert len(pedido.pagos) == 1 and pedido.pagos[0].estatus == "APROBADO" and pedido.pagos[0].monto == total
    assert stock_actual(mundo, v1) == v1.cantidad_stock - 2
    assert stock_actual(mundo, v2) == v2.cantidad_stock - 1
    assert gw.obtener_carrito().lineas == []
    assert pedido.id_pedido in [p.id_pedido for p in gw.listar_mis_pedidos().items]

    # el precio queda congelado aunque el catálogo cambie después
    mundo.cat.actualizar_variante(v1.id_variante, precio=Decimal("1.00"))
    assert gw.obtener_pedido(pedido.id_pedido).lineas[0].precio_unitario == v1.precio

    # otro comprador no puede ver este pedido
    mundo.entrar("comprador2@demo.com")
    with pytest.raises(ErrorNoEncontrado):
        gw.obtener_pedido(pedido.id_pedido)

    # cada vendedor ve SOLO su parte, con título resuelto
    for prod in (p1, p2):
        mundo.entrar(correo_de(mundo, prod.id_vendedor))
        ventas = gw.listar_mis_ventas().items
        assert any(v.id_pedido == pedido.id_pedido and v.titulo == prod.titulo for v in ventas)
        visto = gw.obtener_pedido(pedido.id_pedido)
        assert all(l.id_vendedor == prod.id_vendedor for l in visto.lineas) and not visto.pagos


def test_checkout_validaciones(mundo):
    mundo.entrar("comprador@demo.com")
    gw = mundo.gw
    with pytest.raises(ErrorValidacion):
        gw.checkout(DIRECCION, "TARJETA")  # carrito vacío
    _, v = mundo.variante_con_stock(5)
    gw.agregar_al_carrito(v.id_variante, 1)
    with pytest.raises(ErrorValidacion):
        gw.checkout("corta", "TARJETA")
    with pytest.raises(ErrorValidacion):
        gw.checkout(DIRECCION, "BITCOIN")
    assert stock_actual(mundo, v) == v.cantidad_stock  # nada se descontó


def test_checkout_con_stock_insuficiente_no_toca_nada(mundo):
    mundo.entrar("comprador@demo.com")
    gw = mundo.gw
    _, v = mundo.variante_con_stock(5)
    gw.agregar_al_carrito(v.id_variante, 3)
    mundo.cat.actualizar_variante(v.id_variante, cantidad_stock=1)  # alguien más compró
    with pytest.raises(ErrorStock) as exc:
        gw.checkout(DIRECCION, "TARJETA")
    assert exc.value.detalles
    assert stock_actual(mundo, v) == 1
    assert len(gw.obtener_carrito().lineas) == 1 and gw.listar_mis_pedidos().items == []


def test_reserva_de_stock_es_atomica(mundo):
    """Si la 2.ª variante no alcanza, la 1.ª tampoco se descuenta."""
    (_, a), (_, b) = mundo.variante_con_stock(5), mundo.variante_con_stock(5, excluir={mundo.variante_con_stock(5)[0].id_producto})
    mundo.cat.actualizar_variante(b.id_variante, cantidad_stock=1)
    with pytest.raises(ErrorStock) as exc:
        mundo.cat.reservar_stock([(a.id_variante, 2), (b.id_variante, 2)])
    assert exc.value.ids_afectados == [b.id_variante]
    assert stock_actual(mundo, a) == a.cantidad_stock and stock_actual(mundo, b) == 1


def test_carrera_en_checkout_libera_y_conserva_el_carrito(mundo):
    mundo.entrar("comprador@demo.com")
    gw = mundo.gw
    (_, a), (_, b) = mundo.variante_con_stock(5), mundo.variante_con_stock(5, excluir={mundo.variante_con_stock(5)[0].id_producto})
    gw.agregar_al_carrito(a.id_variante, 1)
    gw.agregar_al_carrito(b.id_variante, 1)
    original = mundo.cat.reservar_stock

    def con_carrera(items):  # otro comprador se lleva la última pieza justo después de validar
        mundo.cat.actualizar_variante(b.id_variante, cantidad_stock=0)
        return original(items)

    mundo.cat.reservar_stock = con_carrera
    try:
        with pytest.raises(ErrorStock):
            gw.checkout(DIRECCION, "TARJETA")
    finally:
        mundo.cat.reservar_stock = original
    assert stock_actual(mundo, a) == a.cantidad_stock          # nada descontado
    assert len(gw.obtener_carrito().lineas) == 2               # carrito intacto
    assert gw.listar_mis_pedidos().items == []                 # sin pedido huérfano


def test_si_falla_mysql_se_devuelve_el_stock(mundo):
    mundo.entrar("comprador@demo.com")
    _, v = mundo.variante_con_stock(5)
    mundo.gw.agregar_al_carrito(v.id_variante, 2)

    def explota(*a, **k):
        raise RuntimeError("MySQL se cayó")

    original = mundo.nucleo.sql.crear_pedido
    mundo.nucleo.sql.crear_pedido = explota
    try:
        with pytest.raises(Exception):
            mundo.gw.checkout(DIRECCION, "TARJETA")
    finally:
        mundo.nucleo.sql.crear_pedido = original
    assert stock_actual(mundo, v) == v.cantidad_stock  # compensación


def test_pago_rechazado_cancela_y_libera(mundo):
    mundo.nucleo.pasarela = PasarelaSimulada(rechazar_si=lambda *a: True)
    mundo.entrar("comprador@demo.com")
    _, v = mundo.variante_con_stock(5)
    mundo.gw.agregar_al_carrito(v.id_variante, 2)
    with pytest.raises(ErrorPago):
        mundo.gw.checkout(DIRECCION, "TARJETA")
    pedido = mundo.gw.listar_mis_pedidos().items[0]
    assert pedido.estatus == "CANCELADO"
    assert stock_actual(mundo, v) == v.cantidad_stock
    mundo.entrar("admin@demo.com")
    pagos = [p for p in recorrer(lambda c, l: mundo.gw.listar_pagos(c, l)) if p.id_pedido == pedido.id_pedido]
    assert [p.estatus for p in pagos] == ["RECHAZADO"]


def test_dos_compradores_por_la_ultima_pieza(mundo):
    """Concurrencia real: solo uno puede quedarse con la única unidad."""
    if mundo.tipo == "api":
        pytest.skip("la API falsa comparte una sola sesión")
    _, v = mundo.variante_con_stock(5)
    mundo.cat.actualizar_variante(v.id_variante, cantidad_stock=1)
    gws = []
    for correo in ("comprador@demo.com", "comprador2@demo.com"):
        g = GatewayDirecto(mundo.cat, mundo.nucleo.sql, bcrypt_rounds=4)
        g.login(correo, "Compra1234")
        g.agregar_al_carrito(v.id_variante, 1)
        gws.append(g)
    resultados: list = []
    barrera = threading.Barrier(2)

    def correr(g):
        barrera.wait()
        try:
            resultados.append(g.checkout(DIRECCION, "TARJETA"))
        except ErrorStock as exc:
            resultados.append(exc)

    hilos = [threading.Thread(target=correr, args=(g,)) for g in gws]
    [h.start() for h in hilos]
    [h.join() for h in hilos]
    ganadores = [r for r in resultados if not isinstance(r, Exception)]
    assert len(ganadores) == 1 and len(resultados) == 2
    assert stock_actual(mundo, v) == 0


# --------------------------------------------------------------------------- pedidos
def test_cancelar_reembolsa_y_devuelve_stock_una_sola_vez(mundo):
    _, v = mundo.variante_con_stock(5)
    pedido = comprar(mundo, v, 2)
    assert stock_actual(mundo, v) == v.cantidad_stock - 2
    cancelado = mundo.gw.cambiar_estatus_pedido(pedido.id_pedido, "CANCELADO")
    assert cancelado.estatus == "CANCELADO" and [p.estatus for p in cancelado.pagos] == ["REEMBOLSADO"]
    assert stock_actual(mundo, v) == v.cantidad_stock
    with pytest.raises(ErrorConflicto):
        mundo.gw.cambiar_estatus_pedido(pedido.id_pedido, "CANCELADO")
    assert stock_actual(mundo, v) == v.cantidad_stock  # no se devolvió dos veces


def test_maquina_de_estados_y_permisos(mundo):
    p, v = mundo.variante_con_stock(5)
    dueno = correo_de(mundo, p.id_vendedor)
    otro = next(c.correo for c in CUENTAS_DEMO if c.rol == "VENDEDOR" and c.correo != dueno)
    pedido = comprar(mundo, v)
    gw = mundo.gw
    with pytest.raises(ErrorPermiso):
        gw.cambiar_estatus_pedido(pedido.id_pedido, "ENVIADO")        # el comprador no envía
    mundo.entrar(otro)
    with pytest.raises(ErrorPermiso):
        gw.cambiar_estatus_pedido(pedido.id_pedido, "ENVIADO")        # ni un vendedor ajeno
    mundo.entrar(dueno)
    with pytest.raises(ErrorConflicto):
        gw.cambiar_estatus_pedido(pedido.id_pedido, "ENTREGADO")      # no se puede saltar PAGADO→ENTREGADO
    assert gw.cambiar_estatus_pedido(pedido.id_pedido, "ENVIADO").estatus == "ENVIADO"
    with pytest.raises(ErrorPermiso):
        gw.cambiar_estatus_pedido(pedido.id_pedido, "ENTREGADO")      # el vendedor no confirma recepción
    mundo.entrar("comprador@demo.com")
    with pytest.raises(ErrorConflicto):
        gw.cambiar_estatus_pedido(pedido.id_pedido, "CANCELADO")      # ya enviado: no se cancela
    assert gw.cambiar_estatus_pedido(pedido.id_pedido, "ENTREGADO").estatus == "ENTREGADO"


def test_admin_ve_todos_los_pedidos_con_nombre_del_comprador(mundo):
    _, v = mundo.variante_con_stock(5)
    pedido = comprar(mundo, v)
    mundo.entrar("admin@demo.com")
    todos = recorrer(lambda c, l: mundo.gw.listar_pedidos_admin(None, c, l))
    mio = next(p for p in todos if p.id_pedido == pedido.id_pedido)
    assert mio.nombre_comprador == "Diego Ramírez"
    assert mundo.gw.listar_pedidos_admin("CANCELADO").items == []
    with pytest.raises(ErrorPermiso):
        mundo.entrar("comprador@demo.com") and mundo.gw.listar_pedidos_admin()


# --------------------------------------------------------------------------- reseñas
def test_resenas_solo_tras_recibir_el_producto(mundo):
    gw = mundo.gw
    p, v = mundo.variante_con_stock(5)
    pedido = comprar(mundo, v)
    assert not gw.elegibilidad_resena(p.id_producto).puede
    with pytest.raises(ErrorPermiso):
        gw.crear_resena(p.id_producto, 5, "Muy bueno")
    with pytest.raises(ErrorValidacion):
        gw.crear_resena(p.id_producto, 6, "fuera de rango")

    entregar(mundo, pedido, correo_de(mundo, p.id_vendedor))
    assert gw.elegibilidad_resena(p.id_producto).puede
    r = gw.crear_resena(p.id_producto, 4, "Muy bien")
    assert r.nombre_usuario == "Diego R." and r.calificacion == 4
    el = gw.elegibilidad_resena(p.id_producto)
    assert not el.puede and "Ya reseñaste" in el.motivo
    with pytest.raises(ErrorPermiso):
        gw.crear_resena(p.id_producto, 5, "otra vez")

    mundo.entrar("comprador2@demo.com")                       # quien no compró no puede reseñar
    assert not gw.elegibilidad_resena(p.id_producto).puede

    d = gw.obtener_producto(p.id_producto)
    assert d.num_resenas == 1 and d.calificacion_promedio == 4.0


def test_promedio_y_orden_de_resenas(mundo):
    p, v = mundo.variante_con_stock(5)
    for correo, nota in (("comprador@demo.com", 5), ("comprador2@demo.com", 2)):
        pedido = comprar(mundo, v, correo=correo)
        entregar(mundo, pedido, correo_de(mundo, p.id_vendedor), comprador=correo)
        mundo.gw.crear_resena(p.id_producto, nota, f"nota {nota}")
    d = mundo.gw.obtener_producto(p.id_producto)
    assert d.num_resenas == 2 and d.calificacion_promedio == 3.5
    resenas = mundo.gw.listar_resenas(p.id_producto).items
    assert [r.calificacion for r in resenas] == [2, 5]          # la más reciente primero
    summary = [x for x in recorrer(lambda c, l: mundo.gw.listar_productos(FiltroProductos(id_categoria=p.id_categoria), c, l))
               if x.id_producto == p.id_producto][0]
    assert summary.calificacion_promedio == 3.5 and summary.num_resenas == 2


# --------------------------------------------------------------------------- vendedor
def test_vendedor_publica_edita_y_pausa(mundo):
    gw = mundo.gw
    mundo.entrar("vendedor1@demo.com")
    cat = "cat_camisas"
    datos = DatosProducto("Camisa Prueba Azul", cat, "Descripción de prueba", "MarcaX", "ACTIVO", [
        DatosVariante("tst-001", Decimal("199.90"), 10, {"Talla": "M"}),
        DatosVariante("TST-002", Decimal("249.90"), 5, {"Talla": "G"})])
    p = gw.guardar_producto(datos)
    assert {v.sku for v in p.variantes} == {"TST-001", "TST-002"}      # SKU se guarda en mayúsculas
    assert p.precio_desde == Decimal("199.90") and p.nombre_vendedor == "Carlos M."

    # SKU repetido en otro producto → error y NO queda un producto a medias
    with pytest.raises(ErrorConflicto):
        gw.guardar_producto(DatosProducto("Producto Fallido", cat, "", "", "ACTIVO", [
            DatosVariante("ZZ-1", Decimal("10"), 1, {}), DatosVariante("TST-001", Decimal("10"), 1, {})]))
    mios = recorrer(lambda c, l: gw.listar_mis_productos(c, l))
    assert "Producto Fallido" not in [x.titulo for x in mios] and p.id_producto in [x.id_producto for x in mios]
    gw.guardar_producto(DatosProducto("Reintento", cat, "", "", "ACTIVO", [DatosVariante("ZZ-1", Decimal("10"), 1, {})]))  # el SKU se liberó

    # bajar precio de una variante actualiza el «desde $»
    v2 = next(v for v in p.variantes if v.sku == "TST-002")
    p2 = gw.guardar_producto(DatosProducto(p.titulo, cat, p.descripcion, p.marca, "ACTIVO", [
        DatosVariante("TST-002", Decimal("99.00"), 5, {"Talla": "G"}, "ACTIVO", v2.id_variante)]), p.id_producto)
    assert p2.precio_desde == Decimal("99.00")
    p3 = gw.guardar_producto(DatosProducto(p.titulo, cat, p.descripcion, p.marca, "ACTIVO", [
        DatosVariante("TST-002", Decimal("99.00"), 5, {"Talla": "G"}, "INACTIVO", v2.id_variante)]), p.id_producto)
    assert p3.precio_desde == Decimal("199.90")

    # visible para compradores…
    mundo.entrar("comprador@demo.com")
    visibles = recorrer(lambda c, l: gw.listar_productos(FiltroProductos(q="camisa prueba"), c, l))
    assert p.id_producto in [x.id_producto for x in visibles]
    assert [v.sku for v in gw.obtener_producto(p.id_producto).variantes] == ["TST-001"]   # la inactiva no se ofrece

    # …hasta que el vendedor lo pausa
    mundo.entrar("vendedor1@demo.com")
    gw.guardar_producto(DatosProducto(p.titulo, cat, p.descripcion, p.marca, "INACTIVO", []), p.id_producto)
    mundo.entrar("comprador@demo.com")
    assert p.id_producto not in [x.id_producto for x in recorrer(lambda c, l: gw.listar_productos(FiltroProductos(q="camisa prueba"), c, l))]
    with pytest.raises(ErrorNoEncontrado):
        gw.obtener_producto(p.id_producto)


def test_permisos_de_vendedor(mundo):
    gw = mundo.gw
    _, _ = mundo.variante_con_stock(1)
    mundo.entrar("vendedor1@demo.com")
    p = gw.guardar_producto(DatosProducto("Mío", "cat_camisas", "", "", "ACTIVO", [DatosVariante("MIO-1", Decimal("10"), 1, {})]))
    mundo.entrar("vendedor2@demo.com")
    with pytest.raises(ErrorPermiso):
        gw.guardar_producto(DatosProducto("Robado", "cat_camisas", "", "", "ACTIVO", []), p.id_producto)
    mundo.entrar("comprador@demo.com")
    with pytest.raises(ErrorPermiso):
        gw.guardar_producto(DatosProducto("Nuevo", "cat_camisas", "", "", "ACTIVO", [DatosVariante("N-1", Decimal("10"), 1, {})]))
    with pytest.raises(ErrorPermiso):
        gw.listar_mis_productos()
    mundo.entrar("vendedor1@demo.com")
    with pytest.raises(ErrorValidacion):
        gw.guardar_producto(DatosProducto("Ab", "cat_camisas", "", "", "ACTIVO", [DatosVariante("N-2", Decimal("10"), 1, {})]))
    with pytest.raises(ErrorValidacion):
        gw.guardar_producto(DatosProducto("Precio malo", "cat_camisas", "", "", "ACTIVO", [DatosVariante("N-3", Decimal("0"), 1, {})]))
    with pytest.raises(ErrorValidacion):
        gw.guardar_producto(DatosProducto("Sin variantes", "cat_camisas", "", "", "ACTIVO", []))
    with pytest.raises(ErrorValidacion):
        gw.guardar_producto(DatosProducto("Categoría mala", "no-existe", "", "", "ACTIVO", [DatosVariante("N-4", Decimal("10"), 1, {})]))


# --------------------------------------------------------------------------- administración
def test_admin_usuarios(mundo):
    gw = mundo.gw
    mundo.entrar("admin@demo.com")
    assert len(recorrer(lambda c, l: gw.listar_usuarios(None, None, None, c, l), limite=3)) == len(CUENTAS_DEMO)
    assert len(gw.listar_usuarios(rol="VENDEDOR").items) == 4
    assert [u.correo for u in gw.listar_usuarios(q="valeria").items] == ["comprador2@demo.com"]
    yo = gw.sesion.usuario.id_usuario
    with pytest.raises(ErrorValidacion):
        gw.actualizar_usuario(yo, rol="COMPRADOR")
    assert gw.actualizar_usuario(mundo.vendedor_id("comprador2@demo.com"), rol="VENDEDOR").rol == "VENDEDOR"
    mundo.entrar("comprador@demo.com")
    with pytest.raises(ErrorPermiso):
        gw.listar_usuarios()


def test_admin_categorias(mundo):
    gw = mundo.gw
    mundo.entrar("admin@demo.com")
    madre = gw.guardar_categoria(Categoria("", "Mascotas", "", None, "ACTIVO"), crear=True)
    assert madre.slug == "mascotas" and madre.id_categoria
    hija = gw.guardar_categoria(Categoria("", "Perros", "", madre.id_categoria), crear=True)
    with pytest.raises(ErrorConflicto):
        gw.guardar_categoria(Categoria("", "Mascotas", "", None), crear=True)               # slug repetido
    with pytest.raises(ErrorValidacion):                                                    # ciclo
        gw.guardar_categoria(Categoria(madre.id_categoria, "Mascotas", "mascotas", hija.id_categoria), crear=False)
    renombrada = gw.guardar_categoria(Categoria(madre.id_categoria, "Mascotas y más", "mascotas", None), crear=False)
    assert renombrada.nombre == "Mascotas y más"
    assert {c.nombre for c in gw.listar_categorias()} >= {"Mascotas y más", "Perros"}
    mundo.entrar("vendedor1@demo.com")
    with pytest.raises(ErrorPermiso):
        gw.guardar_categoria(Categoria("", "Hackeada", ""), crear=True)
    p = gw.guardar_producto(DatosProducto("Croquetas Premium", hija.id_categoria, "", "", "ACTIVO",
                                          [DatosVariante("CRO-1", Decimal("350"), 4, {"Peso": "5 kg"})]))
    mundo.entrar("comprador@demo.com")
    en_cat = recorrer(lambda c, l: gw.listar_productos(FiltroProductos(id_categoria=madre.id_categoria), c, l))
    assert [x.id_producto for x in en_cat] == [p.id_producto]                               # la subcategoría cuenta


def test_estadisticas_y_conexiones(mundo):
    _, v = mundo.variante_con_stock(5)
    pedido = comprar(mundo, v, 2)
    mundo.entrar("admin@demo.com")
    est = mundo.gw.estadisticas()
    assert est.usuarios_por_rol == {"ADMIN": 1, "VENDEDOR": 4, "COMPRADOR": 2}
    assert est.pedidos_por_estatus == {"PAGADO": 1} and est.ingresos_aprobados == pedido.monto_total
    assert est.productos_aprox >= 0
    estados = mundo.gw.estado_conexiones()
    assert len(estados) >= 3 and all(e.ok for e in estados), estados
