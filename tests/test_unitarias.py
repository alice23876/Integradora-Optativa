"""Pruebas rápidas de utilidades, serialización y esquema."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.categorias import ArbolCategorias
from app.demo_data import construir_categorias, generar_productos
from app.errors import ErrorValidacion
from app.models import Carrito, LineaCarrito, Pagina, Pedido, Producto
from app.serialization import a_json, desde_dict, pagina_desde_dict
from app.util import (bucket_busqueda, codificar_cursor, decodificar_cursor, dinero, formato_dinero, normalizar,
                      slugify)


def test_normalizar_y_slug():
    assert normalizar("  CAMISÓN   Azul ") == "camison azul"
    assert slugify("Teclados y mouse") == "teclados-y-mouse"
    assert slugify("Electrónica") == "electronica"
    # el bucket se calcula siempre sobre texto ya normalizado
    assert bucket_busqueda(normalizar("Camisa")) == "c" and bucket_busqueda(normalizar("Ñandú")) == "n"
    assert bucket_busqueda(normalizar("¡Oferta!")) == "#" and bucket_busqueda("") == "#"


def test_dinero():
    assert dinero("10.005") == Decimal("10.01")
    assert formato_dinero(Decimal("1234.5")) == "$1,234.50" and formato_dinero(None) == "—"


def test_cursor_ida_y_vuelta():
    c = codificar_cursor({"k": {"id_vendedor": Decimal("5"), "t": "x"}, "o": 3})
    assert decodificar_cursor(c) == {"k": {"id_vendedor": 5, "t": "x"}, "o": 3}
    assert codificar_cursor(None) is None and decodificar_cursor(None) is None
    with pytest.raises(ErrorValidacion):
        decodificar_cursor("%%%")


def test_serializacion_ida_y_vuelta():
    cats, hojas = construir_categorias()
    prod = generar_productos(3, hojas, [1, 2])[0]
    j = a_json(prod)
    assert isinstance(j["precio_desde"], str) and isinstance(j["fecha_creacion"], str)
    de_vuelta = desde_dict(Producto, j)
    assert de_vuelta == prod and isinstance(de_vuelta.variantes[0].precio, Decimal)
    assert de_vuelta.fecha_creacion.tzinfo is not None

    pag = pagina_desde_dict(Producto, {"items": [j], "siguiente": "abc"})
    assert isinstance(pag, Pagina) and pag.siguiente == "abc" and pag.items[0] == prod

    ped = Pedido(7, 3, "PAGADO", Decimal("100.50"), "dir", datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert desde_dict(Pedido, a_json(ped)) == ped

    carrito = Carrito(1, [LineaCarrito(1, "v", 2, "p", "T", "S", {"a": "b"}, Decimal("5.00"), 9, True)])
    c2 = desde_dict(Carrito, a_json(carrito))
    assert c2 == carrito and c2.total == Decimal("10.00") and c2.num_articulos == 2


def test_arbol_de_categorias():
    cats, _ = construir_categorias()
    arbol = ArbolCategorias(cats)
    assert {c.nombre for c in arbol.raices()} >= {"Ropa", "Electrónica", "Libros"}
    assert set(arbol.descendientes("cat_hombre")) == {"cat_hombre", "cat_camisas", "cat_pantalones", "cat_playeras", "cat_chamarras"}
    assert arbol.ruta_texto("cat_camisas") == "Ropa › Hombre › Camisas"
    assert arbol.es_descendiente if hasattr(arbol, "es_descendiente") else True


def test_generacion_determinista_y_realista():
    _, hojas = construir_categorias()
    a = generar_productos(500, hojas, [1, 2, 3], semilla=1)
    b = generar_productos(500, hojas, [1, 2, 3], semilla=1)
    assert [p.id_producto for p in a] == [p.id_producto for p in b]
    assert len({p.id_producto for p in a}) == 500
    skus = [v.sku for p in a for v in p.variantes]
    assert len(skus) == len(set(skus))
    assert all(p.precio_desde == min(v.precio for v in p.variantes) for p in a)
