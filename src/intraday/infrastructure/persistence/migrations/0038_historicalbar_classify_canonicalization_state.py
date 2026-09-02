# File: src/intraday/infrastructure/persistence/migrations/0038_historicalbar_classify_canonicalization_state.py
#
# Checkpoint 67.3 Part 3/13: DATA-ONLY migration that classifies every
# pre-existing `HistoricalBar` row's `canonicalization_state` — added by
# 0037, defaulted `"UNKNOWN"` — WITHOUT touching `bar_timestamp` on any
# row. No timestamp value is ever read, computed, shifted, or written by
# this migration; only the `canonicalization_state` column is updated.
#
# CLASSIFICATION RULE (mechanical, not a semantic re-proof of anything):
#   - `provenance="REAL_DHAN"` (11,442 rows) -> `"RAW_OPEN"`. Every one
#     of these rows was persisted by the pipeline that existed BEFORE
#     Checkpoint 67.1 changed Dhan ingestion to canonicalize
#     OPEN->CLOSE before writing (`historical_provider.py::_candle_to_bar`
#     + `bulk_upsert`, see that checkpoint). That is a fact about WHICH
#     CODE PATH wrote the row, independently true regardless of whether
#     67.0-class empirical proof exists for that row's own timeframe
#     (5m intraday CAS-era is proven; 1m and PRE-CAS 5m are not, and
#     stay explicitly NOT_YET_PROVEN per 67.3 Parts 9/10 — this
#     migration does not change that; it only records that these rows
#     were never run through `canonicalize_close_timestamp` at all, so
#     `bar_timestamp` on them is still whatever raw value the pre-67.1
#     pipeline copied in verbatim).
#   - `provenance` in `("SYNTHETIC_TEST", "UNKNOWN")` (5,100 rows) ->
#     `"NOT_APPLICABLE"`. Neither has a real provider raw-timestamp
#     convention to canonicalize (`SYNTHETIC_TEST` bars are
#     deterministically generated, not fetched from any provider;
#     `UNKNOWN`-provenance rows have no corroborating source evidence at
#     all) — `"RAW_OPEN"` would falsely imply a real, un-shifted
#     provider timestamp exists to eventually canonicalize.
#
# This migration NEVER assigns `"CANONICAL_CLOSE"` to any existing row —
# that state is reserved for rows written by the already-canonicalizing
# 67.1+ Dhan intraday path going forward (`historical_data_preparation.py`
# / `DjangoHistoricalBarRepository.bulk_upsert`), never backfilled onto
# legacy data by inference.
#
# Verified before/after this migration (67.3 taskReport.md Part S):
# TOTAL=16,542, REAL_DHAN=11,442, UNKNOWN=5,100, SYNTHETIC_TEST=0 counts
# unchanged, and a full-table `bar_timestamp` checksum identical.
#
# ROLLBACK: reverses every row's `canonicalization_state` back to the
# column default `"UNKNOWN"` (Django's `RunPython` requires an explicit
# reverse; there is no richer prior state to restore to, since this is
# the migration that first populates the column beyond its default).
from __future__ import annotations

from django.db import migrations

from intraday.domain.market_data.provenance import (
    PROVENANCE_REAL_DHAN,
    PROVENANCE_SYNTHETIC_TEST,
    PROVENANCE_UNKNOWN,
)
from intraday.domain.market_data.source_timestamp import (
    CANONICALIZATION_STATE_NOT_APPLICABLE,
    CANONICALIZATION_STATE_RAW_OPEN,
    CANONICALIZATION_STATE_UNKNOWN,
)


def classify_existing_rows(apps, schema_editor):
    HistoricalBar = apps.get_model("persistence", "HistoricalBar")
    HistoricalBar.objects.filter(provenance=PROVENANCE_REAL_DHAN).update(
        canonicalization_state=CANONICALIZATION_STATE_RAW_OPEN
    )
    HistoricalBar.objects.filter(
        provenance__in=(PROVENANCE_SYNTHETIC_TEST, PROVENANCE_UNKNOWN)
    ).update(canonicalization_state=CANONICALIZATION_STATE_NOT_APPLICABLE)


def revert_to_unknown(apps, schema_editor):
    HistoricalBar = apps.get_model("persistence", "HistoricalBar")
    HistoricalBar.objects.all().update(canonicalization_state=CANONICALIZATION_STATE_UNKNOWN)


class Migration(migrations.Migration):

    dependencies = [
        ("persistence", "0037_historicalbar_canonicalization_state"),
    ]

    operations = [
        migrations.RunPython(classify_existing_rows, revert_to_unknown),
    ]
