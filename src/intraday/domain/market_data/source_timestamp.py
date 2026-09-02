# File: src/intraday/domain/market_data/source_timestamp.py
#
# Checkpoint 67.1 Part 2 — the smallest reusable representation needed
# to distinguish a market-data PROVIDER's raw candle-timestamp
# convention from this application's own canonical contract
# (`Bar.timestamp` = bar-CLOSE, UTC — see `domain.market_data.
# contracts.Bar`'s own docstring).
#
# WHY THIS EXISTS: Checkpoint 67.0 conclusively proved, for Dhan's
# `/v2/charts/intraday` endpoint (RELIANCE, 2026-08-17, 5m, 15/15
# interior-bucket OPEN-aggregation matches, 0/15 CLOSE matches — see
# that checkpoint's `taskReport.md`), that Dhan's raw intraday candle
# timestamp is OPEN-of-interval, not CLOSE-of-interval. The previous
# adapter code (`historical_provider.py::_candle_to_bar`) copied that
# raw timestamp into `Bar.timestamp` with NO transform — a silent
# mislabeling. This module is deliberately NOT Dhan-specific: any
# future provider (a second broker, a vendor feed, a CSV import) has
# its own timestamp convention, which may be OPEN, CLOSE, or simply
# not yet established for that endpoint — so callers must state it
# explicitly rather than a default silently meaning "assume OPEN" or
# "assume CLOSE".
#
# DELIBERATELY SMALL: this is one enum plus one pure function, not a
# new Bar variant or a parallel timestamp-bearing dataclass — Part 2's
# explicit instruction to "avoid creating an unnecessary large
# abstraction." `ProvenancedBar` (research_bar.py) is a precedent for
# how this codebase already prefers a thin, additive wrapper over
# reshaping `Bar` itself.
from __future__ import annotations

import enum
from datetime import datetime, timedelta


class SourceTimestampSemantics(enum.Enum):
    """What a provider's raw candle timestamp represents, relative to
    the interval it labels. Exhaustive and explicit — there is
    deliberately no default member and no "most likely" fallback: a
    provider/endpoint whose convention has not been empirically
    established (67.0's discipline — only the tested endpoint/interval
    combination is asserted) must be classified UNKNOWN, never silently
    treated as OPEN or CLOSE."""

    OPEN = "OPEN"
    """Raw timestamp T represents the interval [T, T + interval)."""

    CLOSE = "CLOSE"
    """Raw timestamp T already represents this application's canonical
    bar-close contract — no transform needed."""

    UNKNOWN = "UNKNOWN"
    """Not empirically established for this provider/endpoint. Passing
    this to `canonicalize_close_timestamp` always raises — there is no
    silent default, per Checkpoint 67.1 Part 6 test case 8."""

    NOT_APPLICABLE = "NOT_APPLICABLE"
    """Checkpoint 67.4 Part 2: this row/source has no real provider
    raw-timestamp convention to classify at all — e.g. `SYNTHETIC_TEST`
    provenance (deterministically generated, never fetched from a
    provider) or `UNKNOWN` provenance (no corroborating source evidence
    to even name a convention for). Distinguished from `UNKNOWN` (a
    real provider whose convention has simply not yet been proven) so a
    reader can tell "nothing to prove" apart from "not yet proven"."""


class UnknownSourceTimestampSemanticsError(ValueError):
    """Raised by `canonicalize_close_timestamp` when asked to
    canonicalize a raw timestamp whose semantics are `UNKNOWN`. A
    provider must classify its convention (via empirical proof, as
    67.0 did for Dhan intraday) before any bar derived from it can be
    persisted under this application's canonical bar-close contract."""


def canonicalize_close_timestamp(
    raw_timestamp: datetime,
    semantics: SourceTimestampSemantics,
    interval_duration: timedelta,
) -> datetime:
    """Convert one provider-raw candle timestamp into this
    application's canonical bar-CLOSE timestamp. Pure arithmetic,
    generic across every interval (1m/5m/15m/1h/1d) — the caller
    supplies `interval_duration`, this function never hard-codes a
    clock time, symbol, or category (mirrors `_provider_request_
    envelope`'s existing "pure bar-duration arithmetic" discipline in
    `historical_provider.py`).

    OPEN  -> raw_timestamp + interval_duration  (67.0's proven Dhan
             intraday case: canonical_close = source_open + interval).
    CLOSE -> raw_timestamp unchanged (already canonical).
    UNKNOWN -> raises `UnknownSourceTimestampSemanticsError` — never a
             silent OPEN assumption (Part 6 test case 8)."""
    if semantics is SourceTimestampSemantics.OPEN:
        return raw_timestamp + interval_duration
    if semantics is SourceTimestampSemantics.CLOSE:
        return raw_timestamp
    raise UnknownSourceTimestampSemanticsError(
        "cannot canonicalize a raw timestamp whose provider semantics are "
        "UNKNOWN — classify the provider/endpoint's convention first "
        "(empirically, as Checkpoint 67.0 did for Dhan intraday) rather "
        "than silently assuming OPEN or CLOSE."
    )


# ---------------------------------------------------------------------------
# Checkpoint 67.3 (superseded by 67.4 below) — explicit, per-row
# CANONICALIZATION STATE.
#
# WHY THIS EXISTS: `SourceTimestampSemantics` (above) classifies a
# PROVIDER's raw convention (an in-memory, per-fetch concept, never
# persisted). It says nothing about whether any GIVEN, already-persisted
# `HistoricalBar` row was ever actually run through
# `canonicalize_close_timestamp`. 67.2's audit found exactly that gap:
# `HistoricalBar` has one timestamp field that cannot represent both
# raw-OPEN and canonical-CLOSE at once, `provenance='REAL_DHAN'` says
# nothing about which pipeline wrote a row, and 67.1 changed NEW Dhan
# ingestion to canonicalize before persisting — but the 11,442
# pre-existing REAL_DHAN rows were written by the OLD, non-canonicalizing
# pipeline and were never marked as such anywhere.
#
# ---------------------------------------------------------------------------
# Checkpoint 67.4 — THE CONFLATION FIX.
#
# 67.3's independent review (7.6/10, conditionally accepted) found a real
# design flaw: the four `CANONICALIZATION_STATE_*` constants below
# bundled TWO distinct questions into one field:
#
#   (A) SOURCE TIMESTAMP SEMANTICS — was the raw provider timestamp
#       proven OPEN-of-interval, proven CLOSE-of-interval, or never
#       empirically established at all? This is `SourceTimestampSemantics`
#       above (now persisted per-row too, see `HistoricalBar.
#       source_timestamp_semantics`, migrations 0039/0040).
#   (B) CANONICALIZATION PROCESSING STATE — has the OPEN->CLOSE shift
#       actually been APPLIED to this row's `bar_timestamp` value or
#       not? This is what `CANONICALIZATION_STATE_*` below now means,
#       and ONLY means — a purely mechanical "did the arithmetic run"
#       fact, independent of whether that arithmetic was semantically
#       justified.
#
# The dangerous consequence of the old, conflated single field: 67.1's
# `DhanHistoricalBarProvider.canonicalization_state_for()` stamped
# `CANONICAL_CLOSE` for EVERY intraday timeframe (1m/5m/15m/1h) simply
# because `_candle_to_bar` always ran the `+interval` arithmetic on all
# of them — even though 67.0 empirically proved OPEN semantics ONLY for
# 5m, CAS-era. "Code applied +interval" was being silently treated as
# equivalent to "data is semantically proven canonical" for 1m/15m/1h,
# which is exactly the bug this checkpoint closes (see
# `historical_provider.py`'s corrected `canonicalization_state_for`/
# `source_timestamp_semantics_for`).
#
# RENAMES (Part 8 — remove semantically misleading names): the two
# member values that named the WRONG concept are renamed; the two that
# were already dimension-neutral are kept as-is:
#   RAW_OPEN        -> UNCANONICALIZED  (was smuggling "OPEN" — a
#                      semantics claim — into a processing-state name)
#   CANONICAL_CLOSE  -> CANONICALIZED    (was smuggling "CLOSE" — a
#                      semantics claim — into a processing-state name)
#   NOT_APPLICABLE   -> unchanged (already dimension-neutral)
#   UNKNOWN          -> unchanged (already dimension-neutral)
CANONICALIZATION_STATE_UNCANONICALIZED = "UNCANONICALIZED"
"""This row's `bar_timestamp` has NOT been passed through
`canonicalize_close_timestamp` — it is still whatever raw value the
writing pipeline copied in verbatim. Purely a PROCESSING-STATE fact
(which code path wrote the row / whether the shift ran), never a claim
about that raw value's semantics — a row can be `UNCANONICALIZED`
whether or not 67.0-class proof exists for its provider/interval. Never
eligible for performance research (see `is_canonicalized` below)."""

CANONICALIZATION_STATE_CANONICALIZED = "CANONICALIZED"
"""This row's `bar_timestamp` has been run through
`canonicalize_close_timestamp` (or required no shift because its source
semantics were already `CLOSE`) — a PROCESSING-STATE fact only. This
does NOT by itself mean the row is research-eligible: a row can be
`CANONICALIZED` while its `source_timestamp_semantics` is still
`UNKNOWN` (e.g. a future bug that runs the arithmetic regardless of
proof) — `ResearchDataGateService` (67.4 Part 6) checks
`source_timestamp_semantics` SEPARATELY and requires it be proven
(`OPEN`/`CLOSE`) before trusting this flag. Set ONLY by a writer that
can prove the shift actually ran, never inferred or guessed."""

CANONICALIZATION_STATE_NOT_APPLICABLE = "NOT_APPLICABLE"
"""This row has no raw/canonicalized distinction to make at all — e.g.
`SYNTHETIC_TEST`/`UNKNOWN` provenance (no real provider timestamp
convention exists to canonicalize), or a timeframe this checkpoint
explicitly declines to classify (Dhan DAILY — Part 11: never encoded as
canonicalized unless independently proven, so it is kept OUT of this
state transition entirely rather than mislabeled either
`UNCANONICALIZED` or `CANONICALIZED`)."""

CANONICALIZATION_STATE_UNKNOWN = "UNKNOWN"
"""The column's safe default — canonicalization state not yet
determined for this row. Never treated as research-eligible. This is
what any row would show if a future writer forgets to set the field
explicitly; it is deliberately NOT `CANONICALIZED` (fail closed, not
fail open)."""

CANONICALIZATION_STATE_CHOICES = (
    CANONICALIZATION_STATE_UNCANONICALIZED,
    CANONICALIZATION_STATE_CANONICALIZED,
    CANONICALIZATION_STATE_NOT_APPLICABLE,
    CANONICALIZATION_STATE_UNKNOWN,
)


def is_canonicalized(canonicalization_state: str) -> bool:
    """A single, explicit, honest answer to "has this row's raw
    timestamp actually been run through the OPEN->CLOSE shift?" — a
    PURELY MECHANICAL/PROCESSING-STATE question. Only `CANONICALIZED`
    qualifies; `UNCANONICALIZED`, `NOT_APPLICABLE`, and `UNKNOWN` are all
    excluded. Deliberately says NOTHING about whether that shift was
    semantically justified — callers that need the semantic proof too
    (i.e. every research-eligibility caller) must ALSO check
    `is_source_semantics_proven` below; see `ResearchDataGateService`
    for the composition of both."""
    return canonicalization_state == CANONICALIZATION_STATE_CANONICALIZED


def is_source_semantics_proven(source_timestamp_semantics: str) -> bool:
    """A single, explicit, honest answer to "has this row's SOURCE
    timestamp convention actually been empirically established?" — the
    SEMANTICS half of the 67.4 split. Only `OPEN` or `CLOSE` qualify
    (both `SourceTimestampSemantics.OPEN.value`/`.CLOSE.value`);
    `UNKNOWN` and `NOT_APPLICABLE` are excluded. `UNKNOWN` failing here
    is precisely the invariant this checkpoint enforces: a row whose
    `canonicalization_state` is `CANONICALIZED` (the shift ran) but
    whose `source_timestamp_semantics` is `UNKNOWN` (the shift was never
    proven correct for that row's provider/interval/era) must still be
    rejected by the research gate — "code applied +interval" is not
    "data is semantically proven canonical"."""
    return source_timestamp_semantics in (
        SourceTimestampSemantics.OPEN.value,
        SourceTimestampSemantics.CLOSE.value,
    )


# Backward-compatible aliases for the pre-67.4 names, kept ONLY so any
# stray caller/import this audit missed fails loudly at import time
# rather than silently reading a renamed constant that no longer exists
# under its old name — deliberately NOT re-exported in `__all__` below,
# and NOT used anywhere in this codebase's own production code after
# this checkpoint (grep-verified). New code must use the 67.4 names.
CANONICALIZATION_STATE_RAW_OPEN = CANONICALIZATION_STATE_UNCANONICALIZED
CANONICALIZATION_STATE_CANONICAL_CLOSE = CANONICALIZATION_STATE_CANONICALIZED
is_canonical_research_ready = is_canonicalized


__all__ = [
    "SourceTimestampSemantics",
    "UnknownSourceTimestampSemanticsError",
    "canonicalize_close_timestamp",
    "CANONICALIZATION_STATE_UNCANONICALIZED",
    "CANONICALIZATION_STATE_CANONICALIZED",
    "CANONICALIZATION_STATE_NOT_APPLICABLE",
    "CANONICALIZATION_STATE_UNKNOWN",
    "CANONICALIZATION_STATE_CHOICES",
    "is_canonicalized",
    "is_source_semantics_proven",
]
