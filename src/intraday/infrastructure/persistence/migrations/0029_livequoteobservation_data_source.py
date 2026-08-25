# File: src/intraday/infrastructure/persistence/migrations/0029_livequoteobservation_data_source.py
#
# Checkpoint 64.75: raw-observation provenance.
#
# SAFETY NOTE (this checkpoint's explicit forensic-evidence rule): this
# migration is a pure ADD COLUMN with a blank default. It performs NO
# backfill, NO update and NO delete - the 64.62 / 64.70 / 64.72 / 64.74
# live-evidence rows are left byte-for-byte as they are, and simply
# carry `data_source=""`.
#
# Why no backfill (unlike 0028's): `trading_date` was DERIVABLE from a
# column those rows already held (`source_timestamp`), so backfilling it
# recovered a fact already in the data. `data_source` is NOT derivable
# from anything stored - inferring "dhan_websocket" for historical rows
# would be FABRICATED provenance, which is precisely the failure mode a
# provenance column exists to prevent. `""` honestly means "provenance
# was not recorded at observation time".
from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("persistence", "0028_market_data_archive")]

    operations = [
        migrations.AddField(
            model_name="livequoteobservation",
            name="data_source",
            field=models.CharField(blank=True, default="", max_length=32),
        ),
    ]
