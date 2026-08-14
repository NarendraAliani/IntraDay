# File: src/intraday/application/repositories/provider_settings.py
#
# Checkpoint 22: repository Protocols for operational provider settings
# (Dhan broker connectivity, Telegram/Discord notification channels) and
# their shared connection-status tracking. Kept in a dedicated module
# rather than crammed into `application/repositories/__init__.py`
# (Checkpoint 7's original file) purely for file-size readability - the
# same Protocol-in-application/implementation-in-infrastructure pattern
# applies identically; nothing about the dependency-inversion rule
# changes by virtue of the file split.
#
# Every "save" method below takes `str | None` for each secret/value
# field, where `None` means "leave this field unchanged" - the
# write-only replacement pattern (Checkpoint 22 §21): a caller that
# doesn't have (and should never receive) the existing secret cannot
# accidentally blank it out by omission. Translating a blank string from
# an HTTP request body into `None` ("blank preserves the existing
# secret") is the API layer's job (`infrastructure/api/settings_views.py`),
# not this Protocol's - this interface only expresses "no value was
# supplied" vs. "this value was supplied," nothing about HTTP semantics.
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class DhanCredentialRecord:
    """`client_id` is never secret (an account identifier) - always
    returned in full. `has_access_token` is a boolean, never the token
    itself - this record type is what the application layer hands to
    the API layer, and the API layer has no further scrubbing to do for
    the access token specifically because this record never carries it
    in the first place (Checkpoint 22 §3's "never store sensitive
    credentials... beyond the minimum request lifecycle" - the decrypted
    token exists only transiently, inside
    `ProviderConnectionService.test_dhan()`, never assigned to a
    long-lived record)."""

    client_id: str
    has_access_token: bool
    enabled: bool
    updated_at: datetime | None
    updated_by_username: str


@dataclass(frozen=True, slots=True)
class TelegramCredentialRecord:
    channel_id: str
    has_bot_token: bool
    enabled: bool
    updated_at: datetime | None
    updated_by_username: str


@dataclass(frozen=True, slots=True)
class DiscordCredentialRecord:
    has_webhook_url: bool
    enabled: bool
    updated_at: datetime | None
    updated_by_username: str


@dataclass(frozen=True, slots=True)
class ConnectionStatusRecord:
    provider: str
    status: str
    last_checked_at: datetime | None
    last_success_at: datetime | None
    last_failure_at: datetime | None
    failure_reason_safe: str
    latency_ms: int | None


class DhanCredentialRepository(Protocol):
    """Persists and retrieves Dhan broker credentials. `get_decrypted_access_token()`
    is a SEPARATE method from `get()` specifically so that reading the
    safe, displayable record (`DhanCredentialRecord`, no secret) and
    reading the real secret (needed only by
    `ProviderConnectionService.test_dhan()`, immediately before an
    outbound connectivity check) are two different, clearly-named
    operations - a caller can never accidentally receive the plaintext
    token from the method whose whole purpose is to avoid that.

    `save()`'s `actor`/`actor_user_id`/`request_id` mirror the exact
    convention `RiskConfigurationRepository.activate()` already
    established (Checkpoint 12) - every credential change is audited,
    so there is no code path that can change a credential without
    recording who did it and in which request."""

    def get(self) -> DhanCredentialRecord: ...

    def get_decrypted_access_token(self) -> str | None: ...

    def save(
        self,
        *,
        client_id: str | None,
        access_token: str | None,
        enabled: bool | None,
        actor: str,
        actor_user_id: int,
        request_id: str,
    ) -> None: ...


class TelegramCredentialRepository(Protocol):
    def get(self) -> TelegramCredentialRecord: ...

    def get_decrypted_bot_token(self) -> str | None: ...

    def save(
        self,
        *,
        bot_token: str | None,
        channel_id: str | None,
        enabled: bool | None,
        actor: str,
        actor_user_id: int,
        request_id: str,
    ) -> None: ...


class DiscordCredentialRepository(Protocol):
    def get(self) -> DiscordCredentialRecord: ...

    def get_decrypted_webhook_url(self) -> str | None: ...

    def save(
        self,
        *,
        webhook_url: str | None,
        enabled: bool | None,
        actor: str,
        actor_user_id: int,
        request_id: str,
    ) -> None: ...


class ProviderConnectionStatusRepository(Protocol):
    """Reusable across all three providers (Checkpoint 22 §12) - one row
    per `provider` string ("dhan"/"telegram"/"discord")."""

    def get(self, provider: str) -> ConnectionStatusRecord: ...

    def record_check(
        self,
        provider: str,
        *,
        status: str,
        checked_at: datetime,
        success: bool,
        failure_reason_safe: str,
        latency_ms: int | None,
    ) -> None: ...
