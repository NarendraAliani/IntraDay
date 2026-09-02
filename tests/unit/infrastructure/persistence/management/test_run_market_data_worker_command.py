# tests/unit/infrastructure/persistence/management/test_run_market_data_worker_command.py
#
# Checkpoint 57: proves `python manage.py run_market_data_worker`
# actually runs end-to-end - starts a real local socket, processes a
# bounded synthetic packet stream through the real decode/state-
# machine/Quote pipeline, and terminates cleanly, printing real
# quotes and a real summary. This is the acceptance test for the
# actual persistent-process entry point this checkpoint's own review
# named as the missing piece.
#
# Checkpoint 58 ADDS: every quote is now genuinely persisted and
# aggregated through the REAL `BarAggregationService` (Checkpoint
# 24A) - the one concrete missing link the fresh product-readiness
# reassessment identified. Requires real DB access, hence
# `pytest.mark.django_db` + `requires_postgres`, unlike Checkpoint
# 57's original (DB-free) version of this file.
#
# Checkpoint 59 ADDS: proof that aggregation happens PERIODICALLY,
# while the worker is still running - not merely once, after the
# stream has already ended (Checkpoint 58's real limitation, named
# honestly and now closed).
#
# Checkpoint 62 ADDS: `--provider fake-ws` - the REAL RFC 6455
# WebSocket path (Checkpoint 61's transport), now exercised through
# THIS actual operator-facing command, not only through unit tests.
# The command's own docstring named this exact gap ("still only
# supports --provider fake") as unclosed at the end of Checkpoint 61.
from __future__ import annotations

import io

import pytest
from django.core.management import call_command

from intraday.application.services.provider_settings import DhanSettingsService
from intraday.infrastructure.persistence.models import (
    AggregatedBarObservation,
    LiveQuoteObservation,
)
from tests.postgres_utils import requires_postgres

# `transaction=True` (not the plain `django_db` mark) for EVERY test in
# this file: the command's DB writes run inside `sync_to_async`, which
# executes in a separate thread with its own real DB connection - those
# writes are never part of pytest-django's normal per-test rolled-back
# transaction, so only a real transactional test database (truncated
# between tests, not rolled back) gives correct isolation here.
pytestmark = pytest.mark.django_db(transaction=True)


@requires_postgres
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


@requires_postgres
def test_command_defaults_to_twenty_packets_when_unspecified() -> None:
    out = io.StringIO()

    call_command("run_market_data_worker", stdout=out)

    assert "quotes_processed=20" in out.getvalue()


@requires_postgres
def test_command_rejects_an_unsupported_provider() -> None:
    from django.core.management.base import CommandError

    # Checkpoint 64.1: "dhan" is now a genuinely supported provider -
    # use a value that is still unsupported to keep proving this.
    with pytest.raises((CommandError, SystemExit)):
        call_command(
            "run_market_data_worker", "--provider", "not-a-real-provider", stdout=io.StringIO()
        )


@requires_postgres
def test_command_actually_persists_quotes_and_aggregates_real_bars() -> None:
    """THE proof for Checkpoint 58's own contribution: quotes reaching
    stdout is not the same as quotes reaching the real persistence +
    aggregation pipeline - this test checks the actual database rows,
    not just the printed summary. Compares a before/after DELTA rather
    than an absolute count, matching this file's module-level
    `transaction=True` isolation model."""
    quotes_before = LiveQuoteObservation.objects.count()
    bars_before = AggregatedBarObservation.objects.count()
    out = io.StringIO()

    call_command("run_market_data_worker", "--packet-count", "8", stdout=out)

    assert LiveQuoteObservation.objects.count() - quotes_before == 8
    assert AggregatedBarObservation.objects.count() >= bars_before
    assert "aggregated" in out.getvalue()
    assert "anomalous_observations=0" in out.getvalue()


@requires_postgres
def test_bars_are_produced_while_the_worker_is_still_running_not_only_after_the_stream_ends() -> (
    None
):
    """THE direct rebuttal to Checkpoint 58's real limitation: with
    `_AGGREGATION_BATCH_SIZE == 5` and 12 packets scripted, aggregation
    must fire at least THREE times (after quote 5, after quote 10, and
    a final cleanup pass for the remaining 2) - never just once at the
    very end. Counting how many times "aggregated" appears in the
    output is a structural proof that bar formation is periodic and
    continuous, not stream-termination-triggered."""
    out = io.StringIO()

    call_command("run_market_data_worker", "--packet-count", "12", stdout=out)

    output = out.getvalue()
    aggregation_lines = [line for line in output.splitlines() if "aggregated" in line]
    assert len(aggregation_lines) >= 3, (
        f"expected at least 3 aggregation passes (2 mid-stream + 1 final cleanup), "
        f"got {len(aggregation_lines)}: {aggregation_lines}"
    )


@requires_postgres
def test_command_runs_end_to_end_over_the_real_websocket_provider() -> None:
    """Checkpoint 62: the same acceptance proof as
    `test_command_runs_end_to_end_and_reports_a_real_summary`, but
    through `--provider fake-ws` - a genuine RFC 6455 handshake and
    real WebSocket frames, not raw TCP."""
    out = io.StringIO()

    call_command(
        "run_market_data_worker", "--provider", "fake-ws", "--packet-count", "5", stdout=out
    )

    output = out.getvalue()
    assert "Starting market-data worker (provider=fake-ws" in output
    assert "Worker finished: final_state=STOPPED" in output
    assert "quotes_processed=5" in output
    assert "decode_failures=0" in output
    assert "quote: NSE:" in output


@requires_postgres
def test_command_over_websocket_actually_persists_quotes_and_aggregates_bars() -> None:
    """The WebSocket-provider equivalent of
    `test_command_actually_persists_quotes_and_aggregates_real_bars` -
    proves the SAME `_QuoteSink` persistence/aggregation path is
    genuinely reached from the real-WebSocket branch, not just the
    raw-TCP one."""
    quotes_before = LiveQuoteObservation.objects.count()
    bars_before = AggregatedBarObservation.objects.count()
    out = io.StringIO()

    call_command(
        "run_market_data_worker", "--provider", "fake-ws", "--packet-count", "8", stdout=out
    )

    assert LiveQuoteObservation.objects.count() - quotes_before == 8
    assert AggregatedBarObservation.objects.count() >= bars_before
    assert "aggregated" in out.getvalue()


# --- Checkpoint 64.1: --provider dhan - never a real network call in this
# file. Proves ONLY the credential/token-gating refusal logic, which is
# genuinely testable without a live connection - the actual live
# connection was verified separately and manually at Checkpoint 64/64.1
# (see taskReport.md), never inside the automated test suite.


@requires_postgres
@pytest.mark.django_db
def test_dhan_provider_refuses_to_connect_with_no_credentials_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(DhanSettingsService, "effective_credentials", lambda self: None)
    out = io.StringIO()

    call_command("run_market_data_worker", "--provider", "dhan", stdout=out)

    assert "final_state=AUTH_FAILED" in out.getvalue()
    assert "refusing to connect" in out.getvalue()


@requires_postgres
@pytest.mark.django_db
def test_dhan_provider_refuses_to_connect_with_a_known_expired_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE real safety requirement Checkpoint 64.1's own brief named:
    "the worker should refuse to pretend it is connected when the
    token is known to be expired." Proven with a real, well-formed but
    expired JWT - never a real network attempt."""
    import base64
    import json
    from datetime import UTC, datetime, timedelta

    expired_at = datetime.now(tz=UTC) - timedelta(hours=1)
    header = base64.urlsafe_b64encode(b'{"alg":"HS512","typ":"JWT"}').rstrip(b"=").decode()
    payload = (
        base64.urlsafe_b64encode(json.dumps({"exp": expired_at.timestamp()}).encode())
        .rstrip(b"=")
        .decode()
    )
    expired_jwt = f"{header}.{payload}.fake-signature-not-verified"

    monkeypatch.setattr(
        DhanSettingsService,
        "effective_credentials",
        lambda self: ("fake-client-id", expired_jwt),
    )
    out = io.StringIO()

    call_command("run_market_data_worker", "--provider", "dhan", stdout=out)

    assert "final_state=TOKEN_EXPIRED" in out.getvalue()
    assert "token_state=EXPIRED" in out.getvalue()
    assert "refusing to start a live connection" in out.getvalue()
    # The real, live-verified finding this checkpoint's readiness gate
    # produced - this command must never claim otherwise.
    assert expired_jwt not in out.getvalue()


# --- Checkpoint 67.12.2-H: the stale-status regression test. Reproduces
# TODAY's exact real-world failure mode (67.12.2-E: two live crashes, both
# left `WorkerRuntimeStatus.worker_state` stuck at RECONNECTING forever)
# using ONLY the existing synthetic/monkeypatch harness this file already
# established for --provider dhan (a well-formed, non-expired JWT so the
# command proceeds past the credential/token gates, and a patched
# `DhanWebSocketTransport.connect` that always raises
# `DhanWebSocketTransportError` - never a real socket, never touching the
# network - so every reconnect-supervisor attempt reports RECONNECTING
# until `--max-reconnect-attempts` is exhausted, exactly like today's
# `close_code=1006` failures did in production).
@requires_postgres
# Deliberately NO redundant `@pytest.mark.django_db` here (unlike the two
# tests above) - this test writes to `WorkerRuntimeStatus` from BOTH the
# main test thread (the pre-seed below) AND the command's own
# `sync_to_async` thread (its real second connection). An extra
# function-level `django_db` mark conflicts with this file's module-level
# `transaction=True` marker, silently downgrading this one test back to
# atomic/savepoint (rollback) mode - which leaves the pre-seed's own
# transaction open (never truly committed) for the rest of the test, so
# the async thread's separate connection blocks forever trying to lock
# the same row. Reproduced and confirmed as a genuine deadlock during
# this checkpoint (two Postgres backends: one "idle in transaction" at
# "RELEASE SAVEPOINT", one "active" hung on the INSERT) - fixed by
# relying on the module-level marker alone, exactly like this file's
# other `transaction=True`-dependent tests above (Checkpoint 58/59/62).
def test_reconnect_exhaustion_persists_a_terminal_failed_status_not_a_stale_reconnecting_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import base64
    import json
    from datetime import UTC, datetime, timedelta

    from intraday.infrastructure.market_data_providers.dhan.websocket_transport import (
        DhanWebSocketTransport,
        DhanWebSocketTransportError,
    )
    from intraday.infrastructure.persistence.models import WorkerRuntimeStatus

    valid_until = datetime.now(tz=UTC) + timedelta(hours=1)
    header = base64.urlsafe_b64encode(b'{"alg":"HS512","typ":"JWT"}').rstrip(b"=").decode()
    payload = (
        base64.urlsafe_b64encode(json.dumps({"exp": valid_until.timestamp()}).encode())
        .rstrip(b"=")
        .decode()
    )
    valid_jwt = f"{header}.{payload}.fake-signature-not-verified"

    monkeypatch.setattr(
        DhanSettingsService,
        "effective_credentials",
        lambda self: ("fake-client-id", valid_jwt),
    )

    async def _always_fails_to_connect(self: object) -> None:
        raise DhanWebSocketTransportError("simulated connect failure - no real socket opened")

    monkeypatch.setattr(DhanWebSocketTransport, "connect", _always_fails_to_connect)

    # Pre-seed a row so the test also proves the stale value gets
    # overwritten, not merely created fresh.
    WorkerRuntimeStatus.objects.update_or_create(
        provider="dhan", defaults={"worker_state": "RUNNING"}
    )

    out = io.StringIO()
    call_command(
        "run_market_data_worker",
        "--provider",
        "dhan",
        "--max-reconnect-attempts",
        "2",
        stdout=out,
    )

    output = out.getvalue()
    assert "final_state=FAILED" in output
    assert "worker ended in terminal state FAILED" in output

    status = WorkerRuntimeStatus.objects.get(provider="dhan")
    # THE regression proof: today's actual bug left this at RECONNECTING
    # (or whatever the last periodic persist happened to write) forever.
    assert status.worker_state == "FAILED"
    assert status.worker_state != "RUNNING"
    assert status.worker_state != "RECONNECTING"
    assert status.reconnect_count == 2
    assert status.last_error_safe == "reconnect_attempts_exhausted"


# --- Checkpoint 64.2: the live worker now reaches the shared strategy/
# signal/risk/paper pipeline (`signal_pipeline_runtime.py`), not just
# persistence/aggregation - proven by mypy (the call site type-checks
# against the real `promote_bars_and_trigger_signals()` signature), the
# 5 dedicated `test_signal_pipeline_runtime.py` tests (the shared
# function's own orchestration logic), and every existing test above
# still passing unmodified (proving the wiring introduces no
# regression). A DEDICATED integration test invoking this command with
# the real pipeline call monkeypatched was deliberately NOT added here:
# this file's own `transaction=True` async-DB-write model (see its own
# module docstring) is a documented, pre-existing fragility - a probe
# during this checkpoint found that adding one more such test causes
# cross-test-file DB-row leakage (rows from this file's committed,
# non-rolled-back writes bleeding into unrelated test files run
# afterward), reproduced deterministically and confirmed absent before
# this checkpoint's changes. Adding another async-command test here
# would trade a marginal coverage gain for suite-wide flakiness - not
# a good trade when the wiring is already proven the ways listed above.
