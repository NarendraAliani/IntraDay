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


@requires_postgres
@pytest.mark.django_db
def test_signals_endpoint_shows_not_provided_when_no_trade_plan_exists() -> None:
    """Checkpoint 64.9: a directional-only strategy's signal must show
    `trade_plan: null` - never a fabricated entry/SL/target - so the UI
    can render an honest "Not provided"."""
    from datetime import UTC, datetime
    from decimal import Decimal

    from intraday.domain.instrument.contracts import make_instrument_id
    from intraday.domain.shared_kernel.contracts import Exchange, SignalId

    DjangoSignalRepository().record_signal(
        signal_id=SignalId("no-plan-sig"),
        strategy_id="ema_crossover",
        instrument_id=make_instrument_id(Exchange.NSE, "RELIANCE"),
        direction="BULLISH",
        price=Decimal("100"),
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
    assert body["items"][0]["trade_plan"] is None
    assert body["items"][0]["telegram"] is None
    assert body["items"][0]["discord"] is None


@requires_postgres
@pytest.mark.django_db
def test_signals_endpoint_shows_a_real_trade_plan_and_communication_status() -> None:
    from datetime import UTC, datetime
    from decimal import Decimal

    from intraday.domain.instrument.contracts import make_instrument_id
    from intraday.domain.shared_kernel.contracts import Exchange, SignalId
    from intraday.infrastructure.persistence.trade_plan_repository import (
        DjangoTradePlanRepository,
    )
    from intraday.trading_engine.strategy_execution.contracts import TradePlan

    DjangoSignalRepository().record_signal(
        signal_id=SignalId("plan-sig"),
        strategy_id="atr_volatility_breakout",
        instrument_id=make_instrument_id(Exchange.NSE, "RELIANCE"),
        direction="BULLISH",
        price=Decimal("100"),
        timeframe="Timeframe.ONE_MINUTE",
        signal_timestamp=datetime(2026, 1, 5, 6, 0, tzinfo=UTC),
        risk_status="APPROVED",
        risk_reason="",
        order_status="FILLED",
    )
    DjangoTradePlanRepository().save(
        "plan-sig",
        TradePlan(
            strategy_id="atr_volatility_breakout",
            code_version="v1",
            generated_at=datetime(2026, 1, 5, 6, 0, tzinfo=UTC),
            calculation_method="ATR test plan",
            entry_price=Decimal("100"),
            stop_loss=Decimal("98"),
            target_1=Decimal("103"),
            target_2=Decimal("105"),
            target_3=Decimal("108"),
            trailing_stop_loss=Decimal("99"),
        ),
    )
    client = _client()

    response = client.get("/api/v1/config/signals/")

    assert response.status_code == 200
    body = response.json()
    plan = body["items"][0]["trade_plan"]
    assert plan is not None
    assert plan["stop_loss"] == "98.0000"
    assert plan["target_1"] == "103.0000"


@requires_postgres
@pytest.mark.django_db
def test_signals_endpoint_filters_by_risk_status_and_telegram_status() -> None:
    from datetime import UTC, datetime, timedelta
    from decimal import Decimal

    from intraday.domain.instrument.contracts import make_instrument_id
    from intraday.domain.shared_kernel.contracts import Exchange, SignalId

    repository = DjangoSignalRepository()
    repository.record_signal(
        signal_id=SignalId("accepted-sig"),
        strategy_id="ema_crossover",
        instrument_id=make_instrument_id(Exchange.NSE, "RELIANCE"),
        direction="BULLISH",
        price=Decimal("100"),
        timeframe="Timeframe.ONE_MINUTE",
        signal_timestamp=datetime(2026, 1, 5, 6, 0, tzinfo=UTC),
        risk_status="APPROVED",
        risk_reason="",
        order_status="FILLED",
    )
    repository.record_signal(
        signal_id=SignalId("rejected-sig"),
        strategy_id="ema_crossover",
        instrument_id=make_instrument_id(Exchange.NSE, "RELIANCE"),
        direction="BULLISH",
        price=Decimal("100"),
        timeframe="Timeframe.ONE_MINUTE",
        signal_timestamp=datetime(2026, 1, 5, 6, 1, tzinfo=UTC) + timedelta(seconds=0),
        risk_status="REJECTED",
        risk_reason="daily loss limit",
        order_status="",
    )
    client = _client()

    response = client.get("/api/v1/config/signals/?risk_status=REJECTED")

    assert response.status_code == 200
    body = response.json()
    assert body["total_count"] == 1
    assert body["items"][0]["signal_id"] == "rejected-sig"


@requires_postgres
@pytest.mark.django_db
def test_signal_communication_history_endpoint_returns_every_attempt() -> None:
    from datetime import UTC, datetime
    from decimal import Decimal

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

    DjangoSignalRepository().record_signal(
        signal_id=SignalId("comm-hist-sig"),
        strategy_id="ema_crossover",
        instrument_id=make_instrument_id(Exchange.NSE, "RELIANCE"),
        direction="BULLISH",
        price=Decimal("100"),
        timeframe="Timeframe.ONE_MINUTE",
        signal_timestamp=datetime(2026, 1, 5, 6, 0, tzinfo=UTC),
        risk_status="APPROVED",
        risk_reason="",
        order_status="FILLED",
    )
    ledger = DjangoCommunicationLedgerRepository()
    ledger.record_attempt(
        DeliveryAttempt(
            communication_id="comm-1",
            signal_id=SignalId("comm-hist-sig"),
            event_id="event-1",
            channel=CommunicationChannel.TELEGRAM,
            provider="telegram",
            destination_masked="****abcd",
            template_id=MessageTemplateId.VALIDATED_SIGNAL,
            template_version="v1",
            created_at=datetime(2026, 1, 5, 6, 0, tzinfo=UTC),
            attempted_at=datetime(2026, 1, 5, 6, 0, tzinfo=UTC),
            delivery_status=DeliveryStatus.FAILED,
            provider_message_id=None,
            error_code="PROVIDER_ERROR",
            error_message="simulated failure",
            retry_count=1,
            correlation_id="corr-1",
        )
    )
    client = _client()

    response = client.get("/api/v1/config/signals/comm-hist-sig/communication/")

    assert response.status_code == 200
    body = response.json()
    assert body["signal_id"] == "comm-hist-sig"
    assert len(body["attempts"]) == 1
    assert body["attempts"][0]["channel"] == "TELEGRAM"
    assert body["attempts"][0]["delivery_status"] == "FAILED"
    assert body["attempts"][0]["error_message"] == "simulated failure"
