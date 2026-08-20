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
class SignalEvidenceRecordView:
    signal_id: str
    strategy_id: str
    schema_version: str
    fields: tuple[tuple[str, str], ...]
    """`(label, value)` pairs, in strategy-defined order - a plain
    tuple-of-tuples (not a dict) so field ORDER is preserved exactly as
    the strategy produced it, matching `SignalEvidence.fields`."""
    generated_at: datetime


class SignalEvidenceRepository(Protocol):
    def save(self, signal_id: str, evidence: SignalEvidence) -> SignalEvidenceRecordView: ...

    def get_by_signal_id(self, signal_id: str) -> SignalEvidenceRecordView | None: ...


__all__ = ["SignalEvidenceRecordView", "SignalEvidenceRepository"]
