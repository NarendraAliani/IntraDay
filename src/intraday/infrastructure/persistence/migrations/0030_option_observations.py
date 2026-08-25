# File: src/intraday/infrastructure/persistence/migrations/0030_option_observations.py
#
# Checkpoint 64.78: the OptionQuote / OIObservation tables.
#
# SAFETY NOTE (this project's standing forensic-evidence rule): this
# migration only CREATES two new, empty tables. It touches no existing
# table, performs no backfill, no update and no delete - every
# 64.62 / 64.70 / 64.72 / 64.74 live-evidence row in
# `LiveQuoteObservation` is left byte-for-byte as it is, and the equity
# schema is completely unchanged by this checkpoint.
#
# Neither table carries a UNIQUE constraint, deliberately - see the two
# models' own docstrings, and 64.73's Phase 11 lesson about
# over-restrictive uniqueness on an append-only observation log.
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('persistence', '0029_livequoteobservation_data_source'),
    ]

    operations = [
        migrations.CreateModel(
            name='OpenInterestObservation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('contract_id', models.CharField(max_length=96)),
                ('exchange', models.CharField(default='NSE', max_length=8)),
                ('segment', models.CharField(default='NSE_FNO', max_length=8)),
                ('underlying_symbol', models.CharField(max_length=32)),
                ('expiry', models.DateField()),
                ('strike', models.DecimalField(decimal_places=4, max_digits=14)),
                ('option_type', models.CharField(choices=[('CE', 'CE'), ('PE', 'PE')], max_length=2)),
                ('lot_size', models.PositiveIntegerField()),
                ('provider', models.CharField(max_length=32)),
                ('provider_security_id', models.BigIntegerField()),
                ('observed_at', models.DateTimeField()),
                ('fetched_at', models.DateTimeField()),
                ('trading_date', models.DateField()),
                ('open_interest', models.BigIntegerField()),
                ('data_source', models.CharField(blank=True, default='', max_length=32)),
            ],
            options={
                'indexes': [models.Index(fields=['trading_date', 'contract_id'], name='oio_date_contract_idx'), models.Index(fields=['contract_id', '-observed_at'], name='oio_contract_ts_idx')],
            },
        ),
        migrations.CreateModel(
            name='OptionQuoteObservation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('contract_id', models.CharField(max_length=96)),
                ('exchange', models.CharField(default='NSE', max_length=8)),
                ('segment', models.CharField(default='NSE_FNO', max_length=8)),
                ('underlying_symbol', models.CharField(max_length=32)),
                ('expiry', models.DateField()),
                ('strike', models.DecimalField(decimal_places=4, max_digits=14)),
                ('option_type', models.CharField(choices=[('CE', 'CE'), ('PE', 'PE')], max_length=2)),
                ('lot_size', models.PositiveIntegerField()),
                ('provider', models.CharField(max_length=32)),
                ('provider_security_id', models.BigIntegerField()),
                ('source_timestamp', models.DateTimeField()),
                ('fetched_at', models.DateTimeField()),
                ('trading_date', models.DateField()),
                ('last_price', models.DecimalField(decimal_places=4, max_digits=14)),
                ('open_price', models.DecimalField(blank=True, decimal_places=4, max_digits=14, null=True)),
                ('high_price', models.DecimalField(blank=True, decimal_places=4, max_digits=14, null=True)),
                ('low_price', models.DecimalField(blank=True, decimal_places=4, max_digits=14, null=True)),
                ('previous_close', models.DecimalField(blank=True, decimal_places=4, max_digits=14, null=True)),
                ('cumulative_volume', models.DecimalField(blank=True, decimal_places=0, max_digits=18, null=True)),
                ('bid', models.DecimalField(blank=True, decimal_places=4, max_digits=14, null=True)),
                ('ask', models.DecimalField(blank=True, decimal_places=4, max_digits=14, null=True)),
                ('bid_quantity', models.DecimalField(blank=True, decimal_places=0, max_digits=18, null=True)),
                ('ask_quantity', models.DecimalField(blank=True, decimal_places=0, max_digits=18, null=True)),
                ('data_source', models.CharField(blank=True, default='', max_length=32)),
            ],
            options={
                'indexes': [models.Index(fields=['trading_date', 'contract_id'], name='oqo_date_contract_idx'), models.Index(fields=['underlying_symbol', 'expiry', '-source_timestamp'], name='oqo_underlying_expiry_idx'), models.Index(fields=['contract_id', '-source_timestamp'], name='oqo_contract_ts_idx')],
            },
        ),
    ]
