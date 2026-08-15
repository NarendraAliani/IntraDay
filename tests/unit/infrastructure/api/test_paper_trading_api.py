# tests/unit/infrastructure/api/test_paper_trading_api.py
#
# Checkpoint 35 Part 4/5/18: full vertical slice for the paper-trading
# read APIs and the order-submission endpoint - real Django ORM + DRF +
# RBAC, mirroring test_risk_api.py/test_kill_switch_api.py's own
# established pattern.
from __future__ import annotations

import pytest
from django.contrib.auth.models import Group, User
from django.test import Client

from intraday.infrastructure.api.paper_trading_runtime import (
    reset_paper_broker_for_testing,
)
from intraday.infrastructure.api.permissions import CONFIGURATION_OPERATOR_GROUP
from tests.postgres_utils import requires_postgres

READER_USERNAME = "pt-reader"  # noqa: S105 - test fixture username, not a secret
OPERATOR_USERNAME = "pt-operator"  # noqa: S105 - test fixture username, not a secret
PASSWORD = "correct-horse-battery-staple"  # noqa: S105 - test-only fixture credential


@pytest.fixture(autouse=True)
def _reset_paper_broker():  # type: ignore[no-untyped-def]
    reset_paper_broker_for_testing()
    yield
    reset_paper_broker_for_testing()


def _client_as_reader() -> Client:
    User.objects.create_user(username=READER_USERNAME, password=PASSWORD)
    client = Client()
    assert client.login(username=READER_USERNAME, password=PASSWORD)
    return client


def _client_as_operator() -> Client:
    user = User.objects.create_user(username=OPERATOR_USERNAME, password=PASSWORD)
    group, _ = Group.objects.get_or_create(name=CONFIGURATION_OPERATOR_GROUP)
    user.groups.add(group)
    client = Client()
    assert client.login(username=OPERATOR_USERNAME, password=PASSWORD)
    return client


@requires_postgres
@pytest.mark.django_db
def test_orders_empty_list_initially() -> None:
    response = _client_as_reader().get("/api/v1/config/paper-trading/orders/")
    assert response.status_code == 200
    assert response.json() == []


@requires_postgres
@pytest.mark.django_db
def test_reader_cannot_submit_order() -> None:
    response = _client_as_reader().post(
        "/api/v1/config/paper-trading/orders/submit/",
        {
            "instrument_id": "NSE:RELIANCE",
            "side": "BUY",
            "quantity": "10",
            "order_type": "MARKET",
            "strategy_id": "orb-v1",
        },
    )
    assert response.status_code == 403


@requires_postgres
@pytest.mark.django_db
def test_operator_submit_rejected_market_order_with_no_recorded_price() -> None:
    """No price has been recorded for the instrument this checkpoint's
    runtime - PaperBroker rejects the MARKET order (never fabricates a
    price) and this surfaces as a normal HTTP 200 with a REJECTED
    broker-side status, not an HTTP error."""
    client = _client_as_operator()
    response = client.post(
        "/api/v1/config/paper-trading/orders/submit/",
        {
            "instrument_id": "NSE:RELIANCE",
            "side": "BUY",
            "quantity": "10",
            "order_type": "MARKET",
            "strategy_id": "orb-v1",
        },
        content_type="application/json",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["risk_outcome"] == "APPROVED"
    assert body["order_status"] == "REJECTED"


@requires_postgres
@pytest.mark.django_db
def test_submitted_order_appears_in_orders_list() -> None:
    client = _client_as_operator()
    client.post(
        "/api/v1/config/paper-trading/orders/submit/",
        {
            "instrument_id": "NSE:RELIANCE",
            "side": "BUY",
            "quantity": "10",
            "order_type": "LIMIT",
            "limit_price": "100",
            "strategy_id": "orb-v1",
        },
        content_type="application/json",
    )
    orders = _client_as_reader().get("/api/v1/config/paper-trading/orders/").json()
    assert len(orders) == 1
    assert orders[0]["instrument_id"] == "NSE:RELIANCE"
    assert orders[0]["status"] == "PENDING"


@requires_postgres
@pytest.mark.django_db
def test_funds_endpoint_returns_initial_capital_when_untouched() -> None:
    response = _client_as_reader().get("/api/v1/config/paper-trading/funds/")
    assert response.status_code == 200
    assert response.json()["available_balance"] == "0.0000"


@requires_postgres
@pytest.mark.django_db
def test_anonymous_cannot_read_orders() -> None:
    response = Client().get("/api/v1/config/paper-trading/orders/")
    assert response.status_code in (401, 403)


@requires_postgres
@pytest.mark.django_db
def test_kill_switch_blocks_paper_order_submission_via_api() -> None:
    client = _client_as_operator()
    client.post(
        "/api/v1/config/kill-switch/engage/",
        {"reason": "test halt"},
        content_type="application/json",
    )
    response = client.post(
        "/api/v1/config/paper-trading/orders/submit/",
        {
            "instrument_id": "NSE:RELIANCE",
            "side": "BUY",
            "quantity": "10",
            "order_type": "MARKET",
            "strategy_id": "orb-v1",
        },
        content_type="application/json",
    )
    assert response.status_code == 200
    body = response.json()
    assert body["risk_outcome"] == "REJECTED"
    assert body["risk_reason_code"] == "KILL_SWITCH_ENGAGED"
    assert body["order_status"] is None

    client.post("/api/v1/config/kill-switch/reset/")


@requires_postgres
@pytest.mark.django_db
def test_expire_session_expires_pending_orders() -> None:
    client = _client_as_operator()
    submit_response = client.post(
        "/api/v1/config/paper-trading/orders/submit/",
        {
            "instrument_id": "NSE:RELIANCE",
            "side": "BUY",
            "quantity": "10",
            "order_type": "LIMIT",
            "limit_price": "1",
            "strategy_id": "orb-v1",
        },
        content_type="application/json",
    )
    assert submit_response.json()["order_status"] == "PENDING"

    expire_response = client.post("/api/v1/config/paper-trading/expire-session/")
    assert expire_response.status_code == 200
    assert len(expire_response.json()["expired_order_ids"]) == 1

    orders = _client_as_reader().get("/api/v1/config/paper-trading/orders/").json()
    assert orders[0]["status"] == "EXPIRED"


@requires_postgres
@pytest.mark.django_db
def test_reader_cannot_trigger_expiry() -> None:
    response = _client_as_reader().post("/api/v1/config/paper-trading/expire-session/")
    assert response.status_code == 403
