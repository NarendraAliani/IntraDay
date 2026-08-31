# File: src/intraday/domain/market_data/research_bar.py
#
# Checkpoint 66.1 — Part 2's chosen "smallest architecture-preserving"
# provenance-carrying design: Option B, a THIN wrapper value object,
# not Option C (grafting a `provenance` field onto the canonical
# `Bar` — Checkpoint 5/14's shared contract used identically by
# backtest/paper/live, per that dataclass's own docstring; adding a
# historical-archive-only concept to it would leak backtest-only
# knowledge into every live/paper consumer) and not Option A (there is
# no existing "research DTO" to extend — `Bar` itself is already the
# returned type everywhere).
#
# `ProvenancedBar` exists ONLY on the research/backtest read boundary
# (`application.services.research_data_gate`) — it is never returned
# by `HistoricalMarketDataRepository.get_bars()` (the pre-existing,
# unmodified, generic Protocol every non-research consumer depends
# on), so this is additive and does not pollute any unrelated
# market-data consumer (Part 2's explicit warning).
from __future__ import annotations

from dataclasses import dataclass

from intraday.domain.market_data.contracts import Bar


@dataclass(frozen=True, slots=True)
class ProvenancedBar:
    """One historical bar plus the `HistoricalBar.provenance` label
    (`domain.market_data.provenance.PROVENANCE_*`) it was persisted
    with. `bar` is the ordinary, unmodified `Bar` — nothing about its
    own shape changes; `provenance` is carried alongside it, not
    inside it."""

    bar: Bar
    provenance: str


__all__ = ["ProvenancedBar"]
