# File: src/intraday/infrastructure/persistence/migrations/0037_historicalbar_canonicalization_state.py
#
# Checkpoint 67.3 Part 1-3: adds `HistoricalBar.canonicalization_state`
# (see `domain.market_data.source_timestamp.CANONICALIZATION_STATE_*`
# and the field's own docstring on the model for the full rationale) —
# the missing per-row marker 67.2 found was needed before
# `ResearchDataGateService` could distinguish legacy RAW_OPEN REAL_DHAN
# rows from future CANONICAL_CLOSE REAL_DHAN rows.
#
# SAFETY NOTE (same forensic-evidence discipline migration 0029/0036
# followed): this is a pure ADD COLUMN with a fixed default. It performs
# NO backfill by inference, NO update of `HistoricalBar.bar_timestamp`
# (no existing row's timestamp value is read, computed, or written by
# this migration), and NO delete. Every one of the 16,542 pre-67.3 rows
# receives `canonicalization_state="UNKNOWN"` — the column's default —
# here. The FOLLOW-UP migration 0038 (data-only, still no timestamp
# touched) classifies the existing rows more precisely by provenance.
#
# ROLLBACK: `migrate persistence 0036` drops this column outright — no
# data loss beyond the freshly-added column itself.
from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("persistence", "0036_historicalbar_provenance"),
    ]

    operations = [
        migrations.AddField(
            model_name="historicalbar",
            name="canonicalization_state",
            field=models.CharField(default="UNKNOWN", max_length=20),
        ),
        migrations.AddIndex(
            model_name="historicalbar",
            index=models.Index(
                fields=["canonicalization_state"], name="persistence_canonic_20bf60_idx"
            ),
        ),
    ]
