# tests/unit/infrastructure/test_celery_beat_schedule.py
#
# Checkpoint 65.34 Part 5: proves the EOD sequence task is actually
# wired into Celery Beat exactly once (no duplicate scheduler), and
# that the two pre-existing entries (Checkpoint 41/47) are undisturbed.
from __future__ import annotations

from intraday.celery import app


def test_beat_schedule_has_exactly_three_entries() -> None:
    assert set(app.conf.beat_schedule.keys()) == {
        "market-data-ingestion-every-minute",
        "emergency-square-off-check-every-15-seconds",
        "eod-sequence-once-daily",
    }


def test_eod_sequence_is_scheduled_exactly_once() -> None:
    tasks = [entry["task"] for entry in app.conf.beat_schedule.values()]
    assert tasks.count("intraday.infrastructure.api.eod_sequence_tick") == 1


def test_eod_sequence_entry_points_at_the_real_task() -> None:
    entry = app.conf.beat_schedule["eod-sequence-once-daily"]
    assert entry["task"] == "intraday.infrastructure.api.eod_sequence_tick"
