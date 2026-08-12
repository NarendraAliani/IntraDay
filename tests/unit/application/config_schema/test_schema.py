# tests/unit/application/config_schema/test_schema.py
#
# Unit tests for the generic schema-derivation machinery (Checkpoint 6).
from __future__ import annotations

import pytest

from intraday.application.config_schema.schema import build_schema_for
from intraday.domain.risk.contracts import RiskLimits
from intraday.domain.strategy.contracts import StrategyMaturityState


def test_schema_derives_field_names_from_domain_contract() -> None:
    schema = build_schema_for(RiskLimits)
    assert schema.contract_name == "RiskLimits"
    assert schema.field_names() == (
        "max_intraday_loss",
        "max_position_size",
        "max_per_trade_risk",
    )


def test_schema_marks_decimal_fields() -> None:
    schema = build_schema_for(RiskLimits)
    assert all(field.is_decimal for field in schema.fields)


def test_schema_marks_all_fields_required_when_no_defaults() -> None:
    schema = build_schema_for(RiskLimits)
    assert schema.required_field_names() == schema.field_names()


def test_schema_rejects_non_dataclass() -> None:
    with pytest.raises(TypeError):
        build_schema_for(StrategyMaturityState)  # an Enum, not a dataclass
