# File: src/intraday/application/repositories/__init__.py
#
# Repository/application interfaces (Checkpoint 7) mediating between the
# application layer and infrastructure/persistence. These are the only
# three repository abstractions this checkpoint introduces — one per
# persisted configuration concept (Checkpoint 7 §4/§7). No repository was
# created merely for ceremony: each exists because the application layer
# genuinely needs configuration state to survive a process restart, and
# because the persistence *technology* (PostgreSQL via Django ORM today)
# must remain swappable without touching application or domain code.
#
# No Django Model, QuerySet, or ORM-specific exception is exposed through
# any of these interfaces — implementations live in
# infrastructure/persistence/repositories.py and translate Django rows
# into the domain/application dataclasses these Protocols reference.
from __future__ import annotations

from typing import Protocol

from intraday.application.config_schema.records import (
    RiskConfigurationRecord,
    StrategyVersionSnapshot,
    UniverseRecord,
)
from intraday.control_plane.audit.events import ActivationOutcome, AuditEvent
from intraday.domain.strategy.contracts import StrategyVersion
from intraday.domain.universe.contracts import Universe


class DuplicateVersionError(RuntimeError):
    """Raised when attempting to save a version that already exists for a
    given configuration id. Repository implementations translate a
    persistence-technology-specific conflict (e.g. Django's
    IntegrityError) into this technology-neutral exception so callers
    never need to know a Django/PostgreSQL uniqueness constraint fired."""


class RiskConfigurationRepository(Protocol):
    """Persists and retrieves versioned `RiskConfigurationRecord`
    instances. Historical versions are immutable — `save()` only ever
    inserts a new version; there is no `update()`.

    `activate()`'s `actor`/`actor_user_id`/`request_id` (Checkpoint 12)
    are required, not optional — every activation is audited, so there
    is no code path that can change the active version without recording
    who did it and in which request. The concrete implementation appends
    the audit record in the SAME transaction as the state change (see
    `DjangoRiskConfigurationRepository.activate()`), never as a separate,
    independently-committable step."""

    def save(self, record: RiskConfigurationRecord) -> None: ...

    def get_version(
        self, risk_configuration_id: str, version: str
    ) -> RiskConfigurationRecord | None: ...

    def get_active(self, risk_configuration_id: str) -> RiskConfigurationRecord | None: ...

    def list_versions(self, risk_configuration_id: str) -> tuple[RiskConfigurationRecord, ...]: ...

    def activate(
        self,
        risk_configuration_id: str,
        version: str,
        *,
        actor: str,
        actor_user_id: int,
        request_id: str,
    ) -> ActivationOutcome: ...


class UniverseRepository(Protocol):
    """Persists and retrieves versioned `Universe` instances, returned
    wrapped in `UniverseRecord` (adds `created_at` — Checkpoint 8).
    Historical versions are immutable — `save()` only ever inserts a new
    version."""

    def save(self, universe: Universe) -> None: ...

    def get_version(self, universe_id: str, version: str) -> UniverseRecord | None: ...

    def get_active(self, universe_id: str) -> UniverseRecord | None: ...

    def list_versions(self, universe_id: str) -> tuple[UniverseRecord, ...]: ...

    def activate(self, universe_id: str, version: str) -> None: ...


class StrategyVersionRepository(Protocol):
    """Persists and retrieves `StrategyVersion` records, returned wrapped
    in `StrategyVersionSnapshot` (adds `created_at` — Checkpoint 8). A
    version is identified by the tuple (strategy_id, specification_version,
    code_version, configuration_version) — `universe_version` may differ
    across otherwise-identical records without creating a new identity,
    per how `domain.strategy.StrategyVersion` itself is shaped."""

    def save(self, strategy_version: StrategyVersion) -> None: ...

    def get_version(
        self,
        strategy_id: str,
        specification_version: str,
        code_version: str,
        configuration_version: str,
    ) -> StrategyVersionSnapshot | None: ...

    def get_active(self, strategy_id: str) -> StrategyVersionSnapshot | None: ...

    def list_versions(self, strategy_id: str) -> tuple[StrategyVersionSnapshot, ...]: ...

    def activate(
        self,
        strategy_id: str,
        specification_version: str,
        code_version: str,
        configuration_version: str,
    ) -> None: ...


class AuditRepository(Protocol):
    """Read-only access to durable control-plane audit events
    (Checkpoint 12). Deliberately has no `save`/`update`/`delete` method
    — the write path is not exposed through this Protocol at all,
    because the write must happen inside the SAME transaction as the
    state change it records (see `RiskConfigurationRepository.activate()`
    above), which only the concrete resource repository can guarantee.
    This Protocol exists solely so the read side (an audit-listing API)
    can depend on an abstraction instead of importing
    `infrastructure.persistence` directly, matching every other
    read path in this codebase."""

    def list_for_resource(self, resource_type: str, resource_id: str) -> tuple[AuditEvent, ...]: ...
