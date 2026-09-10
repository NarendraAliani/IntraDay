# tests/unit/infrastructure/api/test_watchlist_market_data_api.py
#
# CHECKPOINT-WATCHLIST-A, Phase A of WATCHLIST_REDESIGN_ROADMAP.md:
# API-level coverage for the read-only, thin
# `GET /watchlists/<name>/market-data/` endpoint. Real `HistoricalBar`
# fixtures (real PostgreSQL, `@requires_postgres`), real
# `ResearchDataGateService`/`WorkerRuntimeStatus` reads - never mocked
# gate logic, matching this project's own established discipline
# (`test_screening_api.py`'s own precedent, reused verbatim here).
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.test import Client

from intraday.application.services.historical_data_coverage import _expected_timestamps
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.provenance import PROVENANCE_REAL_DHAN
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe
from intraday.infrastructure.persistence.models import (
    AggregatedBarObservation,
    HistoricalBar,
    LiveQuoteObservation,
    WorkerRuntimeStatus,
)
from tests.postgres_utils import requires_postgres

USERNAME = "watchlist-md-tester"  # noqa: S105
PASSWORD = "correct-horse-battery-staple"  # noqa: S105

# Checkpoint 67.12.2-O's own established convention, reused verbatim
# from `test_screening_api.py`: the one empirically-proven (NSE_EQ, 5m,
# CAS_ERA) date `ResearchDataGateService` actually accepts REAL_DHAN +
# CANONICALIZED rows for.
CAS_ERA_TRADING_DATE = date(2026, 8, 17)
RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
TCS = make_instrument_id(Exchange.NSE, "TCS")

# The view resolves its own sparkline/change% window as "the last
# `_SPARKLINE_LOOKBACK_CALENDAR_DAYS` calendar days ending now" - real
# "now" (this session's real current date) is weeks past the one
# empirically-proven gate-eligible date above, so every test in this
# file pins the view's own `_now()` to just after that date's market
# close instead, exactly as CHECKPOINT-SCANNER-B's own test precedent
# would if it needed a NOW-relative window (it does not - screening
# takes an explicit date range on the wire).
_FIXED_NOW = datetime(2026, 8, 17, 11, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _pinned_now():
    # 2026-08-17 is a Monday; a 1-calendar-day lookback from `_FIXED_NOW`
    # spans only Sunday 8/16 (not a trading day) + Monday 8/17 itself -
    # exactly the one gate-eligible trading day these fixtures build,
    # so the gate's whole-window completeness check is satisfiable
    # without fabricating weeks of surrounding fixture data. Production
    # keeps the real `_SPARKLINE_LOOKBACK_CALENDAR_DAYS` - only this
    # test's own window is narrowed.
    with (
        patch(
            "intraday.infrastructure.api.watchlist_market_data_views._now",
            return_value=_FIXED_NOW,
        ),
        patch(
            "intraday.infrastructure.api.watchlist_market_data_views."
            "_SPARKLINE_LOOKBACK_CALENDAR_DAYS",
            1,
        ),
    ):
        yield


def _login_client() -> Client:
    User.objects.create_user(username=USERNAME, password=PASSWORD)
    client = Client()
    assert client.login(username=USERNAME, password=PASSWORD)
    return client


def _save_watchlist(client: Client, name: str, instrument_ids: list[str]) -> None:
    response = client.post(
        "/api/v1/config/watchlists/save/",
        data={"name": name, "instrument_ids": instrument_ids},
        content_type="application/json",
    )
    assert response.status_code == 201, response.content


def _gate_verified_bars(instrument_id, closes: list[float]) -> None:
    """Builds a full, gate-eligible day of `HistoricalBar` rows for
    `instrument_id` on `CAS_ERA_TRADING_DATE` - reused verbatim from
    `test_screening_api.py`'s own established fixture builder."""
    timestamps = _expected_timestamps(
        datetime(2026, 8, 17, 3, 45, tzinfo=UTC),
        datetime(2026, 8, 17, 10, 0, tzinfo=UTC),
        Timeframe.FIVE_MINUTE,
        instrument_id,
    )
    assert len(timestamps) == len(closes), (
        f"fixture must supply exactly {len(timestamps)} closes for a complete day, got {len(closes)}"
    )
    exchange, symbol = str(instrument_id).split(":")
    rows = []
    for ts, close in zip(timestamps, closes, strict=True):
        c = Decimal(str(close))
        rows.append(
            HistoricalBar(
                instrument_id=str(instrument_id),
                exchange=exchange,
                symbol=symbol,
                timeframe="5m",
                bar_timestamp=ts,
                open_price=c,
                high_price=c + Decimal("1"),
                low_price=c - Decimal("1"),
                close_price=c,
                volume=Decimal("1000"),
                source="API_FETCH",
                provenance=PROVENANCE_REAL_DHAN,
                canonicalization_state="CANONICALIZED",
                source_timestamp_semantics="CLOSE",
            )
        )
    HistoricalBar.objects.bulk_create(rows)


def _market_data_url(name: str) -> str:
    return f"/api/v1/config/watchlists/{name}/market-data/"


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_gate_verified_instrument_reports_historical_price_and_sparkline() -> None:
    client = _login_client()
    _save_watchlist(client, "gate-ok", [str(RELIANCE)])
    _gate_verified_bars(RELIANCE, [100 + i for i in range(72)])  # last close = 171

    response = client.get(_market_data_url("gate-ok"))
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["mode"] == "HISTORICAL"
    result = body["results"][0]
    assert result["instrument_id"] == str(RELIANCE)
    assert result["gate_status"] == "OK"
    assert result["price_source"] == "HISTORICAL"
    assert Decimal(result["price"]) == Decimal("171.0000")
    assert result["volume_basis"] == "HISTORICAL_DAY"
    assert result["sparkline"] == [result["price"]]  # only one gate-verified trading day
    assert result["as_of"] == "2026-08-17 close"
    # Only one trading day in range -> no prior close to compare against.
    assert result["change_percent"] is None


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_no_data_instrument_reports_not_gate_verified_honestly() -> None:
    client = _login_client()
    _save_watchlist(client, "no-data", [str(TCS)])
    # TCS has zero bars anywhere - genuinely no data.

    response = client.get(_market_data_url("no-data"))
    assert response.status_code == 200, response.content
    result = response.json()["results"][0]
    assert result["gate_status"] == "NOT_GATE_VERIFIED"
    assert result["coverage_detail"] != ""
    assert result["price"] is None
    assert result["price_source"] == ""
    assert result["sparkline"] == []
    assert result["change_percent"] is None


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_mixed_watchlist_reports_each_instrument_independently() -> None:
    client = _login_client()
    _save_watchlist(client, "mixed", [str(RELIANCE), str(TCS)])
    _gate_verified_bars(RELIANCE, [100 + i for i in range(72)])
    # TCS left with zero bars.

    response = client.get(_market_data_url("mixed"))
    assert response.status_code == 200, response.content
    results_by_id = {r["instrument_id"]: r for r in response.json()["results"]}
    assert results_by_id[str(RELIANCE)]["gate_status"] == "OK"
    assert results_by_id[str(TCS)]["gate_status"] == "NOT_GATE_VERIFIED"


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_default_mode_is_historical_with_no_worker_running() -> None:
    """The roadmap's own explicit requirement: a watchlist must have a
    working default with ZERO live infrastructure running - no
    `WorkerRuntimeStatus` row exists at all in a fresh test DB."""
    client = _login_client()
    _save_watchlist(client, "quiet", [str(RELIANCE)])
    _gate_verified_bars(RELIANCE, [100 + i for i in range(72)])
    assert not WorkerRuntimeStatus.objects.filter(provider="dhan").exists()

    response = client.get(_market_data_url("quiet"))
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["mode"] == "HISTORICAL"
    assert body["results"][0]["price_source"] == "HISTORICAL"


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_live_mode_with_running_worker_and_fresh_quote_uses_live_price() -> None:
    client = _login_client()
    _save_watchlist(client, "live-list", [str(RELIANCE)])
    _gate_verified_bars(RELIANCE, [100 + i for i in range(72)])
    WorkerRuntimeStatus.objects.create(
        provider="dhan",
        worker_state="RUNNING",
        token_state="VALID",
        watchdog_state="HEALTHY",
        subscribed_instrument_count=1,
    )
    LiveQuoteObservation.objects.create(
        instrument_symbol="RELIANCE",
        exchange="NSE",
        last_price=Decimal("999.5000"),
        source_timestamp=_FIXED_NOW,
        fetched_at=_FIXED_NOW,
        cumulative_volume=Decimal("0"),
    )
    from datetime import timedelta

    AggregatedBarObservation.objects.create(
        instrument_symbol="RELIANCE",
        exchange="NSE",
        timeframe="1m",
        interval_start=_FIXED_NOW,
        interval_end=_FIXED_NOW + timedelta(minutes=1),
        open_price=Decimal("999"),
        high_price=Decimal("1000"),
        low_price=Decimal("998"),
        close_price=Decimal("999.5"),
        status="CLOSED",
        observation_count=1,
        data_source="LIVE_AGGREGATION",
        volume=Decimal("4200"),
        trading_date=_FIXED_NOW.date(),
    )

    response = client.get(_market_data_url("live-list"))
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["mode"] == "LIVE"
    result = body["results"][0]
    assert result["price_source"] == "LIVE"
    assert Decimal(result["price"]) == Decimal("999.5000")
    assert result["volume_basis"] == "SESSION_TO_DATE"
    assert Decimal(result["volume"]) == Decimal("4200.0000")
    # The daily-close data (sparkline/change%) is unaffected by LIVE mode.
    assert result["gate_status"] == "OK"
    assert result["sparkline"] != []


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_live_mode_with_running_worker_but_no_quote_falls_back_to_historical() -> None:
    """A worker can be running for OTHER instruments without this
    particular watchlist symbol ever having a fresh quote - must fall
    back to the historical row honestly, never error."""
    client = _login_client()
    _save_watchlist(client, "live-no-quote", [str(RELIANCE)])
    _gate_verified_bars(RELIANCE, [100 + i for i in range(72)])
    WorkerRuntimeStatus.objects.create(
        provider="dhan",
        worker_state="RUNNING",
        token_state="VALID",
        watchdog_state="HEALTHY",
        subscribed_instrument_count=0,
    )

    response = client.get(_market_data_url("live-no-quote"))
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["mode"] == "LIVE"  # the envelope reflects the worker being up
    result = body["results"][0]
    assert result["price_source"] == "HISTORICAL"  # but this row fell back honestly
    assert Decimal(result["price"]) == Decimal("171.0000")


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_unknown_watchlist_returns_404() -> None:
    client = _login_client()
    response = client.get(_market_data_url("does-not-exist"))
    assert response.status_code == 404


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_unauthenticated_request_is_rejected() -> None:
    client = Client()
    response = client.get(_market_data_url("anything"))
    assert response.status_code in (401, 403)
