# File: src/intraday/application/repositories/paper_session.py
#
# Checkpoint 64.68 §18: the persistence Protocol for a REPLAY PAPER
# SESSION. Mirrors this project's established repository shape
# (`scanner_configuration.py`, `worker_runtime_status.py`): a frozen
# dataclass record + a `Protocol`, implemented by
# `infrastructure/persistence/paper_session_repository.py` (dependency
# inversion, `.importlinter` contract 6).
#
# WHAT IS PERSISTED, AND WHY THAT IS SUFFICIENT (§18's "session state
# can be reconstructed after a fresh service instance"): a replay paper
# session is, by construction, a PURE DETERMINISTIC FUNCTION of its own
# specification (strategy, instrument, timeframe, replay date, starting
# capital, quantity) and its `replay_cursor`. Persisting those fields is
# therefore persisting the session ENTIRELY - positions, trades, fills
# and P&L are re-derived by replaying the same bars through the same
# canonical PaperBroker/risk path, and are guaranteed identical because
# the reproducibility test proves exactly that. Snapshotting derived
# P&L rows into a second set of tables would create a competing source
# of truth for numbers the canonical accounting already owns, which
# §16 forbids.
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True, slots=True)
class PaperSessionRecord:
    session_id: str
    status: str
    """A `PaperSessionStatus` value. Stored as its string value (the
    same discipline `PaperOrderRecord.status` already uses for
    `OrderStatus`) so a future enum addition can never silently
    invalidate historic rows."""
    strategy_id: str
    timeframe: str
    instrument_ids: tuple[str, ...]
    starting_capital: Decimal
    quantity: Decimal
    replay_date: date
    """The single trading date whose deterministic replay bars this
    session runs against - part of the session's reproducibility
    identity, never `today()` at read time."""
    replay_cursor: int
    """How many replay STEPS have been applied. 0 = nothing replayed."""
    replay_total_steps: int
    playback_speed: int
    """Steps advanced per RUN tick. >= 1. Purely a playback-rate control;
    it never changes WHICH bars are replayed or in what order, so it can
    never affect reproducibility of a completed session."""
    created_at: datetime | None
    updated_at: datetime | None
    last_error: str = ""


class PaperSessionRepository(Protocol):
    def get(self, session_id: str) -> PaperSessionRecord | None: ...

    def save(self, record: PaperSessionRecord) -> PaperSessionRecord:
        """Create-or-update by `session_id`. Never bumps a version or
        mutates any field the caller did not set - the caller always
        supplies a complete record."""
        ...

    def list_all(self) -> tuple[PaperSessionRecord, ...]:
        """Newest first."""
        ...


__all__ = ["PaperSessionRecord", "PaperSessionRepository"]
