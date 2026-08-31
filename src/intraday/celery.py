# src/intraday/celery.py
#
# Celery application bootstrap (Checkpoint 4 — infrastructure only).
# Wires Celery to Django settings (broker/result-backend URLs, task
# serialization, timezone) per docs/architecture/TECHNOLOGY_MAPPING.md §5.
#
# `celery_smoke_task` (Checkpoint 4) remains infrastructure-only, no
# business logic, unchanged. Checkpoint 40 registers the FIRST real
# task, `active_loop_tick` — owned by `infrastructure/api/tasks.py`
# (not this file, per this module's own original "real tasks belong to
# their owning bounded context" instruction), discovered explicitly
# below since `infrastructure.api` is not a Django INSTALLED_APPS
# entry (the default `autodiscover_tasks()` only scans those).
from __future__ import annotations

import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "intraday.settings.development")

app = Celery("intraday")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
app.autodiscover_tasks(["intraday.infrastructure.api"], related_name="tasks")

# Checkpoint 41 Part 3: the Celery Beat schedule - the one thing
# Checkpoint 40 built a task but never actually scheduled ("a scheduler
# with nothing meaningful to schedule" is exactly what Checkpoint 41
# explicitly forbade repeating).
#
# Cadence decision: every 60 SECONDS, matching this project's canonical
# base timeframe (`bar_aggregation.py::DEFAULT_TIMEFRAME =
# Timeframe.ONE_MINUTE`, Checkpoint 24A). A faster cadence would poll
# Dhan's REST quote endpoint more often than a new 1-minute bar could
# even close, wasting the documented 1 request/second rate-limit
# budget (Checkpoint 23) for no additional information; a slower
# cadence would let a closed bar sit un-evaluated for longer than one
# bar's own duration, directly hurting `market_event_to_bar` latency
# for no benefit. `market_data_ingestion_tick` (not `active_loop_tick`
# directly - see `infrastructure/api/tasks.py`) is what's scheduled,
# since it is the function that ALSO decides, every single tick,
# whether the session is even OPEN - never a blind, always-on poll.
#
# Checkpoint 47 Part 4: `emergency_square_off_check_tick` is scheduled
# SEPARATELY, at its OWN faster cadence, deliberately independent of
# `market_data_ingestion_tick`. This is a direct fix to a real
# architectural weakness Checkpoint 46 had: automatic square-off was
# only ever invoked FROM the ingestion tick, meaning kill-switch safety
# implicitly depended on ingestion succeeding - exactly backwards, since
# ingestion (a Dhan REST call, a rate-limited external dependency) may
# itself be the thing that has failed when an operator needs the kill
# switch to actually work. 15 seconds is fast enough that an engaged
# kill switch is acted on promptly without being an "artificial
# one-second polling loop" (this project's own established anti-
# pattern to avoid, Checkpoint 41) - safety-critical, so faster than
# the 60s market-data cadence is justified; `check_and_trigger_
# automatic_square_off()` itself is a cheap no-op whenever the kill
# switch is not engaged, so the faster cadence costs almost nothing
# in the common case.
# Checkpoint 65.34 Part 5: `eod-sequence-once-daily` - the FIRST
# scheduled trigger for `run_eod_sequence()` (previously unwired,
# reachable only from tests/manual calls per Checkpoint 65.30's own
# audit). Judged safe to schedule "blindly" (per this checkpoint's own
# "only if it can be done without guessing segment-specific/CAS
# behavior" instruction) precisely BECAUSE `run_eod_sequence()` does
# not need to know anything CAS-specific to do its job correctly - it
# force-closes whatever is still open at a fixed later instant and is
# idempotent per calendar date (see `eod_sequence_tick`'s own
# docstring, `infrastructure/api/tasks.py`). 10:15 UTC = 15:45 IST
# (`CELERY_TIMEZONE = "UTC"`, `settings/base.py`) is chosen as a fixed
# point comfortably AFTER both `SQUARE_OFF_DEADLINE_IST` (15:20,
# `domain/session/calendar.py`) and the NSE/BSE cash-equity market
# close (15:30) - so by the time this task runs, every position that
# was ever going to be closed by price-driven exits, the existing
# 15:20 gate, or a market-close-driven halt has already had the
# chance; this task exists purely as the final, unconditional
# "nothing should still be open" backstop, not a new close-earlier
# policy. This does NOT change what "EOD" means, does NOT rename or
# touch `SQUARE_OFF_DEADLINE_IST`, and does NOT activate 15:10 as a
# constant - it only gives `run_eod_sequence()` an actual scheduled
# caller, which it never had before.
app.conf.beat_schedule = {
    "market-data-ingestion-every-minute": {
        "task": "intraday.infrastructure.api.market_data_ingestion_tick",
        "schedule": 60.0,
    },
    "emergency-square-off-check-every-15-seconds": {
        "task": "intraday.infrastructure.api.emergency_square_off_check_tick",
        "schedule": 15.0,
    },
    "eod-sequence-once-daily": {
        "task": "intraday.infrastructure.api.eod_sequence_tick",
        "schedule": crontab(hour=10, minute=15),
    },
}


@app.task(name="intraday.infrastructure.celery_smoke_task")  # type: ignore[untyped-decorator]
def celery_smoke_task() -> str:
    """Infrastructure-only smoke task (Checkpoint 4).

    Verifies that a Celery worker can receive and execute a task. Contains
    no business logic and must not be extended — see module docstring.

    The ignore above is necessary because Celery's `@app.task` decorator
    has no type stubs (see the `celery.*` override in pyproject.toml's
    [tool.mypy] config) — this is a known third-party typing gap, not a
    project-code typing gap (Checkpoint 4 §11: "strict project code, not
    pretending every third-party library is perfectly typed").
    """
    return "ok"
