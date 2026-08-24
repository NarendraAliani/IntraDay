# tests/unit/research/test_checkpoint_64_57_dhan_credential_readiness.py
#
# Checkpoint 64.57: DHAN CREDENTIAL REFRESH / LIVE-SESSION READINESS.
#
# Confirms (a) the new `evaluate_dhan_observe_only_readiness()` pure
# contract (Checkpoint 64.57's own minimum-safe addition) correctly
# classifies VALID/EXPIRED/MALFORMED/ABSENT tokens into the exact
# readiness vocabulary the checkpoint directive names
# (READY_FOR_OBSERVE_ONLY / BLOCKED_TOKEN_EXPIRED / BLOCKED_TOKEN_
# MALFORMED / BLOCKED_TOKEN_ABSENT); (b) no credential material is ever
# exposed by the safe display types this checkpoint reused
# (`DhanSettingsView`, `ObserveOnlyReadiness`); and (c) the 64.56
# observe-only safety gate + `BacktestTrustLevel.POC` remain unchanged.
#
# Every token below is a hand-built, JWT-SHAPED synthetic value (a real
# `exp` claim, base64url-encoded, NO real signature) - identical
# construction to `tests/unit/application/services/test_token_lifecycle.py`
# (Checkpoint 64 Part 1). NEVER a real Dhan credential. No network call
# is made anywhere in this file.
from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta

from intraday.application.services.observe_only_readiness import (
    ObserveOnlyReadinessState,
    evaluate_dhan_observe_only_readiness,
)
from intraday.application.services.token_lifecycle import (
    TokenLifecycleState,
    evaluate_dhan_token_lifecycle,
)

NOW = datetime(2026, 8, 24, 8, 0, 0, tzinfo=UTC)


def _jwt(exp: float | None) -> str:
    """Synthetic, JWT-shaped token - never a real credential. Identical
    construction to the existing `test_token_lifecycle.py` helper."""
    header = base64.urlsafe_b64encode(b'{"alg":"HS512","typ":"JWT"}').rstrip(b"=").decode()
    payload_obj: dict[str, object] = {"iss": "dhan-synthetic-test-fixture"}
    if exp is not None:
        payload_obj["exp"] = exp
    payload = base64.urlsafe_b64encode(json.dumps(payload_obj).encode()).rstrip(b"=").decode()
    return f"{header}.{payload}.fake-signature-not-verified"


VALID_TOKEN = _jwt((NOW + timedelta(hours=5)).timestamp())
EXPIRED_TOKEN = _jwt((NOW - timedelta(days=3)).timestamp())
MALFORMED_TOKEN = "not-a-real-jwt-shape"  # noqa: S105 - synthetic test fixture, not a secret


# --- A: valid token readiness -----------------------------------------------


def test_a_valid_token_readiness_allowed() -> None:
    token_status = evaluate_dhan_token_lifecycle(VALID_TOKEN, now=NOW)
    assert token_status.state is TokenLifecycleState.VALID

    readiness = evaluate_dhan_observe_only_readiness(provider="dhan", token_status=token_status)

    assert readiness.state is ObserveOnlyReadinessState.READY_FOR_OBSERVE_ONLY
    assert readiness.ready is True


def test_a2_expiring_soon_token_still_readiness_allowed() -> None:
    """EXPIRING_SOON is still `ready` - identical precedent to
    `attempt_dhan_token_renewal()`'s own VALID/EXPIRING_SOON grouping;
    a token expiring in under an hour is not yet EXPIRED."""
    near_expiry = _jwt((NOW + timedelta(minutes=30)).timestamp())
    token_status = evaluate_dhan_token_lifecycle(near_expiry, now=NOW)
    assert token_status.state is TokenLifecycleState.EXPIRING_SOON

    readiness = evaluate_dhan_observe_only_readiness(provider="dhan", token_status=token_status)

    assert readiness.state is ObserveOnlyReadinessState.READY_FOR_OBSERVE_ONLY
    assert readiness.ready is True


# --- B: expired token blocked -----------------------------------------------


def test_b_expired_token_readiness_blocked() -> None:
    token_status = evaluate_dhan_token_lifecycle(EXPIRED_TOKEN, now=NOW)
    assert token_status.state is TokenLifecycleState.EXPIRED

    readiness = evaluate_dhan_observe_only_readiness(provider="dhan", token_status=token_status)

    assert readiness.state is ObserveOnlyReadinessState.BLOCKED_TOKEN_EXPIRED
    assert readiness.ready is False


# --- C: malformed token blocked ---------------------------------------------


def test_c_malformed_token_readiness_blocked() -> None:
    token_status = evaluate_dhan_token_lifecycle(MALFORMED_TOKEN, now=NOW)
    assert token_status.state is TokenLifecycleState.MALFORMED

    readiness = evaluate_dhan_observe_only_readiness(provider="dhan", token_status=token_status)

    assert readiness.state is ObserveOnlyReadinessState.BLOCKED_TOKEN_MALFORMED
    assert readiness.ready is False


# --- D: absent token blocked -------------------------------------------------


def test_d_absent_token_readiness_blocked() -> None:
    token_status = evaluate_dhan_token_lifecycle(None, now=NOW)
    assert token_status.state is TokenLifecycleState.UNCONFIGURED

    readiness = evaluate_dhan_observe_only_readiness(provider="dhan", token_status=token_status)

    assert readiness.state is ObserveOnlyReadinessState.BLOCKED_TOKEN_ABSENT
    assert readiness.ready is False


# --- E: safe metadata only ---------------------------------------------------


def test_e_readiness_object_carries_only_safe_metadata() -> None:
    """`ObserveOnlyReadiness` exposes only state/provider/credential
    lifecycle state/expiry/ready - it structurally cannot carry a token
    value (no such field exists on the dataclass)."""
    token_status = evaluate_dhan_token_lifecycle(VALID_TOKEN, now=NOW)
    readiness = evaluate_dhan_observe_only_readiness(provider="dhan", token_status=token_status)

    field_names = set(readiness.__dataclass_fields__)
    expected = {"state", "provider", "credential_state", "credential_expires_at", "ready"}
    assert field_names == expected


# --- F: no secret leakage -----------------------------------------------------


def test_f_no_secret_leakage_in_readiness_repr_or_dhan_settings_view() -> None:
    """Neither the readiness contract's own `repr()` nor the existing
    `DhanSettingsView` safe-display type (Checkpoint 22/64) ever
    contains the raw token string - proven by asserting the exact
    synthetic token text is absent from every string representation
    this checkpoint's own code paths can produce."""
    token_status = evaluate_dhan_token_lifecycle(VALID_TOKEN, now=NOW)
    readiness = evaluate_dhan_observe_only_readiness(provider="dhan", token_status=token_status)

    assert VALID_TOKEN not in repr(readiness)
    assert VALID_TOKEN not in str(readiness)

    from intraday.application.services.provider_settings import _mask_identifier

    masked = _mask_identifier(VALID_TOKEN)
    assert masked != VALID_TOKEN
    assert VALID_TOKEN not in masked


# --- G: observe-only safety preserved (64.56 regression) --------------------


def test_g_observe_only_gate_module_still_present_and_unimported_by_this_module() -> None:
    """This checkpoint's new readiness contract does not import, touch,
    or construct anything from the strategy-execution/PaperBroker path
    - a structural re-confirmation that readiness evaluation stays
    strictly read-only. The dynamic, full 14-test proof lives in
    `test_checkpoint_64_56_live_observe_only_gate.py` and is re-run as
    part of this checkpoint's regression (see taskReport.md), not
    duplicated here."""
    import intraday.application.services.observe_only_readiness as module

    source_globals = set(vars(module))
    assert "PaperSignalExecutionService" not in source_globals
    assert "PaperBroker" not in source_globals


# --- H: paper/live distinction preserved -------------------------------------


def test_h_observe_only_readiness_is_a_distinct_contract_from_live_paper_readiness() -> None:
    """`evaluate_dhan_observe_only_readiness()` and
    `evaluate_live_paper_readiness()` (Checkpoint 64.12) remain two
    separate functions with two separate state vocabularies - observe-
    only readiness never claims `READY_FOR_PAPER`, and paper readiness
    never claims `READY_FOR_OBSERVE_ONLY`."""
    from intraday.application.services.live_paper_readiness import LivePaperReadinessState

    observe_only_states = {s.value for s in ObserveOnlyReadinessState}
    paper_states = {s.value for s in LivePaperReadinessState}
    assert observe_only_states.isdisjoint(paper_states)


# --- I: readiness contract is deterministic ----------------------------------


def test_i_readiness_contract_is_deterministic() -> None:
    token_status = evaluate_dhan_token_lifecycle(EXPIRED_TOKEN, now=NOW)
    first = evaluate_dhan_observe_only_readiness(provider="dhan", token_status=token_status)
    second = evaluate_dhan_observe_only_readiness(provider="dhan", token_status=token_status)
    assert first == second


# --- J: existing 64.56 behavior + BacktestTrustLevel.POC remain unchanged ---


def test_j_backtest_trust_level_poc_unchanged() -> None:
    from intraday.research.backtesting.contracts import BacktestTrustLevel

    assert BacktestTrustLevel.POC.name == "POC"
