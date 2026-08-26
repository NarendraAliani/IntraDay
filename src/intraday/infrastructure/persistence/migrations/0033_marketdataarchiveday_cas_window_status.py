# Checkpoint 64.88: additive, defaulted CAS-window-status column on
# `MarketDataArchiveDay`. Nullable-by-default (`default='NOT_APPLICABLE'`)
# so no historical row is rewritten and every pre-64.88 consumer keeps
# reading the exact same rows it always has, with an honest default for
# a question that simply did not exist before this checkpoint.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('persistence', '0032_reconciliation_result_persistence'),
    ]

    operations = [
        migrations.AddField(
            model_name='marketdataarchiveday',
            name='cas_window_status',
            field=models.CharField(
                choices=[
                    ('NOT_APPLICABLE', 'NOT_APPLICABLE'),
                    ('EXPECTED_NON_CONTINUOUS', 'EXPECTED_NON_CONTINUOUS'),
                    ('PROVIDER_BEHAVIOR_UNKNOWN', 'PROVIDER_BEHAVIOR_UNKNOWN'),
                ],
                default='NOT_APPLICABLE',
                max_length=32,
            ),
        ),
    ]
