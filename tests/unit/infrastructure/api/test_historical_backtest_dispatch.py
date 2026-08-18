# tests/unit/infrastructure/api/test_historical_backtest_dispatch.py
#
# Follow-up to Checkpoint 63.x: proves the real bug fixes in
# dispatch_historical_backtest_run() across all three scenarios that
# actually matter:
#
#   1. No Celery worker is listening (this project's own normal dev
#      flow) - `.delay()` must never even be attempted (a bare
#      try/except around `.delay()` alone cannot distinguish "the
#      broker is reachable but nobody is consuming" from "dispatched
#      successfully" - a REAL live report hit exactly this: a run
#      stuck at QUEUED/0% forever, no error anywhere, because `.delay()`
#      "succeeded" (published to a reachable broker) with zero workers
#      to ever pick it up).
#   2. A worker IS listening and `.delay()` succeeds - the synchronous
#      fallback must NOT also run (no double-execution).
#   3. A worker IS listening but `.delay()` itself still fails for some
#      other reason - falls back to synchronous, and any failure THERE
#      must never propagate up to the caller (the view) - it's already
#      durably recorded on the BacktestRun row itself.
from __future__ import annotations

from unittest.mock import MagicMock, patch

from intraday.infrastructure.api.tasks import dispatch_historical_backtest_run


def test_no_worker_listening_never_even_attempts_delay_and_runs_synchronously() -> None:
    """THE real bug: a reachable-but-unconsumed broker used to leave a
    run permanently stuck at QUEUED with no error anywhere. Now, no
    live worker means `.delay()` is skipped entirely."""
    mock_task = MagicMock()
    with (
        patch(
            "intraday.infrastructure.api.tasks._a_celery_worker_is_actually_listening",
            return_value=False,
        ),
        patch("intraday.infrastructure.api.tasks.run_historical_backtest_run_task", mock_task),
    ):
        dispatch_historical_backtest_run("some-run-id")

    assert not mock_task.delay.called
    mock_task.assert_called_once_with("some-run-id")


def test_worker_listening_and_delay_succeeds_never_also_runs_synchronously() -> None:
    """No double-execution: once a live worker has genuinely accepted
    the async dispatch, the synchronous fallback must not ALSO run."""
    mock_task = MagicMock()
    with (
        patch(
            "intraday.infrastructure.api.tasks._a_celery_worker_is_actually_listening",
            return_value=True,
        ),
        patch("intraday.infrastructure.api.tasks.run_historical_backtest_run_task", mock_task),
    ):
        dispatch_historical_backtest_run("some-run-id")

    mock_task.delay.assert_called_once_with("some-run-id")
    assert not mock_task.called  # the bare (synchronous) call, distinct from .delay()


def test_worker_listening_but_delay_itself_fails_falls_back_and_never_raises() -> None:
    """A live worker was detected, but the actual publish call still
    failed for some other reason (e.g. a transient broker error) - AND
    the synchronous fallback itself also fails (the run genuinely
    blew up). Neither failure may propagate to the caller - both are
    already recorded on the BacktestRun row itself."""
    mock_task = MagicMock(side_effect=RuntimeError("the orchestrator itself blew up"))
    mock_task.delay.side_effect = RuntimeError("transient broker error")

    with (
        patch(
            "intraday.infrastructure.api.tasks._a_celery_worker_is_actually_listening",
            return_value=True,
        ),
        patch("intraday.infrastructure.api.tasks.run_historical_backtest_run_task", mock_task),
    ):
        dispatch_historical_backtest_run("some-run-id")  # must not raise

    assert mock_task.delay.called
    mock_task.assert_called_once_with("some-run-id")
