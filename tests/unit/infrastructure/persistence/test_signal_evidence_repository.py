# tests/unit/infrastructure/persistence/test_signal_evidence_repository.py
#
# Checkpoint 64.18 §10/§11: real-Postgres coverage for
# `DjangoSignalEvidenceRepository` - mirrors `test_trade_plan_repository`'s
# own established pattern.
from __future__ import annotations

import pytest

from intraday.infrastructure.persistence.signal_evidence_repository import (
    DjangoSignalEvidenceRepository,
)
from intraday.trading_engine.strategy_execution.evidence import SignalEvidence, SignalEvidenceField
from tests.postgres_utils import requires_postgres


def _evidence(**overrides: object) -> SignalEvidence:
    defaults: dict[str, object] = {
        "schema_version": "1",
        "strategy_id": "ema_crossover",
        "fields": (
            SignalEvidenceField(label="Fast EMA", value="1234.50"),
            SignalEvidenceField(label="Slow EMA", value="1229.40"),
            SignalEvidenceField(label="Crossover", value="Bullish"),
        ),
    }
    defaults.update(overrides)
    return SignalEvidence(**defaults)  # type: ignore[arg-type]


@requires_postgres
@pytest.mark.django_db
def test_save_and_get_round_trips_fields_in_order() -> None:
    repo = DjangoSignalEvidenceRepository()

    repo.save("sig-1", _evidence())
    record = repo.get_by_signal_id("sig-1")

    assert record is not None
    assert record.signal_id == "sig-1"
    assert record.strategy_id == "ema_crossover"
    assert record.schema_version == "1"
    # Checkpoint 64.81: fields are now `SignalEvidenceFieldView`s
    # carrying canonical identity. `label`/`value` and their ORDER are
    # asserted exactly as before - the identity is additive.
    assert [(f.label, f.value) for f in record.fields] == [
        ("Fast EMA", "1234.50"),
        ("Slow EMA", "1229.40"),
        ("Crossover", "Bullish"),
    ]
    # This fixture builds fields with no `feature_name`, so no identity
    # is invented for them.
    assert all(f.feature_name is None and f.field_id is None for f in record.fields)


@requires_postgres
@pytest.mark.django_db
def test_get_by_signal_id_returns_none_when_no_evidence_persisted() -> None:
    assert DjangoSignalEvidenceRepository().get_by_signal_id("no-such-signal") is None


@requires_postgres
@pytest.mark.django_db
def test_save_is_idempotent_one_signal_one_evidence_record() -> None:
    """§10: one signal_id -> one evidence record - a second save() for
    the same signal_id must never create a duplicate row."""
    from intraday.infrastructure.persistence.models import SignalEvidenceRecord

    repo = DjangoSignalEvidenceRepository()
    repo.save("sig-1", _evidence())
    repo.save("sig-1", _evidence(strategy_id="ema_crossover"))

    assert SignalEvidenceRecord.objects.filter(signal_id="sig-1").count() == 1


@requires_postgres
@pytest.mark.django_db
def test_evidence_for_different_strategies_persists_independently() -> None:
    repo = DjangoSignalEvidenceRepository()
    ema_evidence = _evidence(strategy_id="ema_crossover")
    atr_evidence = _evidence(
        strategy_id="atr_volatility_breakout",
        fields=(
            SignalEvidenceField(label="ATR", value="12.5"),
            SignalEvidenceField(label="Breakout", value="Bearish"),
        ),
    )

    repo.save("sig-ema", ema_evidence)
    repo.save("sig-atr", atr_evidence)

    ema_record = repo.get_by_signal_id("sig-ema")
    atr_record = repo.get_by_signal_id("sig-atr")
    assert ema_record is not None and atr_record is not None
    assert ema_record.strategy_id == "ema_crossover"
    assert atr_record.strategy_id == "atr_volatility_breakout"
    assert [(f.label, f.value) for f in atr_record.fields] == [
        ("ATR", "12.5"),
        ("Breakout", "Bearish"),
    ]
