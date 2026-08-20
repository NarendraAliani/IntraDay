# tests/unit/application/services/test_live_paper_readiness_checklist.py
#
# Checkpoint 64.14: coverage for the 10-item Pre-Session Readiness
# Workbench - proves each check's real semantics (§3), never a
# fabricated state, and that all 10 items are always present in the
# documented order.
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from intraday.application.repositories.scanner_configuration import ScannerConfigurationRecord
from intraday.application.repositories.worker_runtime_status import WorkerRuntimeStatusRecord
from intraday.application.services.live_paper_readiness import (
    LivePaperReadiness,
    LivePaperReadinessState,
)
from intraday.application.services.live_paper_readiness_checklist import (
    ReadinessCheckState,
    build_readiness_checklist,
)
from intraday.application.services.token_lifecycle import TokenLifecycleState
from intraday.domain.session.contracts import SessionStatus

NOW = datetime(2026, 1, 5, 6, 0, tzinfo=UTC)


def _readiness(
    *, credential_state: TokenLifecycleState, provider_state: str, can_start: bool = False
) -> LivePaperReadiness:
    return LivePaperReadiness(
        state=LivePaperReadinessState.READY_FOR_PAPER
        if can_start
        else LivePaperReadinessState.CREDENTIAL_EXPIRED,
        provider="dhan",
        credential_state=credential_state,
        credential_expires_at=NOW + timedelta(hours=1)
        if credential_state != TokenLifecycleState.UNCONFIGURED
        else None,
        provider_state=provider_state,
        market_state="OPEN",
        paper_execution_state="ENABLED",
        real_trading_state="DISABLED",
        can_start=can_start,
        safe_reason="test",
        remediation="test remediation",
    )


def _desired(
    *,
    universe_mode: str = "ALL_CONFIGURED",
    selected_instrument_ids: tuple[str, ...] = (),
    selected_watchlist_name: str = "",
    timeframe: str = "5m",
    selected_strategy_ids: tuple[str, ...] = ("ema_crossover",),
) -> ScannerConfigurationRecord:
    return ScannerConfigurationRecord(
        provider="dhan",
        enabled=True,
        timeframe=timeframe,
        universe_mode=universe_mode,
        selected_instrument_ids=selected_instrument_ids,
        selected_watchlist_name=selected_watchlist_name,
        selected_strategy_ids=selected_strategy_ids,
        configuration_version=1,
        requested_by="operator",
        requested_at=NOW,
    )


def test_all_ten_checks_are_always_present_in_the_documented_order() -> None:
    checks = build_readiness_checklist(
        readiness=_readiness(credential_state=TokenLifecycleState.VALID, provider_state="HEALTHY"),
        market_session_status=SessionStatus.OPEN,
        desired=_desired(),
        effective=None,
    )

    assert [c.label for c in checks] == [
        "Dhan Credential",
        "Provider Connectivity",
        "Token Validity",
        "Watchdog",
        "Market State",
        "Universe",
        "Timeframe",
        "Strategy Selection",
        "Paper Execution",
        "Real Trading Safety",
    ]


def test_credential_check_maps_every_token_lifecycle_state_correctly() -> None:
    expected = {
        TokenLifecycleState.VALID: ReadinessCheckState.READY,
        TokenLifecycleState.EXPIRING_SOON: ReadinessCheckState.WARNING,
        TokenLifecycleState.EXPIRED: ReadinessCheckState.BLOCKED,
        TokenLifecycleState.MALFORMED: ReadinessCheckState.BLOCKED,
        TokenLifecycleState.UNCONFIGURED: ReadinessCheckState.BLOCKED,
    }
    for token_state, want in expected.items():
        checks = build_readiness_checklist(
            readiness=_readiness(credential_state=token_state, provider_state="HEALTHY"),
            market_session_status=SessionStatus.OPEN,
            desired=_desired(),
            effective=None,
        )
        credential = next(c for c in checks if c.key == "dhan_credential")
        assert credential.state is want, f"{token_state} expected {want}, got {credential.state}"


def test_token_validity_is_unknown_when_nothing_is_configured_not_blocked_twice() -> None:
    checks = build_readiness_checklist(
        readiness=_readiness(
            credential_state=TokenLifecycleState.UNCONFIGURED, provider_state="HEALTHY"
        ),
        market_session_status=SessionStatus.OPEN,
        desired=_desired(),
        effective=None,
    )
    token_validity = next(c for c in checks if c.key == "token_validity")
    assert token_validity.state is ReadinessCheckState.UNKNOWN


def test_watchdog_and_provider_connectivity_reflect_real_watchdog_state() -> None:
    for watchdog, want in [
        ("HEALTHY", ReadinessCheckState.READY),
        ("STALE", ReadinessCheckState.WARNING),
        ("DEGRADED", ReadinessCheckState.WARNING),
        ("DISCONNECTED", ReadinessCheckState.BLOCKED),
        ("FAILED", ReadinessCheckState.BLOCKED),
        ("NEVER_REPORTED", ReadinessCheckState.UNKNOWN),
    ]:
        checks = build_readiness_checklist(
            readiness=_readiness(
                credential_state=TokenLifecycleState.VALID, provider_state=watchdog
            ),
            market_session_status=SessionStatus.OPEN,
            desired=_desired(),
            effective=None,
        )
        watchdog_check = next(c for c in checks if c.key == "watchdog")
        connectivity_check = next(c for c in checks if c.key == "provider_connectivity")
        assert watchdog_check.state is want, watchdog
        assert connectivity_check.state is want, watchdog


def test_market_state_check_reflects_the_real_session_status() -> None:
    for status, want in [
        (SessionStatus.OPEN, ReadinessCheckState.READY),
        (SessionStatus.PRE_OPEN, ReadinessCheckState.WARNING),
        (SessionStatus.CLOSING, ReadinessCheckState.WARNING),
        (SessionStatus.CLOSED, ReadinessCheckState.BLOCKED),
        (SessionStatus.HOLIDAY, ReadinessCheckState.BLOCKED),
    ]:
        checks = build_readiness_checklist(
            readiness=_readiness(
                credential_state=TokenLifecycleState.VALID, provider_state="HEALTHY"
            ),
            market_session_status=status,
            desired=_desired(),
            effective=None,
        )
        market = next(c for c in checks if c.key == "market_state")
        assert market.state is want, status


def test_universe_check_blocks_on_an_empty_selected_universe() -> None:
    checks = build_readiness_checklist(
        readiness=_readiness(credential_state=TokenLifecycleState.VALID, provider_state="HEALTHY"),
        market_session_status=SessionStatus.OPEN,
        desired=_desired(universe_mode="SELECTED", selected_instrument_ids=()),
        effective=None,
    )
    universe = next(c for c in checks if c.key == "universe")
    assert universe.state is ReadinessCheckState.BLOCKED


def test_universe_check_warns_on_a_partial_subscription() -> None:
    effective = WorkerRuntimeStatusRecord(
        provider="dhan",
        worker_state="RUNNING",
        token_state="VALID",
        watchdog_state="HEALTHY",
        last_packet_at=None,
        last_bar_at=None,
        reconnect_count=0,
        consecutive_failures=0,
        subscribed_instrument_count=2,
        last_error_safe="",
        updated_at=None,
        effective_configuration_version=1,
        effective_timeframe="5m",
        effective_strategy_ids=("ema_crossover",),
        effective_universe_requested_count=5,
        effective_universe_subscribed_count=2,
    )
    checks = build_readiness_checklist(
        readiness=_readiness(credential_state=TokenLifecycleState.VALID, provider_state="HEALTHY"),
        market_session_status=SessionStatus.OPEN,
        desired=_desired(),
        effective=effective,
    )
    universe = next(c for c in checks if c.key == "universe")
    assert universe.state is ReadinessCheckState.WARNING
    assert "3" in universe.explanation


def test_strategy_selection_blocks_when_empty() -> None:
    checks = build_readiness_checklist(
        readiness=_readiness(credential_state=TokenLifecycleState.VALID, provider_state="HEALTHY"),
        market_session_status=SessionStatus.OPEN,
        desired=_desired(selected_strategy_ids=()),
        effective=None,
    )
    strategy = next(c for c in checks if c.key == "strategy_selection")
    assert strategy.state is ReadinessCheckState.BLOCKED


def test_paper_execution_and_real_trading_safety_are_always_ready() -> None:
    """Structural constants - proven across a blocked overall scenario
    too, since they never depend on credential/worker state."""
    checks = build_readiness_checklist(
        readiness=_readiness(
            credential_state=TokenLifecycleState.EXPIRED, provider_state="NEVER_REPORTED"
        ),
        market_session_status=SessionStatus.CLOSED,
        desired=_desired(),
        effective=None,
    )
    paper = next(c for c in checks if c.key == "paper_execution")
    real_trading = next(c for c in checks if c.key == "real_trading_safety")
    assert paper.state is ReadinessCheckState.READY
    assert real_trading.state is ReadinessCheckState.READY
