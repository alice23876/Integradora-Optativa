"""Errores de dominio.

Todas las capas (DynamoDB, MySQL, API HTTP) traducen sus fallos a estas
excepciones, de modo que la interfaz solo necesita conocer un conjunto
pequeño y mostrar mensajes claros al usuario.
"""
from __future__ import annotations


class ErrorMarketplace(Exception):
    """Base de todos los errores controlados de la aplicación."""

    codigo = "error"

    def __init__(self, mensaje: str = "", *, detalles: list[str] | None = None):
        super().__init__(mensaje)
        self.mensaje = mensaje or self.__class__.__name__
        self.detalles = list(detalles or [])

    def __str__(self) -> str:
        return self.mensaje


class ErrorConexion(ErrorMarketplace):
    """No se pudo hablar con DynamoDB, MySQL o el backend."""

    codigo = "conexion"


class ErrorAutenticacion(ErrorMarketplace):
    codigo = "autenticacion"


class ErrorPermiso(ErrorMarketplace):
    codigo = "permiso"


class ErrorNoEncontrado(ErrorMarketplace):
    codigo = "no_encontrado"


class ErrorValidacion(ErrorMarketplace):
    codigo = "validacion"


class ErrorConflicto(ErrorMarketplace):
    """Duplicados (correo, SKU, reseña repetida) o estados incompatibles."""

    codigo = "conflicto"


class ErrorStock(ErrorMarketplace):
    codigo = "stock_insuficiente"

    def __init__(self, mensaje: str = "", *, detalles: list[str] | None = None,
                 ids_afectados: list[str] | None = None):
        super().__init__(mensaje, detalles=detalles)
        self.ids_afectados = list(ids_afectados or [])


class ErrorPago(ErrorMarketplace):
    codigo = "pago"


CODIGOS: dict[str, type[ErrorMarketplace]] = {
    c.codigo: c
    for c in (ErrorConexion, ErrorAutenticacion, ErrorPermiso, ErrorNoEncontrado,
              ErrorValidacion, ErrorConflicto, ErrorStock, ErrorPago)
}
