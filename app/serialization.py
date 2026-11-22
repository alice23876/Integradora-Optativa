"""Conversión modelos ⇄ JSON para el modo API.

`a_json` y `desde_dict` son simétricos: lo que el backend escriba con la misma
forma que `a_json` produce lo entiende `GatewayApi` sin código adicional.
Convenciones del contrato:
  * dinero  → texto decimal ("1234.50")  (evita errores de coma flotante)
  * fechas  → ISO-8601 en UTC
  * cursores → texto opaco
"""
from __future__ import annotations

import dataclasses
import types
import typing
from datetime import datetime
from decimal import Decimal
from typing import Any, Union, get_args, get_origin, get_type_hints

from .models import Pagina
from .util import a_utc


def a_json(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: a_json(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, Decimal):
        return format(obj, "f")
    if isinstance(obj, datetime):
        return a_utc(obj).isoformat()
    if isinstance(obj, (list, tuple, set)):
        return [a_json(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): a_json(v) for k, v in obj.items()}
    return obj


def _coercionar(tipo: Any, valor: Any) -> Any:
    if valor is None:
        return None
    origen = get_origin(tipo)
    args = get_args(tipo)
    if origen in (Union, types.UnionType):
        no_nulos = [a for a in args if a is not type(None)]
        return _coercionar(no_nulos[0], valor) if no_nulos else valor
    if origen is list:
        return [_coercionar(args[0], v) for v in valor]
    if origen is dict:
        return {str(k): _coercionar(args[1], v) if len(args) == 2 else v for k, v in valor.items()}
    if tipo is Decimal:
        return Decimal(str(valor))
    if tipo is datetime:
        return a_utc(datetime.fromisoformat(str(valor).replace("Z", "+00:00")))
    if tipo is int:
        return int(valor)
    if tipo is float:
        return float(valor)
    if tipo is str:
        return str(valor)
    if tipo is bool:
        return bool(valor)
    if dataclasses.is_dataclass(tipo):
        return desde_dict(tipo, valor)
    return valor


def desde_dict(cls: type, datos: dict[str, Any]) -> Any:
    hints = get_type_hints(cls, localns=vars(typing))
    kwargs = {}
    for f in dataclasses.fields(cls):
        if f.name in datos:
            kwargs[f.name] = _coercionar(hints[f.name], datos[f.name])
    return cls(**kwargs)


def pagina_desde_dict(cls: type, datos: dict[str, Any]) -> Pagina:
    return Pagina(items=[desde_dict(cls, d) for d in datos.get("items", [])],
                  siguiente=datos.get("siguiente"))
