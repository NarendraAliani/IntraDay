# tests/unit/application/services/test_historical_backtest_run_orchestrator.py
#
# Checkpoint 63.x Phase 24: THE mandatory architectural proof of this
# entire checkpoint - that a historical backtest run's data path is
#
#     API -> DB -> Scanner
#
# and NEVER
#
#     API -> Scanner
#
# Two tests, exactly as Phase 24 specifies:
#
#   1. Populate `HistoricalBar` directly, then run the orchestrator with
#      a provider that RAISES on any `fetch()` call. The run must still
#      COMPLETE successfully with zero API requests - proving the
#      scanner reads from the database, never the provider, once data
#      is already there.
#
#   2. Start with an EMPTY database and an available provider - the run
#      fetches, persists, and scans (api_requests > 0). Then disable the
#      provider entirely and run the SAME configuration again - it must
#      still COMPLETE, with zero further API requests, proving the full
#      sequence API -> DB -> Scanner and that the scanner never falls
#      back to the (now-unavailable) API once data is persisted.
#
# Uses the real Django database and the real `BacktestingService`/
# `run_backtest` engine (Phase 10 parity) - only the provider's
# `is_available` flag is toggled between assertions.
from __future__ import annotations

from datetime import date

import pytest

from intraday.application.services.backtesting import BacktestingService
from intraday.application.services.historical_backtest_run import HistoricalBacktestRunOrchestrator
from intraday.application.services.historical_data_coverage import HistoricalDataCoverageService
from intraday.application.services.historical_data_preparation import (
    HistoricalDataPreparationService,
)
from intraday.application.services.market_data import HistoricalMarketDataService
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.shared_kernel.contracts import Exchange
from intraday.infrastructure.market_data_providers.synthetic_historical import (
    SyntheticHistoricalBarProvider,
)
from intraday.infrastructure.persistence.historical_backtest_run_repository import (
    DjangoBacktestRunRepository,
)
from intraday.infrastructure.persistence.historical_bar_repository import (
    DjangoHistoricalBarRepository,
)
from intraday.infrastructure.persistence.repositories import DjangoBacktestResultRepository
from intraday.trading_engine.strategy_execution.registry import build_default_registry
from tests.postgres_utils import requires_postgres

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")


class _AlwaysRaisesProvider:
    """A provider whose `fetch()` must NEVER be called once the database
    is already complete - if it IS called, the test fails immediately
    with a clear assertion, not a silent pass."""

    def __init__(self) -> None:
        self.fetch_calls = 0

    def fetch(self, *args: object, **kwargs: object) -> tuple[object, ...]:
        self.fetch_calls += 1
        raise AssertionError(
            "provider.fetch() was called even though the database was already complete"
        )


def _orchestrator(provider: object) -> HistoricalBacktestRunOrchestrator:
    bar_repository = DjangoHistoricalBarRepository()
    return HistoricalBacktestRunOrchestrator(
        run_repository=DjangoBacktestRunRepository(),
        preparation=HistoricalDataPreparationService(
            coverage=HistoricalDataCoverageService(repository=bar_repository),
            provider=provider,
            writer=bar_repository,
        ),
        backtesting=BacktestingService(
            market_data=HistoricalMarketDataService(repository=bar_repository),
            registry=build_default_registry(),
            repository=DjangoBacktestResultRepository(),
        ),
    )


def _create_run(run_id: str, *, start: date, end: date) -> None:
    DjangoBacktestRunRepository().create(
        run_id,
        created_by="test-operator",
        start_date=start,
        end_date=end,
        timeframe="5m",
        instrument_ids=["NSE:RELIANCE"],
        strategy_id="ema_crossover",
        specification_version="v1",
        code_version="v1",
        configuration_version="v1",
        strategy_values={"fast_lookback": 3, "slow_lookback": 6},
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
def test_scanner_reads_only_from_database_never_the_provider_once_complete() -> None:
    start, end = date(2026, 1, 5), date(2026, 1, 5)  # one trading Monday

    # First: populate the database for real, using an available provider.
    seeding_orchestrator = _orchestrator(SyntheticHistoricalBarProvider(is_available=True))
    seed_run_id = "seed-run"
    _create_run(seed_run_id, start=start, end=end)
    seeding_orchestrator.run(seed_run_id)
    seed_snapshot = DjangoBacktestRunRepository().get(seed_run_id)
    assert seed_snapshot is not None
    assert seed_snapshot.status == "COMPLETED"
    assert seed_snapshot.api_requests > 0  # confirms data really was fetched this time

    # Now: run AGAIN with a provider that raises if ever called.
    proving_provider = _AlwaysRaisesProvider()
    proving_orchestrator = _orchestrator(proving_provider)
    proving_run_id = "proving-run"
    _create_run(proving_run_id, start=start, end=end)
    proving_orchestrator.run(proving_run_id)

    snapshot = DjangoBacktestRunRepository().get(proving_run_id)
    assert snapshot is not None
    assert snapshot.status == "COMPLETED"
    assert snapshot.api_requests == 0
    assert proving_provider.fetch_calls == 0  # THE proof: never called
    assert snapshot.cache_hits > 0
    assert snapshot.scanned_bars > 0  # the scanner genuinely evaluated real bars from the DB


@requires_postgres
@pytest.mark.django_db
def test_full_sequence_api_then_db_then_scanner_survives_api_being_disabled_after() -> None:
    """Scenario E (Phase 37): prepare data successfully, THEN disable
    the external API entirely, then run again - success proves the
    scanner never depends on the provider once preparation is done."""
    start, end = date(2026, 1, 6), date(2026, 1, 6)  # one trading Tuesday

    available_provider = SyntheticHistoricalBarProvider(is_available=True)
    first_orchestrator = _orchestrator(available_provider)
    first_run_id = "prep-run"
    _create_run(first_run_id, start=start, end=end)
    first_orchestrator.run(first_run_id)

    first_snapshot = DjangoBacktestRunRepository().get(first_run_id)
    assert first_snapshot is not None
    assert first_snapshot.status == "COMPLETED"
    assert first_snapshot.api_requests > 0
    assert first_snapshot.cache_misses > 0
    assert available_provider.fetch_call_count > 0

    # Disable the provider entirely - simulating the external historical
    # API being unreachable.
    disabled_provider = SyntheticHistoricalBarProvider(is_available=False)
    second_orchestrator = _orchestrator(disabled_provider)
    second_run_id = "post-disable-run"
    _create_run(second_run_id, start=start, end=end)
    second_orchestrator.run(second_run_id)

    second_snapshot = DjangoBacktestRunRepository().get(second_run_id)
    assert second_snapshot is not None
    assert second_snapshot.status == "COMPLETED"  # SUCCESS despite the API being disabled
    assert second_snapshot.api_requests == 0
    assert disabled_provider.fetch_call_count == 0
    assert not second_snapshot.failed_instruments
