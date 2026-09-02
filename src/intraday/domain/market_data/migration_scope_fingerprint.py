# File: src/intraday/domain/market_data/migration_scope_fingerprint.py
#
# Checkpoint 67.9 Part 7 — DETERMINISTIC MIGRATION SCOPE FINGERPRINT.
#
# A migration run's "scope" (which rows it believes it is entitled to
# touch) can go stale: a new row could be ingested into the eligible
# range between planning and commit, an eligibility rule could change
# version, or a previously-planned row could be deleted/reclassified.
# Without a way to detect that, a resumed or long-running migration
# could silently act on a DIFFERENT population than the one it was
# validated against — exactly the "silently refreshed scope" failure
# mode the directive prohibits.
#
# `compute_scope_fingerprint` hashes a CANONICAL, STABLE representation
# of every dimension the directive lists as load-bearing:
#   migration version, provider, segment, timeframe, era, eligibility
#   predicate/version, eligible row IDs, old timestamps, proof scope.
#
# "Canonical" here means: every collection is sorted before hashing (no
# dependence on iteration/insertion order), every value is rendered
# through a fixed, explicit format (no reliance on `repr`/`str`
# defaults that could change across Python versions), and the digest is
# computed over one single deterministic byte string, not a Python
# `hash()` (which is process-randomized for security by default and
# therefore NOT reproducible across processes/restarts — using it here
# would silently break Part 11 resume semantics, since a value computed
# in the old process could never be verified as unchanged by a new
# one).
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class MigrationScopeInputs:
    """Every dimension `compute_scope_fingerprint` covers, exactly as
    named in the directive's Part 7 list. `eligible_row_ids` and
    `old_timestamps_by_row_id` together let a re-fingerprint at
    revalidation time detect BOTH "the eligible population changed"
    (row set differs) AND "a row's pre-migration timestamp changed
    under us" (same row id, different recorded old_timestamp) — either
    is a genuine scope drift, not merely a cosmetic difference."""

    migration_version: str
    provider: str
    segment: str
    timeframe: str
    era: str
    eligibility_predicate_version: str
    eligible_row_ids: tuple[int, ...]
    old_timestamps_by_row_id: tuple[tuple[int, datetime], ...]
    proof_scope: str


def _canonical_payload(inputs: MigrationScopeInputs) -> str:
    """Builds the single deterministic string that gets hashed. Row IDs
    and the (row_id, old_timestamp) pairs are BOTH sorted by row_id
    before rendering — input order (e.g. whatever order a queryset
    happened to iterate in) must never affect the fingerprint. Every
    timestamp is rendered via `.isoformat()` on a value the caller is
    responsible for keeping timezone-aware (this function does not
    silently normalize a naive datetime — a naive value renders
    visibly without a UTC offset, and any timestamp comparison bug
    upstream shows up as a fingerprint mismatch rather than being
    hidden here)."""
    sorted_row_ids = sorted(inputs.eligible_row_ids)
    sorted_old_timestamps = sorted(inputs.old_timestamps_by_row_id, key=lambda pair: pair[0])
    parts = [
        f"migration_version={inputs.migration_version}",
        f"provider={inputs.provider}",
        f"segment={inputs.segment}",
        f"timeframe={inputs.timeframe}",
        f"era={inputs.era}",
        f"eligibility_predicate_version={inputs.eligibility_predicate_version}",
        "eligible_row_ids=[" + ",".join(str(rid) for rid in sorted_row_ids) + "]",
        "old_timestamps=["
        + ",".join(f"{rid}:{ts.isoformat()}" for rid, ts in sorted_old_timestamps)
        + "]",
        f"proof_scope={inputs.proof_scope}",
    ]
    return "|".join(parts)


def compute_scope_fingerprint(inputs: MigrationScopeInputs) -> str:
    """Hex SHA-256 digest of the canonical payload. SHA-256 (not
    Python's `hash()`) specifically because it is stable across
    processes, machines, and Python versions/runs — a requirement for
    Part 11's "recompute and compare after a restart" resume check to
    mean anything at all."""
    payload = _canonical_payload(inputs)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ScopeFingerprintMismatch(RuntimeError):
    """Raised by `require_scope_fingerprint_unchanged` — the directive's
    explicit STOP/REVALIDATION_MISMATCH behavior. Never auto-resolved;
    a caller catching this must re-plan a fresh run, not silently adopt
    the new fingerprint under the old migration_id."""

    def __init__(self, *, expected: str, actual: str, unit_id: str | None = None) -> None:
        self.expected = expected
        self.actual = actual
        self.unit_id = unit_id
        scope = f" for unit {unit_id}" if unit_id else ""
        super().__init__(
            f"scope fingerprint mismatch{scope}: expected {expected}, recomputed {actual} - "
            "STOPPED_REVALIDATION_MISMATCH, not silently refreshed"
        )


def require_scope_fingerprint_unchanged(
    *, expected: str, recomputed: str, unit_id: str | None = None
) -> None:
    """The one call every write-capable unit must make immediately
    before proceeding, per Part 7: lock -> recompute eligibility ->
    recompute scope fingerprint -> compare -> continue only if
    identical. Raises `ScopeFingerprintMismatch` on any difference;
    never returns a bool a caller could accidentally ignore."""
    if expected != recomputed:
        raise ScopeFingerprintMismatch(expected=expected, actual=recomputed, unit_id=unit_id)


__all__ = [
    "MigrationScopeInputs",
    "compute_scope_fingerprint",
    "ScopeFingerprintMismatch",
    "require_scope_fingerprint_unchanged",
]
