# File: src/intraday/infrastructure/persistence/provider_settings_repositories.py
#
# Checkpoint 22: Django ORM implementations of the provider-settings
# repository Protocols (application/repositories/provider_settings.py).
# Kept in a dedicated module, mirroring
# application/repositories/provider_settings.py's own file split.
#
# Singleton pattern: each credential table is expected to hold at most
# one row (Checkpoint 22 §9's "one Dhan account, one Telegram bot, one
# Discord webhook per deployment"). `_singleton()` implements
# get-or-create-by-first-row - not a database uniqueness constraint
# (Checkpoint 22 §20's "reuse the existing configuration architecture"
# read together with this codebase's own precedent of some invariants
# being application-level, e.g. `AuditLogEntry`'s append-only `save()`).
#
# Encryption: every secret field is encrypted via
# `infrastructure/persistence/encryption.py` (Fernet) before being
# written, and decrypted only inside `get_decrypted_*()` - never inside
# `get()`, whose whole purpose is to be safe to hand to the API layer.
from __future__ import annotations

import datetime as _dt

from django.db import transaction

from intraday.application.repositories.provider_settings import (
    ConnectionStatusRecord,
    DhanCredentialRecord,
    DiscordCredentialRecord,
    TelegramCredentialRecord,
)
from intraday.infrastructure.persistence.encryption import decrypt_value, encrypt_value
from intraday.infrastructure.persistence.models import (
    AuditLogEntry,
    DhanCredential,
    DiscordCredential,
    ProviderConnectionStatus,
    TelegramCredential,
)


def _audit_credential_change(
    *, provider: str, field_changed: str, actor: str, actor_user_id: int, request_id: str
) -> None:
    """Records a provider-credential change in the existing append-only
    audit trail (Checkpoint 12) - NEVER the value itself (Checkpoint 22
    §25). `version_identifier` carries which field changed (e.g.
    "access_token", "enabled") since there is no real "version" concept
    for a credential the way there is for risk/universe/strategy
    configuration. Written inside the SAME transaction as the state
    change (see each repository's `save()` below), mirroring
    `DjangoRiskConfigurationRepository.activate()`'s own guarantee."""
    AuditLogEntry.objects.create(
        occurred_at=_dt.datetime.now(tz=_dt.UTC),
        actor_username=actor,
        actor_user_id=actor_user_id,
        action="settings.provider_credential_changed",
        resource_type="provider_credential",
        resource_id=provider,
        version_identifier=field_changed,
        previous_version=None,
        outcome="updated",
        request_id=request_id,
    )


class DjangoDhanCredentialRepository:
    """Django ORM implementation of `DhanCredentialRepository`."""

    def _singleton(self) -> DhanCredential:
        row, _created = DhanCredential.objects.get_or_create(pk=1)
        return row

    def get(self) -> DhanCredentialRecord:
        row = self._singleton()
        return DhanCredentialRecord(
            client_id=row.client_id,
            has_access_token=row.encrypted_access_token is not None,
            enabled=row.enabled,
            updated_at=row.updated_at if row.client_id or row.encrypted_access_token else None,
            updated_by_username=row.updated_by_username,
        )

    def get_decrypted_access_token(self) -> str | None:
        row = self._singleton()
        if row.encrypted_access_token is None:
            return None
        return decrypt_value(bytes(row.encrypted_access_token))

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
        with transaction.atomic():
            row = self._singleton()
            changed_fields: list[str] = []
            if client_id is not None:
                row.client_id = client_id
                changed_fields.append("client_id")
            if access_token is not None:
                row.encrypted_access_token = encrypt_value(access_token)
                changed_fields.append("access_token")
            if enabled is not None:
                row.enabled = enabled
                changed_fields.append("enabled")
            if not changed_fields:
                return
            row.updated_by_username = actor
            row.save()
            _audit_credential_change(
                provider="dhan",
                field_changed=",".join(changed_fields),
                actor=actor,
                actor_user_id=actor_user_id,
                request_id=request_id,
            )


class DjangoTelegramCredentialRepository:
    """Django ORM implementation of `TelegramCredentialRepository`."""

    def _singleton(self) -> TelegramCredential:
        row, _created = TelegramCredential.objects.get_or_create(pk=1)
        return row

    def get(self) -> TelegramCredentialRecord:
        row = self._singleton()
        return TelegramCredentialRecord(
            channel_id=row.channel_id,
            has_bot_token=row.encrypted_bot_token is not None,
            enabled=row.enabled,
            updated_at=row.updated_at if row.channel_id or row.encrypted_bot_token else None,
            updated_by_username=row.updated_by_username,
        )

    def get_decrypted_bot_token(self) -> str | None:
        row = self._singleton()
        if row.encrypted_bot_token is None:
            return None
        return decrypt_value(bytes(row.encrypted_bot_token))

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
        with transaction.atomic():
            row = self._singleton()
            changed_fields: list[str] = []
            if bot_token is not None:
                row.encrypted_bot_token = encrypt_value(bot_token)
                changed_fields.append("bot_token")
            if channel_id is not None:
                row.channel_id = channel_id
                changed_fields.append("channel_id")
            if enabled is not None:
                row.enabled = enabled
                changed_fields.append("enabled")
            if not changed_fields:
                return
            row.updated_by_username = actor
            row.save()
            _audit_credential_change(
                provider="telegram",
                field_changed=",".join(changed_fields),
                actor=actor,
                actor_user_id=actor_user_id,
                request_id=request_id,
            )


class DjangoDiscordCredentialRepository:
    """Django ORM implementation of `DiscordCredentialRepository`."""

    def _singleton(self) -> DiscordCredential:
        row, _created = DiscordCredential.objects.get_or_create(pk=1)
        return row

    def get(self) -> DiscordCredentialRecord:
        row = self._singleton()
        return DiscordCredentialRecord(
            has_webhook_url=row.encrypted_webhook_url is not None,
            enabled=row.enabled,
            updated_at=row.updated_at if row.encrypted_webhook_url else None,
            updated_by_username=row.updated_by_username,
        )

    def get_decrypted_webhook_url(self) -> str | None:
        row = self._singleton()
        if row.encrypted_webhook_url is None:
            return None
        return decrypt_value(bytes(row.encrypted_webhook_url))

    def save(
        self,
        *,
        webhook_url: str | None,
        enabled: bool | None,
        actor: str,
        actor_user_id: int,
        request_id: str,
    ) -> None:
        with transaction.atomic():
            row = self._singleton()
            changed_fields: list[str] = []
            if webhook_url is not None:
                row.encrypted_webhook_url = encrypt_value(webhook_url)
                changed_fields.append("webhook_url")
            if enabled is not None:
                row.enabled = enabled
                changed_fields.append("enabled")
            if not changed_fields:
                return
            row.updated_by_username = actor
            row.save()
            _audit_credential_change(
                provider="discord",
                field_changed=",".join(changed_fields),
                actor=actor,
                actor_user_id=actor_user_id,
                request_id=request_id,
            )


class DjangoProviderConnectionStatusRepository:
    """Django ORM implementation of `ProviderConnectionStatusRepository`."""

    def get(self, provider: str) -> ConnectionStatusRecord:
        row, _created = ProviderConnectionStatus.objects.get_or_create(provider=provider)
        return ConnectionStatusRecord(
            provider=row.provider,
            status=row.status,
            last_checked_at=row.last_checked_at,
            last_success_at=row.last_success_at,
            last_failure_at=row.last_failure_at,
            failure_reason_safe=row.failure_reason_safe,
            latency_ms=row.latency_ms,
        )

    def record_check(
        self,
        provider: str,
        *,
        status: str,
        checked_at: _dt.datetime,
        success: bool,
        failure_reason_safe: str,
        latency_ms: int | None,
    ) -> None:
        row, _created = ProviderConnectionStatus.objects.get_or_create(provider=provider)
        row.status = status
        row.last_checked_at = checked_at
        if success:
            row.last_success_at = checked_at
            row.failure_reason_safe = ""
        else:
            row.last_failure_at = checked_at
            row.failure_reason_safe = failure_reason_safe
        row.latency_ms = latency_ms
        row.save()
