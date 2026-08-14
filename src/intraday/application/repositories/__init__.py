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

from datetime import datetime
from typing import Protocol

from intraday.application.config_schema.records import (
    RiskConfigurationRecord,
    StrategyConfigurationSnapshot,
    StrategyVersionSnapshot,
    UniverseRecord,
)
from intraday.control_plane.audit.events import ActivationOutcome, AuditEvent
from intraday.domain.market_data.contracts import Bar
from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe
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
    version.

    `activate()`'s `actor`/`actor_user_id`/`request_id` (Checkpoint 13,
    extending the Checkpoint 12 pattern established for
    `RiskConfigurationRepository`) are required, not optional — every
    activation is audited. The concrete implementation appends the audit
    record in the SAME transaction as the state change, never as a
    separate, independently-committable step."""

    def save(self, universe: Universe) -> None: ...

    def get_version(self, universe_id: str, version: str) -> UniverseRecord | None: ...

    def get_active(self, universe_id: str) -> UniverseRecord | None: ...

    def list_versions(self, universe_id: str) -> tuple[UniverseRecord, ...]: ...

    def activate(
        self, universe_id: str, version: str, *, actor: str, actor_user_id: int, request_id: str
    ) -> ActivationOutcome: ...


class StrategyVersionRepository(Protocol):
    """Persists and retrieves `StrategyVersion` records, returned wrapped
    in `StrategyVersionSnapshot` (adds `created_at` — Checkpoint 8). A
    version is identified by the tuple (strategy_id, specification_version,
    code_version, configuration_version) — `universe_version` may differ
    across otherwise-identical records without creating a new identity,
    per how `domain.strategy.StrategyVersion` itself is shaped.

    `activate()`'s `actor`/`actor_user_id`/`request_id` (Checkpoint 13,
    same pattern as `RiskConfigurationRepository`/`UniverseRepository`)
    are required — every activation is audited. `AuditLogEntry.
    version_identifier` is a single string column, so the 3-tuple
    identity is encoded as `"{specification_version}:{code_version}:
    {configuration_version}"` (see `DjangoStrategyVersionRepository.
    activate()`) — the domain/application identity itself is NOT
    flattened; only its audit-row representation is."""

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
        *,
        actor: str,
        actor_user_id: int,
        request_id: str,
    ) -> ActivationOutcome: ...


class StrategyConfigurationRepository(Protocol):
    """Persists and retrieves `StrategyConfigurationSnapshot` records -
    the actual parameter VALUES a `configuration_version` label points
    at (Checkpoint 26). Deliberately separate from
    `StrategyVersionRepository` above: that Protocol persists
    version-IDENTITY/activation-pointer records only (Checkpoint 8/13,
    unchanged); this one persists values, and is layered alongside it,
    never replacing it. `save()` is append-only - a configuration record
    is immutable once written (Part 11: "Do not mutate an activated
    immutable configuration"); a materially different configuration
    must be saved under a new `configuration_version`, which
    `DuplicateVersionError` enforces at the identity level."""

    def save(self, snapshot: StrategyConfigurationSnapshot) -> None: ...

    def get(
        self,
        strategy_id: str,
        specification_version: str,
        code_version: str,
        configuration_version: str,
    ) -> StrategyConfigurationSnapshot | None: ...

    def list_for_strategy(self, strategy_id: str) -> tuple[StrategyConfigurationSnapshot, ...]: ...


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


class HistoricalMarketDataRepository(Protocol):
    """Checkpoint 14: provider-neutral access to historical OHLCV bars.
    Read-only — this platform never writes market data through this
    Protocol; ingestion (a future checkpoint) is a separate concern. No
    provider name, request/response shape, SDK type, or HTTP detail
    appears here — a Dhan-backed implementation and a deterministic
    fixture implementation (`infrastructure/market_data_providers/`)
    satisfy this Protocol identically, and `feature_engine`/
    `signal_generation`/`research.backtesting` (future consumers) never
    know or care which one is behind it.

    `get_bars()` returns every bar for `instrument_id`/`timeframe` with
    `start <= timestamp <= end` (both UTC, both required — an unbounded
    query is not a use case this checkpoint defines), in whatever order
    the concrete adapter naturally produces them. Ordering and integrity
    validation is the caller's/application-service's job
    (`domain.market_data.quality.ensure_chronological`), not this
    Protocol's — a read-only data-access interface should not also be a
    validation gate that silently reorders results."""

    def get_bars(
        self,
        instrument_id: InstrumentId,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> tuple[Bar, ...]: ...
