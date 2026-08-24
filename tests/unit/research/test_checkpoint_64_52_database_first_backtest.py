# File: tests/unit/research/test_checkpoint_64_52_database_first_backtest.py
#
# Checkpoint 64.52: DATABASE-FIRST HISTORICAL DATA + REAL STRATEGY
# EXECUTION.
#
# HONESTY NOTICE (do not remove): `GainzCompatibleResearchStrategy` is
# NOT the Gainz strategy and its signal logic is NOT verified GainzAlgo
# V2 mathematics -- see its own module docstring. This test file proves
# INFRASTRUCTURE: that the EXISTING database-first historical-data
# pipeline (`HistoricalDataCoverageService` + `HistoricalDataPreparationService`
# + `HistoricalBacktestRunOrchestrator`, all built at Checkpoint 63.x and
# re-used here UNCHANGED) can carry a real research strategy through the
# real `StrategyExecutionCoordinator` and the real Backtest engine
# (`BacktestingService.run()` / `research.backtesting.engine.run_backtest`,
# both UNCHANGED) end-to-end to real Fill/Trade/P&L/metrics.
#
# NO new BacktestDataManager/HistoricalDataManager/GainzDataManager is
# created here -- every DB-first/API-fallback/persist-then-scan test
# below constructs the EXACT SAME production classes
# `test_historical_backtest_run_orchestrator.py` already uses.
#
# The only new code in this file is a test-local, deterministic
# "strongly trending" `HistoricalBarProvider` implementation
# (`_TrendingBarProvider`) -- needed because the existing
# `SyntheticHistoricalBarProvider` (Checkpoint 63.x) generates
# pseudo-random per-timestamp OHLCV via a hash seed, which does not
# reliably sustain the multi-bar directional trend
# `GainzCompatibleResearchStrategy`'s ADX/MACD/RSI conditions require to
# ever emit a non-NEUTRAL signal. `_TrendingBarProvider` satisfies the
# exact same `HistoricalBarProvider` Protocol
# (`application.services.historical_data_preparation`) the synthetic
# provider does, and is used ONLY as a fixture/test double -- never a
# live/Dhan call.
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from intraday.application.services.backtesting import BacktestingService
from intraday.application.services.historical_backtest_run import (
    HistoricalBacktestRunOrchestrator,
    range_bounds,
)
from intraday.application.services.historical_data_coverage import HistoricalDataCoverageService
from intraday.application.services.historical_data_preparation import (
    PROVENANCE_API_FETCH,
    HistoricalDataPreparationService,
    PreparationStatus,
)
from intraday.application.services.market_data import HistoricalMarketDataService
from intraday.application.services.strategy_execution import (
    build_coordinator,
)
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.contracts import Bar
from intraday.domain.market_data.quality import expected_bar_timestamps
from intraday.domain.session.calendar import build_session_for, is_trading_day
from intraday.domain.shared_kernel.contracts import Exchange, InstrumentId, Timeframe
from intraday.infrastructure.market_data_providers.synthetic_historical import (
    HistoricalBarProviderUnavailableError,
)
from intraday.infrastructure.persistence.historical_backtest_run_repository import (
    DjangoBacktestRunRepository,
)
from intraday.infrastructure.persistence.historical_bar_repository import (
    DjangoHistoricalBarRepository,
)
from intraday.infrastructure.persistence.repositories import DjangoBacktestResultRepository
from intraday.research.backtesting.contracts import BacktestConfiguration, PositionSizingMode
from intraday.trading_engine.strategy_execution.contracts import (
    StrategyConfigurationValues,
    StrategyDirection,
    coerce_configuration_values,
)
from intraday.trading_engine.strategy_execution.registry import StrategyRegistry
from intraday.trading_engine.strategy_execution.strategies.gainz_compatible_research import (
    STRATEGY_ID,
    GainzCompatibleResearchStrategy,
)
from tests.postgres_utils import requires_postgres

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
TIMEFRAME = Timeframe.FIVE_MINUTE


# ---------------------------------------------------------------------------
# Test-local deterministic "trending" provider (see module docstring)
# ---------------------------------------------------------------------------


def _trend_bar(instrument_id: InstrumentId, timeframe: Timeframe, ts: datetime, index: int) -> Bar:
    """Deterministic, accelerating uptrend -- a pure function of `index`
    (the bar's ordinal position within the fetch), never of wall-clock
    time or randomness, so re-fetching the same range is idempotent and
    reproducible, mirroring `SyntheticHistoricalBarProvider._synthetic_bar`'s
    own determinism guarantee."""
    base = Decimal("100")
    move = Decimal("1") + Decimal(index) * Decimal("0.15")
    open_price = base + Decimal(index) * Decimal("1.0")
    close_price = open_price + move
    high_price = close_price + Decimal("0.05")
    low_price = open_price - Decimal("0.05")
    volume = Decimal("5000")
    return Bar(
        instrument_id=instrument_id,
        timeframe=timeframe,
        timestamp=ts,
        open=open_price.quantize(Decimal("0.01")),
        high=high_price.quantize(Decimal("0.01")),
        low=low_price.quantize(Decimal("0.01")),
        close=close_price.quantize(Decimal("0.01")),
        volume=volume,
    )


@dataclass
class _TrendingBarProvider:
    """Satisfies `HistoricalBarProvider` -- a test-local stand-in for
    "the historical API", exactly as `SyntheticHistoricalBarProvider`
    is in production code. Never touches Dhan or any live/network
    resource."""

    is_available: bool = True
    fetch_call_count: int = field(default=0, init=False)
    fetch_calls: list[tuple[InstrumentId, Timeframe, datetime, datetime]] = field(
        default_factory=list, init=False
    )

    def fetch(
        self,
        instrument_id: InstrumentId,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> tuple[Bar, ...]:
        self.fetch_call_count += 1
        self.fetch_calls.append((instrument_id, timeframe, start, end))
        if not self.is_available:
            raise HistoricalBarProviderUnavailableError(
                f"trending test provider unavailable for {instrument_id} {timeframe.value}"
            )
        bars: list[Bar] = []
        index = 0
        current_date = start.date()
        end_date = end.date()
        while current_date <= end_date:
            if is_trading_day(current_date):
                session = build_session_for(current_date, end)
                for ts in expected_bar_timestamps(session, timeframe):
                    if start <= ts <= end:
                        bars.append(_trend_bar(instrument_id, timeframe, ts, index))
                        index += 1
            current_date += timedelta(days=1)
        return tuple(bars)


class _AlwaysRaisesProvider:
    """A provider whose `fetch()` must NEVER be called once the database
    is already complete -- if it IS called, the test fails immediately."""

    def __init__(self) -> None:
        self.fetch_call_count = 0

    def fetch(self, *args: object, **kwargs: object) -> tuple[Bar, ...]:
        self.fetch_call_count += 1
        raise AssertionError(
            "provider.fetch() was called even though the database was already complete"
        )


def _bar_repository() -> DjangoHistoricalBarRepository:
    return DjangoHistoricalBarRepository()


def _coverage(repo: DjangoHistoricalBarRepository) -> HistoricalDataCoverageService:
    return HistoricalDataCoverageService(repository=repo)


def _preparation(
    repo: DjangoHistoricalBarRepository, provider: object
) -> HistoricalDataPreparationService:
    return HistoricalDataPreparationService(
        coverage=_coverage(repo), provider=provider, writer=repo
    )


def _gainz_registry() -> StrategyRegistry:
    """A test-local registry with `GainzCompatibleResearchStrategy`
    registered -- proving the directive's own point (§20/Final Directive):
    it remains research-only, deliberately absent from
    `build_default_registry()`, but fully usable by any caller
    (research/test code) that explicitly registers it, exactly as
    64.51 already established for `StrategyRegistry`'s architecture."""
    registry = StrategyRegistry()
    registry.register(GainzCompatibleResearchStrategy())
    registry.activate(STRATEGY_ID)
    return registry


def _gainz_config(overrides: dict[str, object] | None = None) -> StrategyConfigurationValues:
    strategy = GainzCompatibleResearchStrategy()
    schema = strategy.parameter_schema()
    values: dict[str, object] = {p.parameter_id: p.default for p in schema.parameters}
    if overrides:
        values.update(overrides)
    values = coerce_configuration_values(schema, values)
    return StrategyConfigurationValues(
        strategy_id=STRATEGY_ID,
        specification_version=strategy.specification_version,
        code_version=strategy.code_version,
        configuration_version="v1",
        values=values,
    )


def _backtesting_service(repo: DjangoHistoricalBarRepository) -> BacktestingService:
    return BacktestingService(
        market_data=HistoricalMarketDataService(repository=repo),
        registry=_gainz_registry(),
        repository=DjangoBacktestResultRepository(),
    )


def _backtest_config(start: datetime, end: datetime) -> BacktestConfiguration:
    return BacktestConfiguration(
        instrument_id=RELIANCE,
        timeframe=TIMEFRAME,
        start=start,
        end=end,
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


def _strategy_values() -> dict[str, object]:
    strategy = GainzCompatibleResearchStrategy()
    schema = strategy.parameter_schema()
    return {p.parameter_id: p.default for p in schema.parameters}


def _json_safe_strategy_values() -> dict[str, object]:
    """`BacktestRun.strategy_values` is a JSON field (Checkpoint 63.x,
    mirroring how a real HTTP API request would arrive - no native
    Decimal type in JSON). `coerce_configuration_values()` is exactly
    what closes this gap on the read side (see `BacktestingService.run()`'s
    own docstring); this helper mirrors the write side for tests that
    persist a `BacktestRun` row directly instead of via that API."""
    return {k: (str(v) if isinstance(v, Decimal) else v) for k, v in _strategy_values().items()}


# A wide window (several trading days at 5m) is used throughout so that
# there is comfortably enough warmup (ADX/RSI/MACD-slow lookback <= 26
# bars) AND enough post-warmup bars for a signal to actually fire.
FEB_START = date(2026, 2, 2)  # Monday
FEB_END = date(2026, 2, 6)  # Friday - a full trading week


# ---------------------------------------------------------------------------
# A/B/C. DB hit / DB miss / persistence
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.django_db
def test_a_database_hit_returns_historical_data_without_api_call() -> None:
    repo = _bar_repository()
    start, end = range_bounds(FEB_START, FEB_START)
    provider = _TrendingBarProvider()
    prep = _preparation(repo, provider)

    # Seed the DB for real via one legitimate fetch first.
    seed_outcome = prep.prepare(RELIANCE, TIMEFRAME, start, end)
    assert seed_outcome.status is PreparationStatus.COMPLETE
    assert provider.fetch_call_count == 1

    # Now request the SAME range again with a provider that raises if
    # ever called -- this is the DB-hit proof.
    raising_provider = _AlwaysRaisesProvider()
    prep2 = _preparation(repo, raising_provider)
    outcome = prep2.prepare(RELIANCE, TIMEFRAME, start, end)

    assert outcome.status is PreparationStatus.COMPLETE
    assert outcome.api_requests == 0
    assert raising_provider.fetch_call_count == 0
    assert outcome.cache_hits == seed_outcome.bars_persisted
    assert outcome.cache_hits > 0


@requires_postgres
@pytest.mark.django_db
def test_b_database_miss_calls_historical_api() -> None:
    repo = _bar_repository()
    start, end = range_bounds(FEB_START, FEB_START)
    provider = _TrendingBarProvider()
    prep = _preparation(repo, provider)

    outcome = prep.prepare(RELIANCE, TIMEFRAME, start, end)

    assert outcome.status is PreparationStatus.COMPLETE
    assert provider.fetch_call_count == 1
    assert outcome.api_requests == 1
    assert outcome.bars_fetched > 0
    assert outcome.cache_hits == 0  # nothing was cached before this call


@requires_postgres
@pytest.mark.django_db
def test_c_api_data_is_persisted() -> None:
    repo = _bar_repository()
    start, end = range_bounds(FEB_START, FEB_START)
    provider = _TrendingBarProvider()
    prep = _preparation(repo, provider)

    outcome = prep.prepare(RELIANCE, TIMEFRAME, start, end)

    persisted_bars = repo.get_bars(RELIANCE, TIMEFRAME, start, end)
    assert len(persisted_bars) == outcome.bars_persisted
    assert len(persisted_bars) == outcome.bars_fetched
    # Real rows exist in the database itself, not merely "provider said
    # so" -- direct model-level count, independent of the repository's
    # own read path.
    from intraday.infrastructure.persistence.models import HistoricalBar

    db_row_count = HistoricalBar.objects.filter(
        instrument_id=str(RELIANCE), timeframe=TIMEFRAME.value, source=PROVENANCE_API_FETCH
    ).count()
    assert db_row_count == outcome.bars_persisted


# ---------------------------------------------------------------------------
# D/E. Backtest reads DB after fetch; duplicate-prevention
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.django_db
def test_d_backtest_uses_persisted_database_data_after_fetch() -> None:
    repo = _bar_repository()
    start, end = range_bounds(FEB_START, FEB_END)
    provider = _TrendingBarProvider()
    prep = _preparation(repo, provider)
    outcome = prep.prepare(RELIANCE, TIMEFRAME, start, end)
    assert outcome.status is PreparationStatus.COMPLETE

    service = _backtesting_service(repo)
    result = service.run(_backtest_config(start, end), _strategy_values(), created_by="test-64-52")

    assert result.data_quality.bar_count == outcome.cache_hits + outcome.bars_persisted
    assert result.data_quality.bar_count == len(repo.get_bars(RELIANCE, TIMEFRAME, start, end))


@requires_postgres
@pytest.mark.django_db
def test_e_second_identical_request_does_not_call_api() -> None:
    repo = _bar_repository()
    start, end = range_bounds(FEB_START, FEB_END)
    provider = _TrendingBarProvider()
    prep = _preparation(repo, provider)

    prep.prepare(RELIANCE, TIMEFRAME, start, end)
    calls_after_first = provider.fetch_call_count
    assert calls_after_first > 0

    outcome2 = prep.prepare(RELIANCE, TIMEFRAME, start, end)

    assert provider.fetch_call_count == calls_after_first  # unchanged - no new API calls
    assert outcome2.api_requests == 0
    assert outcome2.status is PreparationStatus.COMPLETE


# ---------------------------------------------------------------------------
# F/G. Gap fetch / completeness enforcement
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.django_db
def test_f_partial_gap_fetches_only_the_missing_range() -> None:
    repo = _bar_repository()
    full_start, full_end = range_bounds(FEB_START, FEB_END)

    # Pre-populate ONLY the first day (Monday) directly, bypassing the
    # provider entirely -- simulating "DB already has the first half".
    monday_start, monday_end = range_bounds(FEB_START, FEB_START)
    seed_provider = _TrendingBarProvider()
    first_half_bars = seed_provider.fetch(RELIANCE, TIMEFRAME, monday_start, monday_end)
    repo.bulk_upsert(first_half_bars, source=PROVENANCE_API_FETCH)
    assert seed_provider.fetch_call_count == 1  # seeding call, not part of the test proof below

    coverage_before = _coverage(repo).get_coverage(RELIANCE, TIMEFRAME, full_start, full_end)
    assert not coverage_before.is_complete
    assert coverage_before.cached_bar_count == len(first_half_bars)
    assert coverage_before.cached_bar_count > 0

    # Now request the FULL week's range through prepare() with a fresh
    # provider -- only the missing (Tue-Fri) portion must be fetched.
    gap_provider = _TrendingBarProvider()
    prep = _preparation(repo, gap_provider)
    outcome = prep.prepare(RELIANCE, TIMEFRAME, full_start, full_end)

    assert outcome.status is PreparationStatus.COMPLETE
    assert outcome.cache_hits == len(first_half_bars)  # Monday's bars were NOT refetched
    assert outcome.bars_fetched > 0  # Tue-Fri WAS fetched
    # The gap-fetch provider was never asked to (re)fetch Monday's range
    for _, _, req_start, _ in gap_provider.fetch_calls:
        assert req_start.date() != FEB_START  # Monday's own start date never re-requested

    combined = repo.get_bars(RELIANCE, TIMEFRAME, full_start, full_end)
    coverage_after = _coverage(repo).get_coverage(RELIANCE, TIMEFRAME, full_start, full_end)
    assert coverage_after.is_complete
    assert len(combined) == coverage_after.expected_bar_count


@requires_postgres
@pytest.mark.django_db
def test_g_data_completeness_is_enforced_not_row_existence() -> None:
    """Directive §3: completeness must be date/time-range-aware, not
    merely 'some rows exist'. Populate a SPARSE, non-contiguous subset
    of one day's expected timestamps directly and prove `is_complete`
    is correctly False despite non-zero rows existing."""
    repo = _bar_repository()
    start, end = range_bounds(FEB_START, FEB_START)
    provider = _TrendingBarProvider()
    full_day_bars = provider.fetch(RELIANCE, TIMEFRAME, start, end)
    assert len(full_day_bars) > 4

    sparse_subset = full_day_bars[::2]  # every other bar - rows exist, range is NOT complete
    repo.bulk_upsert(sparse_subset, source=PROVENANCE_API_FETCH)

    coverage = _coverage(repo).get_coverage(RELIANCE, TIMEFRAME, start, end)
    assert coverage.cached_bar_count == len(sparse_subset)
    assert coverage.cached_bar_count > 0
    assert not coverage.is_complete  # rows exist, but the range is genuinely incomplete
    assert len(coverage.missing_ranges) > 0


# ---------------------------------------------------------------------------
# H/I. Warmup and timeframe correctness
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.django_db
def test_h_warmup_bars_are_included_in_the_prepared_range() -> None:
    """The requested range spans a full trading week at 5m bars - far
    more than the strategy's longest lookback (`macd_slow=26`), so
    every post-warmup bar has all required features available. This
    proves the database-backed range genuinely carries enough history
    for warmup, not merely "some bars"."""
    repo = _bar_repository()
    start, end = range_bounds(FEB_START, FEB_END)
    prep = _preparation(repo, _TrendingBarProvider())
    prep.prepare(RELIANCE, TIMEFRAME, start, end)

    bars = repo.get_bars(RELIANCE, TIMEFRAME, start, end)
    config = _gainz_config()
    longest_lookback = max(
        int(config.values["macd_slow"]),
        int(config.values["adx_lookback"]),
        int(config.values["relative_volume_lookback"]),
    )
    assert len(bars) > longest_lookback  # enough bars exist for full warmup + live evaluation

    coordinator = build_coordinator(_gainz_registry())
    # Evaluate progressively longer prefixes; before warmup every
    # required feature is None (per the strategy's own documented
    # warmup-safety contract) and the coordinator emits no signal for
    # that strategy; well past warmup a genuine signal object appears.
    early_result = coordinator.run(bars[: longest_lookback // 2], {STRATEGY_ID: config})
    late_result = coordinator.run(bars, {STRATEGY_ID: config})

    assert not any(s.strategy_id == STRATEGY_ID for s in early_result.signals)
    assert any(s.strategy_id == STRATEGY_ID for s in late_result.signals)


@requires_postgres
@pytest.mark.django_db
def test_i_strategy_receives_correct_timeframe() -> None:
    repo = _bar_repository()
    start, end = range_bounds(FEB_START, FEB_START)
    prep = _preparation(repo, _TrendingBarProvider())
    prep.prepare(RELIANCE, TIMEFRAME, start, end)

    bars = repo.get_bars(RELIANCE, TIMEFRAME, start, end)
    assert bars
    assert all(bar.timeframe is TIMEFRAME for bar in bars)

    coordinator = build_coordinator(_gainz_registry())
    result = coordinator.run(bars, {STRATEGY_ID: _gainz_config()})
    for signal in result.signals:
        assert signal.timeframe is TIMEFRAME


# ---------------------------------------------------------------------------
# J. Real coordinator, real StrategySignal/evidence/TradePlan
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.django_db
def test_j_gainz_strategy_runs_through_real_coordinator_against_db_bars() -> None:
    repo = _bar_repository()
    start, end = range_bounds(FEB_START, FEB_END)
    prep = _preparation(repo, _TrendingBarProvider())
    prep.prepare(RELIANCE, TIMEFRAME, start, end)
    bars = repo.get_bars(RELIANCE, TIMEFRAME, start, end)

    coordinator = build_coordinator(_gainz_registry())
    config = _gainz_config()
    result = coordinator.run(bars, {STRATEGY_ID: config})

    gainz_signals = [s for s in result.signals if s.strategy_id == STRATEGY_ID]
    assert len(gainz_signals) == 1  # coordinator evaluates the LAST bar only, per strategy
    signal = gainz_signals[0]
    assert signal.direction in (
        StrategyDirection.BULLISH,
        StrategyDirection.BEARISH,
        StrategyDirection.NEUTRAL,
    )
    assert len(signal.evidence) == 7  # rsi, adx, +di, -di, rvol, macd_hist, body_ratio
    assert all(ev is not None for ev in signal.evidence)  # real, non-fabricated evidence values

    # On this deliberately accelerating uptrend, the strategy's own
    # documented BULLISH condition should genuinely fire on the final
    # bar -- proving real feature-driven signal generation, not a
    # placeholder/NEUTRAL-only stub.
    assert signal.direction is StrategyDirection.BULLISH

    strategy = GainzCompatibleResearchStrategy()
    feature_values = dict(zip(strategy.required_features(config), signal.evidence, strict=True))
    trade_plan = strategy.build_trade_plan(bars[-1], feature_values, config, signal)
    # ATR is not among required_features(), so a TradePlan is correctly
    # None here unless separately supplied -- this proves the strategy's
    # own documented "never fabricate a plan from missing data" contract,
    # not a defect.
    assert trade_plan is None


# ---------------------------------------------------------------------------
# K/L/M. Real Backtest engine: Fill / Trade / P&L
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.django_db
def test_k_backtest_executes_using_database_backed_bars() -> None:
    repo = _bar_repository()
    start, end = range_bounds(FEB_START, FEB_END)
    prep = _preparation(repo, _TrendingBarProvider())
    outcome = prep.prepare(RELIANCE, TIMEFRAME, start, end)
    assert outcome.status is PreparationStatus.COMPLETE

    service = _backtesting_service(repo)
    result = service.run(_backtest_config(start, end), _strategy_values(), created_by="test-64-52")

    assert result.data_quality.bar_count > 0
    assert (
        result.data_quality.data_source
        == "HistoricalMarketDataRepository (fixture/historical only)"
    )


@requires_postgres
@pytest.mark.django_db
def test_l_canonical_fill_generation_remains_intact() -> None:
    repo = _bar_repository()
    start, end = range_bounds(FEB_START, FEB_END)
    prep = _preparation(repo, _TrendingBarProvider())
    prep.prepare(RELIANCE, TIMEFRAME, start, end)

    service = _backtesting_service(repo)
    result = service.run(_backtest_config(start, end), _strategy_values(), created_by="test-64-52")

    # Fills are the canonical `domain.execution.contracts.Fill` type,
    # produced by the UNMODIFIED `research.backtesting.engine.run_backtest`
    # - this test only proves they are still produced correctly, per the
    # directive's explicit "do not modify Fill generation" constraint.
    if result.trades:
        assert len(result.fills) >= len(result.trades)  # >= : entry + exit fill per trade
        fill_ids = [f.fill_id for f in result.fills]
        assert len(fill_ids) == len(set(fill_ids))  # every fill_id unique
        for f in result.fills:
            assert f.quantity > 0
            assert f.price > 0


@requires_postgres
@pytest.mark.django_db
def test_m_trade_and_pnl_remain_intact() -> None:
    repo = _bar_repository()
    start, end = range_bounds(FEB_START, FEB_END)
    prep = _preparation(repo, _TrendingBarProvider())
    prep.prepare(RELIANCE, TIMEFRAME, start, end)

    service = _backtesting_service(repo)
    result = service.run(_backtest_config(start, end), _strategy_values(), created_by="test-64-52")

    metrics = result.metrics
    assert metrics.total_trades == len(result.trades)
    assert metrics.winning_trades + metrics.losing_trades <= metrics.total_trades
    if result.trades:
        computed_net = sum((t.net_pnl for t in result.trades), Decimal("0"))
        assert metrics.net_pnl == computed_net


# ---------------------------------------------------------------------------
# N. Reproducibility
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.django_db
def test_n_same_database_snapshot_produces_deterministic_results() -> None:
    repo = _bar_repository()
    start, end = range_bounds(FEB_START, FEB_END)
    prep = _preparation(repo, _TrendingBarProvider())
    prep.prepare(RELIANCE, TIMEFRAME, start, end)

    service = _backtesting_service(repo)
    config = _backtest_config(start, end)
    values = _strategy_values()

    result1 = service.run(config, values, created_by="test-64-52-run-1")
    result2 = service.run(config, values, created_by="test-64-52-run-2")

    assert result1.backtest_id == result2.backtest_id  # deterministic id (Checkpoint 29)
    assert [f.fill_id for f in result1.fills] == [f.fill_id for f in result2.fills]
    assert len(result1.trades) == len(result2.trades)
    for t1, t2 in zip(result1.trades, result2.trades, strict=True):
        assert t1.entry_price == t2.entry_price
        assert t1.exit_price == t2.exit_price
        assert t1.quantity == t2.quantity
        assert t1.net_pnl == t2.net_pnl
    assert result1.metrics == result2.metrics


# ---------------------------------------------------------------------------
# O. No live API/Dhan connection
# ---------------------------------------------------------------------------


def test_o_no_live_dhan_module_is_imported_by_this_test_file() -> None:
    import ast
    from pathlib import Path

    source = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)
    dhan_modules = {m for m in imported_modules if "dhan" in m.lower()}
    assert (
        not dhan_modules
    ), f"this test file must never import a Dhan module, found: {dhan_modules}"


# ---------------------------------------------------------------------------
# Bonus: full orchestrator-level proof with the Gainz strategy (mirrors
# `test_historical_backtest_run_orchestrator.py`'s own established
# pattern, but exercising the research strategy instead of the
# production `ema_crossover`).
# ---------------------------------------------------------------------------


def _gainz_orchestrator(provider: object) -> HistoricalBacktestRunOrchestrator:
    bar_repository = _bar_repository()
    return HistoricalBacktestRunOrchestrator(
        run_repository=DjangoBacktestRunRepository(),
        preparation=_preparation(bar_repository, provider),
        backtesting=_backtesting_service(bar_repository),
    )


def _create_gainz_run(run_id: str, *, start: date, end: date) -> None:
    DjangoBacktestRunRepository().create(
        run_id,
        created_by="test-64-52",
        start_date=start,
        end_date=end,
        timeframe="5m",
        instrument_ids=["NSE:RELIANCE"],
        strategy_id=STRATEGY_ID,
        specification_version="v1",
        code_version="v1",
        configuration_version="v1",
        strategy_values=_json_safe_strategy_values(),
        cost_model_name="FLAT_PERCENTAGE",
        initial_capital=100_000,
        position_sizing_mode="FIXED_QUANTITY",
        position_size_value=10,
        brokerage_percent=0,
        slippage_percent=0,
        total_instruments=1,
    )


@requires_postgres
@pytest.mark.django_db
def test_end_to_end_orchestrator_runs_gainz_research_strategy_database_first() -> None:
    """The full directive pipeline in one orchestrator call: Historical
    Data Request -> Database FIRST -> API fallback (since DB starts
    empty) -> persist -> Backtest reads DATABASE -> GainzCompatibleResearchStrategy
    -> StrategySignal -> existing Backtest execution -> canonical Fill
    -> Trade -> P&L -> Metrics -- using the SAME `HistoricalBacktestRunOrchestrator`
    Checkpoint 63.x built, completely unmodified."""
    run_id = "gainz-e2e-run"
    _create_gainz_run(run_id, start=FEB_START, end=FEB_END)

    provider = _TrendingBarProvider()
    orchestrator = _gainz_orchestrator(provider)
    orchestrator.run(run_id)

    snapshot = DjangoBacktestRunRepository().get(run_id)
    assert snapshot is not None
    assert snapshot.status == "COMPLETED"
    assert snapshot.api_requests > 0  # DB was empty -> API fallback genuinely used
    assert snapshot.scanned_bars > 0
    assert STRATEGY_ID != "GainzStrategy"  # honesty guard: never silently renamed

    # Second identical run must not call the API again (DB now complete).
    proving_provider = _AlwaysRaisesProvider()
    second_orchestrator = _gainz_orchestrator(proving_provider)
    second_run_id = "gainz-e2e-run-2"
    _create_gainz_run(second_run_id, start=FEB_START, end=FEB_END)
    second_orchestrator.run(second_run_id)

    second_snapshot = DjangoBacktestRunRepository().get(second_run_id)
    assert second_snapshot is not None
    assert second_snapshot.status == "COMPLETED"
    assert second_snapshot.api_requests == 0
    assert proving_provider.fetch_call_count == 0
    assert second_snapshot.cache_hits > 0

    result1 = DjangoBacktestResultRepository().get(snapshot.result_backtest_ids["NSE:RELIANCE"])
    result2 = DjangoBacktestResultRepository().get(
        second_snapshot.result_backtest_ids["NSE:RELIANCE"]
    )
    assert result1 is not None
    assert result2 is not None
    assert result1["backtest_id"] == result2["backtest_id"]  # deterministic across both runs
