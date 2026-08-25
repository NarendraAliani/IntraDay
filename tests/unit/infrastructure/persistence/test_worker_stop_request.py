# tests/unit/infrastructure/persistence/test_worker_stop_request.py
#
# Checkpoint 64.73: real-database coverage for the process-independent
# stop-request mechanism that replaces 64.72's three failed OS-signal
# shutdown attempts as the PRIMARY shutdown path.
#
# Nothing here starts a worker process, opens a socket, or contacts a
# provider - that is precisely the property being demonstrated.
from __future__ import annotations

import datetime as dt

import pytest
from django.core.management import call_command

from intraday.infrastructure.persistence.models import WorkerRuntimeStatus
from intraday.infrastructure.persistence.worker_runtime_status_repository import (
    DjangoWorkerRuntimeStatusRepository,
)
from tests.postgres_utils import requires_postgres

NOW = dt.datetime(2026, 8, 25, 6, 0, tzinfo=dt.UTC)


@requires_postgres
@pytest.mark.django_db
def test_no_stop_request_by_default() -> None:
    assert DjangoWorkerRuntimeStatusRepository().get_stop_request("dhan") is None


@requires_postgres
@pytest.mark.django_db
def test_request_then_read_round_trips() -> None:
    repo = DjangoWorkerRuntimeStatusRepository()

    repo.request_stop(
        "dhan", requested_at=NOW, requested_by="operator", reason_safe="end_of_session"
    )

    request = repo.get_stop_request("dhan")
    assert request is not None
    assert request.provider == "dhan"
    assert request.requested_by == "operator"
    assert request.reason_safe == "end_of_session"


@requires_postgres
@pytest.mark.django_db
def test_requesting_twice_leaves_one_pending_request() -> None:
    repo = DjangoWorkerRuntimeStatusRepository()

    repo.request_stop("dhan", requested_at=NOW, requested_by="a", reason_safe="x")
    repo.request_stop("dhan", requested_at=NOW, requested_by="b", reason_safe="y")

    assert WorkerRuntimeStatus.objects.filter(provider="dhan").count() == 1
    request = repo.get_stop_request("dhan")
    assert request is not None
    assert request.requested_by == "b"


@requires_postgres
@pytest.mark.django_db
def test_clear_removes_the_pending_request() -> None:
    """The staleness guard: the worker clears at startup, so a request
    left over from a previous run can never instantly kill a fresh one."""
    repo = DjangoWorkerRuntimeStatusRepository()
    repo.request_stop("dhan", requested_at=NOW, requested_by="operator", reason_safe="x")

    repo.clear_stop_request("dhan")

    assert repo.get_stop_request("dhan") is None


@requires_postgres
@pytest.mark.django_db
def test_stop_request_does_not_disturb_reported_runtime_state() -> None:
    """A stop REQUEST is not a state change - `worker_state` must still
    reflect what the worker itself last reported until it actually
    stops and writes STOPPED."""
    repo = DjangoWorkerRuntimeStatusRepository()
    repo.save(
        "dhan",
        worker_state="RUNNING",
        token_state="VALID",
        watchdog_state="HEALTHY",
        last_packet_at=NOW,
        last_bar_at=NOW,
        reconnect_count=0,
        consecutive_failures=0,
        subscribed_instrument_count=4,
        last_error_safe="",
    )

    repo.request_stop("dhan", requested_at=NOW, requested_by="operator", reason_safe="x")

    record = repo.get("dhan")
    assert record is not None
    assert record.worker_state == "RUNNING"


@requires_postgres
@pytest.mark.django_db
def test_management_command_records_and_clears_a_request() -> None:
    repo = DjangoWorkerRuntimeStatusRepository()

    call_command("request_market_data_worker_stop", "--provider", "dhan", "--reason", "eod")
    assert repo.get_stop_request("dhan") is not None

    call_command("request_market_data_worker_stop", "--provider", "dhan", "--clear")
    assert repo.get_stop_request("dhan") is None


@requires_postgres
@pytest.mark.django_db
def test_management_command_never_touches_worker_state() -> None:
    """It records a request; it does not kill anything and does not lie
    about the worker having stopped."""
    call_command("request_market_data_worker_stop", "--provider", "dhan")

    row = WorkerRuntimeStatus.objects.get(provider="dhan")
    assert row.worker_state == "STOPPED"  # the model default - never forced by this command
    assert row.stop_requested_at is not None
