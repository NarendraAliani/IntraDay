# tests/unit/infrastructure/api/test_checkpoint_64_84_archive_reconciliation_fields.py
#
# Checkpoint 64.84: the archive read API must expose the PERSISTED
# reconciliation verdict without merging it into the archive status.
#
# The combination this file exists to protect is
# `archive_status: "COMPLETE"` + `reconciliation_status: "NOT_RECONCILED"`:
# it is valid, it is what every day in the real database looks like, and
# an API that could not express it would be pushing consumers toward
# treating "complete" as "validated".
from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from django.contrib.auth.models import User
from django.test import Client

from intraday.infrastructure.persistence.models import MarketDataArchiveDay
from tests.postgres_utils import requires_postgres

READER = "archive_reader_6484"
PASSWORD = "correct-horse-battery-staple"  # noqa: S105
TRADING_DAY = date(2026, 8, 24)
ARCHIVE_URL = f"/api/v1/market-data/archive/{TRADING_DAY.isoformat()}/"


def _client() -> Client:
    User.objects.create_user(username=READER, password=PASSWORD)
    client = Client()
    assert client.login(username=READER, password=PASSWORD)
    return client


def _cell(**overrides: object) -> MarketDataArchiveDay:
    defaults: dict[str, object] = {
        "exchange": "NSE",
        "trading_date": TRADING_DAY,
        "instrument_symbol": "RELIANCE",
        "timeframe": "1m",
        "data_source": "dhan",
        "status": "COMPLETE",
        "reason": "all_expected_bars_present",
        "completeness_supported": True,
        "expected_bar_count": 375,
        "closed_bar_count": 375,
        "missing_bar_count": 0,
        "quote_observation_count": 120,
    }
    return MarketDataArchiveDay.objects.create(**(defaults | overrides))


@requires_postgres
@pytest.mark.django_db
def test_complete_but_unreconciled_is_reported_as_exactly_that() -> None:
    _cell()

    body = _client().get(ARCHIVE_URL).json()
    (cell,) = body["cells"]

    assert cell["archive_status"] == "COMPLETE"
    assert cell["reconciliation_status"] == "NOT_RECONCILED"
    assert cell["reconciliation_outcome"] == "NOT_RECONCILED"
    assert cell["reconciled_at"] is None
    # `null`, not `""` - no reconciliation has been persisted at all,
    # which differs from "reconciled against an unnamed source".
    assert cell["reconciliation_evidence_source"] is None


@requires_postgres
@pytest.mark.django_db
def test_persisted_verdict_is_read_back_verbatim() -> None:
    """A PARTIAL verdict stores as NOT_RECONCILED but must remain
    recoverable in full - the coarse projection is additional
    information, never a replacement for the exact result."""
    reconciled_at = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
    _cell(
        reconciliation_status="NOT_RECONCILED",
        reconciliation_outcome="PARTIAL",
        reconciliation_reason="incomplete_coverage:observed_missing=5",
        reconciliation_evidence_source="dhan_historical_candle_api",
        reconciled_at=reconciled_at,
    )

    (cell,) = _client().get(ARCHIVE_URL).json()["cells"]

    assert cell["reconciliation_status"] == "NOT_RECONCILED"
    assert cell["reconciliation_outcome"] == "PARTIAL"
    assert cell["reconciliation_reason"] == "incomplete_coverage:observed_missing=5"
    assert cell["reconciliation_evidence_source"] == "dhan_historical_candle_api"
    assert cell["reconciled_at"] is not None
