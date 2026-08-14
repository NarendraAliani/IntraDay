# File: src/intraday/application/config_schema/records.py
#
# Application-level versioning envelopes (Checkpoint 7; extended
# Checkpoint 8).
#
# domain.risk.RiskLimits (Checkpoint 5) is a pure value object — it has no
# identity or version, deliberately, because the shared kernel is locked
# to exactly 14 contracts and identity/versioning was not part of that
# approved shape. Persistence requires identity + version + a creation
# timestamp to make configuration reconstructable and immutable
# (Checkpoint 7 §5-6), so RiskConfigurationRecord adds exactly those
# fields WITHOUT modifying the locked domain contract.
#
# domain.universe.Universe and domain.strategy.StrategyVersion already
# carry their own identity/version fields, so Checkpoint 7 did not wrap
# them — but neither carries a `created_at`. Checkpoint 8's API surface
# needs "when was this version created" for all three resources (a
# genuine, newly-surfaced requirement, not scope creep), so
# UniverseRecord and StrategyVersionSnapshot add exactly that one field
# each, the same pattern as RiskConfigurationRecord. This is application
# code, not domain code — it may know about persistence/API-oriented
# concerns (timestamps of record creation) that the domain contracts
# themselves must not.
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from intraday.domain.risk.contracts import RiskLimits
from intraday.domain.shared_kernel.contracts import Version, ensure_utc
from intraday.domain.strategy.contracts import StrategyVersion
from intraday.domain.universe.contracts import Universe


@dataclass(frozen=True, slots=True)
class RiskConfigurationRecord:
    """One immutable, versioned RiskLimits configuration instance.

    `risk_configuration_id` identifies *which* named risk policy this is
    (e.g. "default", "conservative") — a config family, not a single
    value. `version` + `created_at` make every historical record
    reconstructable; nothing about this dataclass permits in-place
    mutation of a past version (Checkpoint 7 §6).
    """

    risk_configuration_id: str
    version: Version
    limits: RiskLimits
    created_at: datetime

    def __post_init__(self) -> None:
        if not self.risk_configuration_id.strip():
            raise ValueError("RiskConfigurationRecord.risk_configuration_id must be non-empty")
        ensure_utc(self.created_at, field_name="RiskConfigurationRecord.created_at")


@dataclass(frozen=True, slots=True)
class UniverseRecord:
    """A persisted `Universe` version plus its creation timestamp
    (Checkpoint 8) — `Universe` itself already carries identity/version,
    so this wrapper adds only `created_at`."""

    universe: Universe
    created_at: datetime

    def __post_init__(self) -> None:
        ensure_utc(self.created_at, field_name="UniverseRecord.created_at")


@dataclass(frozen=True, slots=True)
class StrategyVersionSnapshot:
    """A persisted `StrategyVersion` plus its creation timestamp
    (Checkpoint 8). Named "Snapshot", not "Record", to avoid confusion
    with the unrelated `StrategyVersionRecord` Django model in
    `infrastructure/persistence/models.py`."""

    strategy_version: StrategyVersion
    created_at: datetime

    def __post_init__(self) -> None:
        ensure_utc(self.created_at, field_name="StrategyVersionSnapshot.created_at")


@dataclass(frozen=True, slots=True)
class StrategyConfigurationSnapshot:
    """A persisted set of strategy parameter VALUES plus its identity and
    creation metadata (Checkpoint 26). Layered alongside, not on top of,
    `StrategyVersionSnapshot` above - that type remains the version-
    IDENTITY record; this carries the actual values a
    `configuration_version` label points at (a genuinely new need,
    per `application/config_schema/strategy.py`'s own prior-checkpoint
    deferral comment)."""

    strategy_id: str
    specification_version: str
    code_version: str
    configuration_version: str
    parameter_values: dict[str, object]
    created_at: datetime
    created_by: str

    def __post_init__(self) -> None:
        ensure_utc(self.created_at, field_name="StrategyConfigurationSnapshot.created_at")
        for name in (
            "strategy_id",
            "specification_version",
            "code_version",
            "configuration_version",
            "created_by",
        ):
            if not getattr(self, name).strip():
                raise ValueError(f"StrategyConfigurationSnapshot.{name} must be non-empty")
