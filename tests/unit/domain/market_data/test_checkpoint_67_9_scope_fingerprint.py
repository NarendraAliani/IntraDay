# File: tests/unit/domain/market_data/test_checkpoint_67_9_scope_fingerprint.py
#
# Checkpoint 67.9 Part 7 — deterministic scope-fingerprint proofs. Pure
# functions, no DB.
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from intraday.domain.market_data.migration_scope_fingerprint import (
    MigrationScopeInputs,
    ScopeFingerprintMismatch,
    compute_scope_fingerprint,
    require_scope_fingerprint_unchanged,
)

_TS = datetime(2026, 1, 5, 9, 20, tzinfo=timezone.utc)


def _inputs(**overrides) -> MigrationScopeInputs:
    base = dict(
        migration_version="2026.09-1",
        provider="DHAN",
        segment="NSE_EQ",
        timeframe="5m",
        era="CAS",
        eligibility_predicate_version="v3",
        eligible_row_ids=(3, 1, 2),
        old_timestamps_by_row_id=((1, _TS), (2, _TS + timedelta(minutes=5)), (3, _TS + timedelta(minutes=10))),
        proof_scope="RELIANCE/5m/2026-01-05",
    )
    base.update(overrides)
    return MigrationScopeInputs(**base)


def test_fingerprint_is_stable_across_repeated_calls() -> None:
    a = compute_scope_fingerprint(_inputs())
    b = compute_scope_fingerprint(_inputs())
    assert a == b
    assert len(a) == 64  # hex sha256


def test_fingerprint_independent_of_row_id_and_timestamp_ordering() -> None:
    """Same population, different input order -> identical fingerprint."""
    forward = _inputs(
        eligible_row_ids=(1, 2, 3),
        old_timestamps_by_row_id=((1, _TS), (2, _TS + timedelta(minutes=5)), (3, _TS + timedelta(minutes=10))),
    )
    reversed_order = _inputs(
        eligible_row_ids=(3, 2, 1),
        old_timestamps_by_row_id=((3, _TS + timedelta(minutes=10)), (1, _TS), (2, _TS + timedelta(minutes=5))),
    )
    assert compute_scope_fingerprint(forward) == compute_scope_fingerprint(reversed_order)


@pytest.mark.parametrize(
    "field,override",
    [
        ("migration_version", {"migration_version": "2026.09-2"}),
        ("provider", {"provider": "OTHER"}),
        ("segment", {"segment": "NSE_FNO"}),
        ("timeframe", {"timeframe": "1m"}),
        ("era", {"era": "PRE_CAS"}),
        ("eligibility_predicate_version", {"eligibility_predicate_version": "v4"}),
        ("eligible_row_ids", {"eligible_row_ids": (1, 2, 3, 4)}),
        ("proof_scope", {"proof_scope": "RELIANCE/5m/2026-01-06"}),
    ],
)
def test_fingerprint_changes_when_any_covered_dimension_changes(field, override) -> None:
    baseline = compute_scope_fingerprint(_inputs())
    changed = compute_scope_fingerprint(_inputs(**override))
    assert baseline != changed, f"fingerprint did not change when {field} changed"


def test_fingerprint_changes_when_an_old_timestamp_changes_for_same_row_id() -> None:
    baseline = compute_scope_fingerprint(_inputs())
    drifted = compute_scope_fingerprint(
        _inputs(
            old_timestamps_by_row_id=(
                (1, _TS + timedelta(seconds=1)),  # row 1's OLD timestamp silently drifted
                (2, _TS + timedelta(minutes=5)),
                (3, _TS + timedelta(minutes=10)),
            )
        )
    )
    assert baseline != drifted


def test_require_scope_fingerprint_unchanged_passes_on_identical_values() -> None:
    fp = compute_scope_fingerprint(_inputs())
    require_scope_fingerprint_unchanged(expected=fp, recomputed=fp, unit_id="u1")  # no raise


def test_require_scope_fingerprint_unchanged_raises_on_mismatch_never_silently_refreshes() -> None:
    expected = compute_scope_fingerprint(_inputs())
    recomputed = compute_scope_fingerprint(_inputs(eligible_row_ids=(1, 2, 3, 4)))
    with pytest.raises(ScopeFingerprintMismatch) as exc_info:
        require_scope_fingerprint_unchanged(expected=expected, recomputed=recomputed, unit_id="u1")
    assert exc_info.value.expected == expected
    assert exc_info.value.actual == recomputed
    assert exc_info.value.unit_id == "u1"
