# File: src/intraday/application/config_schema/records.py
#
# Application-level versioning envelope for RiskLimits (Checkpoint 7).
#
# domain.risk.RiskLimits (Checkpoint 5) is a pure value object — it has no
# identity or version, deliberately, because the shared kernel is locked
# to exactly 14 contracts and identity/versioning was not part of that
# approved shape. Persistence requires identity + version + a creation
# timestamp to make configuration reconstructable and immutable
# (Checkpoint 7 §5-6), so this small application-layer wrapper adds
# exactly those three fields WITHOUT modifying the locked domain
# contract. This is application code, not domain code — it may know
# about persistence-oriented concerns (identity, versioning) that the
# domain contract itself must not.
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from intraday.domain.risk.contracts import RiskLimits
from intraday.domain.shared_kernel.contracts import Version, ensure_utc


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
