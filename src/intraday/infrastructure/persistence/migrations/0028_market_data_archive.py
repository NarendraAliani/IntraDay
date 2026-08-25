# File: src/intraday/infrastructure/persistence/migrations/0028_market_data_archive.py
#
# Checkpoint 64.73: the daily market-data archive schema.
#
# SAFETY NOTE (this checkpoint's explicit forensic-evidence rule): the
# backfill below UPDATES only the newly added, purely DERIVED
# `trading_date` column on existing rows. It deletes nothing, alters no
# price/volume/timestamp field, and therefore preserves the 64.62,
# 64.70 and 64.72 live-evidence observations intact - it merely files
# each of them under the IST trading day it already belonged to.
from __future__ import annotations

from datetime import UTC
from zoneinfo import ZoneInfo

from django.db import migrations, models

_IST = ZoneInfo("Asia/Kolkata")


def _ist_date(value: object) -> object:
    """Mirrors `domain.market_data.archive.trading_date_for()`. A
    migration must not import application/domain code (which is free to
    change shape later, breaking replay of a historical migration), so
    the one-line rule is restated here deliberately - and
    `tests/unit/research/test_checkpoint_64_73_market_data_archive.py`
    asserts the two agree."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(_IST).date()


def backfill_trading_dates(apps, schema_editor):  # type: ignore[no-untyped-def]
    quote_model = apps.get_model("persistence", "LiveQuoteObservation")
    bar_model = apps.get_model("persistence", "AggregatedBarObservation")

    quotes = []
    for row in quote_model.objects.filter(trading_date__isnull=True).only(
        "id", "source_timestamp"
    ):
        row.trading_date = _ist_date(row.source_timestamp)
        quotes.append(row)
    if quotes:
        quote_model.objects.bulk_update(quotes, ["trading_date"], batch_size=1000)

    bars = []
    for row in bar_model.objects.filter(trading_date__isnull=True).only("id", "interval_end"):
        # A bar belongs to the trading day it CLOSED in.
        row.trading_date = _ist_date(row.interval_end)
        bars.append(row)
    if bars:
        bar_model.objects.bulk_update(bars, ["trading_date"], batch_size=1000)


def unbackfill(apps, schema_editor):  # type: ignore[no-untyped-def]
    """Reverse is a no-op: the columns themselves are removed by the
    reversed AddField operations, so there is nothing to undo and
    certainly nothing to delete."""


class Migration(migrations.Migration):
    dependencies = [("persistence", "0027_papertradingsessionrecord")]

    operations = [
        migrations.AddField(
            model_name="livequoteobservation",
            name="trading_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="aggregatedbarobservation",
            name="trading_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.RunPython(backfill_trading_dates, unbackfill),
        migrations.AddIndex(
            model_name="livequoteobservation",
            index=models.Index(
                fields=["trading_date", "instrument_symbol"],
                name="lqo_trading_date_symbol_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="aggregatedbarobservation",
            index=models.Index(
                fields=["trading_date", "instrument_symbol", "timeframe"],
                name="abo_trading_date_sym_tf_idx",
            ),
        ),
        migrations.AddField(
            model_name="workerruntimestatus",
            name="stop_requested_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="workerruntimestatus",
            name="stop_requested_by",
            field=models.CharField(blank=True, default="", max_length=150),
        ),
        migrations.AddField(
            model_name="workerruntimestatus",
            name="stop_reason_safe",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.CreateModel(
            name="MarketDataArchiveDay",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("exchange", models.CharField(default="NSE", max_length=8)),
                ("trading_date", models.DateField()),
                ("instrument_symbol", models.CharField(max_length=32)),
                ("timeframe", models.CharField(max_length=8)),
                ("data_source", models.CharField(max_length=32)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("NOT_OBSERVED", "NOT_OBSERVED"),
                            ("IN_PROGRESS", "IN_PROGRESS"),
                            ("PARTIAL", "PARTIAL"),
                            ("COMPLETE", "COMPLETE"),
                            ("FAILED", "FAILED"),
                        ],
                        default="NOT_OBSERVED",
                        max_length=16,
                    ),
                ),
                ("reason", models.CharField(blank=True, default="", max_length=120)),
                ("completeness_supported", models.BooleanField(default=False)),
                ("expected_bar_count", models.PositiveIntegerField(default=0)),
                ("closed_bar_count", models.PositiveIntegerField(default=0)),
                ("forming_bar_count", models.PositiveIntegerField(default=0)),
                ("missing_bar_count", models.PositiveIntegerField(default=0)),
                ("duplicate_bar_count", models.PositiveIntegerField(default=0)),
                ("quote_observation_count", models.PositiveIntegerField(default=0)),
                ("first_observation_at", models.DateTimeField(blank=True, null=True)),
                ("last_observation_at", models.DateTimeField(blank=True, null=True)),
                (
                    "reconciliation_status",
                    models.CharField(
                        choices=[
                            ("NOT_RECONCILED", "NOT_RECONCILED"),
                            ("RECONCILED", "RECONCILED"),
                            ("MISMATCH", "MISMATCH"),
                        ],
                        default="NOT_RECONCILED",
                        max_length=16,
                    ),
                ),
                ("reconciled_at", models.DateTimeField(blank=True, null=True)),
                ("computed_at", models.DateTimeField(blank=True, null=True)),
            ],
        ),
        migrations.AddConstraint(
            model_name="marketdataarchiveday",
            constraint=models.UniqueConstraint(
                fields=(
                    "exchange",
                    "trading_date",
                    "instrument_symbol",
                    "timeframe",
                    "data_source",
                ),
                name="unique_archive_day_cell",
            ),
        ),
        migrations.AddIndex(
            model_name="marketdataarchiveday",
            index=models.Index(
                fields=["-trading_date", "status"], name="mdad_trading_date_status_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="marketdataarchiveday",
            index=models.Index(
                fields=["trading_date", "instrument_symbol", "timeframe"],
                name="mdad_date_sym_tf_idx",
            ),
        ),
    ]
