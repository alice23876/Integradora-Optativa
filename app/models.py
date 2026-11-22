"""Modelos de dominio (independientes de dónde se guarden los datos).

Los nombres de campos siguen exactamente las 10 tablas del diseño.
Los campos calculados o "enriquecidos" (título de un producto dentro de una
línea de pedido, ruta de categorías, etc.) se rellenan en la capa de acceso
porque las tablas viven en bases de datos distintas y no hay JOIN entre ellas.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Generic, TypeVar

T = TypeVar("T")

ROLES = ("COMPRADOR", "VENDEDOR", "ADMIN")
ESTATUS_USUARIO = ("ACTIVO", "SUSPENDIDO")
ESTATUS_PRODUCTO = ("ACTIVO", "INACTIVO")
ESTATUS_PEDIDO = ("PENDIENTE", "PAGADO", "ENVIADO", "ENTREGADO", "CANCELADO")
ESTATUS_PAGO = ("APROBADO", "RECHAZADO", "REEMBOLSADO")
ESTATUS_CARRITO = ("ACTIVO", "CONVERTIDO", "ABANDONADO")
METODOS_PAGO = ("TARJETA", "TRANSFERENCIA", "PAYPAL", "OXXO")

# Máquina de estados de un pedido
TRANSICIONES_PEDIDO: dict[str, tuple[str, ...]] = {
    "PENDIENTE": ("PAGADO", "CANCELADO"),
    "PAGADO": ("ENVIADO", "CANCELADO"),
    "ENVIADO": ("ENTREGADO",),
    "ENTREGADO": (),
    "CANCELADO": (),
}


@dataclass
class Pagina(Generic[T]):
    """Una página de resultados + cursor opaco para pedir la siguiente."""

    items: list[T] = field(default_factory=list)
    siguiente: str | None = None


# --------------------------------------------------------------------------- MySQL A: usuarios y pagos
@dataclass
class Usuario:
    id_usuario: int
    correo: str
    rol: str
    nombre: str
    apellido: str
    telefono: str | None = None
    estatus: str = "ACTIVO"
    fecha_registro: datetime | None = None

    @property
    def nombre_completo(self) -> str:
        return f"{self.nombre} {self.apellido}".strip()


@dataclass
class Sesion:
    usuario: Usuario
    token: str | None = None  # solo en modo API


@dataclass
class Pago:
    id_pago: int
    id_pedido: int
    metodo_pago: str
    estatus: str
    monto: Decimal
    referencia_transaccion: str | None = None
    fecha_pago: datetime | None = None


# --------------------------------------------------------------------------- DynamoDB: catálogo
@dataclass
class Categoria:
    id_categoria: str
    nombre: str
    slug: str
    id_categoria_padre: str | None = None
    estatus: str = "ACTIVO"


@dataclass
class Variante:
    id_variante: str
    id_producto: str
    sku: str
    precio: Decimal
    cantidad_stock: int
    atributos: dict[str, str] = field(default_factory=dict)
    estatus: str = "ACTIVO"


@dataclass
class ProductoResumen:
    """Lo mínimo para pintar una tarjeta del catálogo sin consultar variantes."""

    id_producto: str
    titulo: str
    id_categoria: str
    id_vendedor: int
    marca: str = ""
    estatus: str = "ACTIVO"
    fecha_creacion: datetime | None = None
    precio_desde: Decimal | None = None       # desnormalizado: mínimo de variantes activas
    calificacion_promedio: float | None = None  # desnormalizado desde reseñas
    num_resenas: int = 0


@dataclass
class Producto(ProductoResumen):
    descripcion: str = ""
    variantes: list[Variante] = field(default_factory=list)
    ruta_categoria: list[str] = field(default_factory=list)
    nombre_vendedor: str | None = None


@dataclass
class Resena:
    id_resena: str
    id_producto: str
    id_usuario: int
    calificacion: int
    comentario: str = ""
    nombre_usuario: str = ""
    fecha_resena: datetime | None = None


@dataclass
class Elegibilidad:
    puede: bool
    motivo: str = ""


# --------------------------------------------------------------------------- MySQL B: carritos y pedidos
@dataclass
class LineaCarrito:
    id_detalle_carrito: int
    id_variante: str
    cantidad: int
    id_producto: str | None = None
    titulo: str = "(producto no disponible)"
    sku: str = ""
    atributos: dict[str, str] = field(default_factory=dict)
    precio_unitario: Decimal = Decimal("0")
    stock_disponible: int = 0
    disponible: bool = False

    @property
    def subtotal(self) -> Decimal:
        return self.precio_unitario * self.cantidad


@dataclass
class Carrito:
    id_carrito: int
    lineas: list[LineaCarrito] = field(default_factory=list)

    @property
    def total(self) -> Decimal:
        return sum((l.subtotal for l in self.lineas if l.disponible), Decimal("0"))

    @property
    def num_articulos(self) -> int:
        return sum(l.cantidad for l in self.lineas)

    @property
    def hay_problemas(self) -> bool:
        return any(not l.disponible or l.cantidad > l.stock_disponible for l in self.lineas)


@dataclass
class LineaPedido:
    id_detalle_pedido: int
    id_pedido: int
    id_variante: str
    id_vendedor: int
    precio_unitario: Decimal
    cantidad: int
    subtotal: Decimal
    id_producto: str | None = None
    titulo: str = "(producto no disponible)"
    sku: str = ""
    atributos: dict[str, str] = field(default_factory=dict)


@dataclass
class Pedido:
    id_pedido: int
    id_comprador: int
    estatus: str
    monto_total: Decimal
    direccion_envio: str
    fecha_pedido: datetime | None = None
    lineas: list[LineaPedido] = field(default_factory=list)
    pagos: list[Pago] = field(default_factory=list)
    nombre_comprador: str | None = None


@dataclass
class LineaVenta:
    id_detalle_pedido: int
    id_pedido: int
    id_variante: str
    precio_unitario: Decimal
    cantidad: int
    subtotal: Decimal
    estatus_pedido: str
    fecha_pedido: datetime | None = None
    titulo: str = "(producto no disponible)"
    sku: str = ""
    atributos: dict[str, str] = field(default_factory=dict)


# --------------------------------------------------------------------------- peticiones / utilidades
@dataclass
class FiltroProductos:
    q: str | None = None
    id_categoria: str | None = None
    en_cualquier_parte: bool = False  # False: por prefijo (índice); True: Scan con filtro (lento)


@dataclass
class DatosRegistro:
    correo: str
    password: str
    nombre: str
    apellido: str
    telefono: str | None = None
    rol: str = "COMPRADOR"


@dataclass
class DatosVariante:
    sku: str
    precio: Decimal
    cantidad_stock: int
    atributos: dict[str, str] = field(default_factory=dict)
    estatus: str = "ACTIVO"
    id_variante: str | None = None  # None → variante nueva


@dataclass
class DatosProducto:
    titulo: str
    id_categoria: str
    descripcion: str = ""
    marca: str = ""
    estatus: str = "ACTIVO"
    variantes: list[DatosVariante] = field(default_factory=list)


@dataclass
class EstadoConexion:
    nombre: str
    tipo: str
    ok: bool
    detalle: str = ""
    latencia_ms: float | None = None
    contiene: str = ""


@dataclass
class Estadisticas:
    usuarios_por_rol: dict[str, int] = field(default_factory=dict)
    pedidos_por_estatus: dict[str, int] = field(default_factory=dict)
    ingresos_aprobados: Decimal = Decimal("0")
    productos_aprox: int = 0
