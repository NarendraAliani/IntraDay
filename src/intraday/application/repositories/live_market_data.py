# File: src/intraday/application/repositories/live_market_data.py
#
# Checkpoint 23: repository Protocols for live-observed market data and
# its health tracking. Mirrors `application/repositories/
# provider_settings.py`'s own file-split precedent (Checkpoint 22) -
# dedicated module, not crammed into `application/repositories/
# __init__.py`.
#
# `LiveQuoteRepository` deals only in the canonical domain `Quote`
# contract (Checkpoint 5) - never a Dhan-shaped type. The application
# layer, and this Protocol, have zero knowledge of Dhan's security_id/
# exchange-segment vocabulary; that translation happens entirely inside
# `infrastructure/api/market_data_views.py` (the one place allowed to
# import both `application/*` and `infrastructure/market_data_providers/
# dhan/*` - matching Checkpoint 22 decision 105's precedent for exactly
# this reason: `.importlinter` contract 6 forbids `application/*` from
# importing `intraday.infrastructure.*`).
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from intraday.domain.market_data.contracts import Quote


@dataclass(frozen=True, slots=True)
class MarketDataHealthRecord:
    """The persisted health facts - what `MarketDataHealthRepository.get()`
    returns. `control_plane.market_data_health.evaluator.evaluate_health()`
    turns this into a classified `MarketDataHealthSnapshot`; this record
    itself makes no classification judgement."""

    last_success_at: datetime | None
    last_failure_at: datetime | None
    last_error_safe: str
    consecutive_failures: int


class LiveQuoteRepository(Protocol):
    """Persists and retrieves live-observed `Quote`s. Read-only from the
    perspective of `application/services/live_market_data.py`'s own
    business logic - it has no validation/business rule of its own
    beyond "store what was fetched, return the latest per instrument."""

    def save_all(self, quotes: tuple[Quote, ...], *, fetched_at: datetime) -> None: ...

    def get_latest(self) -> tuple[Quote, ...]:
        """The most recently observed `Quote` for each instrument in the
        configured observation universe that has ever been successfully
        fetched - empty tuple if none has."""
        ...


class MarketDataHealthRepository(Protocol):
    """Reusable, single-row (singleton-by-convention, matching Checkpoint
    22's `ProviderConnectionStatus` precedent) health tracking - one
    process-wide record, since this checkpoint has exactly one market-
    data source (Dhan) and one observation universe, not per-instrument
    health."""

    def get(self) -> MarketDataHealthRecord: ...

    def record_success(self, *, checked_at: datetime) -> None: ...

    def record_failure(self, *, checked_at: datetime, error_safe: str) -> None: ...
