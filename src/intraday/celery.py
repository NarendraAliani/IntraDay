# src/intraday/celery.py
#
# Celery application bootstrap (Checkpoint 4 — infrastructure only).
# Wires Celery to Django settings (broker/result-backend URLs, task
# serialization, timezone) per docs/architecture/TECHNOLOGY_MAPPING.md §5.
#
# This file defines exactly one task: `celery_smoke_task`, an
# infrastructure-only smoke task that proves a worker can boot, discover,
# and execute a task end-to-end. It performs no business logic and MUST NOT
# be extended to represent future trading behavior — real tasks belong to
# their owning bounded context (e.g. control_plane for reconciliation jobs,
# communication for notification dispatch) in later checkpoints.
from __future__ import annotations

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "intraday.settings.development")

app = Celery("intraday")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


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
