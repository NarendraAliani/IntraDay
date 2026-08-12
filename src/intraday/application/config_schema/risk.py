# File: src/intraday/application/config_schema/risk.py
#
# Config schema and loader for domain.risk.RiskLimits (Checkpoint 6).
# Bridges raw, untyped configuration data (e.g. parsed YAML) to a
# validated domain.risk.RiskLimits instance. Coercion (string -> Decimal)
# happens here; invariant enforcement (positivity) happens exclusively
# inside RiskLimits.__post_init__ — this module never re-implements that
# check.
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from intraday.application.config_schema.errors import ConfigValidationError
from intraday.application.config_schema.schema import ConfigSchema, build_schema_for
from intraday.domain.risk.contracts import RiskLimits

RISK_LIMITS_SCHEMA: ConfigSchema = build_schema_for(RiskLimits)


def _to_decimal(raw: Any, *, field_name: str, source: str) -> Decimal:
    try:
        return Decimal(str(raw))
    except (InvalidOperation, TypeError) as exc:
        raise ConfigValidationError(source=f"{source}:{field_name}", original=exc) from exc


def load_risk_limits(raw: dict[str, Any], *, source: str = "<config>") -> RiskLimits:
    """Parse a raw config dict into a validated `RiskLimits` instance.

    `source` is a human-readable label (typically a file path) included
    in any raised `ConfigValidationError`, so a bad value is traceable
    back to exactly where it came from.
    """
    missing = [
        field.name
        for field in RISK_LIMITS_SCHEMA.fields
        if field.required and field.name not in raw
    ]
    if missing:
        raise ConfigValidationError(
            source=source,
            original=ValueError(f"missing required field(s): {', '.join(missing)}"),
        )
    try:
        return RiskLimits(
            max_intraday_loss=_to_decimal(
                raw["max_intraday_loss"], field_name="max_intraday_loss", source=source
            ),
            max_position_size=_to_decimal(
                raw["max_position_size"], field_name="max_position_size", source=source
            ),
            max_per_trade_risk=_to_decimal(
                raw["max_per_trade_risk"], field_name="max_per_trade_risk", source=source
            ),
        )
    except (ValueError, TypeError) as exc:
        raise ConfigValidationError(source=source, original=exc) from exc
