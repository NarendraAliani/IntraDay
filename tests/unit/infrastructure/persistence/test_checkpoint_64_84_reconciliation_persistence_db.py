# tests/unit/infrastructure/persistence/test_checkpoint_64_84_reconciliation_persistence_db.py
#
# Checkpoint 64.84: the same persistence rule as the research suite, but
# carried out against a REAL PostgreSQL database - because idempotency,
# "updates the same cell rather than appending", and "does not touch the
# archive assessment" are properties of the SQL, not of the service.
#
# The archive cell is the persistence boundary: there is no
# reconciliation table, and these tests assert that re-running a
# reconciliation cannot produce a second row.
#
# No provider connection, no live worker, no order path.
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from intraday.application.services.market_data_archive import MarketDataArchiveService
from intraday.application.services.market_data_reconciliation import (
    MarketDataReconciliationService,
)
from intraday.application.services.market_data_reconciliation_persistence import (
    MarketDataReconciliationPersistenceService,
)
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.aggregation import AggregatedBar, BarStatus
from intraday.domain.market_data.archive import ArchiveStatus, ReconciliationStatus
from intraday.domain.market_data.reconciliation import ReconciliationOutcome, ReferenceBar
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe
from intraday.infrastructure.persistence.live_market_data_repositories import (
    DjangoAggregatedBarRepository,
)
from intraday.infrastructure.persistence.market_data_archive_repository import (
    DjangoMarketDataArchiveRepository,
)
from intraday.infrastructure.persistence.market_data_reference_repository import (
    DjangoHistoricalReferenceBarRepository,
)
from intraday.infrastructure.persistence.models import MarketDataArchiveDay
from tests.postgres_utils import requires_postgres

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
TRADING_DAY = date(2026, 8, 25)
MARKET_OPEN = datetime(2026, 8, 25, 3, 45, tzinfo=UTC)  # 09:15 IST
AFTER_CLOSE = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)  # 17:30 IST


def _bar(interval_start: datetime) -> AggregatedBar:
    return AggregatedBar(
        instrument_id=RELIANCE,
        timeframe=Timeframe.ONE_MINUTE,
        interval_start=interval_start,
        interval_end=interval_start + timedelta(minutes=1),
        open=Decimal("100.00"),
        high=Decimal("100.00"),
        low=Decimal("100.00"),
        close=Decimal("100.00"),
        status=BarStatus.CLOSED,
        observation_count=3,
        data_source="dhan",
    )


class _EmptyReference:
    """The reference pipeline as it actually stands for every cell in
    the real database today: nothing overlapping to compare against."""

    def reference_bars_for(self, **_: object) -> tuple[ReferenceBar, ...]:
        return ()

    def describe_source(self) -> str:
        return "dhan_historical_candle_api"


def _archive_one_partial_day() -> None:
    DjangoAggregatedBarRepository().save_all(
        tuple(_bar(MARKET_OPEN + timedelta(minutes=i)) for i in range(20))
    )
    MarketDataArchiveService(DjangoMarketDataArchiveRepository()).refresh_trading_date(
        trading_date=TRADING_DAY, as_of=AFTER_CLOSE
    )


def _persistence_service(
    reference: object = None,
) -> MarketDataReconciliationPersistenceService:
    repo = DjangoMarketDataArchiveRepository()
    source = reference if reference is not None else _EmptyReference()
    return MarketDataReconciliationPersistenceService(
        MarketDataReconciliationService(repo, source),  # type: ignore[arg-type]
        repo,
    )


@requires_postgres
@pytest.mark.django_db
def test_persisting_not_reconciled_leaves_the_row_honestly_unreconciled() -> None:
    _archive_one_partial_day()

    (result,) = _persistence_service().reconcile_and_persist_trading_date(
        trading_date=TRADING_DAY, timeframe=Timeframe.ONE_MINUTE, as_of=AFTER_CLOSE
    )

    row = MarketDataArchiveDay.objects.get()
    assert result.report.outcome is ReconciliationOutcome.NOT_RECONCILED
    assert row.reconciliation_status == "NOT_RECONCILED"
    assert row.reconciliation_outcome == "NOT_RECONCILED"
    assert row.reconciliation_reason == "no_reference_bars_available"
    assert row.reconciled_at is None
    # The archive assessment is untouched by the reconciliation write.
    assert row.status == ArchiveStatus.PARTIAL.value
    assert row.closed_bar_count == 20


@requires_postgres
@pytest.mark.django_db
def test_repeated_reconciliation_updates_one_row_and_never_appends() -> None:
    """Phase 7 idempotency, and Phase 12's "no new table" made
    observable: three runs, one row, identical stored verdict."""
    _archive_one_partial_day()
    service = _persistence_service()

    for _ in range(3):
        service.reconcile_and_persist_trading_date(
            trading_date=TRADING_DAY, timeframe=Timeframe.ONE_MINUTE, as_of=AFTER_CLOSE
        )

    assert MarketDataArchiveDay.objects.count() == 1
    row = MarketDataArchiveDay.objects.get()
    assert row.reconciliation_status == "NOT_RECONCILED"
    assert row.reconciled_at is None


@requires_postgres
@pytest.mark.django_db
def test_reconciliation_never_creates_an_archive_cell() -> None:
    """No archived day, so nothing to make a claim about. The verdict is
    still computed and reported truthfully - it simply lands nowhere."""
    result = _persistence_service().reconcile_and_persist_cell(
        trading_date=TRADING_DAY,
        instrument_symbol="RELIANCE",
        timeframe=Timeframe.ONE_MINUTE,
        as_of=AFTER_CLOSE,
    )

    assert MarketDataArchiveDay.objects.count() == 0
    assert not result.persisted
    assert result.report.outcome is ReconciliationOutcome.NOT_RECONCILED


@requires_postgres
@pytest.mark.django_db
def test_a_later_archive_refresh_does_not_clear_a_persisted_verdict() -> None:
    """The two writers stay out of each other's columns in BOTH
    directions: recomputing the archive from our own observations must
    not erase (or forge) a reconciliation verdict."""
    _archive_one_partial_day()
    MarketDataArchiveDay.objects.update(
        reconciliation_status=ReconciliationStatus.RECONCILED.value,
        reconciliation_outcome=ReconciliationOutcome.PASS.value,
        reconciled_at=AFTER_CLOSE,
    )

    MarketDataArchiveService(DjangoMarketDataArchiveRepository()).refresh_trading_date(
        trading_date=TRADING_DAY, as_of=AFTER_CLOSE
    )

    row = MarketDataArchiveDay.objects.get()
    assert row.reconciliation_status == "RECONCILED"
    assert row.reconciled_at == AFTER_CLOSE


@requires_postgres
@pytest.mark.django_db
def test_real_reference_repository_against_stored_data_stays_not_reconciled() -> None:
    """The honest end-to-end shape: the REAL `HistoricalBar`-backed
    reference repository, against a freshly archived day with no
    historical rows for it, must persist NOT_RECONCILED. This is the
    test that would fail if anyone ever made persistence itself imply
    agreement."""
    _archive_one_partial_day()

    (result,) = _persistence_service(
        DjangoHistoricalReferenceBarRepository()
    ).reconcile_and_persist_trading_date(
        trading_date=TRADING_DAY, timeframe=Timeframe.ONE_MINUTE, as_of=AFTER_CLOSE
    )

    row = MarketDataArchiveDay.objects.get()
    assert result.report.evidence_source == "dhan_historical_candle_api"
    assert row.reconciliation_status == "NOT_RECONCILED"
    assert row.reconciled_at is None
