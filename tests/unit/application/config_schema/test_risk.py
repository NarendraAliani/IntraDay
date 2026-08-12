# tests/unit/application/config_schema/test_risk.py
#
# Unit tests for the RiskLimits config loader (Checkpoint 6).
from __future__ import annotations

from decimal import Decimal

import pytest

from intraday.application.config_schema.errors import ConfigValidationError
from intraday.application.config_schema.risk import load_risk_limits


def test_valid_raw_dict_loads_into_risk_limits() -> None:
    limits = load_risk_limits(
        {
            "max_intraday_loss": "10000.00",
            "max_position_size": "50000.00",
            "max_per_trade_risk": "2000.00",
        }
    )
    assert limits.max_intraday_loss == Decimal("10000.00")


def test_missing_required_field_raises_config_validation_error() -> None:
    with pytest.raises(ConfigValidationError):
        load_risk_limits({"max_intraday_loss": "10000.00"})


def test_domain_invariant_violation_is_wrapped_as_config_validation_error() -> None:
    """A zero limit is rejected by RiskLimits.__post_init__ itself — the
    config loader must not swallow that, only wrap it with source
    context."""
    with pytest.raises(ConfigValidationError) as exc_info:
        load_risk_limits(
            {
                "max_intraday_loss": "0",
                "max_position_size": "50000.00",
                "max_per_trade_risk": "2000.00",
            },
            source="test.yaml",
        )
    assert "test.yaml" in str(exc_info.value)


def test_non_numeric_value_raises_config_validation_error() -> None:
    with pytest.raises(ConfigValidationError):
        load_risk_limits(
            {
                "max_intraday_loss": "not-a-number",
                "max_position_size": "50000.00",
                "max_per_trade_risk": "2000.00",
            }
        )
