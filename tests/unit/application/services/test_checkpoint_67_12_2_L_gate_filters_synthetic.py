# File: tests/unit/application/services/test_checkpoint_67_12_2_L_gate_filters_synthetic.py
#
# Checkpoint 67.12.2-L Part 2 — THE TEST THAT SETTLES THIS CHECKPOINT'S
# CENTRAL QUESTION: does `ResearchDataGateService` actually FILTER OUT
# synthetic-provenance `HistoricalBar` rows from a real `RESEARCH`-mode
# backtest run, or does "the gate is always constructed" (67.12.2-B)
# merely mean it exists without actually rejecting anything?
#
# This test deliberately reproduces EXACTLY what `backtesting_views.py::
# _prepare_if_needed` does TODAY for any non-fixture instrument: it
# populates `HistoricalBar` rows using the real, unmodified
# `HistoricalDataPreparationService` + `SyntheticHistoricalBarProvider()`
# pair (so the rows carry `provenance=PROVENANCE_SYNTHETIC_TEST`, the
# genuine production stamp — not a hand-rolled fixture value), then
# drives a `RESEARCH`-mode backtest through the REAL, unmodified
# `BacktestingService.for_database_backed_research()` construction path
# (the same one `backtesting_views.py::_service()` uses in production)
# with a REAL `ResearchDataGateService` wired to the REAL
# `DjangoHistoricalBarRepository` — a genuine end-to-end path through
# Postgres, no shortcut, no fake repository, no mock of the gate itself.
#
# No real Dhan network call anywhere in this file (only
# `SyntheticHistoricalBarProvider` is used).
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from intraday.application.services.backtesting import BacktestingService
from intraday.application.services.historical_data_coverage import HistoricalDataCoverageService
from intraday.application.services.historical_data_preparation import (
    MAX_FETCH_ATTEMPTS,
    HistoricalDataPreparationService,
    PreparationStatus,
)
from intraday.application.services.market_data import HistoricalMarketDataService
from intraday.application.services.research_data_gate import (
    ResearchDataGateService,
    ResearchDataRejectedError,
    ResearchRejectionReason,
)
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.provenance import PROVENANCE_SYNTHETIC_TEST
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe
from intraday.infrastructure.market_data_providers.synthetic_historical import (
    SyntheticHistoricalBarProvider,
)
from intraday.infrastructure.persistence.historical_bar_repository import (
    DjangoHistoricalBarRepository,
)
from intraday.infrastructure.persistence.models import HistoricalBar
from intraday.infrastructure.persistence.repositories import DjangoBacktestResultRepository
from intraday.research.backtesting.contracts import BacktestConfiguration, PositionSizingMode
from intraday.trading_engine.strategy_execution.registry import build_default_registry
from tests.postgres_utils import requires_postgres

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
TIMEFRAME = Timeframe.FIVE_MINUTE
FEB_START = date(2026, 2, 2)  # Monday


def _range_bounds(d: date):
    import datetime as _dt

    start = _dt.datetime.combine(d, _dt.time.min, tzinfo=_dt.UTC)
    end = _dt.datetime.combine(d, _dt.time.max, tzinfo=_dt.UTC)
    return start, end


def _service_with_real_gate(repo: DjangoHistoricalBarRepository) -> BacktestingService:
    """Mirrors `backtesting_views.py::_service()`'s real, DB-backed
    branch EXACTLY — the same factory, the same gate wiring."""
    return BacktestingService.for_database_backed_research(
        market_data=HistoricalMarketDataService(repository=repo),
        registry=build_default_registry(),
        repository=DjangoBacktestResultRepository(),
        research_gate=ResearchDataGateService(
            repository=repo,
            coverage_service=HistoricalDataCoverageService(repository=repo),
        ),
    )


def _strategy_values(strategy_id: str) -> dict[str, object]:
    registry = build_default_registry()
    strategy = registry.get(strategy_id)
    schema = strategy.parameter_schema()
    return {p.parameter_id: p.default for p in schema.parameters}


def _backtest_config(start, end) -> BacktestConfiguration:
    return BacktestConfiguration(
        instrument_id=RELIANCE,
        timeframe=TIMEFRAME,
        start=start,
        end=end,
        strategy_id="ema_crossover",
        specification_version="v1",
        code_version="v1",
        configuration_version="v1",
        initial_capital=Decimal("100000"),
        position_sizing_mode=PositionSizingMode.FIXED_QUANTITY,
        position_size_value=Decimal("10"),
        brokerage_percent=Decimal("0"),
        slippage_percent=Decimal("0"),
    )


@requires_postgres
@pytest.mark.django_db
def test_gate_rejects_a_real_research_backtest_reading_only_synthetic_data() -> None:
    """THE test that settles this checkpoint: populate `HistoricalBar`
    with ONLY synthetic-provenance data (exactly what today's
    unconditional `SyntheticHistoricalBarProvider()` in
    `_prepare_if_needed` produces), then drive a real RESEARCH backtest
    through the real `for_database_backed_research()` + real gate. The
    SAFE outcome is a loud `ResearchDataRejectedError` with
    `.reason is INELIGIBLE_PROVENANCE` — never a silently-produced
    result using the synthetic bars."""
    repo = DjangoHistoricalBarRepository()
    start, end = _range_bounds(FEB_START)

    preparation = HistoricalDataPreparationService(
        coverage=HistoricalDataCoverageService(repository=repo),
        provider=SyntheticHistoricalBarProvider(),
        writer=repo,
    )
    outcome = preparation.prepare(RELIANCE, TIMEFRAME, start, end)
    assert outcome.status is PreparationStatus.COMPLETE
    assert outcome.bars_persisted > 0

    # Confirm, independently of the preparation service's own report,
    # that every row actually landed in the DB stamped SYNTHETIC_TEST —
    # the exact precondition this test exists to set up.
    db_rows = HistoricalBar.objects.filter(instrument_id=str(RELIANCE), timeframe=TIMEFRAME.value)
    assert db_rows.count() > 0
    assert all(row.provenance == PROVENANCE_SYNTHETIC_TEST for row in db_rows)

    service = _service_with_real_gate(repo)
    config = _backtest_config(start, end)

    with pytest.raises(ResearchDataRejectedError) as exc_info:
        service.run(config, {}, created_by="test-67-12-2-L")

    assert exc_info.value.reason is ResearchRejectionReason.INELIGIBLE_PROVENANCE
    assert PROVENANCE_SYNTHETIC_TEST in exc_info.value.detail


@requires_postgres
@pytest.mark.django_db
def test_gate_allows_the_same_shape_of_request_when_provenance_is_real_dhan() -> None:
    """Control case: the exact same range/instrument/timeframe, but with
    rows genuinely stamped `REAL_DHAN` + proven-canonical, passes
    through the gate and the backtest runs — proving the rejection
    above is really about provenance, not some unrelated failure
    (e.g. a broken coverage check that would reject everything)."""
    from intraday.domain.market_data.source_timestamp import (
        CANONICALIZATION_STATE_CANONICALIZED,
        SourceTimestampSemantics,
    )

    repo = DjangoHistoricalBarRepository()
    start, end = _range_bounds(FEB_START)

    preparation = HistoricalDataPreparationService(
        coverage=HistoricalDataCoverageService(repository=repo),
        provider=SyntheticHistoricalBarProvider(),
        writer=repo,
    )
    # Use the same synthetic provider to generate bars (no live Dhan
    # call), but relabel the persisted rows' provenance directly at the
    # DB level to REAL_DHAN + proven-canonical — isolating "does the
    # gate pass REAL_DHAN data" from "can we really fetch from Dhan",
    # which is explicitly out of scope (no live network call).
    outcome = preparation.prepare(RELIANCE, TIMEFRAME, start, end)
    assert outcome.status is PreparationStatus.COMPLETE

    HistoricalBar.objects.filter(instrument_id=str(RELIANCE), timeframe=TIMEFRAME.value).update(
        provenance="REAL_DHAN",
        canonicalization_state=CANONICALIZATION_STATE_CANONICALIZED,
        source_timestamp_semantics=SourceTimestampSemantics.OPEN.value,
    )

    service = _service_with_real_gate(repo)
    config = _backtest_config(start, end)

    result = service.run(
        config, _strategy_values("ema_crossover"), created_by="test-67-12-2-L-control"
    )
    assert result.data_quality.bar_count > 0


# ---------------------------------------------------------------------------
# Part 3 — provider-selection fix: `_prepare_if_needed` now calls
# `tasks._select_historical_bar_provider()` instead of unconditionally
# constructing `SyntheticHistoricalBarProvider()`. These tests exercise
# THAT selection point directly (monkeypatching
# `backtesting_views._select_historical_bar_provider`, exactly the name
# the fixed `_prepare_if_needed` now calls) with a deterministic
# test-local fake that satisfies the SAME `HistoricalBarProvider`
# Protocol `DhanHistoricalBarProvider` does (REAL_DHAN provenance,
# CANONICALIZED state, proven OPEN semantics) — never a real Dhan
# network call. `DhanHistoricalBarProvider` itself, and the era/segment
# canonicalization-proof rules it implements, are already covered
# unmodified by `test_historical_provider.py` — this file's job is only
# to prove the NEW selector wiring in `_prepare_if_needed`, not to
# re-prove that adapter's own internals.
# ---------------------------------------------------------------------------


from dataclasses import dataclass, field as _field  # noqa: E402

from intraday.domain.market_data.contracts import Bar  # noqa: E402
from intraday.domain.market_data.provenance import PROVENANCE_REAL_DHAN  # noqa: E402
from intraday.domain.market_data.quality import expected_bar_timestamps  # noqa: E402
from intraday.domain.session.calendar import build_session_for, is_trading_day  # noqa: E402
from intraday.domain.shared_kernel.contracts import InstrumentId  # noqa: E402
from intraday.infrastructure.market_data_providers.synthetic_historical import (  # noqa: E402
    HistoricalBarProviderUnavailableError,
)


@dataclass
class _FakeRealDhanProvider:
    """Test-local stand-in for `DhanHistoricalBarProvider` — same
    Protocol shape (`fetch`, `provenance`,
    `canonicalization_state_for`/`source_timestamp_semantics_for`), no
    network call. Deterministic bars, mirroring
    `test_checkpoint_64_52_database_first_backtest.py`'s own
    `_TrendingBarProvider` precedent."""

    is_available: bool = True
    provenance: str = _field(default=PROVENANCE_REAL_DHAN, init=False)
    fetch_call_count: int = _field(default=0, init=False)

    def canonicalization_state_for(self, instrument_id, timeframe, request_start, request_end):
        from intraday.domain.market_data.source_timestamp import (
            CANONICALIZATION_STATE_CANONICALIZED,
        )

        return CANONICALIZATION_STATE_CANONICALIZED

    def source_timestamp_semantics_for(self, instrument_id, timeframe, request_start, request_end):
        from intraday.domain.market_data.source_timestamp import SourceTimestampSemantics

        return SourceTimestampSemantics.OPEN.value

    def fetch(
        self,
        instrument_id: InstrumentId,
        timeframe: Timeframe,
        start,
        end,
    ) -> tuple[Bar, ...]:
        self.fetch_call_count += 1
        if not self.is_available:
            raise HistoricalBarProviderUnavailableError(
                f"fake real-Dhan provider unavailable for {instrument_id} {timeframe.value}"
            )
        bars: list[Bar] = []
        index = 0
        from datetime import timedelta as _timedelta

        current_date = start.date()
        end_date = end.date()
        while current_date <= end_date:
            if is_trading_day(current_date):
                session = build_session_for(current_date, end)
                for ts in expected_bar_timestamps(session, timeframe):
                    if start <= ts <= end:
                        base = Decimal("100") + Decimal(index)
                        bars.append(
                            Bar(
                                instrument_id=instrument_id,
                                timeframe=timeframe,
                                timestamp=ts,
                                open=base,
                                high=base + Decimal("1"),
                                low=base - Decimal("1"),
                                close=base + Decimal("0.5"),
                                volume=Decimal("1000"),
                            )
                        )
                        index += 1
            current_date += _timedelta(days=1)
        return tuple(bars)


@requires_postgres
@pytest.mark.django_db
def test_prepare_if_needed_now_uses_the_real_provider_selector_and_gate_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Part 3 proof: with the fix applied, `_prepare_if_needed` calls
    `_select_historical_bar_provider()` (imported from `tasks.py`) —
    when that selector resolves to a REAL_DHAN-provenance provider, the
    persisted rows pass the research-eligibility gate (no
    `ResearchDataRejectedError`), and a second `prepare()` call for the
    same range makes ZERO further provider calls (cache-hit
    invariant)."""
    from intraday.infrastructure.api import backtesting_views

    fake_provider = _FakeRealDhanProvider()
    monkeypatch.setattr(
        backtesting_views, "_select_historical_bar_provider", lambda: fake_provider
    )

    repo = DjangoHistoricalBarRepository()
    start, end = _range_bounds(FEB_START)
    config = _backtest_config(start, end)

    backtesting_views._prepare_if_needed(config)
    assert fake_provider.fetch_call_count == 1

    db_rows = HistoricalBar.objects.filter(instrument_id=str(RELIANCE), timeframe=TIMEFRAME.value)
    assert db_rows.count() > 0
    assert all(row.provenance == PROVENANCE_REAL_DHAN for row in db_rows)

    # The gate now passes real-provider data through a real RESEARCH run.
    service = _service_with_real_gate(repo)
    result = service.run(
        config, _strategy_values("ema_crossover"), created_by="test-67-12-2-L-part3"
    )
    assert result.data_quality.bar_count > 0

    # Second prepare() call for the identical range: zero further
    # provider calls — the existing cache-hit invariant (67.12.2-J/K's
    # own established pattern) still holds with the real-provider path.
    backtesting_views._prepare_if_needed(config)
    assert fake_provider.fetch_call_count == 1


# ---------------------------------------------------------------------------
# Part 4 — failure-mode honesty: a real-provider failure must propagate
# as a clear "no data available" outcome, never a silent fallback to
# `SyntheticHistoricalBarProvider`.
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.django_db
def test_prepare_if_needed_propagates_provider_failure_never_silently_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failing real-provider selection (rate limit / unsupported
    instrument / network error, simulated here by
    `HistoricalBarProviderUnavailableError`) must never result in
    `_prepare_if_needed` silently switching to
    `SyntheticHistoricalBarProvider` and persisting fabricated data
    under the real provider's name.

    ACTUAL observed behavior (this is the finding, not an assumption):
    `HistoricalDataPreparationService.prepare()` already catches
    provider exceptions internally (bounded retry, `MAX_FETCH_ATTEMPTS
    = 3`) and returns a `PreparationOutcome` with
    `status=NOT_AVAILABLE` rather than raising —
    `_prepare_if_needed()` discards that outcome and returns `None`
    either way, so NO exception propagates out of `_prepare_if_needed`
    itself. What matters for honesty is proven here instead: zero
    `HistoricalBar` rows are persisted for this range (no synthetic
    fallback happened), and the subsequent real RESEARCH backtest call
    (`BacktestingService.for_database_backed_research().run()`) then
    hits the gate's OWN completeness check and raises
    `ResearchDataRejectedError` — a loud, typed rejection, never a
    silently-produced result using fabricated data."""
    from intraday.infrastructure.api import backtesting_views

    failing_provider = _FakeRealDhanProvider(is_available=False)
    monkeypatch.setattr(
        backtesting_views, "_select_historical_bar_provider", lambda: failing_provider
    )

    repo = DjangoHistoricalBarRepository()
    start, end = _range_bounds(FEB_START)
    config = _backtest_config(start, end)

    backtesting_views._prepare_if_needed(config)  # does not raise (see docstring finding above)

    assert failing_provider.fetch_call_count == MAX_FETCH_ATTEMPTS  # bounded retry, confirmed
    db_rows = HistoricalBar.objects.filter(instrument_id=str(RELIANCE), timeframe=TIMEFRAME.value)
    assert db_rows.count() == 0  # no silent synthetic-data fallback occurred

    service = _service_with_real_gate(repo)
    with pytest.raises(ResearchDataRejectedError) as exc_info:
        service.run(config, _strategy_values("ema_crossover"), created_by="test-67-12-2-L-part4")
    assert exc_info.value.reason in (
        ResearchRejectionReason.NO_DATA,
        ResearchRejectionReason.INCOMPLETE_COVERAGE,
    )
