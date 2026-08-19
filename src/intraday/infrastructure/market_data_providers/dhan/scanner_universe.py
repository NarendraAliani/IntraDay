# File: src/intraday/infrastructure/market_data_providers/dhan/scanner_universe.py
#
# Checkpoint 64.4: resolves a `ScannerConfigurationRecord`'s desired
# `universe_mode` into a concrete list of `DhanInstrument`s to
# subscribe to - the ONE place this resolution happens, so the worker
# command never hand-rolls "which mode means what" logic itself.
from __future__ import annotations

import structlog

from intraday.application.repositories import WatchlistRepository
from intraday.application.repositories.scanner_configuration import ScannerConfigurationRecord
from intraday.domain.instrument.contracts import parse_instrument_id
from intraday.infrastructure.market_data_providers.dhan.instrument_master import (
    DhanInstrumentMasterProvider,
)
from intraday.infrastructure.market_data_providers.dhan.instruments import (
    DhanInstrument,
    UnknownObservationSymbolError,
    observation_universe,
)

logger = structlog.get_logger(__name__)


def _instrument_master() -> DhanInstrumentMasterProvider:
    return DhanInstrumentMasterProvider()


def resolve_scanner_universe(
    config: ScannerConfigurationRecord, *, watchlist_repository: WatchlistRepository
) -> tuple[DhanInstrument, ...]:
    """Resolves the DESIRED universe (Checkpoint 64.4's own §6) into a
    concrete instrument list:

    - `ALL_CONFIGURED`: the existing `observation_universe()`
      (Checkpoint 64's own scrip-master-backed resolver) - unchanged,
      never re-implemented.
    - `SELECTED`: `config.selected_instrument_ids` (`"NSE:SYMBOL"`
      strings), resolved via the real scrip master (never guessed).
    - `WATCHLIST`: `config.selected_watchlist_name`, owned by
      `config.requested_by` (the operator who configured the scanner)
      - the SAME `WatchlistRepository` Protocol the research watchlist
        feature already uses, never a duplicate concept.

    An instrument this project cannot resolve a real `security_id` for
    is skipped, not fabricated - matches `observation_universe()`'s own
    "refuse to guess" discipline."""
    if config.universe_mode == "ALL_CONFIGURED":
        return observation_universe()

    if config.universe_mode == "WATCHLIST":
        raw_ids = watchlist_repository.get(config.selected_watchlist_name, config.requested_by)
        if raw_ids is None:
            logger.warning(
                "scanner_universe.watchlist_not_found",
                name=config.selected_watchlist_name,
                owner=config.requested_by,
            )
            return ()
        return _resolve_symbols(raw_ids)

    # SELECTED
    return _resolve_symbols(list(config.selected_instrument_ids))


def _resolve_symbols(raw_instrument_ids: list[str]) -> tuple[DhanInstrument, ...]:
    master = _instrument_master()
    resolved: list[DhanInstrument] = []
    seen_security_ids: set[int] = set()
    for raw_id in raw_instrument_ids:
        try:
            exchange, symbol = parse_instrument_id(raw_id)  # type: ignore[arg-type]
        except ValueError:
            logger.warning("scanner_universe.malformed_instrument_id", instrument_id=raw_id)
            continue
        try:
            entries = master.list_instruments(exchange)
        except Exception:  # noqa: BLE001 - master unavailable for this symbol - skip, never guess
            logger.warning("scanner_universe.master_unavailable", instrument_id=raw_id)
            continue
        match = next((e for e in entries if e.symbol == symbol and e.security_id), None)
        if match is None or match.security_id is None:
            logger.warning("scanner_universe.unresolvable_instrument", instrument_id=raw_id)
            continue
        if match.security_id in seen_security_ids:
            # Checkpoint 64.5 §22: a duplicate configured symbol must never
            # produce a duplicate subscribe entry.
            logger.warning("scanner_universe.duplicate_instrument_skipped", instrument_id=raw_id)
            continue
        seen_security_ids.add(match.security_id)
        segment = "NSE_EQ" if exchange.value == "NSE" else "BSE_EQ"
        resolved.append(
            DhanInstrument(symbol=symbol, security_id=match.security_id, exchange_segment=segment)
        )
    return tuple(resolved)


__all__ = ["resolve_scanner_universe", "UnknownObservationSymbolError"]
