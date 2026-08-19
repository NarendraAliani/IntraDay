# tests/unit/application/services/test_token_lifecycle.py
#
# Checkpoint 64 Part 1: unit coverage for the pure, claims-only Dhan
# access-token lifecycle evaluator. Uses hand-built JWT-shaped tokens
# (a real `exp` claim, base64url-encoded, no real signature - this
# module never verifies the signature) - never a real credential.
from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta

from intraday.application.services.token_lifecycle import (
    EXPIRING_SOON_THRESHOLD,
    TokenLifecycleState,
    TokenRenewalError,
    TokenRenewalResult,
    attempt_dhan_token_renewal,
    evaluate_dhan_token_lifecycle,
)

NOW = datetime(2026, 8, 19, 8, 0, 0, tzinfo=UTC)


def _jwt(exp: float | None) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"HS512","typ":"JWT"}').rstrip(b"=").decode()
    payload_obj: dict[str, object] = {"iss": "dhan"}
    if exp is not None:
        payload_obj["exp"] = exp
    payload = base64.urlsafe_b64encode(json.dumps(payload_obj).encode()).rstrip(b"=").decode()
    return f"{header}.{payload}.fake-signature-not-verified"


def test_no_token_configured_is_unconfigured() -> None:
    status = evaluate_dhan_token_lifecycle(None, now=NOW)
    assert status.state is TokenLifecycleState.UNCONFIGURED
    assert status.expires_at is None


def test_empty_string_token_is_unconfigured() -> None:
    status = evaluate_dhan_token_lifecycle("", now=NOW)
    assert status.state is TokenLifecycleState.UNCONFIGURED


def test_a_non_jwt_token_is_malformed_never_guessed_as_valid_or_expired() -> None:
    status = evaluate_dhan_token_lifecycle("not-a-real-jwt-token", now=NOW)
    assert status.state is TokenLifecycleState.MALFORMED
    assert status.expires_at is None


def test_a_jwt_with_no_exp_claim_is_malformed() -> None:
    token = _jwt(exp=None)
    status = evaluate_dhan_token_lifecycle(token, now=NOW)
    assert status.state is TokenLifecycleState.MALFORMED


def test_a_token_expiring_well_in_the_future_is_valid() -> None:
    exp = (NOW + timedelta(hours=12)).timestamp()
    status = evaluate_dhan_token_lifecycle(_jwt(exp), now=NOW)
    assert status.state is TokenLifecycleState.VALID
    assert status.expires_at == NOW + timedelta(hours=12)


def test_a_token_inside_the_expiring_soon_window_is_flagged() -> None:
    exp = (NOW + EXPIRING_SOON_THRESHOLD - timedelta(minutes=1)).timestamp()
    status = evaluate_dhan_token_lifecycle(_jwt(exp), now=NOW)
    assert status.state is TokenLifecycleState.EXPIRING_SOON


def test_a_token_past_its_own_exp_claim_is_expired() -> None:
    """The exact real-world case this checkpoint's live Dhan
    connectivity check found: a token issued ~24h before `now`, past
    its own documented ~24h TTL."""
    exp = (NOW - timedelta(hours=1)).timestamp()
    status = evaluate_dhan_token_lifecycle(_jwt(exp), now=NOW)
    assert status.state is TokenLifecycleState.EXPIRED
    assert status.expires_at == NOW - timedelta(hours=1)


def test_expiry_boundary_is_treated_as_expired_not_valid() -> None:
    exp = NOW.timestamp()
    status = evaluate_dhan_token_lifecycle(_jwt(exp), now=NOW)
    assert status.state is TokenLifecycleState.EXPIRED


# --- attempt_dhan_token_renewal() -------------------------------------------


def _always_succeeds(*, client_id: str, current_access_token: str) -> TokenRenewalResult:
    return TokenRenewalResult(new_access_token="renewed-fake-token")  # noqa: S106


def _always_rejects(*, client_id: str, current_access_token: str) -> TokenRenewalResult:
    raise TokenRenewalError("Dhan rejected the renewal.")


def test_an_expired_token_goes_straight_to_operator_action_required_never_calls_renew() -> None:
    """Dhan's own documented rule: renewing an already-expired token is
    an endpoint the docs say will always fail - never attempted."""
    exp = (NOW - timedelta(hours=1)).timestamp()

    def _raises_if_called(**kwargs: object) -> TokenRenewalResult:
        raise AssertionError("renew() must never be called for an EXPIRED token")

    state, new_token = attempt_dhan_token_renewal(
        client_id="fake-client-id", access_token=_jwt(exp), now=NOW, renew=_raises_if_called
    )

    assert state is TokenLifecycleState.OPERATOR_ACTION_REQUIRED
    assert new_token is None


def test_unconfigured_goes_straight_to_operator_action_required() -> None:
    state, new_token = attempt_dhan_token_renewal(
        client_id="fake-client-id", access_token=None, now=NOW, renew=_always_succeeds
    )
    assert state is TokenLifecycleState.OPERATOR_ACTION_REQUIRED
    assert new_token is None


def test_a_valid_token_needs_no_renewal() -> None:
    exp = (NOW + timedelta(hours=12)).timestamp()

    def _raises_if_called(**kwargs: object) -> TokenRenewalResult:
        raise AssertionError("renew() must never be called for a VALID token")

    state, new_token = attempt_dhan_token_renewal(
        client_id="fake-client-id", access_token=_jwt(exp), now=NOW, renew=_raises_if_called
    )

    assert state is TokenLifecycleState.VALID
    assert new_token is None


def test_expiring_soon_attempts_renewal_and_succeeds() -> None:
    exp = (NOW + timedelta(minutes=30)).timestamp()

    state, new_token = attempt_dhan_token_renewal(
        client_id="fake-client-id", access_token=_jwt(exp), now=NOW, renew=_always_succeeds
    )

    assert state is TokenLifecycleState.RENEWED
    assert new_token == "renewed-fake-token"  # noqa: S105


def test_expiring_soon_renewal_rejected_reports_auth_failure() -> None:
    exp = (NOW + timedelta(minutes=30)).timestamp()

    state, new_token = attempt_dhan_token_renewal(
        client_id="fake-client-id", access_token=_jwt(exp), now=NOW, renew=_always_rejects
    )

    assert state is TokenLifecycleState.AUTH_FAILURE
    assert new_token is None
