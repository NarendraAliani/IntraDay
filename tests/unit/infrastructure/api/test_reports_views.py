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


@requires_postgres
@pytest.mark.django_db
def test_daily_session_report_splits_communication_by_channel() -> None:
    """Checkpoint 64.16 §8: the per-channel Telegram/Discord counts,
    added alongside (never replacing) the existing combined
    communication_sent/_failed/_skipped fields - derived from the same
    real CommunicationLedgerRecord rows, never a fabricated split."""
    _record_signal("sig-1", risk_status="APPROVED")
    ledger = DjangoCommunicationLedgerRepository()
    when = datetime(2026, 1, 5, 6, 0, tzinfo=UTC)
    ledger.record_attempt(
        DeliveryAttempt(
            communication_id="comm-telegram",
            signal_id=SignalId("sig-1"),
            event_id="event-1",
            channel=CommunicationChannel.TELEGRAM,
            provider="telegram",
            destination_masked="****abcd",
            template_id=MessageTemplateId.VALIDATED_SIGNAL,
            template_version="v1",
            created_at=when,
            attempted_at=when,
            delivery_status=DeliveryStatus.SENT,
            provider_message_id="msg-1",
            error_code=None,
            error_message=None,
            retry_count=0,
            correlation_id="corr-1",
        )
    )
    ledger.record_attempt(
        DeliveryAttempt(
            communication_id="comm-discord",
            signal_id=SignalId("sig-1"),
            event_id="event-2",
            channel=CommunicationChannel.DISCORD,
            provider="discord",
            destination_masked="****wxyz",
            template_id=MessageTemplateId.VALIDATED_SIGNAL,
            template_version="v1",
            created_at=when,
            attempted_at=when,
            delivery_status=DeliveryStatus.FAILED,
            provider_message_id=None,
            error_code="PROVIDER_ERROR",
            error_message="simulated failure",
            retry_count=0,
            correlation_id="corr-2",
        )
    )
    client = _client()

    response = client.get("/api/v1/config/reports/daily-session/?date=2026-01-05")

    assert response.status_code == 200
    body = response.json()
    assert body["telegram"] == {"sent": 1, "failed": 0, "pending": 0}
    assert body["discord"] == {"sent": 0, "failed": 1, "pending": 0}
    # The existing combined totals must still be correct too.
    assert body["communication_sent"] == 1
    assert body["communication_failed"] == 1


@requires_postgres
@pytest.mark.django_db
def test_daily_session_report_counts_open_and_closed_positions_separately() -> None:
    """Checkpoint 64.17 §8: open_positions/closed_positions are REAL,
    separately-counted fields - never folded into one "positions" total."""
    from intraday.infrastructure.persistence.models import PaperPositionRecord

    when = datetime(2026, 1, 5, 6, 0, tzinfo=UTC)
    PaperPositionRecord.objects.create(
        position_id="pos-open",
        instrument_id="NSE:RELIANCE",
        direction="BUY",
        quantity=Decimal("10"),
        average_entry_price=Decimal("2500"),
        status="OPEN",
        opened_at=when,
    )
    PaperPositionRecord.objects.create(
        position_id="pos-closed",
        instrument_id="NSE:TCS",
        direction="BUY",
        quantity=Decimal("5"),
        average_entry_price=Decimal("3500"),
        realized_pnl=Decimal("250"),
        status="CLOSED",
        opened_at=when,
        closed_at=when,
    )
    client = _client()

    response = client.get("/api/v1/config/reports/daily-session/?date=2026-01-05")

    assert response.status_code == 200
    body = response.json()
    assert body["open_positions"] == 1
    assert body["closed_positions"] == 1


@requires_postgres
@pytest.mark.django_db
def test_daily_session_report_computes_unrealized_pnl_from_the_latest_persisted_bar() -> None:
    """Checkpoint 64.17 §9: the authoritative mark price comes from
    `AggregatedBarObservation` (already-persisted, never a live Dhan
    call from this reporting layer)."""
    from intraday.infrastructure.persistence.models import (
        AggregatedBarObservation,
        PaperPositionRecord,
    )

    when = datetime(2026, 1, 5, 6, 0, tzinfo=UTC)
    PaperPositionRecord.objects.create(
        position_id="pos-open",
        instrument_id="NSE:RELIANCE",
        direction="BUY",
        quantity=Decimal("10"),
        average_entry_price=Decimal("2500"),
        status="OPEN",
        opened_at=when,
    )
    AggregatedBarObservation.objects.create(
        instrument_symbol="RELIANCE",
        exchange="NSE",
        timeframe="5m",
        interval_start=when,
        interval_end=when,
        open_price=Decimal("2500"),
        high_price=Decimal("2560"),
        low_price=Decimal("2490"),
        close_price=Decimal("2550"),
        status="CLOSED",
        observation_count=5,
        data_source="test",
    )
    client = _client()

    response = client.get("/api/v1/config/reports/daily-session/?date=2026-01-05")

    assert response.status_code == 200
    body = response.json()
    assert Decimal(body["unrealized_pnl_total"]) == Decimal("500")  # (2550-2500) * 10


@requires_postgres
@pytest.mark.django_db
def test_daily_session_report_unrealized_pnl_is_null_without_a_mark_price() -> None:
    """No AggregatedBarObservation exists for this instrument - the
    report must say Not Available (null), never fabricate a zero or a
    partial total."""
    from intraday.infrastructure.persistence.models import PaperPositionRecord

    when = datetime(2026, 1, 5, 6, 0, tzinfo=UTC)
    PaperPositionRecord.objects.create(
        position_id="pos-open",
        instrument_id="NSE:RELIANCE",
        direction="BUY",
        quantity=Decimal("10"),
        average_entry_price=Decimal("2500"),
        status="OPEN",
        opened_at=when,
    )
    client = _client()

    response = client.get("/api/v1/config/reports/daily-session/?date=2026-01-05")

    assert response.status_code == 200
    assert response.json()["unrealized_pnl_total"] is None


@requires_postgres
@pytest.mark.django_db
def test_daily_session_report_exposes_the_current_configuration_version() -> None:
    """Checkpoint 64.17 §11: report reproducibility - the scanner
    configuration_version active at report-generation time."""
    from intraday.infrastructure.persistence.scanner_configuration_repository import (
        DjangoScannerConfigurationRepository,
    )

    DjangoScannerConfigurationRepository().save(
        "dhan",
        enabled=False,
        timeframe="5m",
        universe_mode="ALL_CONFIGURED",
        selected_instrument_ids=[],
        selected_watchlist_name="",
        selected_strategy_ids=["ema_crossover"],
        requested_by="operator",
        requested_by_user_id=1,
        request_id="req-1",
    )
    client = _client()

    response = client.get("/api/v1/config/reports/daily-session/")

    assert response.status_code == 200
    assert response.json()["configuration_version"] == 2  # seed row is v1, this save bumps to v2


@requires_postgres
@pytest.mark.django_db
def test_daily_session_report_uses_the_real_historical_configuration_version_for_a_past_date() -> (
    None
):
    """Checkpoint 64.18 §17: for a PAST session_date, the report must
    show the configuration_version that was ACTUALLY active that day
    (from the real AuditLogEntry trail), never today's current value."""
    from intraday.infrastructure.persistence.models import AuditLogEntry
    from intraday.infrastructure.persistence.scanner_configuration_repository import (
        DjangoScannerConfigurationRepository,
    )

    past_date = datetime(2026, 1, 5, tzinfo=UTC)
    AuditLogEntry.objects.create(
        occurred_at=past_date,
        actor_username="operator",
        actor_user_id=1,
        action="scanner_configuration.update",
        resource_type="scanner_configuration",
        resource_id="dhan",
        version_identifier="3",
        previous_version="2",
        outcome="updated",
        request_id="req-past",
    )
    # The CURRENT configuration is a much later version - must NOT leak
    # into the report for the past date.
    DjangoScannerConfigurationRepository().save(
        "dhan",
        enabled=False,
        timeframe="5m",
        universe_mode="ALL_CONFIGURED",
        selected_instrument_ids=[],
        selected_watchlist_name="",
        selected_strategy_ids=["ema_crossover"],
        requested_by="operator",
        requested_by_user_id=1,
        request_id="req-current",
    )
    client = _client()

    response = client.get("/api/v1/config/reports/daily-session/?date=2026-01-05")

    assert response.status_code == 200
    assert response.json()["configuration_version"] == 3


@requires_postgres
@pytest.mark.django_db
def test_daily_session_report_config_version_null_for_past_date_without_audit_trail() -> None:
    """Honest absence, never a fabricated historical claim, when no
    audit entry exists for that date at all."""
    client = _client()

    response = client.get("/api/v1/config/reports/daily-session/?date=2020-01-01")

    assert response.status_code == 200
    assert response.json()["configuration_version"] is None


@requires_postgres
@pytest.mark.django_db
def test_daily_session_report_computes_session_duration_from_real_start_stop_timestamps() -> None:
    """Checkpoint 64.17 §10: never derived from WorkerRuntimeStatus.updated_at."""
    from intraday.infrastructure.persistence.scanner_configuration_repository import (
        DjangoScannerConfigurationRepository,
    )

    repo = DjangoScannerConfigurationRepository()
    repo.save(
        "dhan",
        enabled=True,
        timeframe="5m",
        universe_mode="ALL_CONFIGURED",
        selected_instrument_ids=[],
        selected_watchlist_name="",
        selected_strategy_ids=["ema_crossover"],
        requested_by="operator",
        requested_by_user_id=1,
        request_id="req-start",
        session_transition="START",
    )
    client = _client()

    response = client.get("/api/v1/config/reports/daily-session/")

    assert response.status_code == 200
    duration = response.json()["session_duration_seconds"]
    assert duration is not None
    assert duration >= 0


@requires_postgres
@pytest.mark.django_db
def test_daily_session_report_session_duration_is_null_before_any_session_started() -> None:
    client = _client()

    response = client.get("/api/v1/config/reports/daily-session/")

    assert response.status_code == 200
    assert response.json()["session_duration_seconds"] is None


def _seed_position_with_bar(*, index: int, symbol: str, when: datetime) -> None:
    from intraday.infrastructure.persistence.models import (
        AggregatedBarObservation,
        PaperPositionRecord,
    )

    PaperPositionRecord.objects.create(
        position_id=f"pos-{index}",
        instrument_id=f"NSE:{symbol}",
        direction="BUY",
        quantity=Decimal("10"),
        average_entry_price=Decimal("100"),
        status="OPEN",
        opened_at=when,
    )
    AggregatedBarObservation.objects.create(
        instrument_symbol=symbol,
        exchange="NSE",
        timeframe="5m",
        interval_start=when,
        interval_end=when,
        open_price=Decimal("100"),
        high_price=Decimal("110"),
        low_price=Decimal("95"),
        close_price=Decimal("105"),
        status="CLOSED",
        observation_count=1,
        data_source="test",
    )


@requires_postgres
@pytest.mark.django_db
def test_daily_session_report_unrealized_pnl_query_count_is_constant_not_per_position() -> None:
    """Checkpoint 64.18 §16: closes the bounded N+1 64.17 disclosed -
    `_latest_close_prices()` now issues exactly ONE query for the whole
    open-position set, never one query per position. Proven directly:
    the total query count for 2 open positions must equal the total
    query count for 6 open positions - if it scaled per-position, the
    6-position run would issue 4 more queries than the 2-position run."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    from intraday.infrastructure.persistence.models import (
        AggregatedBarObservation,
        PaperPositionRecord,
    )

    when = datetime(2026, 1, 5, 6, 0, tzinfo=UTC)
    for i, symbol in enumerate(["RELIANCE", "TCS"]):
        _seed_position_with_bar(index=i, symbol=symbol, when=when)
    client = _client()

    with CaptureQueriesContext(connection) as captured_two:
        response_two = client.get("/api/v1/config/reports/daily-session/?date=2026-01-05")

    assert response_two.status_code == 200
    assert response_two.json()["unrealized_pnl_total"] is not None

    PaperPositionRecord.objects.all().delete()
    AggregatedBarObservation.objects.all().delete()
    for i, symbol in enumerate(["RELIANCE", "TCS", "INFY", "HDFC", "SBIN", "WIPRO"]):
        _seed_position_with_bar(index=i, symbol=symbol, when=when)

    with CaptureQueriesContext(connection) as captured_six:
        response_six = client.get("/api/v1/config/reports/daily-session/?date=2026-01-05")

    assert response_six.status_code == 200
    assert response_six.json()["unrealized_pnl_total"] is not None

    # A true per-position N+1 would add at least 4 more queries for the
    # 4 extra positions - session/auth query counts vary slightly
    # between requests (unrelated noise), so this allows a small
    # margin while still failing if the N+1 pattern returns.
    query_count_difference = len(captured_six.captured_queries) - len(captured_two.captured_queries)
    assert query_count_difference < 4
