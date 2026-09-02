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
    inside it.

    `canonicalization_state` (Checkpoint 67.3, renamed values only in
    67.4): the row's `HistoricalBar.canonicalization_state` PROCESSING-
    STATE label (`domain.market_data.source_timestamp.
    CANONICALIZATION_STATE_*`), additive alongside `provenance` for the
    exact same reason — `ResearchDataGateService` needs "where did this
    data come from" AND "has this row's timestamp been canonicalized"
    to decide research eligibility.

    `source_timestamp_semantics` (Checkpoint 67.4): the row's
    `HistoricalBar.source_timestamp_semantics` SEMANTICS label
    (`domain.market_data.source_timestamp.SourceTimestampSemantics`),
    a THIRD, orthogonal fact carried alongside the other two — 67.3's
    `canonicalization_state` alone conflated "was the shift arithmetic
    run" with "was the raw convention ever proven"; this field restores
    the second question so `ResearchDataGateService` can require BOTH
    a proven semantics AND an applied canonicalization before treating a
    row as research-eligible (Part 6: REAL_DHAN provenance and a
    CANONICALIZED processing state are together still not sufficient —
    the semantics must also be proven, not merely UNKNOWN-but-shifted)."""

    bar: Bar
    provenance: str
    canonicalization_state: str
    source_timestamp_semantics: str


__all__ = ["ProvenancedBar"]
