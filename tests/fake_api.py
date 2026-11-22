"""Servidor HTTP *falso* (sin red) que expone un GatewayDirecto con el contrato REST.

Sirve para probar GatewayApi + serialización, y como especificación ejecutable de
cómo debe comportarse el backend real.
"""
from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlparse

import requests
from requests.adapters import BaseAdapter

from app.errors import (ErrorAutenticacion, ErrorConexion, ErrorConflicto, ErrorMarketplace, ErrorNoEncontrado,
                        ErrorPago, ErrorPermiso, ErrorStock, ErrorValidacion)
from app.models import Categoria, DatosProducto, DatosRegistro, FiltroProductos
from app.serialization import a_json, desde_dict

ESTADOS = {ErrorAutenticacion: 401, ErrorPermiso: 403, ErrorNoEncontrado: 404, ErrorConflicto: 409,
           ErrorValidacion: 422, ErrorStock: 409, ErrorPago: 402, ErrorConexion: 503}
PUBLICAS = {"/auth/login", "/auth/registro", "/salud"}


class FakeApi(BaseAdapter):
    def __init__(self, nucleo):
        super().__init__()
        self.n = nucleo
        self.token: str | None = None
        self.peticiones: list[tuple[str, str]] = []
        n = self.n
        i = lambda x: int(x)  # noqa: E731
        lim = lambda q, d: int(q.get("limite", d))  # noqa: E731
        self.rutas = [
            ("POST", r"/auth/login", lambda m, q, b: self._abrir(n.login(b["correo"], b["password"]))),
            ("POST", r"/auth/registro", lambda m, q, b: self._abrir(n.registrar(desde_dict(DatosRegistro, b)))),
            ("POST", r"/auth/logout", lambda m, q, b: self._cerrar()),
            ("GET", r"/categorias", lambda m, q, b: {"items": a_json(n.listar_categorias())}),
            ("GET", r"/productos", lambda m, q, b: n.listar_productos(
                FiltroProductos(q.get("q"), q.get("id_categoria"), q.get("en_cualquier_parte") == "true"),
                q.get("cursor"), lim(q, 24))),
            ("GET", r"/productos/([0-9a-f]+)", lambda m, q, b: n.obtener_producto(m[1])),
            ("GET", r"/productos/([0-9a-f]+)/resenas", lambda m, q, b: n.listar_resenas(m[1], q.get("cursor"), lim(q, 10))),
            ("POST", r"/productos/([0-9a-f]+)/resenas", lambda m, q, b: n.crear_resena(m[1], b["calificacion"], b["comentario"])),
            ("GET", r"/productos/([0-9a-f]+)/elegibilidad-resena", lambda m, q, b: n.elegibilidad_resena(m[1])),
            ("GET", r"/carrito", lambda m, q, b: n.obtener_carrito()),
            ("POST", r"/carrito/lineas", lambda m, q, b: n.agregar_al_carrito(b["id_variante"], b["cantidad"])),
            ("PATCH", r"/carrito/lineas/(\d+)", lambda m, q, b: n.cambiar_cantidad(i(m[1]), b["cantidad"])),
            ("DELETE", r"/carrito/lineas/(\d+)", lambda m, q, b: n.quitar_del_carrito(i(m[1]))),
            ("POST", r"/checkout", lambda m, q, b: n.checkout(b["direccion_envio"], b["metodo_pago"])),
            ("GET", r"/pedidos", lambda m, q, b: n.listar_mis_pedidos(q.get("cursor"), lim(q, 20))),
            ("GET", r"/pedidos/(\d+)", lambda m, q, b: n.obtener_pedido(i(m[1]))),
            ("POST", r"/pedidos/(\d+)/estatus", lambda m, q, b: n.cambiar_estatus_pedido(i(m[1]), b["estatus"])),
            ("GET", r"/vendedor/productos", lambda m, q, b: n.listar_mis_productos(q.get("cursor"), lim(q, 30))),
            ("POST", r"/vendedor/productos", lambda m, q, b: n.guardar_producto(desde_dict(DatosProducto, b))),
            ("PUT", r"/vendedor/productos/([0-9a-f]+)", lambda m, q, b: n.guardar_producto(desde_dict(DatosProducto, b), m[1])),
            ("GET", r"/vendedor/ventas", lambda m, q, b: n.listar_mis_ventas(q.get("cursor"), lim(q, 30))),
            ("GET", r"/admin/usuarios", lambda m, q, b: n.listar_usuarios(q.get("rol"), q.get("estatus"), q.get("q"), q.get("cursor"), lim(q, 30))),
            ("PATCH", r"/admin/usuarios/(\d+)", lambda m, q, b: n.actualizar_usuario(i(m[1]), b.get("rol"), b.get("estatus"))),
            ("POST", r"/admin/categorias", lambda m, q, b: n.guardar_categoria(desde_dict(Categoria, b), crear=True)),
            ("PUT", r"/admin/categorias/([\w-]+)", lambda m, q, b: n.guardar_categoria(desde_dict(Categoria, b), crear=False)),
            ("GET", r"/admin/pedidos", lambda m, q, b: n.listar_pedidos_admin(q.get("estatus"), q.get("cursor"), lim(q, 30))),
            ("GET", r"/admin/pagos", lambda m, q, b: n.listar_pagos(q.get("cursor"), lim(q, 30))),
            ("GET", r"/admin/estadisticas", lambda m, q, b: n.estadisticas()),
            ("GET", r"/salud", lambda m, q, b: {"items": a_json(n.estado_conexiones())}),
        ]

    def _abrir(self, sesion):
        self.token = f"tok-{sesion.usuario.id_usuario}"
        return {"token": self.token, "usuario": sesion.usuario}

    def _cerrar(self):
        self.n.logout()
        self.token = None
        return None

    def send(self, request, **kwargs):
        url = urlparse(request.url)
        ruta = url.path
        consulta = {k: v[0] for k, v in parse_qs(url.query).items()}
        cuerpo = json.loads(request.body) if request.body else {}
        self.peticiones.append((request.method, ruta))
        estado, payload = 200, None
        try:
            if ruta not in PUBLICAS and request.headers.get("Authorization") != f"Bearer {self.token}":
                raise ErrorAutenticacion("Tu sesión expiró. Inicia sesión de nuevo.")
            for metodo, patron, fn in self.rutas:
                m = re.fullmatch(patron, ruta)
                if m and metodo == request.method:
                    resultado = fn(m, consulta, cuerpo)
                    payload = a_json(resultado) if resultado is not None else None
                    break
            else:
                estado, payload = 404, {"codigo": "no_encontrado", "mensaje": f"Ruta desconocida {ruta}"}
        except ErrorMarketplace as exc:
            estado = ESTADOS.get(type(exc), 400)
            payload = {"codigo": exc.codigo, "mensaje": exc.mensaje, "detalles": exc.detalles}
            if isinstance(exc, ErrorStock):
                payload["ids_afectados"] = exc.ids_afectados
        resp = requests.Response()
        resp.status_code = 204 if (estado == 200 and payload is None) else estado
        resp._content = b"" if payload is None else json.dumps(payload).encode()
        resp.headers["Content-Type"] = "application/json"
        resp.url, resp.request = request.url, request
        return resp

    def close(self):  # noqa: D401
        pass
