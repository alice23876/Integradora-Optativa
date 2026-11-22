"""Datos de demostración deterministas (misma semilla ⇒ mismos productos).

Sirve para dos cosas:
  * modo demo de la app (catálogo en memoria + SQLite temporal)
  * scripts/sembrar_datos.py para poblar DynamoDB y MySQL reales con 17,000+ productos
"""
from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from itertools import product as producto_cartesiano
from typing import Callable

import bcrypt

from .models import METODOS_PAGO, Categoria, Producto, Variante
from .util import slugify, utcnow

# --------------------------------------------------------------------------- cuentas
@dataclass(frozen=True)
class CuentaDemo:
    rol: str
    correo: str
    password: str
    nombre: str
    apellido: str


CUENTAS_DEMO: tuple[CuentaDemo, ...] = (
    CuentaDemo("ADMIN", "admin@demo.com", "Admin1234", "Ana", "Administradora"),
    CuentaDemo("VENDEDOR", "vendedor1@demo.com", "Vende1234", "Carlos", "Mendoza"),
    CuentaDemo("VENDEDOR", "vendedor2@demo.com", "Vende1234", "Lucía", "Fernández"),
    CuentaDemo("VENDEDOR", "vendedor3@demo.com", "Vende1234", "Miguel", "Torres"),
    CuentaDemo("VENDEDOR", "vendedor4@demo.com", "Vende1234", "Sofía", "Herrera"),
    CuentaDemo("COMPRADOR", "comprador@demo.com", "Compra1234", "Diego", "Ramírez"),
    CuentaDemo("COMPRADOR", "comprador2@demo.com", "Compra1234", "Valeria", "Ortiz"),
)

# --------------------------------------------------------------------------- catálogo
COLORES = ["Negro", "Blanco", "Azul", "Rojo", "Verde", "Gris", "Beige", "Morado"]

PERFILES: dict[str, dict] = {
    "ropa": dict(adj=["Casual", "Clásica", "Slim Fit", "Oversize", "Premium", "Básica", "Deportiva", "Elegante", "Vintage", "Ligera"],
                 marcas=["Urbano", "Nórdica", "Casa Lino", "Trama", "Costa Azul", "Madera"],
                 attrs=[("Talla", ["CH", "M", "G", "XG"]), ("Color", COLORES)]),
    "calzado": dict(adj=["Ligero", "Urbano", "Clásico", "Resistente", "Cómodo", "Premium", "Flexible"],
                    marcas=["Paso Firme", "Ruta", "Cima", "Andar", "Vigor"],
                    attrs=[("Talla", ["24", "25", "26", "27", "28"]), ("Color", COLORES)]),
    "tecnologia": dict(adj=["Pro", "Max", "Lite", "Plus", "Ultra", "Air", "Gen 2", "X"],
                       marcas=["Nova", "Kairo", "Zenit", "Orbita", "Lumen"],
                       attrs=[("Capacidad", ["64 GB", "128 GB", "256 GB", "512 GB"]),
                              ("Color", ["Negro", "Plata", "Azul", "Grafito"])]),
    "accesorio_tec": dict(adj=["Inalámbrico", "Gamer", "Compacto", "Profesional", "Ergonómico", "Bluetooth", "USB-C"],
                          marcas=["Nova", "Kairo", "Zenit", "Orbita", "Lumen"],
                          attrs=[("Color", ["Negro", "Blanco", "Plata", "Azul"])]),
    "hogar": dict(adj=["Moderno", "Rústico", "Minimalista", "Compacto", "Resistente", "Elegante", "Práctico"],
                  marcas=["Casa Viva", "Hogarte", "Nido", "Vivace"],
                  attrs=[("Material", ["Acero", "Madera", "Cerámica", "Vidrio", "Plástico"]), ("Color", COLORES)]),
    "deporte": dict(adj=["Profesional", "Ligero", "Resistente", "Ajustable", "Antiderrapante"],
                    marcas=["Impulso", "Cima", "Ruta", "Vigor"],
                    attrs=[("Talla", ["CH", "M", "G"]), ("Color", COLORES)]),
    "juguete": dict(adj=["Educativo", "Didáctico", "Interactivo", "Armable", "Coleccionable"],
                    marcas=["Chispa", "Mundo Mini", "Brinca"],
                    attrs=[("Edad", ["3+", "6+", "8+", "12+"])]),
    "libro": dict(adj=["Ilustrado", "Esencial", "Completo", "Práctico", "Ampliado"],
                  marcas=["Editorial Faro", "Letra Viva", "Páginas del Sur"],
                  attrs=[("Formato", ["Pasta blanda", "Pasta dura", "Digital"])]),
}

# hoja = (sustantivo, perfil, precio_mín, precio_máx)
ARBOL: dict = {
    "Ropa": {
        "Hombre": {"Camisas": ("Camisa", "ropa", 249, 899), "Pantalones": ("Pantalón", "ropa", 349, 1199),
                   "Playeras": ("Playera", "ropa", 129, 449), "Chamarras": ("Chamarra", "ropa", 599, 2499)},
        "Mujer": {"Vestidos": ("Vestido", "ropa", 299, 1599), "Blusas": ("Blusa", "ropa", 199, 749),
                  "Jeans": ("Jeans", "ropa", 399, 1299), "Faldas": ("Falda", "ropa", 199, 799)},
        "Calzado": {"Tenis": ("Tenis", "calzado", 499, 2999), "Botas": ("Botas", "calzado", 699, 2599),
                    "Sandalias": ("Sandalias", "calzado", 199, 899), "Zapatos de vestir": ("Zapatos", "calzado", 599, 2199)},
    },
    "Electrónica": {
        "Celulares": ("Smartphone", "tecnologia", 2499, 24999),
        "Computadoras": {"Laptops": ("Laptop", "tecnologia", 7999, 39999),
                         "Monitores": ("Monitor", "accesorio_tec", 1999, 12999),
                         "Teclados y mouse": ("Teclado", "accesorio_tec", 199, 1999)},
        "Audio": {"Audífonos": ("Audífonos", "accesorio_tec", 199, 4999), "Bocinas": ("Bocina", "accesorio_tec", 299, 5999)},
        "TV y video": ("Pantalla", "tecnologia", 4999, 29999),
    },
    "Hogar": {
        "Cocina": {"Sartenes y ollas": ("Sartén", "hogar", 149, 1999), "Electrodomésticos": ("Licuadora", "hogar", 399, 4999)},
        "Muebles": {"Sillas": ("Silla", "hogar", 499, 3999), "Mesas": ("Mesa", "hogar", 899, 7999)},
        "Decoración": ("Lámpara", "hogar", 99, 2499),
        "Jardín": ("Maceta", "hogar", 49, 999),
    },
    "Deportes": {
        "Fitness": ("Mancuernas", "deporte", 199, 2999),
        "Ciclismo": ("Casco de ciclismo", "deporte", 299, 3499),
        "Camping": ("Casa de campaña", "deporte", 599, 5999),
    },
    "Juguetes": ("Juego de mesa", "juguete", 99, 1999),
    "Libros": ("Libro", "libro", 79, 799),
}

FRASES = [
    "Envío rápido y garantía de 30 días.", "Ideal para uso diario.",
    "Calidad comprobada y excelente relación precio-valor.", "Disponible en varias presentaciones.",
    "Diseño pensado para durar.", "Muy recomendado por nuestros clientes.",
]
COMENTARIOS = [
    "Excelente calidad, llegó antes de lo esperado.", "Cumple con lo que promete. Lo recomiendo.",
    "Buen producto por el precio, aunque el empaque podría mejorar.", "Me encantó, ya compré otro para regalar.",
    "Es justo lo que buscaba. Muy buena atención del vendedor.", "Regular: esperaba un poco más de calidad.",
]


def construir_categorias() -> tuple[list[Categoria], list[tuple[str, tuple]]]:
    """Devuelve (categorías, hojas). hojas = [(id_categoria, (sustantivo, perfil, pmin, pmax))]."""
    categorias: list[Categoria] = []
    hojas: list[tuple[str, tuple]] = []

    def visitar(nodo: dict, padre: str | None):
        for nombre, valor in nodo.items():
            id_cat = f"cat_{slugify(nombre)}"
            categorias.append(Categoria(id_cat, nombre, slugify(nombre), padre, "ACTIVO"))
            if isinstance(valor, dict):
                visitar(valor, id_cat)
            else:
                hojas.append((id_cat, valor))

    visitar(ARBOL, None)
    return categorias, hojas


def generar_productos(n: int, hojas: list[tuple[str, tuple]], ids_vendedor: list[int], semilla: int = 7) -> list[Producto]:
    rng = random.Random(semilla)
    ahora = utcnow()
    productos: list[Producto] = []
    for i in range(n):
        id_cat, (sustantivo, perfil, pmin, pmax) = hojas[rng.randrange(len(hojas))]
        cfg = PERFILES[perfil]
        adj, marca = rng.choice(cfg["adj"]), rng.choice(cfg["marcas"])
        titulo = f"{sustantivo} {adj} {marca} {rng.randint(100, 9999)}"
        id_producto = f"{rng.getrandbits(128):032x}"
        base = Decimal(rng.randint(pmin, pmax)) - Decimal("0.10")
        combinaciones = list(producto_cartesiano(*[vals for _, vals in cfg["attrs"]]))
        elegidas = rng.sample(combinaciones, min(len(combinaciones), rng.randint(1, 4)))
        variantes = []
        for j, combo in enumerate(elegidas):
            stock = 0 if rng.random() < 0.08 else rng.randint(1, 150)
            precio = (base * (Decimal("1") + Decimal("0.04") * j)).quantize(Decimal("0.01"))
            variantes.append(Variante(
                id_variante=f"{rng.getrandbits(128):032x}", id_producto=id_producto,
                sku=f"{perfil[:3].upper()}-{i + 1:06d}-{j + 1}", precio=precio, cantidad_stock=stock,
                atributos={nombre: valor for (nombre, _), valor in zip(cfg["attrs"], combo)}))
        productos.append(Producto(
            id_producto=id_producto, titulo=titulo, id_categoria=id_cat,
            id_vendedor=ids_vendedor[rng.randrange(len(ids_vendedor))], marca=marca, estatus="ACTIVO",
            fecha_creacion=ahora - timedelta(days=rng.randint(0, 400), seconds=rng.randint(0, 86_399)),
            precio_desde=min(v.precio for v in variantes),
            descripcion=f"{sustantivo} {adj.lower()} de la marca {marca}. {rng.choice(FRASES)}",
            variantes=variantes))
    return productos


# --------------------------------------------------------------------------- siembra completa
def _crear_usuarios(sql, rounds: int):
    creados = {}
    for c in CUENTAS_DEMO:
        h = bcrypt.hashpw(c.password.encode(), bcrypt.gensalt(rounds)).decode()
        try:
            creados[c.correo] = sql.crear_usuario(correo=c.correo, contrasena_hash=h, rol=c.rol,
                                                  nombre=c.nombre, apellido=c.apellido, telefono=None)
        except Exception:  # noqa: BLE001 — ya existía (resiembra): lo reutilizamos
            u, _ = sql.usuario_con_hash_por_correo(c.correo)
            creados[c.correo] = u
    return creados


def sembrar_demo(gw, n_productos: int = 17_000, progreso: Callable[[str, int, int], None] | None = None,
                 rounds: int = 4, semilla: int = 7, con_pedidos: bool = True) -> None:
    """Puebla catálogo, usuarios, pedidos, pagos y reseñas a través del gateway `gw` (GatewayDirecto)."""
    avisar = progreso or (lambda *_: None)
    avisar("Creando usuarios de demostración…", 0, 0)
    usuarios = _crear_usuarios(gw.sql, rounds)
    vendedores = [u.id_usuario for u in usuarios.values() if u.rol == "VENDEDOR"]

    avisar("Generando catálogo…", 0, n_productos)
    categorias, hojas = construir_categorias()
    productos = generar_productos(n_productos, hojas, vendedores, semilla)

    avisar("Guardando catálogo…", 0, n_productos)
    try:
        gw.catalogo.insertar_masivo(categorias, productos,
                                    progreso=lambda a, b: avisar("Guardando catálogo…", a, b))
    except TypeError:
        gw.catalogo.insertar_masivo(categorias, productos)

    if con_pedidos:
        avisar("Creando pedidos y reseñas de ejemplo…", 0, 0)
        _sembrar_pedidos(gw, productos, random.Random(semilla + 1))
    avisar("Listo", 1, 1)


def _sembrar_pedidos(gw, productos: list[Producto], rng: random.Random) -> None:
    candidatos = [p for p in productos if any(v.cantidad_stock >= 5 for v in p.variantes)]
    admin = next(c for c in CUENTAS_DEMO if c.rol == "ADMIN")
    direccion = "Av. Reforma 123, Col. Centro, Ciudad de México, C.P. 06000"
    for correo, password, n_pedidos in (("comprador@demo.com", "Compra1234", 14), ("comprador2@demo.com", "Compra1234", 7)):
        gw.login(correo, password)
        creados: list[tuple[int, str, list[str]]] = []
        for _ in range(n_pedidos):
            elegidos = rng.sample(candidatos, rng.choice([1, 1, 2, 3]))
            for p in elegidos:
                v = rng.choice([v for v in p.variantes if v.cantidad_stock >= 5])
                gw.agregar_al_carrito(v.id_variante, rng.randint(1, 2))
            pedido = gw.checkout(direccion, rng.choice(METODOS_PAGO))
            destino = rng.choices(["PAGADO", "ENVIADO", "ENTREGADO"], [2, 3, 5])[0]
            creados.append((pedido.id_pedido, destino, [p.id_producto for p in elegidos]))
        gw.logout()

        gw.login(admin.correo, admin.password)
        for id_pedido, destino, _ in creados:
            if destino in ("ENVIADO", "ENTREGADO"):
                gw.cambiar_estatus_pedido(id_pedido, "ENVIADO")
        gw.logout()

        gw.login(correo, password)
        entregados: list[str] = []
        for id_pedido, destino, ids_prod in creados:
            if destino == "ENTREGADO":
                gw.cambiar_estatus_pedido(id_pedido, "ENTREGADO")
                entregados += ids_prod
        for k, id_producto in enumerate(dict.fromkeys(entregados)):
            if k % 2 == 0:  # reseñamos la mitad: la otra mitad queda disponible para probar la pantalla
                try:
                    gw.crear_resena(id_producto, rng.choices([3, 4, 5], [1, 3, 5])[0], rng.choice(COMENTARIOS))
                except Exception:  # noqa: BLE001
                    pass
        gw.logout()
