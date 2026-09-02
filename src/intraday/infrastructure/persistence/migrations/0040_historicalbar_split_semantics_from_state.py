# File: src/intraday/infrastructure/persistence/migrations/0040_historicalbar_split_semantics_from_state.py
#
# Checkpoint 67.4 Part 3/8: DATA-ONLY migration that (a) RENAMES
# `HistoricalBar.canonicalization_state`'s existing values off the two
# names 67.3's independent review found semantically misleading
# ("RAW_OPEN"/"CANONICAL_CLOSE" smuggled a SEMANTICS claim into a field
# that is supposed to be a pure PROCESSING-STATE marker) onto their
# dimension-neutral replacements, and (b) classifies the NEW
# `source_timestamp_semantics` column (added by 0039, defaulted
# "UNKNOWN") for every pre-existing row. NEITHER operation ever reads,
# computes, or writes `bar_timestamp`, OHLC, volume, or `provenance` on
# any row — only these two classification columns are updated.
#
# PART (a) — RENAME (no semantic reclassification, a pure string swap):
#   "RAW_OPEN"       -> "UNCANONICALIZED"
#   "CANONICAL_CLOSE" -> "CANONICALIZED"
#   "NOT_APPLICABLE" / "UNKNOWN" -> unchanged (already dimension-neutral)
#
# PART (b) — SOURCE-SEMANTICS CLASSIFICATION (mechanical, per the exact
# table Checkpoint 67.4's directive specifies — Part 3):
#   - provenance=REAL_DHAN, timeframe=5m, bar_timestamp date >=
#     CAS_EFFECTIVE_DATE (2026-08-03, `domain.session.calendar`) ->
#     "OPEN". This is the ONLY scope 67.0 empirically proved (RELIANCE,
#     2026-08-17, 5m, 15/15 interior-bucket match) — 10,266 rows.
#   - provenance=REAL_DHAN, timeframe=1m (any date) -> "UNKNOWN". 67.0's
#     proof never covered 1m; classifying these OPEN merely because they
#     predate 67.1 (or resemble the proven 5m case) is the exact mistake
#     this checkpoint corrects — 880 rows.
#   - provenance=REAL_DHAN, timeframe=5m, bar_timestamp date <
#     CAS_EFFECTIVE_DATE ("PRE-CAS") -> "UNKNOWN". 67.0's proof was
#     CAS-era only; PRE-CAS 5m semantics are not established — 296 rows.
#   - provenance=SYNTHETIC_TEST -> "NOT_APPLICABLE" (no real provider
#     timestamp convention exists to classify at all; 0 rows currently).
#   - provenance=UNKNOWN -> "UNKNOWN" (no corroborating evidence to
#     prove any convention) — 5,100 rows.
#
# `canonicalization_state` (the renamed PROCESSING-STATE column) is NOT
# re-derived here — every pre-existing row keeps exactly the
# UNCANONICALIZED/NOT_APPLICABLE processing-state 0038 already assigned
# it (post-rename); this migration only ADDS the orthogonal semantics
# label alongside it. No pre-existing row is assigned "CANONICALIZED":
# that combination (semantics proven AND shift actually run) has never
# yet been produced by any writer for existing data — it is reserved for
# FUTURE ingestion under the corrected `historical_provider.py` policy
# (Part 4), and future migration eligibility (Part 10) that this
# checkpoint explicitly does not perform.
#
# Verified before/after this migration (this checkpoint's taskReport.md
# Part N/O): TOTAL=16,542, REAL_DHAN=11,442, UNKNOWN=5,100,
# SYNTHETIC_TEST=0 counts unchanged; full-table `(id, bar_timestamp)`
# checksum identical.
#
# ROLLBACK: reverses `canonicalization_state` back to the pre-67.4 value
# names and resets `source_timestamp_semantics` to the column default
# "UNKNOWN" on every row.
from __future__ import annotations

from datetime import date

from django.db import migrations

from intraday.domain.market_data.provenance import (
    PROVENANCE_REAL_DHAN,
    PROVENANCE_SYNTHETIC_TEST,
    PROVENANCE_UNKNOWN,
)
from intraday.domain.market_data.source_timestamp import (
    CANONICALIZATION_STATE_CANONICALIZED,
    CANONICALIZATION_STATE_UNCANONICALIZED,
    CANONICALIZATION_STATE_UNKNOWN,
)
from intraday.domain.session.calendar import CAS_EFFECTIVE_DATE

_LEGACY_RAW_OPEN = "RAW_OPEN"
_LEGACY_CANONICAL_CLOSE = "CANONICAL_CLOSE"


def split_semantics_from_state(apps, schema_editor):
    HistoricalBar = apps.get_model("persistence", "HistoricalBar")

    # (a) rename canonicalization_state's existing values.
    HistoricalBar.objects.filter(canonicalization_state=_LEGACY_RAW_OPEN).update(
        canonicalization_state=CANONICALIZATION_STATE_UNCANONICALIZED
    )
    HistoricalBar.objects.filter(canonicalization_state=_LEGACY_CANONICAL_CLOSE).update(
        canonicalization_state=CANONICALIZATION_STATE_CANONICALIZED
    )

    # (b) classify source_timestamp_semantics.
    real_dhan = HistoricalBar.objects.filter(provenance=PROVENANCE_REAL_DHAN)

    real_dhan.filter(
        timeframe="5m", bar_timestamp__date__gte=CAS_EFFECTIVE_DATE
    ).update(source_timestamp_semantics="OPEN")

    real_dhan.filter(timeframe="1m").update(source_timestamp_semantics="UNKNOWN")

    real_dhan.filter(
        timeframe="5m", bar_timestamp__date__lt=CAS_EFFECTIVE_DATE
    ).update(source_timestamp_semantics="UNKNOWN")

    # Any REAL_DHAN row in a timeframe outside {1m, 5m} (none exist today
    # — 0 rows for 15m/1h/1d — but handled explicitly rather than left at
    # the column default by accident) also stays UNKNOWN: never proven.
    real_dhan.exclude(timeframe__in=["1m", "5m"]).update(
        source_timestamp_semantics="UNKNOWN"
    )

    HistoricalBar.objects.filter(provenance=PROVENANCE_SYNTHETIC_TEST).update(
        source_timestamp_semantics="NOT_APPLICABLE"
    )
    HistoricalBar.objects.filter(provenance=PROVENANCE_UNKNOWN).update(
        source_timestamp_semantics="UNKNOWN"
    )


def revert(apps, schema_editor):
    HistoricalBar = apps.get_model("persistence", "HistoricalBar")
    HistoricalBar.objects.filter(
        canonicalization_state=CANONICALIZATION_STATE_UNCANONICALIZED
    ).update(canonicalization_state=_LEGACY_RAW_OPEN)
    HistoricalBar.objects.filter(
        canonicalization_state=CANONICALIZATION_STATE_CANONICALIZED
    ).update(canonicalization_state=_LEGACY_CANONICAL_CLOSE)
    HistoricalBar.objects.all().update(source_timestamp_semantics=CANONICALIZATION_STATE_UNKNOWN)


class Migration(migrations.Migration):

    dependencies = [
        ("persistence", "0039_historicalbar_source_timestamp_semantics"),
    ]

    operations = [
        migrations.RunPython(split_semantics_from_state, revert),
    ]
