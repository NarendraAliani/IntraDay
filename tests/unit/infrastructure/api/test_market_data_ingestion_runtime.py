# tests/unit/infrastructure/api/test_market_data_ingestion_runtime.py
#
# Checkpoint 41 Part 3/7: proves the scheduler-invocable market-data
# ingestion tick session-gates itself and skips honestly (never
# fabricates data) when Dhan credentials are not configured - the two
# cases fully provable WITHOUT real Dhan credentials in this
# environment. The credentials-configured path (a real fetch_quotes()
# call) is exercised via a monkeypatched fetch_quotes in a SEPARATE
# test, clearly labelled CONTRACT TEST - NOT LIVE VALIDATION.
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from intraday.domain.session.contracts import SessionStatus
from intraday.infrastructure.api.market_data_ingestion_runtime import (
    run_market_data_ingestion_tick,
)
from intraday.infrastructure.market_data_providers.dhan.client import (
    DhanQuoteFetchResult,
    DhanQuoteObservation,
)
from intraday.infrastructure.market_data_providers.dhan.instruments import observation_universe

pytestmark = pytest.mark.django_db

MARKET_HOLIDAY_INSTANT = datetime(2026, 1, 26, 6, 0, tzinfo=UTC)
MARKET_OPEN_INSTANT = datetime(2026, 1, 5, 6, 0, tzinfo=UTC)


def test_tick_skips_on_a_holiday_without_attempting_any_dhan_call() -> None:
    outcome = run_market_data_ingestion_tick(now=MARKET_HOLIDAY_INSTANT)
    assert outcome.ran is False
    assert outcome.session_status is SessionStatus.HOLIDAY
    assert "market_session_not_open" in (outcome.skipped_reason or "")


def test_tick_skips_cleanly_when_dhan_credentials_are_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deterministically forces the "not configured" branch, regardless
    of whatever DHAN_CLIENT_ID/DHAN_ACCESS_TOKEN environment values
    this particular dev/test environment happens to have set (Checkpoint
    22's own 'no fake credentials' rule means an env-level placeholder
    could exist here without being a REAL, usable credential) - this
    proves the SKIP behavior itself, not the state of any particular
    environment's env vars."""
    from intraday.application.services.provider_settings import DhanSettingsService

    monkeypatch.setattr(DhanSettingsService, "effective_credentials", lambda self: None)

    outcome = run_market_data_ingestion_tick(now=MARKET_OPEN_INSTANT)
    assert outcome.ran is False
    assert outcome.session_status is SessionStatus.OPEN
    assert outcome.skipped_reason == "credentials_not_configured"


# --- CONTRACT TEST - NOT LIVE VALIDATION ------------------------------------
#
# The following test monkeypatches fetch_quotes() to return a fixture
# shaped like Dhan's own documented quote response (never real network
# I/O, never real credentials) - it proves the ingestion pipeline
# WIRING (fetch -> persist -> aggregate -> promote) is correct, NOT
# that Dhan's real API behaves this way today. See
# docs/research/ACTIVE_SYSTEM_OPERATIONAL_BENCHMARK.md for the
# distinction this project draws between contract-tested and
# live-validated.


def test_configured_credentials_trigger_a_real_fetch_call(monkeypatch: pytest.MonkeyPatch) -> None:
    from intraday.application.services.provider_settings import DhanSettingsService

    called_with: dict[str, object] = {}

    def _fake_effective_credentials(self):  # type: ignore[no-untyped-def]
        return ("fake-client-id", "fake-access-token")

    def _fake_fetch_quotes(*, client_id, access_token, instruments):  # type: ignore[no-untyped-def]
        called_with["client_id"] = client_id
        called_with["access_token"] = access_token
        called_with["instruments"] = instruments
        return DhanQuoteFetchResult(observations=(), fetched_at=MARKET_OPEN_INSTANT, latency_ms=42)

    monkeypatch.setattr(DhanSettingsService, "effective_credentials", _fake_effective_credentials)
    monkeypatch.setattr(
        "intraday.infrastructure.api.market_data_ingestion_runtime.fetch_quotes",
        _fake_fetch_quotes,
    )

    outcome = run_market_data_ingestion_tick(now=MARKET_OPEN_INSTANT)

    assert outcome.ran is True
    assert called_with["client_id"] == "fake-client-id"
    assert called_with["instruments"] == observation_universe()
    assert outcome.bars_aggregated == 0  # no observations supplied - nothing to aggregate yet
    assert outcome.positions_evaluated == 0  # no open managed positions exist yet either


def test_an_open_managed_position_is_evaluated_and_exited_within_a_scheduled_tick(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Checkpoint 44 Part 3/4 (closes POS-003): proves position
    monitoring now runs INSIDE the scheduled ingestion tick, using the
    same fetched quote prices - not only when directly called in a
    test, as Checkpoint 43 left it. CONTRACT TEST - fetch_quotes is
    monkeypatched, never a real Dhan call."""
    from decimal import Decimal

    from intraday.application.services.provider_settings import DhanSettingsService
    from intraday.domain.instrument.contracts import make_instrument_id
    from intraday.domain.order.contracts import OrderIntent, OrderType, TimeInForce
    from intraday.domain.shared_kernel.contracts import Exchange, Side
    from intraday.infrastructure.api.paper_trading_runtime import (
        get_paper_trading_service,
        reset_paper_broker_for_testing,
    )
    from intraday.infrastructure.market_data_providers.dhan.instruments import DhanInstrument
    from intraday.infrastructure.persistence.models import PaperOrderRecord
    from intraday.infrastructure.persistence.paper_ledger_repository import (
        DjangoPaperLedgerRepository,
    )
    from intraday.trading_engine.position_management.contracts import ExitPlan

    reset_paper_broker_for_testing()
    try:
        reliance = make_instrument_id(Exchange.NSE, "RELIANCE")
        trading_service = get_paper_trading_service()
        trading_service.broker.record_price(reliance, Decimal("100"), MARKET_OPEN_INSTANT)

        entry_order = OrderIntent(
            order_id="entry-1",  # type: ignore[arg-type]
            instrument_id=reliance,
            side=Side.BUY,
            quantity=Decimal("10"),
            order_type=OrderType.MARKET,
            time_in_force=TimeInForce.DAY,
            strategy_id="ema_crossover",  # type: ignore[arg-type]
            created_at=MARKET_OPEN_INSTANT,
            idempotency_key="idem-entry-1",
        )
        entry_result = trading_service.submit_order(
            entry_order,
            strategy_is_active=True,
            market_session_is_open=True,
            data_quality_is_stale=False,
            estimated_order_notional=Decimal("1000"),
            already_submitted_idempotency_keys=frozenset(),
        )
        assert entry_result.broker_report is not None
        position = trading_service.broker.get_positions()[0]

        ledger = DjangoPaperLedgerRepository()
        ledger.attach_exit_plan(
            position_id=str(position.position_id),
            strategy_id="ema_crossover",
            strategy_version="v1",
            entry_order_id="entry-1",
            exit_plan=ExitPlan(stop_loss=Decimal("95")),
            quantity=position.quantity,
            entry_price=position.average_entry_price,
        )

        def _fake_effective_credentials(self):  # type: ignore[no-untyped-def]
            return ("fake-client-id", "fake-access-token")

        def _fake_fetch_quotes(*, client_id, access_token, instruments):  # type: ignore[no-untyped-def]
            observation = DhanQuoteObservation(
                instrument=DhanInstrument(symbol="RELIANCE", security_id=1),
                last_price=Decimal("94"),  # below the 95 stop-loss
                source_timestamp=MARKET_OPEN_INSTANT,
                open=None,
                high=None,
                low=None,
                close=None,
            )
            return DhanQuoteFetchResult(
                observations=(observation,), fetched_at=MARKET_OPEN_INSTANT, latency_ms=10
            )

        monkeypatch.setattr(
            DhanSettingsService, "effective_credentials", _fake_effective_credentials
        )
        monkeypatch.setattr(
            "intraday.infrastructure.api.market_data_ingestion_runtime.fetch_quotes",
            _fake_fetch_quotes,
        )

        outcome = run_market_data_ingestion_tick(now=MARKET_OPEN_INSTANT)

        assert outcome.ran is True
        assert outcome.positions_evaluated == 1
        assert outcome.exits_triggered == 1
        assert PaperOrderRecord.objects.count() == 2  # entry + the automatic exit
    finally:
        reset_paper_broker_for_testing()


def test_tick_skips_when_the_ingestion_lock_is_already_held() -> None:
    """Checkpoint 42 Part 10: proves two overlapping ticks cannot both
    run - the second sees the lock held and skips, never runs
    concurrently."""
    from intraday.infrastructure.scheduling.distributed_lock import acquire

    with acquire("market-data-ingestion-tick"):
        outcome = run_market_data_ingestion_tick(now=MARKET_OPEN_INSTANT)

    assert outcome.ran is False
    assert outcome.skipped_reason == "lock_held_by_another_tick"
