# Checkpoint 64.92: additive, defaulted LIVE/REPLAY/UNKNOWN discriminator
# on `MarketDataArchiveDay`. Nullable-by-default (`default='UNKNOWN'`) so
# no historical row is rewritten and every pre-64.92 consumer keeps
# reading the exact same rows it always has. See
# `MarketDataArchiveDay.session_purpose`'s own docstring for the full
# rationale, including why it is deliberately NOT part of
# `unique_archive_day_cell` yet.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('persistence', '0033_marketdataarchiveday_cas_window_status'),
    ]

    operations = [
        migrations.AddField(
            model_name='marketdataarchiveday',
            name='session_purpose',
            field=models.CharField(
                choices=[
                    ('UNKNOWN', 'UNKNOWN'),
                    ('LIVE', 'LIVE'),
                    ('REPLAY', 'REPLAY'),
                ],
                default='UNKNOWN',
                max_length=16,
            ),
        ),
    ]
