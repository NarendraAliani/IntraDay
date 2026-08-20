# tests/unit/infrastructure/api/test_reports_views.py
#
# Checkpoint 64.10: vertical-slice coverage for the FIRST-EVER API
# wiring of any report-builder function in this project - mirrors
# test_signal_api.py's own established pattern (real Django test
# Client against the real URLconf, real persisted rows).
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.test import Client

from intraday.communication.contracts.signal_communication import (
    CommunicationChannel,
    DeliveryAttempt,
    DeliveryStatus,
    MessageTemplateId,
)
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.shared_kernel.contracts import Exchange, SignalId
from intraday.infrastructure.persistence.communication_ledger_repository import (
    DjangoCommunicationLedgerRepository,
)
from intraday.infrastructure.persistence.signal_repository import DjangoSignalRepository
from tests.postgres_utils import requires_postgres

READER_USERNAME = "reports_reader"  # noqa: S105
PASSWORD = "correct-horse-battery-staple"  # noqa: S105

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")


def _client() -> Client:
    User.objects.create_user(username=READER_USERNAME, password=PASSWORD)
    client = Client()
    assert client.login(username=READER_USERNAME, password=PASSWORD)
    return client


def _record_signal(
    signal_id: str, *, risk_status: str = "APPROVED", direction: str = "BULLISH"
) -> None:
    DjangoSignalRepository().record_signal(
        signal_id=SignalId(signal_id),
        strategy_id="ema_crossover",
        instrument_id=RELIANCE,
        direction=direction,
        price=Decimal("100"),
        timeframe="Timeframe.ONE_MINUTE",
        signal_timestamp=datetime(2026, 1, 5, 6, 0, tzinfo=UTC),
        risk_status=risk_status,
        risk_reason="",
        order_status="FILLED" if risk_status == "APPROVED" else "",
    )


@requires_postgres
@pytest.mark.django_db
def test_signal_report_endpoint_requires_authentication() -> None:
    response = Client().get("/api/v1/config/reports/signals/")
    assert response.status_code in (401, 403)


@requires_postgres
@pytest.mark.django_db
def test_signal_report_returns_an_honest_all_zero_report_with_no_data() -> None:
    client = _client()

    response = client.get("/api/v1/config/reports/signals/")

    assert response.status_code == 200
    body = response.json()
    assert body["total_signals"] == 0
    assert body["by_strategy"] == {}


@requires_postgres
@pytest.mark.django_db
def test_signal_report_aggregates_real_persisted_signals() -> None:
    _record_signal("sig-1", risk_status="APPROVED", direction="BULLISH")
    _record_signal("sig-2", risk_status="REJECTED", direction="BEARISH")
    client = _client()

    response = client.get("/api/v1/config/reports/signals/")

    assert response.status_code == 200
    body = response.json()
    assert body["total_signals"] == 2
    assert body["buy_count"] == 1
    assert body["sell_count"] == 1
    assert body["risk_accepted"] == 1
    assert body["risk_rejected"] == 1
    assert body["by_strategy"] == {"ema_crossover": 2}


@requires_postgres
@pytest.mark.django_db
def test_signal_report_honors_the_risk_status_filter() -> None:
    _record_signal("sig-a", risk_status="APPROVED")
    _record_signal("sig-b", risk_status="REJECTED")
    client = _client()

    response = client.get("/api/v1/config/reports/signals/?risk_status=REJECTED")

    assert response.status_code == 200
    assert response.json()["total_signals"] == 1


@requires_postgres
@pytest.mark.django_db
def test_communication_report_reflects_real_ledger_rows_never_a_credential() -> None:
    _record_signal("sig-1")
    ledger = DjangoCommunicationLedgerRepository()
    ledger.record_attempt(
        DeliveryAttempt(
            communication_id="comm-1",
            signal_id=SignalId("sig-1"),
            event_id="event-1",
            channel=CommunicationChannel.TELEGRAM,
            provider="telegram",
            destination_masked="****abcd",
            template_id=MessageTemplateId.VALIDATED_SIGNAL,
            template_version="v1",
            created_at=datetime(2026, 1, 5, 6, 0, tzinfo=UTC),
            attempted_at=datetime(2026, 1, 5, 6, 0, tzinfo=UTC),
            delivery_status=DeliveryStatus.SENT,
            provider_message_id="msg-1",
            error_code=None,
            error_message=None,
            retry_count=0,
            correlation_id="corr-1",
        )
    )
    client = _client()

    response = client.get("/api/v1/config/reports/communication/")

    assert response.status_code == 200
    body = response.json()
    assert body["total_attempts"] == 1
    assert body["sent_count"] == 1
    assert body["by_channel"] == {"TELEGRAM": 1}
    assert "token" not in str(body).lower()
    assert "webhook" not in str(body).lower()


@requires_postgres
@pytest.mark.django_db
def test_daily_session_report_defaults_to_today_and_is_honestly_empty() -> None:
    client = _client()

    response = client.get("/api/v1/config/reports/daily-session/")

    assert response.status_code == 200
    body = response.json()
    assert body["total_signals"] == 0
    assert body["system_health"] is None
    assert body["realized_pnl_total"] is None


@requires_postgres
@pytest.mark.django_db
def test_daily_session_report_aggregates_a_real_session_by_date() -> None:
    _record_signal("sig-1", risk_status="APPROVED")
    client = _client()

    response = client.get("/api/v1/config/reports/daily-session/?date=2026-01-05")

    assert response.status_code == 200
    body = response.json()
    assert body["session_date"] == "2026-01-05"
    assert body["total_signals"] == 1
    assert body["risk_accepted"] == 1
    assert body["strategies"] == ["ema_crossover"]


@requires_postgres
@pytest.mark.django_db
def test_daily_session_report_excludes_signals_from_other_dates() -> None:
    _record_signal("sig-1", risk_status="APPROVED")
    client = _client()

    response = client.get("/api/v1/config/reports/daily-session/?date=2026-01-06")

    assert response.status_code == 200
    assert response.json()["total_signals"] == 0
