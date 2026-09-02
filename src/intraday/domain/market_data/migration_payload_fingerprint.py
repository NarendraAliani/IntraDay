# File: src/intraday/domain/market_data/migration_payload_fingerprint.py
#
# Checkpoint 67.12-PRE Part 1 — CANONICAL PAYLOAD FINGERPRINT.
#
# `migration_scope_fingerprint.compute_scope_fingerprint()` (67.9) hashes
# migration SCOPE identity: which rows a migration unit believes it is
# entitled to touch (row ids + their pre-migration timestamps), plus the
# eligibility-rule dimensions that make that set valid. It intentionally
# does NOT look at OHLCV/provenance/semantic content at all — that was
# never its job, and conflating the two is exactly the root cause this
# checkpoint diagnosed for the 67.11.6 vs 67.12 mismatch (see
# taskReport.md Deliverable C): the 67.11.6 backup's recorded
# `unit_fingerprint` was produced by an ephemeral, never-committed script
# that is not `compute_scope_fingerprint` at all, so comparing its output
# to a live `compute_scope_fingerprint()` recomputation was an
# apples-to-oranges comparison from the start — two different functions,
# never proven equivalent, being asked to agree.
#
# This module hashes PAYLOAD identity instead: does every OHLCV/
# provenance/semantic field of every row in an exported unit exactly
# match the live source, independent of row/eligibility bookkeeping.
# `compute_payload_fingerprint` and `compute_scope_fingerprint` are
# deliberately separate functions producing separate values that a
# caller must never treat as interchangeable.
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class PayloadRow:
    """Every field the checkpoint 67.12-PRE Part 1 directive lists,
    exactly, no more and no fewer. `Decimal` fields are kept as
    `Decimal` (never `float`) so serialization is exact and
    reproducible."""

    id: int
    instrument_id: str
    exchange: str
    symbol: str
    timeframe: str
    bar_timestamp: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: Decimal
    source: str
    provenance: str
    source_timestamp_semantics: str
    canonicalization_state: str


def _render_row(row: PayloadRow) -> str:
    """One row -> one canonical, self-describing `field=value` line.
    Every field is explicitly named (not positional) so a future field
    reordering in `PayloadRow` can never silently change which value a
    given hash byte represents. `Decimal` is rendered via `str()` on the
    Decimal itself (never via `float()`, which is lossy and platform-
    dependent) so `Decimal("1685.1000")` and `Decimal("1685.10")` are
    intentionally treated as scale-sensitive and NOT collapsed to the
    same string — matching the codebase's existing "no numeric type
    fuzziness" behaviour used elsewhere in the migration modules."""
    return "|".join(
        [
            f"id={row.id}",
            f"instrument_id={row.instrument_id}",
            f"exchange={row.exchange}",
            f"symbol={row.symbol}",
            f"timeframe={row.timeframe}",
            f"bar_timestamp={row.bar_timestamp.isoformat()}",
            f"open_price={row.open_price}",
            f"high_price={row.high_price}",
            f"low_price={row.low_price}",
            f"close_price={row.close_price}",
            f"volume={row.volume}",
            f"source={row.source}",
            f"provenance={row.provenance}",
            f"source_timestamp_semantics={row.source_timestamp_semantics}",
            f"canonicalization_state={row.canonicalization_state}",
        ]
    )


def _canonical_payload(rows: tuple[PayloadRow, ...]) -> str:
    """Sorts rows by `id` (the one field that is guaranteed unique and
    stable per row, per the directive's "deterministic ordering (e.g.
    sort by id)" instruction) before rendering, so callers passing rows
    in ANY order (DB iteration order, dict order, whatever a queryset
    happened to yield) always produce byte-identical output."""
    ordered = sorted(rows, key=lambda r: r.id)
    return "\n".join(_render_row(r) for r in ordered)


def compute_payload_fingerprint(rows: tuple[PayloadRow, ...] | list[PayloadRow]) -> str:
    """Hex SHA-256 digest of the canonical payload rendering. Distinct,
    by construction and by name, from `compute_scope_fingerprint` —
    a caller that wants both proofs (scope identity AND payload content)
    must call both functions and record both results; neither one
    substitutes for the other."""
    payload = _canonical_payload(tuple(rows))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = ["PayloadRow", "compute_payload_fingerprint"]
