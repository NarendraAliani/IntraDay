# File: src/intraday/infrastructure/persistence/migrations/0039_historicalbar_source_timestamp_semantics.py
#
# Checkpoint 67.4 Part 1-2: adds `HistoricalBar.source_timestamp_semantics`
# (see `domain.market_data.source_timestamp.SourceTimestampSemantics` and
# the field's own docstring on the model for the full rationale) — the
# SEMANTICS half of the concept 67.3's `canonicalization_state` had
# conflated: whether a row's raw provider timestamp convention was ever
# empirically PROVEN OPEN or CLOSE, kept separate from whether the
# OPEN->CLOSE shift arithmetic actually RAN on that row.
#
# SAFETY NOTE (same forensic-evidence discipline migrations 0029/0036/0037
# followed): this is a pure ADD COLUMN with a fixed default. It performs
# NO backfill by inference, NO update of `HistoricalBar.bar_timestamp`
# (no existing row's timestamp value is read, computed, or written by
# this migration), and NO delete. Every one of the 16,542 pre-67.4 rows
# receives `source_timestamp_semantics="UNKNOWN"` — the column's default —
# here. The FOLLOW-UP migration 0040 (data-only, still no timestamp
# touched) classifies the existing rows more precisely, and ALSO renames
# `canonicalization_state`'s existing "RAW_OPEN"/"CANONICAL_CLOSE" values
# to "UNCANONICALIZED"/"CANONICALIZED" (Part 8 — a pure string-value
# rename on that column; no `bar_timestamp`/OHLC/volume/provenance value
# is ever touched).
#
# ROLLBACK: drops this column outright — no data loss beyond the
# freshly-added column itself.
from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("persistence", "0038_historicalbar_classify_canonicalization_state"),
    ]

    operations = [
        migrations.AddField(
            model_name="historicalbar",
            name="source_timestamp_semantics",
            field=models.CharField(default="UNKNOWN", max_length=20),
        ),
        migrations.AddIndex(
            model_name="historicalbar",
            index=models.Index(
                fields=["source_timestamp_semantics"], name="persistence_source__0721d1_idx"
            ),
        ),
    ]
