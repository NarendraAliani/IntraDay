# File: src/intraday/application/repositories/signal_evidence.py
#
# Checkpoint 64.18 §8-11: the Protocol for the ONE persisted copy of a
# strategy-produced `SignalEvidence` (see `trading_engine.strategy_
# execution.evidence`'s own docstring for the architecture decision) -
# mirrors `TradePlanRepository`'s own established "one signal_id -> one
# record, save()/get_by_signal_id()" shape exactly, audited before
# creating this (Checkpoint 64.7's own precedent), never a duplicate
# signal record.
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from intraday.trading_engine.strategy_execution.evidence import SignalEvidence


@dataclass(frozen=True, slots=True)
class SignalEvidenceFieldView:
    """Checkpoint 64.81: one persisted evidence row, read back with its
    canonical field identity attached. Replaces the bare `(label,
    value)` 2-tuple this view used to expose - that shape was exactly
    Checkpoint 64.80-F3's gap 2 (free text cannot be correlated with
    `FieldDefinition.field_id`).

    Both identity fields are independently nullable and are NEVER
    fabricated:
      - `feature_name` is `None` when the strategy did not attribute
        this row to a feature (e.g. `Price`, `Direction`), or when the
        row was persisted BEFORE this checkpoint (a legacy 2-element
        JSON pair - see `signal_evidence_repository._to_view()`).
      - `field_id` is `None` whenever `feature_name` is `None`, and
        additionally when the name does not resolve to a registered
        `FieldDefinition` - resolution is done by
        `field_registry.resolve_feature_name()`, never by matching on
        `label`.
    """

    label: str
    value: str
    feature_name: str | None = None
    field_id: str | None = None


@dataclass(frozen=True, slots=True)
class SignalEvidenceRecordView:
    signal_id: str
    strategy_id: str
    schema_version: str
    fields: tuple[SignalEvidenceFieldView, ...]
    """Strategy-defined order preserved exactly (a tuple, not a dict),
    matching `SignalEvidence.fields`."""
    generated_at: datetime


class SignalEvidenceRepository(Protocol):
    def save(self, signal_id: str, evidence: SignalEvidence) -> SignalEvidenceRecordView: ...

    def get_by_signal_id(self, signal_id: str) -> SignalEvidenceRecordView | None: ...


__all__ = [
    "SignalEvidenceFieldView",
    "SignalEvidenceRecordView",
    "SignalEvidenceRepository",
]
