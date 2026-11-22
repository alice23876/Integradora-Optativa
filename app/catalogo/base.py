"""Contrato del catálogo (las 4 tablas de DynamoDB).

Implementaciones:
  * CatalogoDynamo  → DynamoDB real (o DynamoDB Local / moto en pruebas)
  * CatalogoMemoria → mismo comportamiento en memoria (modo demo)

Patrones de acceso soportados (y por qué DynamoDB puede con 17,000+ productos):
  ┌────────────────────────────────┬─────────────────────────────────────────┐
  │ Pantalla                       │ Operación DynamoDB                      │
  ├────────────────────────────────┼─────────────────────────────────────────┤
  │ Explorar todo (feed)           │ Scan con Limit=24 (paginado, barato)    │
  │ Categoría (y sus subcategorías)│ Query en gsi_categoria                  │
  │ Búsqueda por inicio de título  │ Query en gsi_busqueda (begins_with)     │
  │ Búsqueda "en cualquier parte"  │ Scan + filtro contains (lento, opcional)│
  │ Mis productos (vendedor)       │ Query en gsi_vendedor                   │
  │ Variantes de un producto       │ Query en gsi_producto                   │
  │ Líneas de carrito/pedido       │ BatchGetItem por id_variante            │
  │ Reseñas de un producto         │ Query por id_producto (LSI por fecha)   │
  └────────────────────────────────┴─────────────────────────────────────────┘
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable

from ..models import (Categoria, EstadoConexion, Pagina, Producto, ProductoResumen, Resena, Variante)


class CatalogoBase(ABC):
    # ---------------------------------------------------------------- categorías
    @abstractmethod
    def listar_categorias(self) -> list[Categoria]: ...

    @abstractmethod
    def guardar_categoria(self, categoria: Categoria, *, crear: bool) -> Categoria:
        """Crea o actualiza. Lanza ErrorConflicto si el slug ya existe."""

    # ---------------------------------------------------------------- productos
    @abstractmethod
    def listar_productos(self, *, ids_categoria: list[str] | None = None, q: str | None = None,
                         en_cualquier_parte: bool = False, id_vendedor: int | None = None,
                         solo_activos: bool = True, cursor: str | None = None,
                         limite: int = 24) -> Pagina[ProductoResumen]: ...

    @abstractmethod
    def obtener_producto(self, id_producto: str) -> Producto | None:
        """Incluye todas las variantes."""

    @abstractmethod
    def obtener_productos(self, ids: Iterable[str]) -> dict[str, ProductoResumen]: ...

    @abstractmethod
    def crear_producto(self, *, id_producto: str, id_vendedor: int, id_categoria: str, titulo: str,
                       descripcion: str, marca: str, estatus: str = "ACTIVO") -> Producto: ...

    @abstractmethod
    def actualizar_producto(self, id_producto: str, campos: dict) -> Producto:
        """Campos permitidos: titulo, descripcion, marca, id_categoria, estatus."""

    @abstractmethod
    def eliminar_producto_fisico(self, id_producto: str) -> None:
        """Solo para compensar una creación fallida (borra producto, variantes y bloqueos de SKU)."""

    # ---------------------------------------------------------------- variantes
    @abstractmethod
    def obtener_variantes(self, ids: Iterable[str]) -> dict[str, Variante]: ...

    @abstractmethod
    def variantes_de_producto(self, id_producto: str) -> list[Variante]: ...

    @abstractmethod
    def crear_variante(self, *, id_variante: str, id_producto: str, sku: str, precio, cantidad_stock: int,
                       atributos: dict[str, str], estatus: str = "ACTIVO") -> Variante:
        """Lanza ErrorConflicto si el SKU ya existe (único en todo el catálogo)."""

    @abstractmethod
    def actualizar_variante(self, id_variante: str, *, precio=None, cantidad_stock: int | None = None,
                            atributos: dict[str, str] | None = None, estatus: str | None = None) -> Variante: ...

    # ---------------------------------------------------------------- existencias
    @abstractmethod
    def reservar_stock(self, items: list[tuple[str, int]]) -> None:
        """Descuenta existencias de TODAS las variantes o de ninguna (atómico).
        Lanza ErrorStock(ids_afectados=[...]) si alguna no alcanza."""

    @abstractmethod
    def liberar_stock(self, items: list[tuple[str, int]]) -> None:
        """Devuelve existencias (cancelaciones / compensaciones)."""

    # ---------------------------------------------------------------- reseñas
    @abstractmethod
    def listar_resenas(self, id_producto: str, *, cursor: str | None, limite: int) -> Pagina[Resena]:
        """Más recientes primero."""

    @abstractmethod
    def obtener_resena(self, id_producto: str, id_usuario: int) -> Resena | None: ...

    @abstractmethod
    def crear_resena(self, resena: Resena) -> Resena:
        """Una reseña por usuario y producto (ErrorConflicto si ya existe).
        Actualiza el promedio desnormalizado del producto de forma atómica."""

    # ---------------------------------------------------------------- operación
    @abstractmethod
    def salud(self) -> list[EstadoConexion]: ...

    @abstractmethod
    def contar_productos_aprox(self) -> int: ...

    @abstractmethod
    def insertar_masivo(self, categorias: list[Categoria], productos: list[Producto], progreso=None) -> None:
        """Carga inicial (siembra de datos de demostración)."""
