# File: src/intraday/infrastructure/persistence/migrations/0036_historicalbar_provenance.py
#
# Checkpoint 65.12: adds `HistoricalBar.provenance` — the additive
# per-provider provenance tag 65.01 designed but did not implement
# (`domain.market_data.provenance.PROVENANCE_REAL_DHAN` /
# `PROVENANCE_SYNTHETIC_TEST` / `PROVENANCE_UNKNOWN`).
#
# SAFETY NOTE (same forensic-evidence rule migration 0029 followed):
# this is a pure ADD COLUMN with a fixed default. It performs NO
# backfill by inference, NO update of `HistoricalBar.source`, and NO
# delete. Every one of the 5,100 pre-65.12 rows (all currently
# `source="API_FETCH"`, of provenance-mix ~3,900 proven-synthetic /
# ~1,200 UNKNOWN per 65.00/65.01's formula-replay audit) receives
# `provenance="UNKNOWN"` — the column's default — NOT `"REAL_DHAN"` and
# NOT `"SYNTHETIC_TEST"`. Even the ~3,900 rows 65.00/65.01 could
# reproduce via formula-replay are left `UNKNOWN` here rather than
# auto-upgraded to `SYNTHETIC_TEST`, because this migration is a
# mechanical schema change, not a data audit — see 65.12's taskReport
# for why a manual, reviewed backfill (not a migration) is the correct
# place to apply that formula-replay finding, if the project ever
# chooses to.
#
# ROLLBACK: `migrate persistence 0035` drops this column outright — no
# data loss on rollback beyond the (freshly-added, all-`UNKNOWN`)
# column itself, since nothing else reads or depends on it yet.
from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("persistence", "0035_scannerconfiguration_notification_channels")]

    operations = [
        migrations.AddField(
            model_name="historicalbar",
            name="provenance",
            field=models.CharField(default="UNKNOWN", max_length=16),
        ),
        migrations.AddIndex(
            model_name="historicalbar",
            index=models.Index(fields=["provenance"], name="persistence_provena_4ef838_idx"),
        ),
    ]
