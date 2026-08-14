# File: src/intraday/application/services/provider_settings.py
#
# Checkpoint 22: application-layer settings services for the three
# operational providers (Dhan, Telegram, Discord). Each service depends
# only on its repository Protocol (application/repositories/provider_settings.py)
# - never a concrete Django/HTTP client - and implements the ONE genuine
# business rule this checkpoint introduces: configuration precedence
# (Checkpoint 22 §4/§6).
#
# ---------------------------------------------------------------------------
# Configuration precedence (Checkpoint 22 §4, explicit decision)
# ---------------------------------------------------------------------------
#
#     Settings UI (database) value?
#             │
#        YES ─┴──→ use it, source = "DATABASE"
#             │
#             NO
#             ↓
#     Environment variable set?
#             │
#        YES ─┴──→ use it, source = "ENVIRONMENT"
#             │
#             NO
#             ↓
#         source = "UNCONFIGURED"
#
# A database value is NEVER overwritten by an environment variable on
# startup or on any read (Checkpoint 22 §4's explicit warning) - this
# resolver only ever READS both sources and picks one; it has no write
# path back to either. `.env`/the environment remains a bootstrap/
# fallback source forever, not a value that gets "promoted" into the
# database automatically.
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from intraday.application.repositories.provider_settings import (
    DhanCredentialRepository,
    DiscordCredentialRepository,
    TelegramCredentialRepository,
)

ConfigurationSource = Literal["DATABASE", "ENVIRONMENT", "UNCONFIGURED"]


@dataclass(frozen=True, slots=True)
class EffectiveValue:
    """A resolved configuration value's SOURCE, safe to expose to the
    frontend (Checkpoint 22 §4's "the final effective configuration
    should clearly indicate its source... do not expose secret values
    when displaying the source") - never the value itself for a secret
    field. `configured` is `True` for both DATABASE and ENVIRONMENT
    sources."""

    source: ConfigurationSource

    @property
    def configured(self) -> bool:
        return self.source != "UNCONFIGURED"


def _resolve(db_configured: bool, env_var_name: str) -> EffectiveValue:
    if db_configured:
        return EffectiveValue(source="DATABASE")
    if os.environ.get(env_var_name):
        return EffectiveValue(source="ENVIRONMENT")
    return EffectiveValue(source="UNCONFIGURED")


@dataclass(frozen=True, slots=True)
class DhanSettingsView:
    """Safe-to-serialize Dhan configuration state - no secret value
    anywhere in this type (Checkpoint 22 §3/§12)."""

    client_id_masked: str  # e.g. "1234...789" or "" if unconfigured
    client_id_source: ConfigurationSource
    access_token_configured: bool
    access_token_source: ConfigurationSource
    enabled: bool
    updated_at: datetime | None
    updated_by_username: str


@dataclass(frozen=True, slots=True)
class DhanSettingsService:
    repository: DhanCredentialRepository

    def get_display(self) -> DhanSettingsView:
        record = self.repository.get()
        client_id = record.client_id or os.environ.get("DHAN_CLIENT_ID", "")
        client_id_effective = _resolve(bool(record.client_id), "DHAN_CLIENT_ID")
        token_effective = _resolve(record.has_access_token, "DHAN_ACCESS_TOKEN")
        return DhanSettingsView(
            client_id_masked=_mask_identifier(client_id),
            client_id_source=client_id_effective.source,
            access_token_configured=token_effective.configured,
            access_token_source=token_effective.source,
            enabled=record.enabled,
            updated_at=record.updated_at,
            updated_by_username=record.updated_by_username,
        )

    def save(
        self,
        *,
        client_id: str | None,
        access_token: str | None,
        enabled: bool | None,
        actor: str,
        actor_user_id: int,
        request_id: str,
    ) -> None:
        self.repository.save(
            client_id=client_id,
            access_token=access_token,
            enabled=enabled,
            actor=actor,
            actor_user_id=actor_user_id,
            request_id=request_id,
        )

    def effective_credentials(self) -> tuple[str, str] | None:
        """Resolves the real (decrypted) client_id/access_token pair
        per the precedence rule above - used ONLY by the connection-test
        code path (`infrastructure/api/settings_views.py`), immediately
        before an outbound connectivity check. Never cached, never
        logged, never returned from any other method."""
        record = self.repository.get()
        client_id = record.client_id or os.environ.get("DHAN_CLIENT_ID", "")
        access_token = self.repository.get_decrypted_access_token() or os.environ.get(
            "DHAN_ACCESS_TOKEN", ""
        )
        if not client_id or not access_token:
            return None
        return client_id, access_token


@dataclass(frozen=True, slots=True)
class TelegramSettingsView:
    channel_id_masked: str
    channel_id_source: ConfigurationSource
    bot_token_configured: bool
    bot_token_source: ConfigurationSource
    enabled: bool
    updated_at: datetime | None
    updated_by_username: str


@dataclass(frozen=True, slots=True)
class TelegramSettingsService:
    repository: TelegramCredentialRepository

    def get_display(self) -> TelegramSettingsView:
        record = self.repository.get()
        channel_id = record.channel_id or os.environ.get("TELEGRAM_CHANNEL_ID", "")
        channel_effective = _resolve(bool(record.channel_id), "TELEGRAM_CHANNEL_ID")
        token_effective = _resolve(record.has_bot_token, "TELEGRAM_BOT_TOKEN")
        return TelegramSettingsView(
            channel_id_masked=_mask_identifier(channel_id),
            channel_id_source=channel_effective.source,
            bot_token_configured=token_effective.configured,
            bot_token_source=token_effective.source,
            enabled=record.enabled,
            updated_at=record.updated_at,
            updated_by_username=record.updated_by_username,
        )

    def save(
        self,
        *,
        bot_token: str | None,
        channel_id: str | None,
        enabled: bool | None,
        actor: str,
        actor_user_id: int,
        request_id: str,
    ) -> None:
        self.repository.save(
            bot_token=bot_token,
            channel_id=channel_id,
            enabled=enabled,
            actor=actor,
            actor_user_id=actor_user_id,
            request_id=request_id,
        )

    def effective_credentials(self) -> tuple[str, str] | None:
        record = self.repository.get()
        channel_id = record.channel_id or os.environ.get("TELEGRAM_CHANNEL_ID", "")
        bot_token = self.repository.get_decrypted_bot_token() or os.environ.get(
            "TELEGRAM_BOT_TOKEN", ""
        )
        if not channel_id or not bot_token:
            return None
        return bot_token, channel_id


@dataclass(frozen=True, slots=True)
class DiscordSettingsView:
    webhook_configured: bool
    webhook_source: ConfigurationSource
    enabled: bool
    updated_at: datetime | None
    updated_by_username: str


@dataclass(frozen=True, slots=True)
class DiscordSettingsService:
    repository: DiscordCredentialRepository

    def get_display(self) -> DiscordSettingsView:
        record = self.repository.get()
        webhook_effective = _resolve(record.has_webhook_url, "DISCORD_WEBHOOK_URL")
        return DiscordSettingsView(
            webhook_configured=webhook_effective.configured,
            webhook_source=webhook_effective.source,
            enabled=record.enabled,
            updated_at=record.updated_at,
            updated_by_username=record.updated_by_username,
        )

    def save(
        self,
        *,
        webhook_url: str | None,
        enabled: bool | None,
        actor: str,
        actor_user_id: int,
        request_id: str,
    ) -> None:
        self.repository.save(
            webhook_url=webhook_url,
            enabled=enabled,
            actor=actor,
            actor_user_id=actor_user_id,
            request_id=request_id,
        )

    def effective_webhook_url(self) -> str | None:
        record = self.repository.get()
        if not record.has_webhook_url and not os.environ.get("DISCORD_WEBHOOK_URL"):
            return None
        return self.repository.get_decrypted_webhook_url() or os.environ.get(
            "DISCORD_WEBHOOK_URL", ""
        )


def _mask_identifier(value: str) -> str:
    """A non-secret identifier (Dhan client id, Telegram channel id) is
    still partially masked for display (Checkpoint 22 §3's "never" list
    is about SECRETS, but this project treats "all communication
    configuration as controlled configuration" - Checkpoint 22 §15) -
    shows only a short prefix/suffix, never the full value verbatim in
    a generic settings-overview context."""
    if not value:
        return ""
    if len(value) <= 6:
        return "••••"
    return f"{value[:2]}••••{value[-2:]}"
