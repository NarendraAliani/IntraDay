# tests/unit/application/services/test_market_data_sync_run_orchestrator.py
#
# Unit coverage for `MarketDataSyncRunOrchestrator` - proves the
# per-instrument progress mutation and partial-failure handling, using
# the real Django database and the real `HistoricalDataPreparationService`
# pipeline (only the provider is a test double) - mirrors
# `test_historical_backtest_run_orchestrator.py`'s own real-DB
# discipline for its sibling orchestrator.
from __future__ import annotations

import uuid
from datetime import date, datetime

import pytest

from intraday.application.services.historical_data_coverage import HistoricalDataCoverageService
from intraday.application.services.historical_data_preparation import (
    HistoricalBarProvider,
    HistoricalDataPreparationService,
)
from intraday.application.services.market_data_sync_run import MarketDataSyncRunOrchestrator
from intraday.domain.market_data.contracts import Bar
from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe
from intraday.infrastructure.market_data_providers.synthetic_historical import (
    HistoricalBarProviderUnavailableError,
    SyntheticHistoricalBarProvider,
)
from intraday.infrastructure.persistence.historical_bar_repository import (
    DjangoHistoricalBarRepository,
)
from intraday.infrastructure.persistence.market_data_sync_run_repository import (
    DjangoMarketDataSyncRunRepository,
)
from tests.postgres_utils import requires_postgres


class _UnavailableForOneSymbolProvider:
    """Raises for `BADSYMBOL` only - every other instrument delegates to
    a real `SyntheticHistoricalBarProvider` - proves one bad instrument
    is recorded as a failure without aborting the rest of the run."""

    def __init__(self) -> None:
        self._delegate = SyntheticHistoricalBarProvider()

    def fetch(
        self, instrument_id: InstrumentId, timeframe: Timeframe, start: datetime, end: datetime
    ) -> tuple[Bar, ...]:
        if "BADSYMBOL" in str(instrument_id):
            raise HistoricalBarProviderUnavailableError(f"no data for {instrument_id}")
        return self._delegate.fetch(instrument_id, timeframe, start, end)


def _orchestrator(provider: HistoricalBarProvider) -> MarketDataSyncRunOrchestrator:
    bar_repository = DjangoHistoricalBarRepository()
    return MarketDataSyncRunOrchestrator(
        run_repository=DjangoMarketDataSyncRunRepository(),
        preparation=HistoricalDataPreparationService(
            coverage=HistoricalDataCoverageService(repository=bar_repository),
            provider=provider,
            writer=bar_repository,
        ),
    )


@requires_postgres
@pytest.mark.django_db
def test_a_successful_run_fetches_and_persists_real_bars() -> None:
    run_id = str(uuid.uuid4())
    DjangoMarketDataSyncRunRepository().create(
        run_id,
        created_by="test-operator",
        start_date=date(2026, 1, 5),
        end_date=date(2026, 1, 5),
        timeframes=["5m"],
        instrument_ids=["NSE:RELIANCE"],
        total_combinations=1,
    )

    _orchestrator(SyntheticHistoricalBarProvider()).run(run_id)

    snapshot = DjangoMarketDataSyncRunRepository().get(run_id)
    assert snapshot is not None
    assert snapshot.status == "COMPLETED"
    assert snapshot.completed_combinations == 1
    assert snapshot.bars_fetched > 0
    assert snapshot.bars_persisted > 0
    assert not snapshot.failed_combinations


@requires_postgres
@pytest.mark.django_db
def test_one_failing_instrument_does_not_abort_the_rest_of_the_run() -> None:
    run_id = str(uuid.uuid4())
    DjangoMarketDataSyncRunRepository().create(
        run_id,
        created_by="test-operator",
        start_date=date(2026, 1, 5),
        end_date=date(2026, 1, 5),
        timeframes=["5m"],
        instrument_ids=["NSE:RELIANCE", "NSE:BADSYMBOL"],
        total_combinations=2,
    )

    _orchestrator(_UnavailableForOneSymbolProvider()).run(run_id)

    snapshot = DjangoMarketDataSyncRunRepository().get(run_id)
    assert snapshot is not None
    assert snapshot.status == "PARTIAL"
    assert snapshot.completed_combinations == 2
    assert len(snapshot.failed_combinations) == 1
    assert snapshot.failed_combinations[0]["instrument_id"] == "NSE:BADSYMBOL"


@requires_postgres
@pytest.mark.django_db
def test_a_repeat_run_over_already_cached_data_makes_zero_provider_calls() -> None:
    """Same cache-hit discipline `HistoricalDataPreparationService`
    already guarantees, proven through this orchestrator too."""
    run_id_a = str(uuid.uuid4())
    DjangoMarketDataSyncRunRepository().create(
        run_id_a,
        created_by="test-operator",
        start_date=date(2026, 1, 5),
        end_date=date(2026, 1, 5),
        timeframes=["5m"],
        instrument_ids=["NSE:RELIANCE"],
        total_combinations=1,
    )
    _orchestrator(SyntheticHistoricalBarProvider()).run(run_id_a)

    class _AlwaysRaisesProvider:
        def fetch(
            self, instrument_id: InstrumentId, timeframe: Timeframe, start: datetime, end: datetime
        ) -> tuple[Bar, ...]:
            raise AssertionError(
                "provider.fetch() called despite the database already being complete"
            )

    run_id_b = str(uuid.uuid4())
    DjangoMarketDataSyncRunRepository().create(
        run_id_b,
        created_by="test-operator",
        start_date=date(2026, 1, 5),
        end_date=date(2026, 1, 5),
        timeframes=["5m"],
        instrument_ids=["NSE:RELIANCE"],
        total_combinations=1,
    )
    _orchestrator(_AlwaysRaisesProvider()).run(run_id_b)

    snapshot = DjangoMarketDataSyncRunRepository().get(run_id_b)
    assert snapshot is not None
    assert snapshot.status == "COMPLETED"
    assert snapshot.api_requests == 0
    assert snapshot.cache_hits > 0


@requires_postgres
@pytest.mark.django_db
def test_multiple_timeframes_are_each_fetched_as_their_own_combination() -> None:
    run_id = str(uuid.uuid4())
    DjangoMarketDataSyncRunRepository().create(
        run_id,
        created_by="test-operator",
        start_date=date(2026, 1, 5),
        end_date=date(2026, 1, 5),
        timeframes=["1d", "5m"],
        instrument_ids=["NSE:RELIANCE"],
        total_combinations=2,
    )

    _orchestrator(SyntheticHistoricalBarProvider()).run(run_id)

    snapshot = DjangoMarketDataSyncRunRepository().get(run_id)
    assert snapshot is not None
    assert snapshot.status == "COMPLETED"
    assert snapshot.completed_combinations == 2
    assert not snapshot.failed_combinations
