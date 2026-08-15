# tests/unit/infrastructure/persistence/management/test_run_market_data_worker_command.py
#
# Checkpoint 57: proves `python manage.py run_market_data_worker`
# actually runs end-to-end - starts a real local socket, processes a
# bounded synthetic packet stream through the real decode/state-
# machine/Quote pipeline, and terminates cleanly, printing real
# quotes and a real summary. This is the acceptance test for the
# actual persistent-process entry point this checkpoint's own review
# named as the missing piece.
from __future__ import annotations

import io

from django.core.management import call_command


def test_command_runs_end_to_end_and_reports_a_real_summary() -> None:
    out = io.StringIO()

    call_command("run_market_data_worker", "--packet-count", "5", stdout=out)

    output = out.getvalue()
    assert "Starting market-data worker" in output
    assert "NOT a live Dhan connection" in output
    assert "Worker finished: final_state=STOPPED" in output
    assert "quotes_processed=5" in output
    assert "decode_failures=0" in output
    # Real instrument symbols from the real observation universe, not
    # placeholders - proves the command used the real Quote pipeline.
    assert "quote: NSE:" in output


def test_command_defaults_to_twenty_packets_when_unspecified() -> None:
    out = io.StringIO()

    call_command("run_market_data_worker", stdout=out)

    assert "quotes_processed=20" in out.getvalue()


def test_command_rejects_an_unsupported_provider() -> None:
    import pytest
    from django.core.management.base import CommandError

    with pytest.raises((CommandError, SystemExit)):
        call_command("run_market_data_worker", "--provider", "dhan", stdout=io.StringIO())
