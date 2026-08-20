# tests/unit/application/services/test_live_paper_session.py
#
# Checkpoint 64.13: coverage for the explicit START/STOP workflow -
# a fake, in-memory ScannerConfigurationRepository (never the real
# Django one - this is pure orchestration logic, database wiring is
# covered separately by the API vertical-slice tests) proves the
# idempotency, readiness-gating, and state-derivation rules.
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from intraday.application.repositories.scanner_configuration import ScannerConfigurationRecord
from intraday.application.repositories.worker_runtime_status import WorkerRuntimeStatusRecord
from intraday.application.services.live_paper_readiness import (
    LivePaperReadiness,
    LivePaperReadinessState,
)
from intraday.application.services.live_paper_session import (
    LivePaperSessionState,
    derive_live_paper_session_state,
    start_live_paper_session,
    stop_live_paper_session,
)
from intraday.application.services.token_lifecycle import TokenLifecycleState


def _readiness(*, can_start: bool) -> LivePaperReadiness:
    return LivePaperReadiness(
        state=(
            LivePaperReadinessState.READY_FOR_PAPER
            if can_start
            else LivePaperReadinessState.CREDENTIAL_EXPIRED
        ),
        provider="dhan",
        credential_state=(TokenLifecycleState.VALID if can_start else TokenLifecycleState.EXPIRED),
        credential_expires_at=None,
        provider_state="HEALTHY" if can_start else "NEVER_REPORTED",
        market_state="OPEN",
        paper_execution_state="ENABLED",
        real_trading_state="DISABLED",
        can_start=can_start,
        safe_reason="test",
        remediation="Renew the Dhan access token." if not can_start else "test",
    )


def _record(*, enabled: bool, version: int = 1) -> ScannerConfigurationRecord:
    return ScannerConfigurationRecord(
        provider="dhan",
        enabled=enabled,
        timeframe="5m",
        universe_mode="ALL_CONFIGURED",
        selected_instrument_ids=(),
        selected_watchlist_name="",
        selected_strategy_ids=("ema_crossover",),
        configuration_version=version,
        requested_by="operator",
        requested_at=datetime(2026, 1, 5, 6, 0, tzinfo=UTC),
    )


class _FakeScannerConfigurationRepository:
    """In-memory, real-Protocol-shaped fake - never the Django
    implementation (covered separately by API tests)."""

    def __init__(self, initial: ScannerConfigurationRecord) -> None:
        self._row = initial
        self.save_call_count = 0

    def get(self, provider: str) -> ScannerConfigurationRecord:
        return self._row

    def save(self, provider: str, **kwargs: object) -> ScannerConfigurationRecord:
        self.save_call_count += 1
        self._row = replace(
            self._row,
            enabled=kwargs["enabled"],  # type: ignore[arg-type]
            configuration_version=self._row.configuration_version + 1,
        )
        return self._row


def test_start_is_refused_when_readiness_blocks_it() -> None:
    repository = _FakeScannerConfigurationRepository(_record(enabled=False))

    result = start_live_paper_session(
        readiness=_readiness(can_start=False),
        repository=repository,
        provider="dhan",
        requested_by="operator",
        requested_by_user_id=1,
        request_id="req-1",
    )

    assert result.accepted is False
    assert result.state is LivePaperSessionState.NOT_READY
    assert repository.save_call_count == 0
    assert result.remediation is not None


def test_start_succeeds_when_readiness_allows_it() -> None:
    repository = _FakeScannerConfigurationRepository(_record(enabled=False))

    result = start_live_paper_session(
        readiness=_readiness(can_start=True),
        repository=repository,
        provider="dhan",
        requested_by="operator",
        requested_by_user_id=1,
        request_id="req-1",
    )

    assert result.accepted is True
    assert result.desired.enabled is True
    assert repository.save_call_count == 1


def test_start_is_idempotent_and_never_creates_a_duplicate_write() -> None:
    repository = _FakeScannerConfigurationRepository(_record(enabled=True))

    result = start_live_paper_session(
        readiness=_readiness(can_start=True),
        repository=repository,
        provider="dhan",
        requested_by="operator",
        requested_by_user_id=1,
        request_id="req-1",
    )

    assert result.accepted is False
    assert "already running" in result.message.lower()
    assert repository.save_call_count == 0  # no duplicate write/version bump


def test_stop_succeeds_on_a_running_session() -> None:
    repository = _FakeScannerConfigurationRepository(_record(enabled=True))

    result = stop_live_paper_session(
        repository=repository,
        provider="dhan",
        requested_by="operator",
        requested_by_user_id=1,
        request_id="req-1",
    )

    assert result.accepted is True
    assert result.desired.enabled is False
    assert repository.save_call_count == 1


def test_stop_is_idempotent_on_an_already_stopped_session() -> None:
    repository = _FakeScannerConfigurationRepository(_record(enabled=False))

    result = stop_live_paper_session(
        repository=repository,
        provider="dhan",
        requested_by="operator",
        requested_by_user_id=1,
        request_id="req-1",
    )

    assert result.accepted is False
    assert "already stopped" in result.message.lower()
    assert repository.save_call_count == 0


def test_derive_state_not_ready_when_stopped_and_readiness_blocked() -> None:
    state = derive_live_paper_session_state(
        desired=_record(enabled=False), effective=None, readiness=_readiness(can_start=False)
    )
    assert state is LivePaperSessionState.NOT_READY


def test_derive_state_ready_when_stopped_and_readiness_allows() -> None:
    state = derive_live_paper_session_state(
        desired=_record(enabled=False), effective=None, readiness=_readiness(can_start=True)
    )
    assert state is LivePaperSessionState.READY


def test_derive_state_stopped_when_disabled_but_worker_has_reported() -> None:
    effective = WorkerRuntimeStatusRecord(
        provider="dhan",
        worker_state="RUNNING",
        token_state="VALID",
        watchdog_state="HEALTHY",
        last_packet_at=None,
        last_bar_at=None,
        reconnect_count=0,
        consecutive_failures=0,
        subscribed_instrument_count=0,
        last_error_safe="",
        updated_at=None,
        effective_configuration_version=1,
        effective_timeframe="5m",
        effective_strategy_ids=(),
        effective_universe_requested_count=0,
        effective_universe_subscribed_count=0,
    )
    state = derive_live_paper_session_state(
        desired=_record(enabled=False), effective=effective, readiness=_readiness(can_start=True)
    )
    assert state is LivePaperSessionState.STOPPED


def test_derive_state_starting_when_enabled_but_not_yet_reconciled() -> None:
    state = derive_live_paper_session_state(
        desired=_record(enabled=True, version=2),
        effective=None,
        readiness=_readiness(can_start=True),
    )
    assert state is LivePaperSessionState.STARTING


def test_derive_state_running_when_enabled_and_versions_match() -> None:
    effective = WorkerRuntimeStatusRecord(
        provider="dhan",
        worker_state="RUNNING",
        token_state="VALID",
        watchdog_state="HEALTHY",
        last_packet_at=None,
        last_bar_at=None,
        reconnect_count=0,
        consecutive_failures=0,
        subscribed_instrument_count=5,
        last_error_safe="",
        updated_at=None,
        effective_configuration_version=2,
        effective_timeframe="5m",
        effective_strategy_ids=("ema_crossover",),
        effective_universe_requested_count=5,
        effective_universe_subscribed_count=5,
    )
    state = derive_live_paper_session_state(
        desired=_record(enabled=True, version=2),
        effective=effective,
        readiness=_readiness(can_start=True),
    )
    assert state is LivePaperSessionState.RUNNING
