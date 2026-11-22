"""Contrato único entre la interfaz y los datos.

La UI SOLO conoce esta clase. Hay tres implementaciones intercambiables:

  GatewayDirecto  → DynamoDB + 2 MySQL directamente (desarrollo / herramienta interna)
  GatewayApi      → tu backend Python por HTTP (producción)
  GatewayDirecto con almacenes en memoria → modo demo

Cuando exista el backend, la UI no cambia: basta con poner MKT_MODO=api.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import (Carrito, Categoria, DatosProducto, DatosRegistro, Elegibilidad, EstadoConexion,
                      Estadisticas, FiltroProductos, LineaVenta, Pago, Pagina, Pedido, Producto,
                      ProductoResumen, Resena, Sesion, Usuario)


class Gateway(ABC):
    modo: str = ""

    # ----------------------------------------------------------------- sesión
    @property
    @abstractmethod
    def sesion(self) -> Sesion | None: ...

    @abstractmethod
    def login(self, correo: str, password: str) -> Sesion: ...

    @abstractmethod
    def registrar(self, datos: DatosRegistro) -> Sesion: ...

    @abstractmethod
    def logout(self) -> None: ...

    # ----------------------------------------------------------------- catálogo (DynamoDB)
    @abstractmethod
    def listar_categorias(self) -> list[Categoria]: ...

    @abstractmethod
    def listar_productos(self, filtro: FiltroProductos | None = None, cursor: str | None = None,
                         limite: int = 24) -> Pagina[ProductoResumen]: ...

    @abstractmethod
    def obtener_producto(self, id_producto: str) -> Producto: ...

    @abstractmethod
    def listar_resenas(self, id_producto: str, cursor: str | None = None, limite: int = 10) -> Pagina[Resena]: ...

    @abstractmethod
    def elegibilidad_resena(self, id_producto: str) -> Elegibilidad: ...

    @abstractmethod
    def crear_resena(self, id_producto: str, calificacion: int, comentario: str) -> Resena: ...

    # ----------------------------------------------------------------- carrito y pedidos (MySQL B + DynamoDB)
    @abstractmethod
    def obtener_carrito(self) -> Carrito: ...

    @abstractmethod
    def agregar_al_carrito(self, id_variante: str, cantidad: int) -> Carrito: ...

    @abstractmethod
    def cambiar_cantidad(self, id_detalle_carrito: int, cantidad: int) -> Carrito: ...

    @abstractmethod
    def quitar_del_carrito(self, id_detalle_carrito: int) -> Carrito: ...

    @abstractmethod
    def checkout(self, direccion_envio: str, metodo_pago: str) -> Pedido: ...

    @abstractmethod
    def listar_mis_pedidos(self, cursor: str | None = None, limite: int = 20) -> Pagina[Pedido]: ...

    @abstractmethod
    def obtener_pedido(self, id_pedido: int) -> Pedido: ...

    @abstractmethod
    def cambiar_estatus_pedido(self, id_pedido: int, nuevo_estatus: str) -> Pedido: ...

    # ----------------------------------------------------------------- vendedor
    @abstractmethod
    def listar_mis_productos(self, cursor: str | None = None, limite: int = 30) -> Pagina[ProductoResumen]: ...

    @abstractmethod
    def guardar_producto(self, datos: DatosProducto, id_producto: str | None = None) -> Producto: ...

    @abstractmethod
    def listar_mis_ventas(self, cursor: str | None = None, limite: int = 30) -> Pagina[LineaVenta]: ...

    # ----------------------------------------------------------------- administración
    @abstractmethod
    def listar_usuarios(self, rol: str | None = None, estatus: str | None = None, q: str | None = None,
                        cursor: str | None = None, limite: int = 30) -> Pagina[Usuario]: ...

    @abstractmethod
    def actualizar_usuario(self, id_usuario: int, rol: str | None = None, estatus: str | None = None) -> Usuario: ...

    @abstractmethod
    def guardar_categoria(self, categoria: Categoria, *, crear: bool) -> Categoria: ...

    @abstractmethod
    def listar_pedidos_admin(self, estatus: str | None = None, cursor: str | None = None,
                             limite: int = 30) -> Pagina[Pedido]: ...

    @abstractmethod
    def listar_pagos(self, cursor: str | None = None, limite: int = 30) -> Pagina[Pago]: ...

    @abstractmethod
    def estadisticas(self) -> Estadisticas: ...

    # ----------------------------------------------------------------- diagnóstico
    @abstractmethod
    def estado_conexiones(self) -> list[EstadoConexion]: ...
