# tests/unit/infrastructure/persistence/test_scanner_scan_progress_repository.py
#
# Checkpoint 64.18: real-Postgres coverage for
# `DjangoScannerScanProgressRepository` - mirrors the established
# WorkerRuntimeStatus repository test pattern.
from __future__ import annotations

import datetime as dt

import pytest

from intraday.infrastructure.persistence.scanner_scan_progress_repository import (
    DjangoScannerScanProgressRepository,
)
from tests.postgres_utils import requires_postgres

WHEN = dt.datetime(2026, 8, 20, 5, 0, tzinfo=dt.UTC)


@requires_postgres
@pytest.mark.django_db
def test_get_returns_none_before_any_scan_has_started() -> None:
    assert DjangoScannerScanProgressRepository().get("dhan") is None


@requires_postgres
@pytest.mark.django_db
def test_start_scan_resets_counters_and_sets_starting_status() -> None:
    repo = DjangoScannerScanProgressRepository()

    repo.start_scan(
        "dhan",
        scan_id="scan-1",
        scan_started_at=WHEN,
        timeframe="5m",
        universe_total=3,
        strategies_total=2,
    )
    record = repo.get("dhan")

    assert record is not None
    assert record.scan_id == "scan-1"
    assert record.scan_started_at == WHEN
    assert record.timeframe == "5m"
    assert record.universe_total == 3
    assert record.universe_processed == 0
    assert record.strategies_total == 2
    assert record.strategies_processed == 0
    assert record.signals_found == 0
    assert record.status == "STARTING"


@requires_postgres
@pytest.mark.django_db
def test_starting_a_new_scan_resets_counters_from_a_previous_scan() -> None:
    """A stale count from a PRIOR scan must never leak into a new one."""
    repo = DjangoScannerScanProgressRepository()
    repo.start_scan(
        "dhan",
        scan_id="scan-1",
        scan_started_at=WHEN,
        timeframe="5m",
        universe_total=3,
        strategies_total=1,
    )
    repo.update_progress(
        "dhan", status="COMPLETED", universe_processed=3, strategies_processed=1, signals_found=2
    )

    repo.start_scan(
        "dhan",
        scan_id="scan-2",
        scan_started_at=WHEN + dt.timedelta(minutes=1),
        timeframe="5m",
        universe_total=5,
        strategies_total=2,
    )
    record = repo.get("dhan")

    assert record is not None
    assert record.scan_id == "scan-2"
    assert record.universe_processed == 0
    assert record.strategies_processed == 0
    assert record.signals_found == 0
    assert record.status == "STARTING"


@requires_postgres
@pytest.mark.django_db
def test_update_progress_only_changes_fields_explicitly_supplied() -> None:
    repo = DjangoScannerScanProgressRepository()
    repo.start_scan(
        "dhan",
        scan_id="scan-1",
        scan_started_at=WHEN,
        timeframe="5m",
        universe_total=3,
        strategies_total=1,
    )

    repo.update_progress("dhan", status="SCANNING", current_instrument="NSE:RELIANCE")
    after_first = repo.get("dhan")
    assert after_first is not None
    assert after_first.current_instrument == "NSE:RELIANCE"
    assert after_first.universe_processed == 0

    repo.update_progress("dhan", status="SCANNING", universe_processed=1)
    after_second = repo.get("dhan")
    assert after_second is not None
    # current_instrument from the FIRST call is preserved - not reset.
    assert after_second.current_instrument == "NSE:RELIANCE"
    assert after_second.universe_processed == 1


@requires_postgres
@pytest.mark.django_db
def test_update_progress_always_bumps_last_progress_at() -> None:
    repo = DjangoScannerScanProgressRepository()
    repo.start_scan(
        "dhan",
        scan_id="scan-1",
        scan_started_at=WHEN,
        timeframe="5m",
        universe_total=1,
        strategies_total=1,
    )
    before = repo.get("dhan")
    assert before is not None

    repo.update_progress("dhan", status="SCANNING", universe_processed=1)
    after = repo.get("dhan")

    assert after is not None
    assert after.last_progress_at is not None
    assert before.last_progress_at is not None
    assert after.last_progress_at >= before.last_progress_at


@requires_postgres
@pytest.mark.django_db
def test_mark_idle_clears_current_instrument_and_strategy() -> None:
    repo = DjangoScannerScanProgressRepository()
    repo.start_scan(
        "dhan",
        scan_id="scan-1",
        scan_started_at=WHEN,
        timeframe="5m",
        universe_total=1,
        strategies_total=1,
    )
    repo.update_progress("dhan", status="SCANNING", current_instrument="NSE:TCS")

    repo.mark_idle("dhan")
    record = repo.get("dhan")

    assert record is not None
    assert record.status == "IDLE"
    assert record.current_instrument == ""
    assert record.current_strategy == ""
