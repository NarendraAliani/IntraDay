# tests/unit/infrastructure/persistence/test_trade_plan_repository.py
#
# Checkpoint 64.7: real-Postgres coverage for the ONE persisted copy of
# a strategy-produced TradePlan.
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from intraday.infrastructure.persistence.trade_plan_repository import DjangoTradePlanRepository
from intraday.trading_engine.strategy_execution.contracts import TradePlan
from tests.postgres_utils import requires_postgres


def _plan(**overrides: object) -> TradePlan:
    base = {
        "strategy_id": "atr_volatility_breakout",
        "code_version": "v1",
        "generated_at": datetime(2026, 8, 19, 10, 0, tzinfo=UTC),
        "calculation_method": "ATR(14) volatility-based",
        "entry_price": Decimal("100.00"),
        "stop_loss": Decimal("98.00"),
        "target_1": Decimal("103.00"),
        "target_2": Decimal("105.00"),
        "target_3": Decimal("108.00"),
        "trailing_stop_loss": Decimal("99.00"),
    }
    base.update(overrides)
    return TradePlan(**base)  # type: ignore[arg-type]


@requires_postgres
@pytest.mark.django_db
def test_save_and_get_by_signal_id_round_trips_every_field() -> None:
    repository = DjangoTradePlanRepository()
    plan = _plan()

    saved = repository.save("SIG-1", plan)
    assert saved.signal_id == "SIG-1"
    assert saved.entry_price == Decimal("100.00")
    assert saved.stop_loss == Decimal("98.00")
    assert saved.target_1 == Decimal("103.00")
    assert saved.target_2 == Decimal("105.00")
    assert saved.target_3 == Decimal("108.00")
    assert saved.trailing_stop_loss == Decimal("99.00")
    assert saved.calculation_method == "ATR(14) volatility-based"

    fetched = repository.get_by_signal_id("SIG-1")
    assert fetched is not None
    assert fetched.entry_price == plan.entry_price
    assert fetched.target_3 == plan.target_3


@requires_postgres
@pytest.mark.django_db
def test_get_by_signal_id_returns_none_when_no_plan_exists() -> None:
    repository = DjangoTradePlanRepository()
    assert repository.get_by_signal_id("does-not-exist") is None


@requires_postgres
@pytest.mark.django_db
def test_a_partial_plan_persists_only_the_fields_it_actually_has() -> None:
    """A strategy may produce only some levels - the repository must
    never fabricate the missing ones as zero or any other placeholder."""
    repository = DjangoTradePlanRepository()
    plan = _plan(target_2=None, target_3=None, trailing_stop_loss=None)

    saved = repository.save("SIG-2", plan)
    assert saved.target_1 is not None
    assert saved.target_2 is None
    assert saved.target_3 is None
    assert saved.trailing_stop_loss is None


@requires_postgres
@pytest.mark.django_db
def test_save_is_idempotent_per_signal_id() -> None:
    """Re-saving the same signal_id updates the one row rather than
    creating a duplicate - matches this project's `update_or_create`
    convention used elsewhere (e.g. WorkerRuntimeStatus)."""
    repository = DjangoTradePlanRepository()
    repository.save("SIG-3", _plan(entry_price=Decimal("100.00")))
    repository.save("SIG-3", _plan(entry_price=Decimal("101.00")))

    fetched = repository.get_by_signal_id("SIG-3")
    assert fetched is not None
    assert fetched.entry_price == Decimal("101.00")

    from intraday.infrastructure.persistence.models import TradePlanRecord

    assert TradePlanRecord.objects.filter(signal_id="SIG-3").count() == 1
