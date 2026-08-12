# tests/integration/test_celery_bootstrap.py
#
# Integration smoke test (Checkpoint 4 §9, §33): verifies the Celery
# application boots, discovers the infrastructure-only smoke task, and can
# execute it. The synchronous variant needs no live broker (proves task
# registration/execution machinery works). The async variant is skipped
# unless REDIS_URL is set, and then proves round-trip execution against a
# live broker. No business logic — celery_smoke_task performs no trading
# behavior (see src/intraday/celery.py).
from __future__ import annotations

import os

import pytest

from intraday.celery import celery_smoke_task


def test_celery_smoke_task_runs_synchronously() -> None:
    result = celery_smoke_task.apply()
    assert result.get() == "ok"


def test_celery_smoke_task_runs_against_live_broker() -> None:
    if not os.environ.get("REDIS_URL"):
        pytest.skip(
            "REDIS_URL not set - live Celery broker integration skipped in this environment"
        )
    async_result = celery_smoke_task.delay()
    assert async_result.get(timeout=5) == "ok"
