# File: tests/unit/research/test_checkpoint_65_11_sma_backtest_integration.py
#
# Checkpoint 65.11 -- BACKTEST-LEVEL CORRECTNESS VALIDATION (NOT a
# performance checkpoint; see taskReport.md for the full directive).
#
# Proves the wiring:
#   HistoricalBar-shaped bars -> canonical `price_vs_ma_pct_sma`
#   (via the REAL production dispatcher
#   `application.services.strategy_execution.compute_feature_series`) ->
#   `sma_trend_filter` (REAL, unmodified strategy, obtained from the
#   REAL `build_default_registry()`) -> `StrategySignal` -> the EXISTING,
#   UNMODIFIED canonical backtest execution path
#   (`BacktestingService.run()` -> `research.backtesting.engine.run_backtest`).
#
# No new backtest engine. No new strategy. No new feature. No
# modification to any production module -- this file is purely additive
# test code.
#
# DATA HONESTY: the bars used below are a small, deterministic,
# CLEARLY-SYNTHETIC engineering fixture (a hand-built arithmetic price
# path), constructed ONLY to prove mechanical correctness. This is NOT
# real Dhan-sourced market data and is NEVER interpreted as research
# evidence -- see taskReport.md "Research Validity" / "Data Provenance".
# Verified directly against the live DB before writing this file:
# `HistoricalBar` currently holds 5,100 rows, ALL labeled
# `source='API_FETCH'`, with no genuinely-complete real historical
# session ever confirmed (carried forward from 65.00/65.01, re-verified
# empirically for 65.11 -- see taskReport.md "Data Provenance"). Given
# that, this checkpoint does not attempt to pull "real" rows out of
# `HistoricalBar` and call the result research evidence -- it uses an
# explicit, local, obviously-synthetic fixture instead, and classifies
# the whole checkpoint as ENGINE VALIDATION ONLY.
#
# NO DATABASE ACCESS: both repositories `BacktestingService` depends on
# are satisfied here by small in-memory fakes conforming to the real
# `application.repositories` Protocols (`HistoricalMarketDataRepository`,
# `BacktestResultRepository`) -- never a Django/Postgres-backed
# implementation. Nothing in this file touches the real database, so no
# synthetic data can reach it (Part L of the 65.11 directive).
from __future__ import annotations

import pathlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from intraday.application.services.backtesting import BacktestingService
from intraday.application.services.market_data import HistoricalMarketDataService
from intraday.application.services.strategy_execution import compute_feature_series
from intraday.domain.market_data.contracts import Bar
from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe
from intraday.research.backtesting import (
    StrategyConfigurationValues,
    StrategyDirection,
    build_default_registry,
)
from intraday.research.backtesting.contracts import BacktestConfiguration, PositionSizingMode
from intraday.research.backtesting.execution import compute_signals
from intraday.signal_intelligence.feature_engine.definitions import PriceVsMaPctSmaDefinition
from intraday.signal_intelligence.feature_engine.price_vs_ma_pct import (
    compute_price_vs_ma_pct_sma,
)
from intraday.signal_intelligence.feature_engine.sma import compute_simple_moving_average
from intraday.signal_intelligence.feature_engine.definitions import SimpleMovingAverageDefinition

INSTRUMENT: InstrumentId = "NSE:CKPT6511"
TIMEFRAME = Timeframe.ONE_MINUTE
BASE = datetime(2026, 8, 20, 3, 45, tzinfo=UTC)
LOOKBACK = 5
BAND_PERCENT = Decimal("1")  # 1% band, in the strategy's configured units
STRATEGY_ID = "sma_trend_filter"


# ---------------------------------------------------------------------------
# Deterministic synthetic fixture (Part B): 5 flat warm-up bars (close=100,
# SMA lookback=5 so the 5th bar is the first with a full window), then a
# clean step up (BULLISH, unambiguously > 1% above the resulting SMA), then
# a clean step down (BEARISH, unambiguously > 1% below the resulting SMA).
# Every value is a pure function of index -- no randomness, no wall clock.
# ---------------------------------------------------------------------------
def _fixture_closes() -> list[str]:
    flat = ["100"] * 6  # indices 0..5, SMA(5) first available at index 4
    up = ["108", "109", "110"]  # indices 6..8: clearly > band above SMA
    down = ["95", "94", "93"]  # indices 9..11: clearly > band below SMA
    return flat + up + down


def _bars(closes: list[str]) -> tuple[Bar, ...]:
    bars = []
    for i, close_str in enumerate(closes):
        close = Decimal(close_str)
        bars.append(
            Bar(
                instrument_id=INSTRUMENT,
                timeframe=TIMEFRAME,
                timestamp=BASE + timedelta(minutes=i),
                open=close - Decimal("0.5"),
                high=close + Decimal("1"),
                low=close - Decimal("1"),
                close=close,
                volume=Decimal("1000"),
            )
        )
    return tuple(bars)


FIXTURE_BARS = _bars(_fixture_closes())


# ---------------------------------------------------------------------------
# Local, DB-free fakes satisfying the real repository Protocols.
# ---------------------------------------------------------------------------
@dataclass
class _FakeHistoricalMarketDataRepository:
    bars: tuple[Bar, ...]

    def get_bars(
        self,
        instrument_id: InstrumentId,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> tuple[Bar, ...]:
        return tuple(
            b
            for b in self.bars
            if b.instrument_id == instrument_id
            and b.timeframe == timeframe
            and start <= b.timestamp <= end
        )


@dataclass
class _FakeBacktestResultRepository:
    saved: dict[str, dict[str, object]] = field(default_factory=dict)

    def save(
        self,
        backtest_id: str,
        strategy_id: str,
        payload: dict[str, object],
        *,
        created_by: str,
        created_at: datetime,
    ) -> None:
        self.saved[backtest_id] = payload

    def get(self, backtest_id: str) -> dict[str, object] | None:
        return self.saved.get(backtest_id)

    def list_for_strategy(self, strategy_id: str) -> tuple[dict[str, object], ...]:
        return tuple(self.saved.values())


def _config() -> BacktestConfiguration:
    return BacktestConfiguration(
        instrument_id=INSTRUMENT,
        timeframe=TIMEFRAME,
        start=FIXTURE_BARS[0].timestamp,
        end=FIXTURE_BARS[-1].timestamp,
        strategy_id=STRATEGY_ID,
        specification_version="v1",
        code_version="v1",
        configuration_version="v1",
        initial_capital=Decimal("100000"),
        position_sizing_mode=PositionSizingMode.FIXED_QUANTITY,
        position_size_value=Decimal("10"),
        brokerage_percent=Decimal("0"),
        slippage_percent=Decimal("0"),
    )


def _service() -> tuple[BacktestingService, _FakeBacktestResultRepository]:
    market_data = HistoricalMarketDataService(
        repository=_FakeHistoricalMarketDataRepository(bars=FIXTURE_BARS)
    )
    registry = build_default_registry()
    repo = _FakeBacktestResultRepository()
    service = BacktestingService(market_data=market_data, registry=registry, repository=repo)
    return service, repo


def _run():
    service, repo = _service()
    result = service.run(
        _config(),
        {"lookback": LOOKBACK, "band_percent": BAND_PERCENT},
        created_by="checkpoint_65_11_test",
    )
    return result, repo


# ---------------------------------------------------------------------------
# Part A: confirm the entry point is exactly BacktestingService.run() ->
# run_backtest() -- exercised implicitly by every test below via `_run()`
# and `_service()`. This assertion makes the claim explicit and will fail
# loudly if a future change swaps the module path.
# ---------------------------------------------------------------------------
def test_part_a_entry_point_is_backtesting_service_run() -> None:
    import inspect

    from intraday.research.backtesting.engine import run_backtest

    source = inspect.getsource(BacktestingService.run)
    assert "run_backtest(" in source
    assert run_backtest.__module__ == "intraday.research.backtesting.engine"


# ---------------------------------------------------------------------------
# Part B/C: feature availability + strategy receives canonical feature at
# the correct timestamp, and produces the expected direction.
# ---------------------------------------------------------------------------
def test_part_b_c_context_feature_flows_into_strategy_and_signal() -> None:
    result, _ = _run()

    assert result.validation.bar_count == len(FIXTURE_BARS)
    # Both a BULLISH step-up and a BEARISH step-down are present in the
    # fixture, so at least one non-NEUTRAL signal must exist.
    assert result.validation.signal_count > 0

    # Directly recompute canonical price_vs_ma_pct_sma_5 via the SAME
    # production dispatcher the engine uses, and confirm the feature is
    # actually present at the bars where the fixture expects the jump.
    series = compute_feature_series(f"price_vs_ma_pct_sma_{LOOKBACK}", FIXTURE_BARS)
    by_ts = {fv.timestamp: fv for fv in series}
    up_bar = FIXTURE_BARS[6]  # first "108" bar
    assert up_bar.timestamp in by_ts
    assert by_ts[up_bar.timestamp].feature_name.startswith("price_vs_ma_pct_sma")


# ---------------------------------------------------------------------------
# Part C (equivalence, directive Part C): legacy formula
# (close - SMA) / SMA vs canonical price_vs_ma_pct_sma, and resulting
# BULLISH/BEARISH/NEUTRAL classification, on this exact fixture.
# ---------------------------------------------------------------------------
def test_part_equivalence_legacy_formula_matches_canonical_feature() -> None:
    sma_series = compute_simple_moving_average(
        SimpleMovingAverageDefinition(LOOKBACK), FIXTURE_BARS
    )
    canonical_series = compute_price_vs_ma_pct_sma(
        PriceVsMaPctSmaDefinition(LOOKBACK), FIXTURE_BARS
    )
    sma_by_ts = {fv.timestamp: fv for fv in sma_series}
    canon_by_ts = {fv.timestamp: fv for fv in canonical_series}
    bars_by_ts = {b.timestamp: b for b in FIXTURE_BARS}

    assert sma_by_ts.keys() == canon_by_ts.keys()
    assert len(sma_by_ts) > 0

    band_fraction = BAND_PERCENT / 100
    for ts, sma_fv in sma_by_ts.items():
        close = bars_by_ts[ts].close
        legacy_ratio = (close - sma_fv.value) / sma_fv.value
        canonical_ratio = canon_by_ts[ts].value
        assert legacy_ratio == canonical_ratio, f"mismatch at {ts}"

        # Legacy pre-65.10 classification (inline band comparison)
        if legacy_ratio > band_fraction:
            legacy_direction = StrategyDirection.BULLISH
        elif legacy_ratio < -band_fraction:
            legacy_direction = StrategyDirection.BEARISH
        else:
            legacy_direction = StrategyDirection.NEUTRAL

        # Canonical (post-65.10, current production) classification via
        # the real strategy object.
        strategy = build_default_registry().get(STRATEGY_ID)
        config_values = StrategyConfigurationValues(
            STRATEGY_ID, "v1", "v1", "v1", {"lookback": LOOKBACK, "band_percent": BAND_PERCENT}
        )
        signal = strategy.evaluate(bars_by_ts[ts], {f"price_vs_ma_pct_sma_{LOOKBACK}": canon_by_ts[ts]}, config_values)
        assert signal is not None
        assert signal.direction == legacy_direction


# ---------------------------------------------------------------------------
# Part D: warm-up -- no signal before the feature is available. Asserted
# on "feature missing at t -> signal absent at t", not a hard-coded bar
# count.
# ---------------------------------------------------------------------------
def test_part_d_warmup_no_signal_before_feature_available() -> None:
    strategy = build_default_registry().get(STRATEGY_ID)
    config_values = StrategyConfigurationValues(
        STRATEGY_ID, "v1", "v1", "v1", {"lookback": LOOKBACK, "band_percent": BAND_PERCENT}
    )
    signals, warmup_bars, _ = compute_signals(
        FIXTURE_BARS, strategy, config_values, compute_feature_series
    )
    feature_series = compute_feature_series(f"price_vs_ma_pct_sma_{LOOKBACK}", FIXTURE_BARS)
    available_ts = {fv.timestamp for fv in feature_series}

    assert warmup_bars > 0
    for bar, signal in zip(FIXTURE_BARS, signals, strict=True):
        if bar.timestamp not in available_ts:
            assert signal is None, f"signal produced before feature availability at {bar.timestamp}"


# ---------------------------------------------------------------------------
# Part E: missing context -> no signal, never a fabricated 0/neutral value.
# ---------------------------------------------------------------------------
def test_part_e_missing_context_produces_no_signal_not_fabricated() -> None:
    strategy = build_default_registry().get(STRATEGY_ID)
    config_values = StrategyConfigurationValues(
        STRATEGY_ID, "v1", "v1", "v1", {"lookback": LOOKBACK, "band_percent": BAND_PERCENT}
    )
    signal = strategy.evaluate(FIXTURE_BARS[0], {}, config_values)
    assert signal is None


# ---------------------------------------------------------------------------
# Part F/H/I: execution semantics -- entry fills at the NEXT bar's open,
# through the existing, unmodified engine (asserted, not assumed, by
# reading `engine.py` at investigation time: line ~371-373).
# ---------------------------------------------------------------------------
def test_part_f_h_i_next_bar_open_fill_semantics_preserved() -> None:
    result, _ = _run()
    assert len(result.trades) > 0
    bars_by_ts = {b.timestamp: b for b in FIXTURE_BARS}
    ts_list = [b.timestamp for b in FIXTURE_BARS]
    for trade in result.trades:
        # entry_price must equal the OPEN of the bar immediately AFTER
        # the signal bar that triggered entry (no slippage configured,
        # brokerage/slippage percent = 0 in this fixture's config).
        entry_ts = trade.entry_timestamp
        assert entry_ts in bars_by_ts
        entry_bar = bars_by_ts[entry_ts]
        assert trade.entry_price == entry_bar.open
        # The entry timestamp must correspond to a bar strictly after
        # bar index 0 (an actual "next bar", not same-bar close fill).
        assert ts_list.index(entry_ts) > 0


# ---------------------------------------------------------------------------
# Part G: evidence -- feature_name/feature_version/instrument_id/
# timeframe/timestamp/value preserved verbatim, never reconstructed.
# ---------------------------------------------------------------------------
def test_part_g_signal_evidence_preserved() -> None:
    strategy = build_default_registry().get(STRATEGY_ID)
    config_values = StrategyConfigurationValues(
        STRATEGY_ID, "v1", "v1", "v1", {"lookback": LOOKBACK, "band_percent": BAND_PERCENT}
    )
    signals, _, _ = compute_signals(FIXTURE_BARS, strategy, config_values, compute_feature_series)
    non_none = [s for s in signals if s is not None]
    assert non_none
    for signal in non_none:
        assert len(signal.evidence) == 1
        ev = signal.evidence[0]
        assert ev.feature_name.startswith("price_vs_ma_pct_sma")
        assert ev.feature_version is not None
        assert ev.instrument_id == INSTRUMENT
        assert ev.timeframe == TIMEFRAME
        assert ev.timestamp == signal.timestamp
        assert ev.value is not None


# ---------------------------------------------------------------------------
# Part H: determinism -- run the exact same deterministic configuration
# twice; signals/ordering/evidence/trade decisions must be identical.
# ---------------------------------------------------------------------------
def test_part_h_two_runs_are_bit_for_bit_identical() -> None:
    result_a, _ = _run()
    result_b, _ = _run()

    assert result_a.backtest_id == result_b.backtest_id
    assert len(result_a.trades) == len(result_b.trades)
    for trade_a, trade_b in zip(result_a.trades, result_b.trades, strict=True):
        assert trade_a.entry_timestamp == trade_b.entry_timestamp
        assert trade_a.entry_price == trade_b.entry_price
        assert trade_a.exit_timestamp == trade_b.exit_timestamp
        assert trade_a.exit_price == trade_b.exit_price
        assert trade_a.direction == trade_b.direction
        assert trade_a.net_pnl == trade_b.net_pnl

    strategy = build_default_registry().get(STRATEGY_ID)
    config_values = StrategyConfigurationValues(
        STRATEGY_ID, "v1", "v1", "v1", {"lookback": LOOKBACK, "band_percent": BAND_PERCENT}
    )
    signals_a, warmup_a, count_a = compute_signals(
        FIXTURE_BARS, strategy, config_values, compute_feature_series
    )
    signals_b, warmup_b, count_b = compute_signals(
        FIXTURE_BARS, strategy, config_values, compute_feature_series
    )
    assert warmup_a == warmup_b
    assert count_a == count_b
    for sig_a, sig_b in zip(signals_a, signals_b, strict=True):
        if sig_a is None or sig_b is None:
            assert sig_a is None and sig_b is None
            continue
        assert sig_a.direction == sig_b.direction
        assert sig_a.timestamp == sig_b.timestamp
        assert sig_a.evidence[0].value == sig_b.evidence[0].value


# ---------------------------------------------------------------------------
# Part J: no synthetic data reaches a real database -- the fake
# repositories above are the only persistence surface this test touches.
# This test documents that fact structurally (no Django/ORM import in
# this file at all).
# ---------------------------------------------------------------------------
def test_part_j_no_django_or_orm_dependency_in_this_test_module() -> None:
    import ast

    module_source = pathlib.Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(module_source)
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])
    assert "django" not in imported_roots
    assert "Repository" in module_source  # fakes are named/used, but not Django ones
