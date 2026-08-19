# tests/unit/infrastructure/api/test_settings_api.py
#
# Checkpoint 22: full vertical-slice API coverage for the operational
# provider-settings endpoints - persisted credential -> repository ->
# application service -> DRF endpoint -> HTTP response -> stable JSON
# contract, mirroring test_risk_api.py's own established pattern
# (real Django test Client against the actual URLconf, gated by
# requires_postgres since these endpoints need the real ORM-backed
# repositories).
#
# Outbound connectivity (Dhan/Telegram/Discord HTTP clients) is mocked
# at the `infrastructure`/`communication` client boundary - these tests
# assert on the VIEW's handling of each outcome, not on live third-party
# APIs. No real or fake-but-real-looking credential is ever used; every
# secret value in this file is an obviously-fake placeholder string.
from __future__ import annotations

from unittest.mock import patch

import pytest
from django.contrib.auth.models import Group, User
from django.test import Client

from intraday.communication.contracts.connectivity import ConnectivityCheckResult
from intraday.infrastructure.api.permissions import CONFIGURATION_OPERATOR_GROUP
from intraday.infrastructure.brokers.dhan.client import DhanConnectivityResult
from intraday.infrastructure.persistence.models import AuditLogEntry
from tests.postgres_utils import requires_postgres

READER_USERNAME = "settings_reader"  # noqa: S105
OPERATOR_USERNAME = "settings_operator"  # noqa: S105
PASSWORD = "correct-horse-battery-staple"  # noqa: S105


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


# --- Authentication / authorization ----------------------------------------


@requires_postgres
@pytest.mark.django_db
def test_dhan_settings_requires_authentication() -> None:
    client = Client()

    response = client.get("/api/v1/config/settings/dhan/")

    assert response.status_code == 401


@requires_postgres
@pytest.mark.django_db
def test_dhan_settings_get_allowed_for_authenticated_reader() -> None:
    client = _client_as_reader()

    response = client.get("/api/v1/config/settings/dhan/")

    assert response.status_code == 200


@requires_postgres
@pytest.mark.django_db
def test_dhan_settings_save_forbidden_for_reader_without_operator_capability() -> None:
    client = _client_as_reader()

    response = client.post(
        "/api/v1/config/settings/dhan/save/",
        data={"client_id": "1000000123", "access_token": "fake-token", "enabled": True},
        content_type="application/json",
    )

    assert response.status_code == 403


@requires_postgres
@pytest.mark.django_db
def test_dhan_settings_save_allowed_for_operator() -> None:
    client = _client_as_operator()

    response = client.post(
        "/api/v1/config/settings/dhan/save/",
        data={"client_id": "1000000123", "access_token": "fake-token", "enabled": True},
        content_type="application/json",
    )

    assert response.status_code == 200


@requires_postgres
@pytest.mark.django_db
def test_dhan_test_connection_forbidden_for_reader() -> None:
    client = _client_as_reader()

    response = client.post("/api/v1/config/settings/dhan/test/")

    assert response.status_code == 403


# --- Secrets never appear in any response -----------------------------------


@requires_postgres
@pytest.mark.django_db
def test_dhan_settings_response_never_contains_raw_access_token() -> None:
    operator = _client_as_operator()
    operator.post(
        "/api/v1/config/settings/dhan/save/",
        data={
            "client_id": "1000000123",
            "access_token": "fake-super-secret-token-never-leak",
            "enabled": True,
        },
        content_type="application/json",
    )

    save_response = operator.get("/api/v1/config/settings/dhan/")

    assert save_response.status_code == 200
    assert "fake-super-secret-token-never-leak" not in save_response.content.decode()
    body = save_response.json()
    assert "access_token" not in body
    assert set(body.keys()) == {
        "client_id_masked",
        "client_id_source",
        "access_token_configured",
        "access_token_source",
        "enabled",
        "updated_at",
        "updated_by_username",
        "token_state",
        "token_expires_at",
    }
    # "fake-super-secret-token-never-leak" isn't a real JWT, so the
    # lifecycle evaluator correctly can't claim VALID/EXPIRED about it -
    # MALFORMED, never a guessed state (Checkpoint 64).
    assert body["token_state"] == "MALFORMED"  # noqa: S105 - a state name, not a password


@requires_postgres
@pytest.mark.django_db
def test_dhan_settings_reports_expired_for_a_real_shaped_but_expired_token() -> None:
    """Checkpoint 64: proves the exact real-world scenario this
    checkpoint's own live Dhan connectivity check found in THIS
    environment - a well-formed JWT access token past its own `exp`
    claim is reported EXPIRED through the real API, not left showing a
    stale "configured" state with no expiry signal at all."""
    import base64
    import json
    from datetime import UTC, datetime, timedelta

    expired_at = datetime.now(tz=UTC) - timedelta(hours=1)
    header = base64.urlsafe_b64encode(b'{"alg":"HS512","typ":"JWT"}').rstrip(b"=").decode()
    payload = (
        base64.urlsafe_b64encode(json.dumps({"exp": expired_at.timestamp()}).encode())
        .rstrip(b"=")
        .decode()
    )
    expired_jwt = f"{header}.{payload}.fake-signature-not-verified"

    operator = _client_as_operator()
    operator.post(
        "/api/v1/config/settings/dhan/save/",
        data={"client_id": "1000000123", "access_token": expired_jwt, "enabled": True},
        content_type="application/json",
    )

    response = operator.get("/api/v1/config/settings/dhan/")

    assert response.status_code == 200
    body = response.json()
    assert body["token_state"] == "EXPIRED"  # noqa: S105 - a state name, not a password
    assert body["token_expires_at"] is not None


@requires_postgres
@pytest.mark.django_db
def test_dhan_client_id_is_masked_in_the_response() -> None:
    client = _client_as_operator()
    client.post(
        "/api/v1/config/settings/dhan/save/",
        data={"client_id": "1000000123", "access_token": "fake-token", "enabled": True},
        content_type="application/json",
    )

    response = client.get("/api/v1/config/settings/dhan/")

    body = response.json()
    assert body["client_id_masked"] != "1000000123"


@requires_postgres
@pytest.mark.django_db
def test_telegram_settings_response_never_contains_raw_bot_token() -> None:
    client = _client_as_operator()
    client.post(
        "/api/v1/config/settings/telegram/save/",
        data={
            "bot_token": "fake-super-secret-bot-token-never-leak",
            "channel_id": "-100123456",
            "enabled": True,
        },
        content_type="application/json",
    )

    response = client.get("/api/v1/config/settings/telegram/")

    assert "fake-super-secret-bot-token-never-leak" not in response.content.decode()
    assert "bot_token" not in response.json()


@requires_postgres
@pytest.mark.django_db
def test_discord_settings_response_never_contains_raw_webhook_url() -> None:
    client = _client_as_operator()
    secret_webhook = "https://discord.com/api/webhooks/never-leak-this/token-value"  # noqa: S105
    client.post(
        "/api/v1/config/settings/discord/save/",
        data={"webhook_url": secret_webhook, "enabled": True},
        content_type="application/json",
    )

    response = client.get("/api/v1/config/settings/discord/")

    assert secret_webhook not in response.content.decode()
    assert "webhook_url" not in response.json()


# --- Write-only replacement pattern -----------------------------------------


@requires_postgres
@pytest.mark.django_db
def test_dhan_save_with_blank_access_token_leaves_existing_token_unchanged() -> None:
    client = _client_as_operator()
    client.post(
        "/api/v1/config/settings/dhan/save/",
        data={"client_id": "1000000123", "access_token": "fake-original-token", "enabled": True},
        content_type="application/json",
    )

    # Second save: blank access_token, changed client_id only.
    response = client.post(
        "/api/v1/config/settings/dhan/save/",
        data={"client_id": "2000000456", "access_token": "", "enabled": True},
        content_type="application/json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["client_id_masked"] != "1000000123"
    assert body["access_token_configured"] is True

    from intraday.infrastructure.persistence.provider_settings_repositories import (
        DjangoDhanCredentialRepository,
    )

    assert DjangoDhanCredentialRepository().get_decrypted_access_token() == "fake-original-token"


# --- Connection testing (mocked outbound HTTP) ------------------------------


@requires_postgres
@pytest.mark.django_db
def test_dhan_test_connection_when_unconfigured_returns_not_configured_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Isolates this test from whatever the ambient OS/`.env` environment
    # happens to contain (a real deployment may legitimately have real
    # DHAN_CLIENT_ID/DHAN_ACCESS_TOKEN values loaded via python-dotenv at
    # Django-settings-import time - this test's whole point is "nothing
    # is configured," which must be true regardless of environment, the
    # same isolation pattern already used in
    # test_provider_settings.py's precedence tests).
    monkeypatch.delenv("DHAN_CLIENT_ID", raising=False)
    monkeypatch.delenv("DHAN_ACCESS_TOKEN", raising=False)
    client = _client_as_operator()

    response = client.post("/api/v1/config/settings/dhan/test/")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "NOT_CONFIGURED"
    assert body["provider"] == "dhan"


@requires_postgres
@pytest.mark.django_db
def test_dhan_test_connection_success_updates_status_to_connected() -> None:
    client = _client_as_operator()
    client.post(
        "/api/v1/config/settings/dhan/save/",
        data={"client_id": "1000000123", "access_token": "fake-token", "enabled": True},
        content_type="application/json",
    )

    with patch("intraday.infrastructure.api.settings_views.check_dhan_connectivity") as mock_check:
        mock_check.return_value = DhanConnectivityResult(
            success=True, status="CONNECTED", safe_error="", latency_ms=120
        )
        response = client.post("/api/v1/config/settings/dhan/test/")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "CONNECTED"
    assert body["latency_ms"] == 120
    # Never called a trading/order endpoint - only the connectivity check
    # function itself, whose implementation is independently verified to
    # call only GET /v2/profile (infrastructure/brokers/dhan/client.py).
    mock_check.assert_called_once()


@requires_postgres
@pytest.mark.django_db
def test_dhan_test_connection_auth_failure_reports_sanitized_reason() -> None:
    client = _client_as_operator()
    client.post(
        "/api/v1/config/settings/dhan/save/",
        data={"client_id": "1000000123", "access_token": "fake-bad-token", "enabled": True},
        content_type="application/json",
    )

    with patch("intraday.infrastructure.api.settings_views.check_dhan_connectivity") as mock_check:
        mock_check.return_value = DhanConnectivityResult(
            success=False,
            status="AUTHENTICATION_FAILED",
            safe_error="Dhan rejected the configured Client ID/Access Token.",
            latency_ms=300,
        )
        response = client.post("/api/v1/config/settings/dhan/test/")

    body = response.json()
    assert body["status"] == "AUTHENTICATION_FAILED"
    assert "fake-bad-token" not in response.content.decode()
    assert body["failure_reason_safe"] == "Dhan rejected the configured Client ID/Access Token."


@requires_postgres
@pytest.mark.django_db
def test_dhan_test_connection_is_debounced_within_a_few_seconds() -> None:
    client = _client_as_operator()
    client.post(
        "/api/v1/config/settings/dhan/save/",
        data={"client_id": "1000000123", "access_token": "fake-token", "enabled": True},
        content_type="application/json",
    )

    with patch("intraday.infrastructure.api.settings_views.check_dhan_connectivity") as mock_check:
        mock_check.return_value = DhanConnectivityResult(
            success=True, status="CONNECTED", safe_error="", latency_ms=50
        )
        first = client.post("/api/v1/config/settings/dhan/test/")
        second = client.post("/api/v1/config/settings/dhan/test/")

    assert first.status_code == 200
    assert second.status_code == 429
    mock_check.assert_called_once()


@requires_postgres
@pytest.mark.django_db
def test_telegram_test_connection_success() -> None:
    client = _client_as_operator()
    client.post(
        "/api/v1/config/settings/telegram/save/",
        data={"bot_token": "fake-bot-token", "channel_id": "-100123456", "enabled": True},
        content_type="application/json",
    )

    with patch(
        "intraday.infrastructure.api.settings_views.check_telegram_connectivity"
    ) as mock_check:
        mock_check.return_value = ConnectivityCheckResult(
            success=True, status="CONNECTED", safe_error="", latency_ms=90
        )
        response = client.post("/api/v1/config/settings/telegram/test/")

    assert response.status_code == 200
    assert response.json()["status"] == "CONNECTED"


@requires_postgres
@pytest.mark.django_db
def test_discord_test_connection_success() -> None:
    client = _client_as_operator()
    client.post(
        "/api/v1/config/settings/discord/save/",
        data={
            "webhook_url": "https://discord.com/api/webhooks/fake/token",
            "enabled": True,
        },
        content_type="application/json",
    )

    with patch(
        "intraday.infrastructure.api.settings_views.check_discord_connectivity"
    ) as mock_check:
        mock_check.return_value = ConnectivityCheckResult(
            success=True, status="CONNECTED", safe_error="", latency_ms=70
        )
        response = client.post("/api/v1/config/settings/discord/test/")

    assert response.status_code == 200
    assert response.json()["status"] == "CONNECTED"


# --- Status: configured != connected -----------------------------------


@requires_postgres
@pytest.mark.django_db
def test_provider_status_reports_not_configured_before_any_save_or_test() -> None:
    client = _client_as_reader()

    response = client.get("/api/v1/config/settings/dhan/status/")

    assert response.status_code == 200
    assert response.json()["status"] == "NOT_CONFIGURED"


@requires_postgres
@pytest.mark.django_db
def test_saving_credentials_alone_does_not_mark_provider_connected() -> None:
    """Configured != Connected (Checkpoint 22 §14): saving credentials
    must never itself perform or imply a successful connection test."""
    client = _client_as_operator()

    client.post(
        "/api/v1/config/settings/dhan/save/",
        data={"client_id": "1000000123", "access_token": "fake-token", "enabled": True},
        content_type="application/json",
    )
    status_response = client.get("/api/v1/config/settings/dhan/status/")

    assert status_response.json()["status"] != "CONNECTED"


@requires_postgres
@pytest.mark.django_db
def test_provider_status_endpoint_never_performs_a_live_check_itself() -> None:
    """`GET .../status/` reads the last recorded status only - repeated
    calls must never trigger an outbound connectivity check."""
    client = _client_as_reader()

    with patch("intraday.infrastructure.api.settings_views.check_dhan_connectivity") as mock_check:
        client.get("/api/v1/config/settings/dhan/status/")
        client.get("/api/v1/config/settings/dhan/status/")

    mock_check.assert_not_called()


# --- Audit trail --------------------------------------------------------


@requires_postgres
@pytest.mark.django_db
def test_saving_dhan_credentials_creates_an_audit_entry_with_no_secret_value() -> None:
    client = _client_as_operator()

    client.post(
        "/api/v1/config/settings/dhan/save/",
        data={
            "client_id": "1000000123",
            "access_token": "fake-audit-test-token-never-leak",
            "enabled": True,
        },
        content_type="application/json",
    )

    entries = list(AuditLogEntry.objects.filter(resource_type="provider_credential"))
    assert len(entries) == 1
    assert entries[0].actor_username == OPERATOR_USERNAME
    assert entries[0].resource_id == "dhan"
    serialized = "|".join(
        str(getattr(entries[0], field.name)) for field in AuditLogEntry._meta.get_fields()
    )
    assert "fake-audit-test-token-never-leak" not in serialized
