# tests/unit/infrastructure/api/test_signal_api.py
#
# Checkpoint 62.x: vertical-slice coverage for the FIRST read-only
# signals API - mirrors test_market_data_api.py's own established
# pattern (real Django test Client against the real URLconf).
from __future__ import annotations

import pytest
from django.contrib.auth.models import User
from django.test import Client

from intraday.infrastructure.persistence.signal_repository import DjangoSignalRepository
from tests.postgres_utils import requires_postgres

READER_USERNAME = "signal_reader"  # noqa: S105
PASSWORD = "correct-horse-battery-staple"  # noqa: S105


def _client() -> Client:
    User.objects.create_user(username=READER_USERNAME, password=PASSWORD)
    client = Client()
    assert client.login(username=READER_USERNAME, password=PASSWORD)
    return client


@requires_postgres
@pytest.mark.django_db
def test_signals_endpoint_requires_authentication() -> None:
    response = Client().get("/api/v1/config/signals/")
    assert response.status_code in (401, 403)


@requires_postgres
@pytest.mark.django_db
def test_signals_endpoint_returns_empty_list_honestly_when_none_exist() -> None:
    """No fabricated rows - a fresh system with zero real signals must
    report an honest empty page, never invented data."""
    client = _client()

    response = client.get("/api/v1/config/signals/")

    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert body["total_count"] == 0


@requires_postgres
@pytest.mark.django_db
def test_signals_endpoint_returns_a_real_persisted_signal() -> None:
    from datetime import UTC, datetime
    from decimal import Decimal

    from intraday.domain.instrument.contracts import make_instrument_id
    from intraday.domain.shared_kernel.contracts import Exchange, SignalId

    DjangoSignalRepository().record_signal(
        signal_id=SignalId("api-test-sig-1"),
        strategy_id="ema_crossover",
        instrument_id=make_instrument_id(Exchange.NSE, "RELIANCE"),
        direction="BULLISH",
        price=Decimal("2900.50"),
        timeframe="Timeframe.ONE_MINUTE",
        signal_timestamp=datetime(2026, 1, 5, 6, 0, tzinfo=UTC),
        risk_status="APPROVED",
        risk_reason="",
        order_status="FILLED",
    )
    client = _client()

    response = client.get("/api/v1/config/signals/")

    assert response.status_code == 200
    body = response.json()
    assert body["total_count"] == 1
    assert body["items"][0]["signal_id"] == "api-test-sig-1"
    assert body["items"][0]["strategy_id"] == "ema_crossover"
    assert body["items"][0]["direction"] == "BULLISH"
    assert body["items"][0]["risk_status"] == "APPROVED"


@requires_postgres
@pytest.mark.django_db
def test_signals_endpoint_pagination_query_params() -> None:
    from datetime import UTC, datetime, timedelta
    from decimal import Decimal

    from intraday.domain.instrument.contracts import make_instrument_id
    from intraday.domain.shared_kernel.contracts import Exchange, SignalId

    repository = DjangoSignalRepository()
    for i in range(3):
        repository.record_signal(
            signal_id=SignalId(f"pag-sig-{i}"),
            strategy_id="ema_crossover",
            instrument_id=make_instrument_id(Exchange.NSE, "RELIANCE"),
            direction="BULLISH",
            price=Decimal("100"),
            timeframe="Timeframe.ONE_MINUTE",
            signal_timestamp=datetime(2026, 1, 5, 6, 0, tzinfo=UTC) + timedelta(minutes=i),
            risk_status="APPROVED",
            risk_reason="",
            order_status="FILLED",
        )
    client = _client()

    response = client.get("/api/v1/config/signals/?page=1&page_size=2")

    assert response.status_code == 200
    body = response.json()
    assert body["total_count"] == 3
    assert len(body["items"]) == 2
    assert body["page"] == 1
    assert body["page_size"] == 2
