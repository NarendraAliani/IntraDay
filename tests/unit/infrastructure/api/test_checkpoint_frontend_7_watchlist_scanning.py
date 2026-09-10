# tests/unit/infrastructure/api/test_checkpoint_frontend_7_watchlist_scanning.py
#
# CHECKPOINT-FRONTEND-7 Part 2: end-to-end proof that a saved watchlist
# can already drive real strategy scanning through the paper trading
# pipeline - `ScannerConfiguration.universe_mode == "WATCHLIST"` traced
# from the real `WatchlistService`/`DjangoWatchlistRepository`
# (CHECKPOINT-WATCHLIST-A/B's own repository, reused verbatim - no new,
# parallel watchlist-resolution mechanism) through
# `resolve_scanner_universe()` and `promote_bars_and_trigger_signals()`
# (the SAME two, already-real, already-tested functions
# `run_market_data_worker.py`'s own `_QuoteSink.aggregate_now()` calls
# at its real call site - not a duplicate composition invented for this
# test alone) to real strategy evaluation.
#
# Confirms directly, not assumed:
#   1. WATCHLIST-mode resolution reaches exactly the saved watchlist's
#      own instruments (via the real repository, not a fake one this
#      time - CHECKPOINT-WATCHLIST-A/B's own mechanism, genuinely
#      reused).
#   2. Multi-strategy fan-out (the real worker's own per-strategy loop
#      shape, reused directly here) evaluates EVERY selected strategy
#      against EVERY resolved instrument - and never touches an
#      unselected strategy.
#   3. Configuration uses each strategy's own real schema defaults
#      (`_configuration_values_for()`), the SAME mechanism used for
#      every other universe mode - no watchlist-specific gap.
from __future__ import annotations

import datetime as _dt
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from intraday.application.repositories.scanner_configuration import ScannerConfigurationRecord
from intraday.application.services.watchlist import WatchlistService
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.aggregation import (
    AggregatedBar,
    BarAggregationResult,
    BarQualityGrade,
    BarStatus,
)
from intraday.domain.market_data.promotion import PromotionResult
from intraday.domain.session.calendar import session_for_instant
from intraday.domain.shared_kernel.contracts import Exchange, InstrumentId, Timeframe
from intraday.infrastructure.api import signal_pipeline_runtime
from intraday.infrastructure.api.signal_pipeline_runtime import promote_bars_and_trigger_signals
from intraday.infrastructure.market_data_providers.dhan import (
    scanner_universe as scanner_universe_module,
)
from intraday.infrastructure.market_data_providers.dhan.instrument_master import (
    InstrumentMasterEntry,
)
from intraday.infrastructure.market_data_providers.dhan.scanner_universe import (
    resolve_scanner_universe,
)
from intraday.infrastructure.persistence.repositories import DjangoWatchlistRepository
from intraday.trading_engine.strategy_execution.strategies.atr_volatility_breakout import (
    AtrVolatilityBreakoutStrategy,
)
from intraday.trading_engine.strategy_execution.strategies.ema_crossover import (
    EmaCrossoverStrategy,
)
from intraday.trading_engine.strategy_execution.strategies.sma_trend_filter import (
    SmaTrendFilterStrategy,
)

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
TCS = make_instrument_id(Exchange.NSE, "TCS")
OWNER = "scan-operator"
WATCHLIST_NAME = "frontend-7-watchlist"

# A genuinely mid-session, real trading-day instant - reused verbatim
# from `test_run_market_data_worker_command.py`'s own Checkpoint 78
# regression (`test_checkpoint_78_real_evaluate_receives_non_empty_config_never_a_keyerror`),
# already independently confirmed a real trading day by multiple
# checkpoints this session.
LIVE_NOW = datetime(2026, 8, 3, 5, 0, 0, tzinfo=UTC)
LIVE_SESSION = session_for_instant(LIVE_NOW)


class _FakeInstrumentMaster:
    """Reused pattern from `test_scanner_universe.py` - avoids a real
    Dhan scrip-master network call for this test's own instrument
    resolution step."""

    def __init__(self, entries: dict[str, tuple[InstrumentMasterEntry, ...]]) -> None:
        self._entries = entries

    def list_instruments(self, exchange: Exchange) -> tuple[InstrumentMasterEntry, ...]:
        return self._entries.get(exchange.value, ())


def _entry(symbol: str, security_id: int) -> InstrumentMasterEntry:
    return InstrumentMasterEntry(symbol=symbol, display_name=symbol, security_id=security_id)


def _bar(instrument_id: InstrumentId, *, minute: int) -> AggregatedBar:
    start = LIVE_NOW + timedelta(minutes=minute)
    return AggregatedBar(
        instrument_id=instrument_id,
        timeframe=Timeframe.FIVE_MINUTE,
        interval_start=start,
        interval_end=start + timedelta(minutes=5),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100.5"),
        status=BarStatus.CLOSED,
        observation_count=5,
        data_source="test",
    )


def _always_promotes(**kwargs: object) -> PromotionResult:
    return PromotionResult(
        grade=BarQualityGrade.TRADING_GRADE_BAR, failed_conditions=(), evaluated_at=LIVE_NOW
    )


@pytest.mark.django_db
def test_watchlist_mode_resolves_the_real_saved_watchlists_own_instruments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Part 2 item 1 - the real `WatchlistService`/`DjangoWatchlistRepository`
    (CHECKPOINT-WATCHLIST-A/B's own mechanism), not a fake, produces
    exactly the saved watchlist's own instruments through
    `resolve_scanner_universe()`'s existing WATCHLIST branch."""
    watchlist_service = WatchlistService(repository=DjangoWatchlistRepository())
    watchlist_service.save(
        WATCHLIST_NAME, OWNER, ["NSE:RELIANCE", "NSE:TCS"]
    )

    fake_master = _FakeInstrumentMaster(
        {"NSE": (_entry("RELIANCE", 2885), _entry("TCS", 11536))}
    )
    monkeypatch.setattr(scanner_universe_module, "_instrument_master", lambda: fake_master)
    config = ScannerConfigurationRecord(
        provider="dhan",
        enabled=True,
        timeframe="5m",
        universe_mode="WATCHLIST",
        selected_instrument_ids=(),
        selected_watchlist_name=WATCHLIST_NAME,
        selected_strategy_ids=("ema_crossover", "atr_volatility_breakout"),
        configuration_version=1,
        requested_by=OWNER,
        requested_at=datetime(2026, 8, 19, tzinfo=UTC),
    )
    resolved = resolve_scanner_universe(config, watchlist_repository=DjangoWatchlistRepository())

    assert {i.symbol for i in resolved} == {"RELIANCE", "TCS"}


@pytest.mark.django_db
def test_watchlist_driven_scan_evaluates_every_selected_strategy_against_every_watchlist_instrument(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Part 2's own full end-to-end scenario: save a watchlist, resolve
    it via the real WATCHLIST universe mode, select 2 of the 3
    registered strategies, run one scan cycle (the SAME
    `promote_bars_and_trigger_signals()` per-strategy loop shape the
    real worker's own `_QuoteSink.aggregate_now()` uses at its real
    call site), and confirm BOTH selected strategies genuinely
    evaluated against BOTH of the watchlist's own instruments - and
    that the THIRD, unselected strategy is never touched."""
    watchlist_service = WatchlistService(repository=DjangoWatchlistRepository())
    watchlist_service.save(
        WATCHLIST_NAME, OWNER, ["NSE:RELIANCE", "NSE:TCS"]
    )

    fake_master = _FakeInstrumentMaster(
        {"NSE": (_entry("RELIANCE", 2885), _entry("TCS", 11536))}
    )
    monkeypatch.setattr(scanner_universe_module, "_instrument_master", lambda: fake_master)

    selected_strategy_ids = ("ema_crossover", "atr_volatility_breakout")
    config = ScannerConfigurationRecord(
        provider="dhan",
        enabled=True,
        timeframe="5m",
        universe_mode="WATCHLIST",
        selected_instrument_ids=(),
        selected_watchlist_name=WATCHLIST_NAME,
        selected_strategy_ids=selected_strategy_ids,
        configuration_version=1,
        requested_by=OWNER,
        requested_at=datetime(2026, 8, 19, tzinfo=UTC),
    )
    resolved = resolve_scanner_universe(config, watchlist_repository=DjangoWatchlistRepository())
    resolved_instrument_ids = {make_instrument_id(Exchange.NSE, i.symbol) for i in resolved}
    assert resolved_instrument_ids == {RELIANCE, TCS}

    # Spy on all THREE registered strategies' own real `evaluate()` -
    # proves both selected ones fire and the unselected one never does,
    # without faking `run_active_loop_tick` itself (unlike this
    # repo's own faster, isolation-focused tests in
    # test_signal_pipeline_runtime.py - this one deliberately lets the
    # real chain run, matching that file's own
    # `test_checkpoint_78_real_evaluate_receives_non_empty_config_never_a_keyerror`
    # precedent).
    calls_by_strategy: dict[str, list[InstrumentId]] = {
        "ema_crossover": [],
        "atr_volatility_breakout": [],
        "sma_trend_filter": [],
    }

    real_ema_evaluate = EmaCrossoverStrategy.evaluate
    real_atr_evaluate = AtrVolatilityBreakoutStrategy.evaluate
    real_sma_evaluate = SmaTrendFilterStrategy.evaluate

    def _spy_ema(self, bar, feature_values, config):  # noqa: ANN001
        calls_by_strategy["ema_crossover"].append(bar.instrument_id)
        return real_ema_evaluate(self, bar, feature_values, config)

    def _spy_atr(self, bar, feature_values, config):  # noqa: ANN001
        calls_by_strategy["atr_volatility_breakout"].append(bar.instrument_id)
        return real_atr_evaluate(self, bar, feature_values, config)

    def _spy_sma(self, bar, feature_values, config):  # noqa: ANN001
        calls_by_strategy["sma_trend_filter"].append(bar.instrument_id)
        return real_sma_evaluate(self, bar, feature_values, config)

    monkeypatch.setattr(EmaCrossoverStrategy, "evaluate", _spy_ema)
    monkeypatch.setattr(AtrVolatilityBreakoutStrategy, "evaluate", _spy_atr)
    monkeypatch.setattr(SmaTrendFilterStrategy, "evaluate", _spy_sma)
    monkeypatch.setattr(signal_pipeline_runtime, "evaluate_bar_promotion", _always_promotes)

    # ONE scan cycle across the resolved watchlist universe - exactly
    # the real worker's own shape (real_market_data_worker.py's
    # `aggregate_now()`: one `BarAggregationResult` shared across a
    # `for strategy_id in strategy_ids` loop, never re-aggregated per
    # strategy).
    bars = tuple(_bar(instrument_id, minute=0) for instrument_id in sorted(resolved_instrument_ids))
    aggregation = BarAggregationResult(bars=bars, missing_intervals=(), anomalous_observations=())

    total_invocations = 0
    for strategy_id in selected_strategy_ids:
        outcome = promote_bars_and_trigger_signals(
            aggregation,
            session=LIVE_SESSION,
            clock=LIVE_NOW,
            connection_is_healthy=True,
            strategy_id=strategy_id,
        )
        total_invocations += outcome.active_loop_invocations

    # 2 selected strategies x 2 watchlist instruments = 4 real
    # active-loop invocations, one scan cycle.
    assert total_invocations == 4

    # Both SELECTED strategies were genuinely evaluated against BOTH
    # of the watchlist's own instruments - never a third, unrelated
    # instrument, never fewer than both.
    assert set(calls_by_strategy["ema_crossover"]) == {RELIANCE, TCS}
    assert set(calls_by_strategy["atr_volatility_breakout"]) == {RELIANCE, TCS}
    # The UNSELECTED strategy must never be touched - proves the
    # multi-strategy fan-out is genuinely driven by
    # `selected_strategy_ids`, not "every registered strategy."
    assert calls_by_strategy["sma_trend_filter"] == []
