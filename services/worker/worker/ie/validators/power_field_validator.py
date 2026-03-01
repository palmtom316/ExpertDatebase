"""Validation rules for critical power-domain fields."""

from __future__ import annotations

from typing import Any


def _to_value(fields: dict[str, Any], key: str) -> float | None:
    value = fields.get(key)
    if isinstance(value, dict):
        value = value.get("value")
    try:
        if value is None:
            return None
        return float(value)
    except Exception:  # noqa: BLE001
        return None


def validate_power_fields(fields: dict[str, Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []

    voltage_kv = _to_value(fields, "voltage_kv")
    if voltage_kv is not None and (voltage_kv < 1 or voltage_kv > 1500):
        errors.append(
            {
                "field": "voltage_kv",
                "fatal": True,
                "reason": f"voltage_kv out of range: {voltage_kv}",
            }
        )

    amount_wan = _to_value(fields, "amount_wan")
    if amount_wan is not None and (amount_wan <= 0.01 or amount_wan > 100000000):
        errors.append(
            {
                "field": "amount_wan",
                "fatal": True,
                "reason": f"amount_wan out of range: {amount_wan}",
            }
        )

    return errors

