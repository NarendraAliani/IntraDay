# File: src/intraday/application/services/live_market_data.py
#
# Checkpoint 23: application-layer orchestration for live market-data
# observation. Depends only on the repository Protocols
# (application/repositories/live_market_data.py) and pure domain logic
# (domain/session/calendar.py, control_plane/market_data_health's pure
# evaluator) - NEVER a concrete Dhan/HTTP client (`.importlinter`
# contract 6, "Application must not depend on infrastructure" -
# Checkpoint 22 decision 105's precedent applies identically here: the
# actual Dhan HTTP call happens in `infrastructure/api/
# market_data_views.py`, which calls INTO this service with already-
# fetched, already-normalized `Quote`s, never the reverse).
#
# Signal generation is deliberately absent from every import here
# (Checkpoint 23 §13's explicit instruction) - this service has no way
# to reach `signal_intelligence.signal_generation` even if a future
# change wanted it to, since nothing in this module imports it.
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from intraday.application.repositories.live_market_data import (
    LiveQuoteRepository,
    MarketDataHealthRepository,
)
from intraday.control_plane.market_data_health.contracts import MarketDataHealthSnapshot
from intraday.control_plane.market_data_health.evaluator import evaluate_health
from intraday.domain.market_data.contracts import Quote
from intraday.domain.session.calendar import session_for_instant
from intraday.domain.session.contracts import TradingSession


@dataclass(frozen=True, slots=True)
class LiveMarketDataService:
    quote_repository: LiveQuoteRepository
    health_repository: MarketDataHealthRepository

    def record_refresh_success(self, quotes: tuple[Quote, ...], *, fetched_at: datetime) -> None:
        """Called by the view layer after a successful live fetch -
        persists the observed quotes and marks the health record's most
        recent attempt as a success. Contains no logic of its own beyond
        this direct pass-through: the actual fetch, and the decision of
        whether it succeeded, already happened one layer up."""
        self.quote_repository.save_all(quotes, fetched_at=fetched_at)
        self.health_repository.record_success(checked_at=fetched_at)

    def record_refresh_failure(self, *, checked_at: datetime, error_safe: str) -> None:
        """Called by the view layer after a failed live fetch (network,
        auth, or malformed-response error, already sanitized by the
        infrastructure client) - records the failure without touching
        any previously-persisted quote (a failed refresh must never
        silently blank out the last known-good observation)."""
        self.health_repository.record_failure(checked_at=checked_at, error_safe=error_safe)

    def get_quotes(self) -> tuple[Quote, ...]:
        """The latest observed `Quote` per instrument. May be empty if a
        refresh has never succeeded - the caller (API view) is
        responsible for representing that honestly, never fabricating a
        placeholder quote."""
        return self.quote_repository.get_latest()

    def get_health(self, *, now: datetime) -> MarketDataHealthSnapshot:
        """Classifies current market-data health by combining the
        persisted facts (`MarketDataHealthRepository.get()`) with the
        current market session state - MARKET_CLOSED is a legitimate,
        distinct health state (Checkpoint 23 §9), not an error."""
        record = self.health_repository.get()
        session = session_for_instant(now)
        return evaluate_health(
            last_success_at=record.last_success_at,
            last_failure_at=record.last_failure_at,
            last_error_safe=record.last_error_safe,
            consecutive_failures=record.consecutive_failures,
            session_status=session.status,
            now=now,
        )

    def get_session(self, *, now: datetime) -> TradingSession:
        """The current NSE cash-equity trading session (Checkpoint 23
        §8) - computed fresh on every call, never cached/persisted, since
        it is a pure function of `now` and needs no I/O."""
        return session_for_instant(now)
