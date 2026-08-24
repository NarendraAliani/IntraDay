# tests/unit/research/test_checkpoint_64_60_dhan_provisioning.py
#
# Checkpoint 64.60: proves the NEW `provision_dhan_credentials`
# management command is a SAFE, EXPLICIT, operator-invoked bridge from
# an environment-provided Dhan credential into the SAME encrypted
# database record 64.59 already proved the Settings API save/persist/
# read path uses -- never a parallel credential system, never an
# automatic startup sync.
#
# SECURITY: every token in this file is a synthetic, self-constructed
# JWT-shaped string, supplied to the process environment ONLY through
# pytest's `monkeypatch.setenv` -- never read from, or written to, the
# real `.env` file. No real credential appears anywhere in this file.
# No network call is made anywhere in this file (no Dhan connectivity
# check, no WebSocket, no order API).
from __future__ import annotations

import base64
import io
import json
import logging
from datetime import UTC, datetime, timedelta

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from intraday.application.services.provider_settings import DhanSettingsService
from intraday.application.services.token_lifecycle import TokenLifecycleState
from intraday.infrastructure.persistence.management.commands.provision_dhan_credentials import (
    DHAN_ACCESS_TOKEN_ENV_VAR,
    DHAN_CLIENT_ID_ENV_VAR,
)
from intraday.infrastructure.persistence.provider_settings_repositories import (
    DjangoDhanCredentialRepository,
)
from tests.postgres_utils import requires_postgres


def _synthetic_jwt(*, exp: datetime | None, marker: str) -> str:
    """A clearly synthetic, self-authored JWT-shaped string -- dummy
    header/signature segments, a payload we construct ourselves. Never
    derived from, or resembling, any real credential. `marker` makes
    the token uniquely identifiable in leakage-detection assertions
    without it being (or looking like) a real secret."""
    header = base64.urlsafe_b64encode(b'{"alg":"HS512","typ":"JWT"}').rstrip(b"=").decode()
    claims: dict[str, object] = {"synthetic_marker": marker}
    if exp is not None:
        claims["exp"] = exp.timestamp()
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"{header}.{payload}.synthetic-fake-signature-cp6460-{marker}"


FUTURE_TOKEN_A = _synthetic_jwt(exp=datetime.now(tz=UTC) + timedelta(hours=10), marker="cp6460-A")
FUTURE_TOKEN_B = _synthetic_jwt(exp=datetime.now(tz=UTC) + timedelta(hours=20), marker="cp6460-B")
EXPIRED_TOKEN = _synthetic_jwt(exp=datetime.now(tz=UTC) - timedelta(hours=3), marker="cp6460-EXP")
MALFORMED_TOKEN = "not-a-jwt-shaped-value-cp6460"  # noqa: S105

ALL_SYNTHETIC_TOKENS = (FUTURE_TOKEN_A, FUTURE_TOKEN_B, EXPIRED_TOKEN, MALFORMED_TOKEN)


def _run_provision_command() -> tuple[str, str]:
    """Invokes the real management command exactly as an operator's
    shell would (`python manage.py provision_dhan_credentials`),
    capturing stdout/stderr as text for leakage assertions -- never
    calling the underlying service function directly, so this proves
    the actual operator-facing entry point."""
    out, err = io.StringIO(), io.StringIO()
    call_command("provision_dhan_credentials", stdout=out, stderr=err)
    return out.getvalue(), err.getvalue()


def _fresh_view():
    return DhanSettingsService(repository=DjangoDhanCredentialRepository()).get_display()


def _assert_token_absent(haystack: str) -> None:
    for token in ALL_SYNTHETIC_TOKENS:
        assert token not in haystack


# --- A/B: environment token available -> provisioning succeeds, fresh service sees VALID ---


@requires_postgres
@pytest.mark.django_db
def test_environment_token_available_provisioning_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(DHAN_CLIENT_ID_ENV_VAR, "9990000099")
    monkeypatch.setenv(DHAN_ACCESS_TOKEN_ENV_VAR, FUTURE_TOKEN_A)

    out, err = _run_provision_command()

    assert "success=True" in out
    assert err == ""


@requires_postgres
@pytest.mark.django_db
def test_fresh_database_service_sees_valid_after_provisioning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DHAN_CLIENT_ID_ENV_VAR, "9990000099")
    monkeypatch.setenv(DHAN_ACCESS_TOKEN_ENV_VAR, FUTURE_TOKEN_A)

    _run_provision_command()

    view = _fresh_view()  # brand-new service+repository instance, no shared state
    assert view.access_token_configured is True
    assert view.token_state == TokenLifecycleState.VALID
    assert view.token_expires_at is not None


# --- C: expiry propagates ---------------------------------------------------


@requires_postgres
@pytest.mark.django_db
def test_expiry_propagates_through_provisioning(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(DHAN_ACCESS_TOKEN_ENV_VAR, FUTURE_TOKEN_A)
    _run_provision_command()
    first_expiry = _fresh_view().token_expires_at

    monkeypatch.setenv(DHAN_ACCESS_TOKEN_ENV_VAR, FUTURE_TOKEN_B)
    _run_provision_command()
    second_expiry = _fresh_view().token_expires_at

    assert first_expiry is not None
    assert second_expiry is not None
    assert second_expiry > first_expiry


# --- D: environment source metadata is reported safely ---------------------


@requires_postgres
@pytest.mark.django_db
def test_environment_source_metadata_reported_in_command_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DHAN_ACCESS_TOKEN_ENV_VAR, FUTURE_TOKEN_A)

    out, _ = _run_provision_command()

    assert "source=ENVIRONMENT_PROVISION" in out
    assert "source=DATABASE" not in out


# --- E: missing environment token -> clear failure --------------------------


@requires_postgres
@pytest.mark.django_db
def test_missing_environment_token_fails_clearly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(DHAN_ACCESS_TOKEN_ENV_VAR, raising=False)
    monkeypatch.delenv(DHAN_CLIENT_ID_ENV_VAR, raising=False)

    with pytest.raises(CommandError):
        call_command("provision_dhan_credentials", stdout=io.StringIO(), stderr=io.StringIO())

    # Nothing was written -- database remains UNCONFIGURED.
    view = _fresh_view()
    assert view.access_token_configured is False


# --- F: malformed environment token -> lifecycle state remains honest ------


@requires_postgres
@pytest.mark.django_db
def test_malformed_environment_token_reports_malformed_not_guessed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DHAN_ACCESS_TOKEN_ENV_VAR, MALFORMED_TOKEN)

    _run_provision_command()

    view = _fresh_view()
    assert view.access_token_configured is True
    assert view.token_state == TokenLifecycleState.MALFORMED
    assert view.token_expires_at is None


# --- G: expired environment token -> lifecycle state remains EXPIRED -------


@requires_postgres
@pytest.mark.django_db
def test_expired_environment_token_reports_expired_not_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DHAN_ACCESS_TOKEN_ENV_VAR, EXPIRED_TOKEN)

    _run_provision_command()

    view = _fresh_view()
    assert view.access_token_configured is True
    assert view.token_state == TokenLifecycleState.EXPIRED
    assert view.token_expires_at is not None


# --- H: explicit invocation is required -------------------------------------


@requires_postgres
@pytest.mark.django_db
def test_provisioning_requires_explicit_command_invocation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Merely setting the environment variable does nothing on its own --
    the database is only touched by actually calling the command."""
    monkeypatch.setenv(DHAN_ACCESS_TOKEN_ENV_VAR, FUTURE_TOKEN_A)

    # `access_token_configured` is True here already because the existing,
    # UNMODIFIED precedence rule reports ENVIRONMENT as a configured
    # source too (see provider_settings.py's `_resolve()`) -- so the real
    # proof that the DATABASE itself was untouched is the repository's
    # own `has_access_token` flag, which reflects the DB row directly.
    record_before = DjangoDhanCredentialRepository().get()
    assert record_before.has_access_token is False

    # No command invocation here -- setting the env var alone must be a no-op.
    record_still_before = DjangoDhanCredentialRepository().get()
    assert record_still_before.has_access_token is False

    _run_provision_command()
    record_after = DjangoDhanCredentialRepository().get()
    assert record_after.has_access_token is True


# --- I: startup does NOT overwrite DB ---------------------------------------


@requires_postgres
@pytest.mark.django_db
def test_importing_command_module_does_not_touch_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """Merely importing/loading the command module (what Django's own
    app startup / command discovery does) must never itself provision
    anything -- only an explicit `call_command(...)` may."""
    monkeypatch.setenv(DHAN_ACCESS_TOKEN_ENV_VAR, FUTURE_TOKEN_A)

    import importlib

    import intraday.infrastructure.persistence.management.commands.provision_dhan_credentials as mod

    importlib.reload(mod)

    record = DjangoDhanCredentialRepository().get()
    assert record.has_access_token is False


# --- J: normal runtime still reads DATABASE afterward -----------------------


@requires_postgres
@pytest.mark.django_db
def test_runtime_precedence_still_prefers_database_after_provisioning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DHAN_ACCESS_TOKEN_ENV_VAR, FUTURE_TOKEN_A)
    _run_provision_command()

    # Now the environment variable changes again (simulating a later
    # .env edit that is NOT re-provisioned) -- normal runtime reads must
    # continue to prefer the DATABASE value, unchanged, per the existing,
    # documented, unmodified precedence rule in provider_settings.py.
    monkeypatch.setenv(DHAN_ACCESS_TOKEN_ENV_VAR, FUTURE_TOKEN_B)

    view = _fresh_view()
    assert view.access_token_source == "DATABASE"  # noqa: S105 - source label, not a secret
    stored = DjangoDhanCredentialRepository().get_decrypted_access_token()
    assert stored == FUTURE_TOKEN_A  # NOT token B -- env change alone never wrote through


# --- K/L: provisioning makes no network / order calls -----------------------


@requires_postgres
@pytest.mark.django_db
def test_provisioning_never_calls_dhan_connectivity_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DHAN_ACCESS_TOKEN_ENV_VAR, FUTURE_TOKEN_A)

    called = {"connectivity": False}

    def _fail_if_called(*args: object, **kwargs: object) -> None:
        called["connectivity"] = True
        raise AssertionError("provisioning must never call Dhan connectivity")

    monkeypatch.setattr(
        "intraday.infrastructure.brokers.dhan.client.check_dhan_connectivity",
        _fail_if_called,
    )

    _run_provision_command()

    assert called["connectivity"] is False


@requires_postgres
@pytest.mark.django_db
def test_provisioning_command_module_imports_no_order_placement_code() -> None:
    """Static/mechanical check: the command module's own source never
    references any order-placement symbol/module."""
    import inspect

    import intraday.infrastructure.persistence.management.commands.provision_dhan_credentials as mod

    source = inspect.getsource(mod)
    for forbidden in ("place_order", "PaperBroker", "OrderIntent", "trading_engine"):
        assert forbidden not in source


# --- M/N: API/read responses and logs never contain token ------------------


@requires_postgres
@pytest.mark.django_db
def test_command_stdout_never_contains_token_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(DHAN_ACCESS_TOKEN_ENV_VAR, FUTURE_TOKEN_A)

    out, err = _run_provision_command()

    _assert_token_absent(out)
    _assert_token_absent(err)


@requires_postgres
@pytest.mark.django_db
def test_fresh_service_display_view_never_contains_token_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(DHAN_ACCESS_TOKEN_ENV_VAR, FUTURE_TOKEN_A)
    _run_provision_command()

    view = _fresh_view()
    _assert_token_absent(repr(view))
    _assert_token_absent(str(view))


@requires_postgres
@pytest.mark.django_db
def test_command_logs_never_contain_token_text(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv(DHAN_ACCESS_TOKEN_ENV_VAR, FUTURE_TOKEN_A)

    with caplog.at_level(logging.DEBUG):
        _run_provision_command()

    _assert_token_absent(caplog.text)


@requires_postgres
@pytest.mark.django_db
def test_command_error_message_never_contains_token_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even a CommandError raised on a bad/missing configuration must
    never echo back any token text (there is none here, but this proves
    the exception path is safe against future changes too)."""
    monkeypatch.delenv(DHAN_ACCESS_TOKEN_ENV_VAR, raising=False)

    with pytest.raises(CommandError) as exc_info:
        call_command("provision_dhan_credentials", stdout=io.StringIO(), stderr=io.StringIO())

    _assert_token_absent(str(exc_info.value))


# --- O: BacktestTrustLevel unchanged -----------------------------------------


def test_backtest_trust_level_poc_unchanged() -> None:
    from intraday.research.backtesting.contracts import BacktestTrustLevel

    assert BacktestTrustLevel.POC.value == "POC"


# --- Cross-instance proof (§9 of the directive) -----------------------------


@requires_postgres
@pytest.mark.django_db
def test_cross_instance_proof_two_sequential_provisions_both_visible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The single most important test: provision token A, a FRESH
    service instance sees A/expiry-A; provision token B, a FRESH
    service instance sees B/expiry-B. Proves the explicit provisioning
    path genuinely updates the authoritative database credential, not
    merely an in-memory echo."""
    monkeypatch.setenv(DHAN_ACCESS_TOKEN_ENV_VAR, FUTURE_TOKEN_A)
    _run_provision_command()
    view_a = _fresh_view()
    stored_a = DjangoDhanCredentialRepository().get_decrypted_access_token()
    assert stored_a == FUTURE_TOKEN_A
    assert view_a.token_state == TokenLifecycleState.VALID

    monkeypatch.setenv(DHAN_ACCESS_TOKEN_ENV_VAR, FUTURE_TOKEN_B)
    _run_provision_command()
    view_b = _fresh_view()
    stored_b = DjangoDhanCredentialRepository().get_decrypted_access_token()
    assert stored_b == FUTURE_TOKEN_B
    assert stored_b != stored_a
    assert view_b.token_state == TokenLifecycleState.VALID
    assert view_b.token_expires_at != view_a.token_expires_at


# --- Runtime precedence test (§10 of the directive) -------------------------


@requires_postgres
@pytest.mark.django_db
def test_database_precedence_over_environment_before_any_provisioning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Proves DB > environment for normal runtime reads, using the
    existing, UNMODIFIED `_resolve()` precedence rule -- seeded here via
    a direct repository save (simulating a prior Settings-API save),
    never via this checkpoint's new provisioning command, to isolate
    "existing precedence" from "new provisioning" as two separate
    claims."""
    DjangoDhanCredentialRepository().save(
        client_id="8880000001",
        access_token=FUTURE_TOKEN_A,
        enabled=True,
        actor="test-seed",
        actor_user_id=0,
        request_id="test-seed-request",
    )
    monkeypatch.setenv(DHAN_ACCESS_TOKEN_ENV_VAR, FUTURE_TOKEN_B)

    view = _fresh_view()
    assert view.access_token_source == "DATABASE"  # noqa: S105 - source label, not a secret
    stored = DjangoDhanCredentialRepository().get_decrypted_access_token()
    assert stored == FUTURE_TOKEN_A
