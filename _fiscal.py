"""
Kushki — deterministic fiscal engine.

Builds the `amount` dict that Kushki expects:
  {subtotalIva, subtotalIva0, iva, ice, currency}
"""

from __future__ import annotations

import os
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum

_TWO = Decimal("0.01")


class TipoMonto(str, Enum):
    SUBTOTAL = "subtotal"
    TOTAL_CON_IVA = "total_con_iva"


def _iva_rate() -> Decimal:
    raw = os.environ.get("IVA_EC_PERCENTAGE", "0.15")
    try:
        rate = Decimal(raw)
        if not (Decimal(0) < rate <= Decimal(1)):
            raise ValueError()
        return rate
    except Exception:
        raise ValueError(f"IVA_EC_PERCENTAGE inválido: {raw!r}.")


def _r2(v: Decimal) -> Decimal:
    return v.quantize(_TWO, rounding=ROUND_HALF_UP)


def calcular_monto_kushki(monto: float, tipo: TipoMonto, currency: str = "USD") -> dict:
    """Return the Kushki amount dict {subtotalIva, subtotalIva0, iva, ice, currency}."""
    if monto <= 0:
        raise ValueError(f"monto debe ser > 0. Recibido: {monto}")
    rate = _iva_rate()
    d = Decimal(str(monto))
    if tipo == TipoMonto.TOTAL_CON_IVA:
        total = _r2(d)
        subtotal = _r2(d / (1 + rate))
        iva = _r2(total - subtotal)
    else:
        subtotal = _r2(d)
        iva = _r2(d * rate)
    return {"subtotalIva": float(subtotal), "subtotalIva0": 0.0, "iva": float(iva), "ice": 0.0, "currency": currency}
