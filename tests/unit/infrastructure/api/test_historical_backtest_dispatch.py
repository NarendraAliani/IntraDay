# tests/unit/infrastructure/api/test_historical_backtest_dispatch.py
#
# Follow-up to Checkpoint 63.x: proves the real bug fix in
# dispatch_historical_backtest_run() - a broker-unavailable fallback
# that ALSO fails (the run itself hit an unexpected error) must never
# propagate an exception up to the caller (the view). The failure is
# already durably recorded on the BacktestRun row by the task itself;
# this function's only remaining job is to never crash the HTTP
# request on top of that.
from __future__ import annotations

from unittest.mock import MagicMock, patch

from intraday.infrastructure.api.tasks import dispatch_historical_backtest_run


def test_broker_unavailable_and_task_itself_failing_does_not_raise() -> None:
    # A single mock task object: `.delay()` fails (no broker configured -
    # the honest fallback trigger), and calling it directly (the
    # synchronous fallback path) ALSO fails (the run itself hit an
    # unexpected error) - both real failure modes at once.
    mock_task = MagicMock(side_effect=RuntimeError("the orchestrator itself blew up"))
    mock_task.delay.side_effect = RuntimeError("no broker configured")

    with patch("intraday.infrastructure.api.tasks.run_historical_backtest_run_task", mock_task):
        dispatch_historical_backtest_run("some-run-id")  # must not raise

    assert mock_task.delay.called
    mock_task.assert_called_once_with("some-run-id")
