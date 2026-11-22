"""Gateway HTTP: habla con el backend Python (el que construiremos después).

Contrato REST completo en docs/contrato_api.md. Resumen:
  · JSON en español, mismas formas que app/models.py (ver app/serialization.py)
  · Autenticación: `Authorization: Bearer <token>` devuelto por POST /auth/login
  · Listas paginadas: {"items": [...], "siguiente": "<cursor opaco>"|null}
  · Errores: HTTP 4xx/5xx con {"codigo": "...", "mensaje": "...", "detalles": [...]}
"""
from __future__ import annotations

from typing import Any

import requests

from ..errors import (CODIGOS, ErrorAutenticacion, ErrorConexion, ErrorConflicto, ErrorMarketplace,
                      ErrorNoEncontrado, ErrorPermiso, ErrorStock, ErrorValidacion)
from ..models import (Carrito, Categoria, DatosProducto, DatosRegistro, Elegibilidad, EstadoConexion,
                      Estadisticas, FiltroProductos, LineaVenta, Pago, Pagina, Pedido, Producto,
                      ProductoResumen, Resena, Sesion, Usuario)
from ..serialization import a_json, desde_dict, pagina_desde_dict
from .base import Gateway


class GatewayApi(Gateway):
    modo = "api"

    def __init__(self, base_url: str, timeout: float = 15.0, http: requests.Session | None = None):
        self.base = base_url.rstrip("/")
        self.timeout = timeout
        self._http = http or requests.Session()
        self._sesion: Sesion | None = None

    # ------------------------------------------------------------------ HTTP
    def _req(self, metodo: str, ruta: str, *, params: dict | None = None, cuerpo: Any = None) -> Any:
        headers = {"Accept": "application/json"}
        if self._sesion and self._sesion.token:
            headers["Authorization"] = f"Bearer {self._sesion.token}"
        params = {k: v for k, v in (params or {}).items() if v not in (None, "")}
        try:
            r = self._http.request(metodo, self.base + ruta, params=params or None,
                                   json=a_json(cuerpo) if cuerpo is not None else None,
                                   headers=headers, timeout=self.timeout)
        except requests.exceptions.RequestException as exc:
            raise ErrorConexion(f"No se pudo conectar con el backend en {self.base} ({exc.__class__.__name__}). "
                                "¿Está encendido el servidor?") from exc
        if r.status_code >= 400:
            raise self._error(r)
        if r.status_code == 204 or not r.content:
            return None
        try:
            return r.json()
        except ValueError as exc:
            raise ErrorConexion("El backend respondió algo que no es JSON.") from exc

    @staticmethod
    def _error(r: requests.Response) -> ErrorMarketplace:
        try:
            cuerpo = r.json()
        except ValueError:
            cuerpo = {}
        mensaje = cuerpo.get("mensaje") or cuerpo.get("detail") or ""
        if not isinstance(mensaje, str):
            mensaje = "Datos no válidos."
        detalles = cuerpo.get("detalles") or []
        clase = CODIGOS.get(cuerpo.get("codigo", ""))
        if clase is ErrorStock:
            return ErrorStock(mensaje or "Sin existencias suficientes.", detalles=detalles,
                              ids_afectados=cuerpo.get("ids_afectados") or [])
        if clase:
            return clase(mensaje or clase.__name__, detalles=detalles)
        por_estado = {401: ErrorAutenticacion, 403: ErrorPermiso, 404: ErrorNoEncontrado, 409: ErrorConflicto,
                      400: ErrorValidacion, 422: ErrorValidacion}
        if r.status_code in por_estado:
            return por_estado[r.status_code](mensaje or f"Error {r.status_code}", detalles=detalles)
        return ErrorConexion(mensaje or f"El servidor tuvo un problema (HTTP {r.status_code}).")

    # ------------------------------------------------------------------ sesión
    @property
    def sesion(self) -> Sesion | None:
        return self._sesion

    def _abrir_sesion(self, datos: dict) -> Sesion:
        self._sesion = Sesion(usuario=desde_dict(Usuario, datos["usuario"]), token=datos.get("token"))
        return self._sesion

    def login(self, correo: str, password: str) -> Sesion:
        return self._abrir_sesion(self._req("POST", "/auth/login", cuerpo={"correo": correo, "password": password}))

    def registrar(self, datos: DatosRegistro) -> Sesion:
        return self._abrir_sesion(self._req("POST", "/auth/registro", cuerpo=datos))

    def logout(self) -> None:
        try:
            if self._sesion:
                self._req("POST", "/auth/logout")
        except ErrorMarketplace:
            pass
        finally:
            self._sesion = None

    # ------------------------------------------------------------------ catálogo
    def listar_categorias(self) -> list[Categoria]:
        datos = self._req("GET", "/categorias")
        lista = datos["items"] if isinstance(datos, dict) else datos
        return [desde_dict(Categoria, d) for d in lista]

    def listar_productos(self, filtro: FiltroProductos | None = None, cursor: str | None = None,
                         limite: int = 24) -> Pagina[ProductoResumen]:
        f = filtro or FiltroProductos()
        datos = self._req("GET", "/productos", params={
            "q": f.q, "id_categoria": f.id_categoria, "en_cualquier_parte": "true" if f.en_cualquier_parte else None,
            "limite": limite, "cursor": cursor})
        return pagina_desde_dict(ProductoResumen, datos)

    def obtener_producto(self, id_producto: str) -> Producto:
        return desde_dict(Producto, self._req("GET", f"/productos/{id_producto}"))

    def listar_resenas(self, id_producto: str, cursor: str | None = None, limite: int = 10) -> Pagina[Resena]:
        return pagina_desde_dict(Resena, self._req("GET", f"/productos/{id_producto}/resenas",
                                                   params={"limite": limite, "cursor": cursor}))

    def elegibilidad_resena(self, id_producto: str) -> Elegibilidad:
        return desde_dict(Elegibilidad, self._req("GET", f"/productos/{id_producto}/elegibilidad-resena"))

    def crear_resena(self, id_producto: str, calificacion: int, comentario: str) -> Resena:
        return desde_dict(Resena, self._req("POST", f"/productos/{id_producto}/resenas",
                                            cuerpo={"calificacion": calificacion, "comentario": comentario}))

    # ------------------------------------------------------------------ carrito / pedidos
    def obtener_carrito(self) -> Carrito:
        return desde_dict(Carrito, self._req("GET", "/carrito"))

    def agregar_al_carrito(self, id_variante: str, cantidad: int) -> Carrito:
        return desde_dict(Carrito, self._req("POST", "/carrito/lineas",
                                             cuerpo={"id_variante": id_variante, "cantidad": cantidad}))

    def cambiar_cantidad(self, id_detalle_carrito: int, cantidad: int) -> Carrito:
        return desde_dict(Carrito, self._req("PATCH", f"/carrito/lineas/{id_detalle_carrito}",
                                             cuerpo={"cantidad": cantidad}))

    def quitar_del_carrito(self, id_detalle_carrito: int) -> Carrito:
        return desde_dict(Carrito, self._req("DELETE", f"/carrito/lineas/{id_detalle_carrito}"))

    def checkout(self, direccion_envio: str, metodo_pago: str) -> Pedido:
        return desde_dict(Pedido, self._req("POST", "/checkout",
                                            cuerpo={"direccion_envio": direccion_envio, "metodo_pago": metodo_pago}))

    def listar_mis_pedidos(self, cursor: str | None = None, limite: int = 20) -> Pagina[Pedido]:
        return pagina_desde_dict(Pedido, self._req("GET", "/pedidos", params={"limite": limite, "cursor": cursor}))

    def obtener_pedido(self, id_pedido: int) -> Pedido:
        return desde_dict(Pedido, self._req("GET", f"/pedidos/{id_pedido}"))

    def cambiar_estatus_pedido(self, id_pedido: int, nuevo_estatus: str) -> Pedido:
        return desde_dict(Pedido, self._req("POST", f"/pedidos/{id_pedido}/estatus", cuerpo={"estatus": nuevo_estatus}))

    # ------------------------------------------------------------------ vendedor
    def listar_mis_productos(self, cursor: str | None = None, limite: int = 30) -> Pagina[ProductoResumen]:
        return pagina_desde_dict(ProductoResumen, self._req("GET", "/vendedor/productos",
                                                            params={"limite": limite, "cursor": cursor}))

    def guardar_producto(self, datos: DatosProducto, id_producto: str | None = None) -> Producto:
        if id_producto is None:
            return desde_dict(Producto, self._req("POST", "/vendedor/productos", cuerpo=datos))
        return desde_dict(Producto, self._req("PUT", f"/vendedor/productos/{id_producto}", cuerpo=datos))

    def listar_mis_ventas(self, cursor: str | None = None, limite: int = 30) -> Pagina[LineaVenta]:
        return pagina_desde_dict(LineaVenta, self._req("GET", "/vendedor/ventas",
                                                       params={"limite": limite, "cursor": cursor}))

    # ------------------------------------------------------------------ administración
    def listar_usuarios(self, rol=None, estatus=None, q=None, cursor=None, limite=30) -> Pagina[Usuario]:
        return pagina_desde_dict(Usuario, self._req("GET", "/admin/usuarios", params={
            "rol": rol, "estatus": estatus, "q": q, "limite": limite, "cursor": cursor}))

    def actualizar_usuario(self, id_usuario: int, rol: str | None = None, estatus: str | None = None) -> Usuario:
        return desde_dict(Usuario, self._req("PATCH", f"/admin/usuarios/{id_usuario}",
                                             cuerpo={"rol": rol, "estatus": estatus}))

    def guardar_categoria(self, categoria: Categoria, *, crear: bool) -> Categoria:
        if crear:
            return desde_dict(Categoria, self._req("POST", "/admin/categorias", cuerpo=categoria))
        return desde_dict(Categoria, self._req("PUT", f"/admin/categorias/{categoria.id_categoria}", cuerpo=categoria))

    def listar_pedidos_admin(self, estatus=None, cursor=None, limite=30) -> Pagina[Pedido]:
        return pagina_desde_dict(Pedido, self._req("GET", "/admin/pedidos", params={
            "estatus": estatus, "limite": limite, "cursor": cursor}))

    def listar_pagos(self, cursor=None, limite=30) -> Pagina[Pago]:
        return pagina_desde_dict(Pago, self._req("GET", "/admin/pagos", params={"limite": limite, "cursor": cursor}))

    def estadisticas(self) -> Estadisticas:
        return desde_dict(Estadisticas, self._req("GET", "/admin/estadisticas"))

    # ------------------------------------------------------------------ diagnóstico
    def estado_conexiones(self) -> list[EstadoConexion]:
        try:
            datos = self._req("GET", "/salud")
            lista = datos["items"] if isinstance(datos, dict) else datos
            return [EstadoConexion(nombre="Backend API", tipo="HTTP", ok=True, detalle=self.base)] + \
                   [desde_dict(EstadoConexion, d) for d in lista]
        except ErrorMarketplace as exc:
            return [EstadoConexion(nombre="Backend API", tipo="HTTP", ok=False, detalle=str(exc))]
