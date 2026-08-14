# File: src/intraday/control_plane/reconciliation/contracts.py
#
# Checkpoint 34 Part 13: broker-neutral reconciliation contracts. This
# module answers "what happened," never "what should we do about it" -
# Part 13's own explicit "no automatic corrective action... only
# detect, classify, report, audit."
from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime

from intraday.domain.shared_kernel.contracts import ensure_utc


class DivergenceType(enum.Enum):
    """Exactly the seven divergence types Checkpoint 34 Part 13 names,
    nothing else."""

    MISSING_LOCALLY = "MISSING_LOCALLY"
    MISSING_AT_BROKER = "MISSING_AT_BROKER"
    QUANTITY_MISMATCH = "QUANTITY_MISMATCH"
    STATUS_MISMATCH = "STATUS_MISMATCH"
    PRICE_MISMATCH = "PRICE_MISMATCH"
    POSITION_MISMATCH = "POSITION_MISMATCH"
    FUNDS_MISMATCH = "FUNDS_MISMATCH"


@dataclass(frozen=True, slots=True)
class Divergence:
    """One detected fact - a local record and a broker record disagree
    (or one is missing). `local_value`/`broker_value` are pre-formatted
    strings, not typed values - deliberately, since the two sides being
    compared can be entirely different shapes (an order status vs. a
    funds balance) and this contract must represent all of them
    uniformly for reporting/audit purposes (Part 14's reporting
    extension consumes this shape directly)."""

    divergence_type: DivergenceType
    entity_type: str  # "order" | "trade" | "position" | "funds"
    entity_id: str
    local_value: str | None
    broker_value: str | None
    detected_at: datetime
    explanation: str

    def __post_init__(self) -> None:
        ensure_utc(self.detected_at, field_name="Divergence.detected_at")
        if not self.entity_id.strip():
            raise ValueError("Divergence.entity_id must not be empty")


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    """The full result of one reconciliation pass - orders, trades,
    positions, and funds divergences, all together, so a single report
    answers "is everything consistent" in one place."""

    generated_at: datetime
    order_divergences: tuple[Divergence, ...]
    trade_divergences: tuple[Divergence, ...]
    position_divergences: tuple[Divergence, ...]
    funds_divergences: tuple[Divergence, ...]

    def __post_init__(self) -> None:
        ensure_utc(self.generated_at, field_name="ReconciliationReport.generated_at")

    @property
    def is_clean(self) -> bool:
        return not (
            self.order_divergences
            or self.trade_divergences
            or self.position_divergences
            or self.funds_divergences
        )

    @property
    def total_divergence_count(self) -> int:
        return (
            len(self.order_divergences)
            + len(self.trade_divergences)
            + len(self.position_divergences)
            + len(self.funds_divergences)
        )
