# tests/unit/application/services/test_provider_settings.py
#
# Checkpoint 22: the ONE genuine business rule this checkpoint
# introduces - configuration precedence (Database > Environment >
# Unconfigured, database never overwritten by environment on read) -
# exercised directly against the real Django-backed repositories so the
# resolver is proven against real persistence, not a hand-rolled fake.
from __future__ import annotations

import pytest

from intraday.application.services.provider_settings import (
    DhanSettingsService,
    DiscordSettingsService,
    TelegramSettingsService,
)
from intraday.infrastructure.persistence.provider_settings_repositories import (
    DjangoDhanCredentialRepository,
    DjangoDiscordCredentialRepository,
    DjangoTelegramCredentialRepository,
)
from tests.postgres_utils import requires_postgres

ACTOR = "operator_user"
ACTOR_ID = 1
REQUEST_ID = "11111111-1111-1111-1111-111111111111"


@requires_postgres
@pytest.mark.django_db
def test_dhan_unconfigured_when_neither_database_nor_environment_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DHAN_CLIENT_ID", raising=False)
    monkeypatch.delenv("DHAN_ACCESS_TOKEN", raising=False)
    service = DhanSettingsService(repository=DjangoDhanCredentialRepository())

    view = service.get_display()

    assert view.client_id_source == "UNCONFIGURED"
    assert view.access_token_source == "UNCONFIGURED"  # noqa: S105
    assert view.access_token_configured is False
    assert service.effective_credentials() is None


@requires_postgres
@pytest.mark.django_db
def test_dhan_falls_back_to_environment_when_database_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DHAN_CLIENT_ID", "env-client-id")
    monkeypatch.setenv("DHAN_ACCESS_TOKEN", "fake-env-token-not-real")
    service = DhanSettingsService(repository=DjangoDhanCredentialRepository())

    view = service.get_display()

    assert view.client_id_source == "ENVIRONMENT"
    assert view.access_token_source == "ENVIRONMENT"  # noqa: S105
    assert view.access_token_configured is True
    assert service.effective_credentials() == ("env-client-id", "fake-env-token-not-real")


@requires_postgres
@pytest.mark.django_db
def test_dhan_database_value_takes_precedence_over_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DHAN_CLIENT_ID", "env-client-id")
    monkeypatch.setenv("DHAN_ACCESS_TOKEN", "fake-env-token-not-real")
    repository = DjangoDhanCredentialRepository()
    repository.save(
        client_id="db-client-id",
        access_token="fake-db-token-not-real",  # noqa: S106
        enabled=True,
        actor=ACTOR,
        actor_user_id=ACTOR_ID,
        request_id=REQUEST_ID,
    )
    service = DhanSettingsService(repository=repository)

    view = service.get_display()

    assert view.client_id_source == "DATABASE"
    assert view.access_token_source == "DATABASE"  # noqa: S105
    assert service.effective_credentials() == ("db-client-id", "fake-db-token-not-real")


@requires_postgres
@pytest.mark.django_db
def test_dhan_database_value_is_never_overwritten_by_environment_on_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The explicit Checkpoint 22 §4 warning: a database value must never
    be silently overwritten by an environment value on any read path -
    this resolver only ever reads, it has no write-back path at all."""
    repository = DjangoDhanCredentialRepository()
    repository.save(
        client_id="db-client-id",
        access_token="fake-db-token-not-real",  # noqa: S106
        enabled=True,
        actor=ACTOR,
        actor_user_id=ACTOR_ID,
        request_id=REQUEST_ID,
    )
    service = DhanSettingsService(repository=repository)
    monkeypatch.setenv("DHAN_CLIENT_ID", "env-client-id")
    monkeypatch.setenv("DHAN_ACCESS_TOKEN", "fake-env-token-not-real")

    service.get_display()
    service.get_display()
    service.effective_credentials()

    record = repository.get()
    assert record.client_id == "db-client-id"


@requires_postgres
@pytest.mark.django_db
def test_dhan_partial_database_configuration_still_reports_per_field_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """client_id saved in the database, access_token only in the
    environment - each field's source is resolved independently."""
    monkeypatch.setenv("DHAN_ACCESS_TOKEN", "fake-env-token-not-real")
    repository = DjangoDhanCredentialRepository()
    repository.save(
        client_id="db-client-id",
        access_token=None,
        enabled=True,
        actor=ACTOR,
        actor_user_id=ACTOR_ID,
        request_id=REQUEST_ID,
    )
    service = DhanSettingsService(repository=repository)

    view = service.get_display()

    assert view.client_id_source == "DATABASE"
    assert view.access_token_source == "ENVIRONMENT"  # noqa: S105


@requires_postgres
@pytest.mark.django_db
def test_dhan_effective_credentials_none_when_only_one_half_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DHAN_ACCESS_TOKEN", raising=False)
    repository = DjangoDhanCredentialRepository()
    repository.save(
        client_id="db-client-id",
        access_token=None,
        enabled=True,
        actor=ACTOR,
        actor_user_id=ACTOR_ID,
        request_id=REQUEST_ID,
    )
    service = DhanSettingsService(repository=repository)

    assert service.effective_credentials() is None


@requires_postgres
@pytest.mark.django_db
def test_dhan_client_id_is_masked_never_shown_in_full(monkeypatch: pytest.MonkeyPatch) -> None:
    repository = DjangoDhanCredentialRepository()
    repository.save(
        client_id="1000000123",
        access_token=None,
        enabled=True,
        actor=ACTOR,
        actor_user_id=ACTOR_ID,
        request_id=REQUEST_ID,
    )
    service = DhanSettingsService(repository=repository)

    view = service.get_display()

    assert view.client_id_masked != "1000000123"
    assert "1000000123" not in view.client_id_masked or view.client_id_masked.count("0") < 3


@requires_postgres
@pytest.mark.django_db
def test_telegram_precedence_matches_dhan_pattern(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-env-bot-token")
    monkeypatch.setenv("TELEGRAM_CHANNEL_ID", "-100999")
    service = TelegramSettingsService(repository=DjangoTelegramCredentialRepository())

    view = service.get_display()

    assert view.bot_token_source == "ENVIRONMENT"  # noqa: S105
    assert view.channel_id_source == "ENVIRONMENT"
    assert service.effective_credentials() == ("fake-env-bot-token", "-100999")


@requires_postgres
@pytest.mark.django_db
def test_discord_precedence_matches_dhan_pattern(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.com/api/webhooks/env/token")
    service = DiscordSettingsService(repository=DjangoDiscordCredentialRepository())

    view = service.get_display()

    assert view.webhook_source == "ENVIRONMENT"
    assert view.webhook_configured is True
    assert service.effective_webhook_url() == "https://discord.com/api/webhooks/env/token"


@requires_postgres
@pytest.mark.django_db
def test_discord_effective_webhook_url_none_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    service = DiscordSettingsService(repository=DjangoDiscordCredentialRepository())

    assert service.effective_webhook_url() is None
