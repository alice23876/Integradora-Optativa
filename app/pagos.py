"""Pasarela de pago.

IMPORTANTE: esta aplicación NUNCA captura números de tarjeta (PCI-DSS). El cobro
real lo debe hacer el backend con una pasarela (Stripe, Conekta, Mercado Pago…).
Aquí solo existe una pasarela *simulada* para poder probar el flujo completo.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Protocol


@dataclass
class ResultadoPago:
    estatus: str  # APROBADO | RECHAZADO
    referencia: str


class Pasarela(Protocol):
    def cobrar(self, id_pedido: int, monto: Decimal, metodo: str) -> ResultadoPago: ...


class PasarelaSimulada:
    def __init__(self, rechazar_si: Callable[[int, Decimal, str], bool] | None = None):
        self._rechazar_si = rechazar_si

    def cobrar(self, id_pedido: int, monto: Decimal, metodo: str) -> ResultadoPago:
        referencia = f"SIM-{uuid.uuid4().hex[:12].upper()}"
        if self._rechazar_si and self._rechazar_si(id_pedido, monto, metodo):
            return ResultadoPago("RECHAZADO", referencia)
        return ResultadoPago("APROBADO", referencia)
