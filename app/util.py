"""Utilidades pequeñas y sin dependencias de Qt ni de AWS."""
from __future__ import annotations

import base64
import json
import re
import unicodedata
import uuid
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from .errors import ErrorValidacion


# --------------------------------------------------------------------------- tiempo
def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def a_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def a_naive_utc(dt: datetime | None) -> datetime | None:
    """MySQL DATETIME no guarda zona horaria: guardamos siempre UTC sin tzinfo."""
    dt = a_utc(dt)
    return dt.replace(tzinfo=None) if dt else None


def a_iso(dt: datetime) -> str:
    """ISO-8601 de ancho fijo (ordenable como texto en DynamoDB)."""
    return a_utc(dt).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def de_iso(texto: str | None) -> datetime | None:
    if not texto:
        return None
    return a_utc(datetime.fromisoformat(str(texto).replace("Z", "+00:00")))


# --------------------------------------------------------------------------- ids / dinero
def nuevo_id() -> str:
    return uuid.uuid4().hex


_CENTAVOS = Decimal("0.01")


def dinero(valor: Any) -> Decimal:
    return Decimal(str(valor)).quantize(_CENTAVOS, rounding=ROUND_HALF_UP)


def formato_dinero(valor: Any) -> str:
    if valor is None:
        return "—"
    return f"${dinero(valor):,.2f}"


# --------------------------------------------------------------------------- texto
def normalizar(texto: str | None) -> str:
    """Minúsculas, sin acentos y sin espacios repetidos (clave de búsqueda)."""
    if not texto:
        return ""
    sin_acentos = "".join(
        c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
    )
    return re.sub(r"\s+", " ", sin_acentos.lower()).strip()


def bucket_busqueda(texto_normalizado: str) -> str:
    """Primer carácter alfanumérico ASCII (o '#'): reparte la clave de partición
    del índice de búsqueda en ~37 particiones en lugar de una sola."""
    c = texto_normalizado[:1]
    return c if c and c.isascii() and c.isalnum() else "#"


def slugify(texto: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", normalizar(texto)).strip("-")


# --------------------------------------------------------------------------- cursores
def _json_default(o: Any):
    if isinstance(o, Decimal):
        return int(o) if o == o.to_integral_value() else float(o)
    raise TypeError(f"No serializable: {type(o)}")


def codificar_cursor(datos: dict | None) -> str | None:
    """Cursores opacos: el cliente nunca interpreta su contenido."""
    if not datos:
        return None
    crudo = json.dumps(datos, default=_json_default, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(crudo).decode().rstrip("=")


def decodificar_cursor(cursor: str | None) -> dict | None:
    if not cursor:
        return None
    try:
        relleno = "=" * (-len(cursor) % 4)
        return json.loads(base64.urlsafe_b64decode(cursor + relleno))
    except Exception as exc:  # noqa: BLE001
        raise ErrorValidacion("El cursor de paginación no es válido.") from exc
