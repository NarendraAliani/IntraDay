# tests/unit/application/services/test_live_paper_readiness.py
#
# Checkpoint 64.12: coverage for the ONE canonical "can we safely start
# a LIVE PAPER SESSION" decision - composes token_lifecycle,
# WorkerRuntimeStatus's watchdog_state, market session status, and
# kill-switch engagement, per §13's "use deterministic generated
# tokens or a testable clock, never a real production JWT value, never
# a hardcoded today's timestamp."
from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta

from intraday.application.services.live_paper_readiness import (
    LivePaperReadiness,
    LivePaperReadinessState,
    evaluate_live_paper_readiness,
)
from intraday.application.services.token_lifecycle import evaluate_dhan_token_lifecycle
from intraday.domain.session.contracts import SessionStatus

NOW = datetime(2026, 1, 5, 6, 0, tzinfo=UTC)  # a fixed, deterministic instant - never real "now"


def _fake_jwt(*, exp: datetime) -> str:
    """A deterministic, LOCALLY GENERATED token (never a real Dhan
    value, never placed in a fixture as a real credential) - only the
    unsigned JWT SHAPE (header.payload.signature) matters to
    `evaluate_dhan_token_lifecycle()`, which never verifies signatures."""

    def _segment(payload: dict[str, object]) -> str:
        raw = json.dumps(payload).encode("utf-8")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    header = _segment({"alg": "HS512", "typ": "JWT"})
    payload = _segment({"exp": int(exp.timestamp()), "dhanClientId": "test-client"})
    return f"{header}.{payload}.fake-signature-not-a-real-credential"


def _readiness(
    *,
    access_token: str | None,
    watchdog_state: str | None = "HEALTHY",
    market_session_status: SessionStatus = SessionStatus.OPEN,
    kill_switch_engaged: bool = False,
) -> LivePaperReadiness:
    token_status = evaluate_dhan_token_lifecycle(access_token, now=NOW)
    return evaluate_live_paper_readiness(
        provider="dhan",
        token_status=token_status,
        watchdog_state=watchdog_state,
        market_session_status=market_session_status,
        kill_switch_engaged=kill_switch_engaged,
    )


def test_missing_credential_blocks_with_not_configured() -> None:
    result = _readiness(access_token=None)

    assert result.state is LivePaperReadinessState.NOT_CONFIGURED
    assert result.can_start is False
    assert (
        "no usable" in result.safe_reason.lower() or "not configured" in result.safe_reason.lower()
    )


def test_malformed_token_blocks_with_credential_invalid() -> None:
    result = _readiness(access_token="not-a-real-jwt")

    assert result.state is LivePaperReadinessState.CREDENTIAL_INVALID
    assert result.can_start is False


def test_expired_token_blocks_with_credential_expired_and_reports_expiry() -> None:
    expired_token = _fake_jwt(exp=NOW - timedelta(hours=1))

    result = _readiness(access_token=expired_token)

    assert result.state is LivePaperReadinessState.CREDENTIAL_EXPIRED
    assert result.can_start is False
    assert result.credential_expires_at == NOW - timedelta(hours=1)
    assert "renew" in result.remediation.lower()


def test_valid_token_with_no_worker_report_blocks_with_provider_unavailable() -> None:
    valid_token = _fake_jwt(exp=NOW + timedelta(hours=12))

    result = _readiness(access_token=valid_token, watchdog_state=None)

    assert result.state is LivePaperReadinessState.PROVIDER_UNAVAILABLE
    assert result.can_start is False
    assert result.provider_state == "NEVER_REPORTED"


def test_valid_token_with_disconnected_worker_blocks_with_provider_unavailable() -> None:
    valid_token = _fake_jwt(exp=NOW + timedelta(hours=12))

    result = _readiness(access_token=valid_token, watchdog_state="DISCONNECTED")

    assert result.state is LivePaperReadinessState.PROVIDER_UNAVAILABLE
    assert result.can_start is False


def test_valid_token_and_healthy_worker_is_ready_for_paper() -> None:
    valid_token = _fake_jwt(exp=NOW + timedelta(hours=12))

    result = _readiness(access_token=valid_token, watchdog_state="HEALTHY")

    assert result.state is LivePaperReadinessState.READY_FOR_PAPER
    assert result.can_start is True
    assert result.real_trading_state == "DISABLED"
    assert result.paper_execution_state == "ENABLED"


def test_kill_switch_engaged_blocks_even_with_an_otherwise_ready_state() -> None:
    valid_token = _fake_jwt(exp=NOW + timedelta(hours=12))

    result = _readiness(
        access_token=valid_token, watchdog_state="HEALTHY", kill_switch_engaged=True
    )

    assert result.state is LivePaperReadinessState.BLOCKED_BY_SAFETY
    assert result.can_start is False


def test_real_trading_state_is_always_disabled_regardless_of_readiness() -> None:
    """The single most important invariant this module carries: no
    combination of inputs can ever make `real_trading_state` anything
    other than DISABLED - it is a structural constant, never derived."""
    for access_token, watchdog_state, kill_switch in [
        (None, None, False),
        ("garbage", None, False),
        (_fake_jwt(exp=NOW + timedelta(hours=12)), "HEALTHY", False),
        (_fake_jwt(exp=NOW + timedelta(hours=12)), "HEALTHY", True),
    ]:
        result = _readiness(
            access_token=access_token,
            watchdog_state=watchdog_state,
            kill_switch_engaged=kill_switch,
        )
        assert result.real_trading_state == "DISABLED"


def test_market_state_reflects_the_supplied_session_status() -> None:
    result = _readiness(
        access_token=_fake_jwt(exp=NOW + timedelta(hours=12)),
        market_session_status=SessionStatus.CLOSED,
    )

    assert result.market_state == "CLOSED"


def test_expiring_soon_token_with_healthy_worker_is_still_ready() -> None:
    """`EXPIRING_SOON` is still a usable, VALID-adjacent credential
    (Dhan's own token is still accepted) - the gate must not block on
    it, only warn via `credential_state`."""
    soon_token = _fake_jwt(exp=NOW + timedelta(minutes=30))

    result = _readiness(access_token=soon_token, watchdog_state="HEALTHY")

    assert result.state is LivePaperReadinessState.READY_FOR_PAPER
    assert result.can_start is True
