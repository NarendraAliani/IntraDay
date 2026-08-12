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
    inserts a new version; there is no `update()`."""

    def save(self, record: RiskConfigurationRecord) -> None: ...

    def get_version(
        self, risk_configuration_id: str, version: str
    ) -> RiskConfigurationRecord | None: ...

    def get_active(self, risk_configuration_id: str) -> RiskConfigurationRecord | None: ...

    def list_versions(self, risk_configuration_id: str) -> tuple[RiskConfigurationRecord, ...]: ...

    def activate(self, risk_configuration_id: str, version: str) -> None: ...


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
