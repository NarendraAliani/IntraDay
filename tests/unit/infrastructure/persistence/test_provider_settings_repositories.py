# tests/unit/infrastructure/persistence/test_provider_settings_repositories.py
#
# Checkpoint 22: Django ORM repository coverage for provider-credential
# persistence - singleton behavior, encryption round-trip through the
# real repository, write-only "None means unchanged" semantics, and
# audit-trail creation without ever recording the secret value itself.
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from intraday.infrastructure.persistence.models import AuditLogEntry
from intraday.infrastructure.persistence.provider_settings_repositories import (
    DjangoDhanCredentialRepository,
    DjangoDiscordCredentialRepository,
    DjangoProviderConnectionStatusRepository,
    DjangoTelegramCredentialRepository,
)
from tests.postgres_utils import requires_postgres

ACTOR = "operator_user"
ACTOR_ID = 1
REQUEST_ID = "11111111-1111-1111-1111-111111111111"


@requires_postgres
@pytest.mark.django_db
def test_dhan_get_before_any_save_returns_unconfigured_record() -> None:
    repo = DjangoDhanCredentialRepository()

    record = repo.get()

    assert record.client_id == ""
    assert record.has_access_token is False
    assert record.enabled is False
    assert record.updated_at is None


@requires_postgres
@pytest.mark.django_db
def test_dhan_save_then_get_reflects_new_values_never_the_raw_token() -> None:
    repo = DjangoDhanCredentialRepository()

    repo.save(
        client_id="1000000123",
        access_token="fake-test-token-not-real",  # noqa: S106
        enabled=True,
        actor=ACTOR,
        actor_user_id=ACTOR_ID,
        request_id=REQUEST_ID,
    )

    record = repo.get()
    assert record.client_id == "1000000123"
    assert record.has_access_token is True
    assert record.enabled is True
    assert record.updated_by_username == ACTOR
    assert record.updated_at is not None


@requires_postgres
@pytest.mark.django_db
def test_dhan_get_decrypted_access_token_round_trips() -> None:
    repo = DjangoDhanCredentialRepository()
    repo.save(
        client_id="1000000123",
        access_token="fake-test-token-not-real",  # noqa: S106
        enabled=True,
        actor=ACTOR,
        actor_user_id=ACTOR_ID,
        request_id=REQUEST_ID,
    )

    assert repo.get_decrypted_access_token() == "fake-test-token-not-real"


@requires_postgres
@pytest.mark.django_db
def test_dhan_save_with_none_fields_leaves_existing_values_unchanged() -> None:
    repo = DjangoDhanCredentialRepository()
    repo.save(
        client_id="1000000123",
        access_token="fake-test-token-not-real",  # noqa: S106
        enabled=True,
        actor=ACTOR,
        actor_user_id=ACTOR_ID,
        request_id=REQUEST_ID,
    )

    # A subsequent save with client_id=None must NOT blank the client_id -
    # the write-only replacement pattern's core guarantee (Checkpoint 22 §21).
    repo.save(
        client_id=None,
        access_token=None,
        enabled=False,
        actor=ACTOR,
        actor_user_id=ACTOR_ID,
        request_id=REQUEST_ID,
    )

    record = repo.get()
    assert record.client_id == "1000000123"
    assert record.has_access_token is True
    assert record.enabled is False
    assert repo.get_decrypted_access_token() == "fake-test-token-not-real"


@requires_postgres
@pytest.mark.django_db
def test_dhan_save_is_a_singleton_repeated_saves_do_not_create_new_rows() -> None:
    from intraday.infrastructure.persistence.models import DhanCredential

    repo = DjangoDhanCredentialRepository()
    repo.save(
        client_id="1000000123",
        access_token=None,
        enabled=None,
        actor=ACTOR,
        actor_user_id=ACTOR_ID,
        request_id=REQUEST_ID,
    )
    repo.save(
        client_id="9999999999",
        access_token=None,
        enabled=None,
        actor=ACTOR,
        actor_user_id=ACTOR_ID,
        request_id=REQUEST_ID,
    )

    assert DhanCredential.objects.count() == 1


@requires_postgres
@pytest.mark.django_db
def test_dhan_save_records_an_audit_entry_without_the_secret_value() -> None:
    repo = DjangoDhanCredentialRepository()

    repo.save(
        client_id="1000000123",
        access_token="fake-test-token-not-real",  # noqa: S106
        enabled=True,
        actor=ACTOR,
        actor_user_id=ACTOR_ID,
        request_id=REQUEST_ID,
    )

    entries = list(AuditLogEntry.objects.filter(resource_type="provider_credential"))
    assert len(entries) == 1
    entry = entries[0]
    assert entry.action == "settings.provider_credential_changed"
    assert entry.resource_id == "dhan"
    assert entry.actor_username == ACTOR
    assert entry.outcome == "updated"
    assert "access_token" in entry.version_identifier
    # The raw secret must never appear anywhere in the audit row.
    serialized = "|".join(
        str(getattr(entry, field.name)) for field in AuditLogEntry._meta.get_fields()
    )
    assert "fake-test-token-not-real" not in serialized


@requires_postgres
@pytest.mark.django_db
def test_dhan_save_with_all_none_fields_writes_no_audit_entry() -> None:
    """A no-op save (e.g. a request with every field blank) must not
    fabricate a change event."""
    repo = DjangoDhanCredentialRepository()

    repo.save(
        client_id=None,
        access_token=None,
        enabled=None,
        actor=ACTOR,
        actor_user_id=ACTOR_ID,
        request_id=REQUEST_ID,
    )

    assert AuditLogEntry.objects.filter(resource_type="provider_credential").count() == 0


@requires_postgres
@pytest.mark.django_db
def test_telegram_save_then_get_and_decrypt_round_trips() -> None:
    repo = DjangoTelegramCredentialRepository()

    repo.save(
        bot_token="fake-bot-token-123",  # noqa: S106
        channel_id="-100123456",
        enabled=True,
        actor=ACTOR,
        actor_user_id=ACTOR_ID,
        request_id=REQUEST_ID,
    )

    record = repo.get()
    assert record.channel_id == "-100123456"
    assert record.has_bot_token is True
    assert repo.get_decrypted_bot_token() == "fake-bot-token-123"


@requires_postgres
@pytest.mark.django_db
def test_discord_save_then_get_and_decrypt_round_trips() -> None:
    repo = DjangoDiscordCredentialRepository()

    repo.save(
        webhook_url="https://discord.com/api/webhooks/fake/token",
        enabled=True,
        actor=ACTOR,
        actor_user_id=ACTOR_ID,
        request_id=REQUEST_ID,
    )

    record = repo.get()
    assert record.has_webhook_url is True
    assert repo.get_decrypted_webhook_url() == "https://discord.com/api/webhooks/fake/token"


@requires_postgres
@pytest.mark.django_db
def test_connection_status_get_before_any_check_returns_default_row() -> None:
    repo = DjangoProviderConnectionStatusRepository()

    record = repo.get("dhan")

    assert record.provider == "dhan"
    assert record.last_checked_at is None


@requires_postgres
@pytest.mark.django_db
def test_connection_status_record_check_success_sets_last_success_and_clears_failure() -> None:
    repo = DjangoProviderConnectionStatusRepository()
    checked_at = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)

    repo.record_check(
        "dhan",
        status="CONNECTED",
        checked_at=checked_at,
        success=True,
        failure_reason_safe="",
        latency_ms=250,
    )

    record = repo.get("dhan")
    assert record.status == "CONNECTED"
    assert record.last_success_at == checked_at
    assert record.last_failure_at is None
    assert record.failure_reason_safe == ""
    assert record.latency_ms == 250


@requires_postgres
@pytest.mark.django_db
def test_connection_status_record_check_failure_sets_last_failure_and_reason() -> None:
    repo = DjangoProviderConnectionStatusRepository()
    checked_at = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)

    repo.record_check(
        "dhan",
        status="AUTHENTICATION_FAILED",
        checked_at=checked_at,
        success=False,
        failure_reason_safe="Dhan rejected the configured Client ID/Access Token.",
        latency_ms=530,
    )

    record = repo.get("dhan")
    assert record.status == "AUTHENTICATION_FAILED"
    assert record.last_failure_at == checked_at
    assert record.last_success_at is None
    assert record.failure_reason_safe == "Dhan rejected the configured Client ID/Access Token."


@requires_postgres
@pytest.mark.django_db
def test_connection_status_is_independent_per_provider() -> None:
    repo = DjangoProviderConnectionStatusRepository()
    checked_at = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)

    repo.record_check(
        "dhan",
        status="CONNECTED",
        checked_at=checked_at,
        success=True,
        failure_reason_safe="",
        latency_ms=100,
    )

    telegram_record = repo.get("telegram")
    assert telegram_record.status != "CONNECTED"
    assert telegram_record.last_checked_at is None
