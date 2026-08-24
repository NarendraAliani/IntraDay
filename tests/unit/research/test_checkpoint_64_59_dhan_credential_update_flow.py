# tests/unit/research/test_checkpoint_64_59_dhan_credential_update_flow.py
#
# Checkpoint 64.59: proves (or disproves) that the EXISTING Dhan
# credential update path -- Operator -> Settings API/UI ->
# DhanSettingsService.save() -> DjangoDhanCredentialRepository ->
# encrypted_access_token -> database -> DhanSettingsService.get_display()
# -> token lifecycle state -- actually propagates a newly supplied token
# end to end. 64.55/64.56/64.57/64.58 all independently found the stored
# credential's expires_at unchanged; this checkpoint's job is to
# determine, with SYNTHETIC tokens only, whether that is a code defect
# or an operator/environment-side issue.
#
# SECURITY: every token in this file is a synthetic, self-constructed
# JWT-shaped string (base64 header + a JSON payload we author ourselves
# + a fake signature segment). No real Dhan credential, .env value, or
# raw credential file is ever read, referenced, or approximated here.
# No live network call is made -- `evaluate_dhan_token_lifecycle()` is
# pure/local (decodes only the `exp` claim), and `check_dhan_connectivity`
# is never invoked by any test in this file (no `/test/` endpoint call).
from __future__ import annotations

import base64
import json
from datetime import UTC, datetime, timedelta

import pytest
from django.contrib.auth.models import Group, User
from django.test import Client

from intraday.application.services.provider_settings import DhanSettingsService
from intraday.application.services.token_lifecycle import TokenLifecycleState
from intraday.infrastructure.api.permissions import CONFIGURATION_OPERATOR_GROUP
from intraday.infrastructure.persistence.provider_settings_repositories import (
    DjangoDhanCredentialRepository,
)
from tests.postgres_utils import requires_postgres

OPERATOR_USERNAME = "cp6459_operator"  # noqa: S105
PASSWORD = "correct-horse-battery-staple-6459"  # noqa: S105

SAVE_URL = "/api/v1/config/settings/dhan/save/"
GET_URL = "/api/v1/config/settings/dhan/"


def _client_as_operator() -> Client:
    user = User.objects.create_user(username=OPERATOR_USERNAME, password=PASSWORD)
    group, _ = Group.objects.get_or_create(name=CONFIGURATION_OPERATOR_GROUP)
    user.groups.add(group)
    client = Client()
    assert client.login(username=OPERATOR_USERNAME, password=PASSWORD)
    return client


def _synthetic_jwt(*, exp: datetime | None, extra_claims: dict | None = None) -> str:
    """Builds a clearly synthetic, self-authored JWT-shaped string --
    dummy header/signature segments, a payload we construct ourselves.
    Never derived from, or resembling, any real credential."""
    header = base64.urlsafe_b64encode(b'{"alg":"HS512","typ":"JWT"}').rstrip(b"=").decode()
    claims: dict[str, object] = dict(extra_claims or {})
    if exp is not None:
        claims["exp"] = exp.timestamp()
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"{header}.{payload}.synthetic-fake-signature-cp6459"


FUTURE_VALID_TOKEN = _synthetic_jwt(exp=datetime.now(tz=UTC) + timedelta(hours=12))
EXPIRED_TOKEN = _synthetic_jwt(exp=datetime.now(tz=UTC) - timedelta(hours=2))
MALFORMED_TOKEN = "not-a-jwt-shaped-value"  # noqa: S105


# --- A/B/C/D: synthetic VALID token saves and propagates --------------------


@requires_postgres
@pytest.mark.django_db
def test_synthetic_future_expiry_token_saves_successfully_via_real_api() -> None:
    """Item A/C: uses the SAME save path an operator's browser would hit
    (POST .../dhan/save/), not a private/internal shortcut."""
    client = _client_as_operator()

    response = client.post(
        SAVE_URL,
        data={"client_id": "9990000001", "access_token": FUTURE_VALID_TOKEN, "enabled": True},
        content_type="application/json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["access_token_configured"] is True
    assert body["token_state"] == "VALID"  # noqa: S105 - lifecycle state literal, not a secret
    assert body["token_expires_at"] is not None


@requires_postgres
@pytest.mark.django_db
def test_save_then_fresh_service_instance_reports_valid() -> None:
    """Item B/J: proves persistence is NOT merely in-memory state on one
    service object. A brand-new DhanSettingsService, backed by a brand
    new DjangoDhanCredentialRepository, must independently observe the
    saved state by reading the database."""
    client = _client_as_operator()
    client.post(
        SAVE_URL,
        data={"client_id": "9990000001", "access_token": FUTURE_VALID_TOKEN, "enabled": True},
        content_type="application/json",
    )

    # A fresh repository + fresh service -- no object reused from the
    # request/response cycle above.
    fresh_service = DhanSettingsService(repository=DjangoDhanCredentialRepository())
    view = fresh_service.get_display()

    assert view.access_token_configured is True
    assert view.token_state == TokenLifecycleState.VALID
    assert view.token_expires_at is not None
    assert view.token_expires_at > datetime.now(tz=UTC)


@requires_postgres
@pytest.mark.django_db
def test_expiry_timestamp_updates_between_two_distinct_synthetic_tokens() -> None:
    """Item C: proves the expiry moves when a genuinely different token
    is submitted -- ruling out a "save is a no-op that just echoes
    whatever was already there" defect."""
    client = _client_as_operator()

    first_token = _synthetic_jwt(exp=datetime.now(tz=UTC) + timedelta(hours=1, minutes=30))
    client.post(
        SAVE_URL,
        data={"client_id": "9990000001", "access_token": first_token, "enabled": True},
        content_type="application/json",
    )
    first_view = DhanSettingsService(repository=DjangoDhanCredentialRepository()).get_display()

    second_token = _synthetic_jwt(exp=datetime.now(tz=UTC) + timedelta(hours=20))
    client.post(
        SAVE_URL,
        data={"client_id": "9990000001", "access_token": second_token, "enabled": True},
        content_type="application/json",
    )
    second_view = DhanSettingsService(repository=DjangoDhanCredentialRepository()).get_display()

    assert second_view.token_expires_at is not None
    assert first_view.token_expires_at is not None
    assert second_view.token_expires_at > first_view.token_expires_at


# --- E: blank token preserves existing value --------------------------------


@requires_postgres
@pytest.mark.django_db
def test_blank_access_token_preserves_existing_valid_token() -> None:
    """Item E/6: a blank/omitted access_token on a subsequent save must
    leave the previously-saved (VALID) token completely unchanged -- not
    erase it, not downgrade its state."""
    client = _client_as_operator()
    client.post(
        SAVE_URL,
        data={"client_id": "9990000001", "access_token": FUTURE_VALID_TOKEN, "enabled": True},
        content_type="application/json",
    )
    before = DhanSettingsService(repository=DjangoDhanCredentialRepository()).get_display()

    # Second save: blank access_token, only client_id changes.
    response = client.post(
        SAVE_URL,
        data={"client_id": "9990000002", "access_token": "", "enabled": True},
        content_type="application/json",
    )
    assert response.status_code == 200

    after = DhanSettingsService(repository=DjangoDhanCredentialRepository()).get_display()
    assert after.access_token_configured is True
    assert after.token_state == TokenLifecycleState.VALID
    assert after.token_expires_at == before.token_expires_at
    assert DjangoDhanCredentialRepository().get_decrypted_access_token() == FUTURE_VALID_TOKEN


# --- F/G: malformed and expired token behavior match the existing contract --


@requires_postgres
@pytest.mark.django_db
def test_malformed_token_is_saved_and_reported_malformed_not_guessed() -> None:
    """Item F/7: the existing documented contract (token_lifecycle.py) is
    that save is UNCONDITIONAL (any non-blank string is accepted and
    encrypted) -- validity/expiry is a separately-computed READ-time
    concern, never a save-time gate. A malformed value must read back as
    MALFORMED, never silently coerced to VALID or EXPIRED."""
    client = _client_as_operator()

    response = client.post(
        SAVE_URL,
        data={"client_id": "9990000001", "access_token": MALFORMED_TOKEN, "enabled": True},
        content_type="application/json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["access_token_configured"] is True
    assert body["token_state"] == "MALFORMED"  # noqa: S105 - state name, not a password


@requires_postgres
@pytest.mark.django_db
def test_expired_token_is_saved_and_reported_expired_not_rejected() -> None:
    """Item G/7: same unconditional-save contract for an already-expired
    but well-formed token -- the existing design lets an expired token
    be saved (readiness gates block USE of it elsewhere, e.g. Checkpoint
    64.56/64.57's observe-only gate), it does not reject it at save time.
    This matches the documented behavior already covered by
    test_settings_api.py's `..._reports_expired_for_a_real_shaped_...`
    test; this test re-confirms it as part of 64.59's own evidence."""
    client = _client_as_operator()

    response = client.post(
        SAVE_URL,
        data={"client_id": "9990000001", "access_token": EXPIRED_TOKEN, "enabled": True},
        content_type="application/json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["access_token_configured"] is True
    assert body["token_state"] == "EXPIRED"  # noqa: S105 - state name, not a password
    assert body["token_expires_at"] is not None

    # And a fresh service instance must see the SAME expired state --
    # this is the exact scenario 64.55-64.58 observed for the real
    # credential; here we prove the propagation mechanics are sound by
    # reproducing it deliberately with a synthetic token.
    fresh_view = DhanSettingsService(repository=DjangoDhanCredentialRepository()).get_display()
    assert fresh_view.token_state == TokenLifecycleState.EXPIRED


# --- H: API response never contains token text ------------------------------


@requires_postgres
@pytest.mark.django_db
def test_api_response_never_contains_any_synthetic_token_text() -> None:
    """Item H/8: checks the save response, the follow-up GET response,
    and their repr()/str() forms never contain any of the synthetic
    token strings used in this file."""
    client = _client_as_operator()

    save_response = client.post(
        SAVE_URL,
        data={"client_id": "9990000001", "access_token": FUTURE_VALID_TOKEN, "enabled": True},
        content_type="application/json",
    )
    get_response = client.get(GET_URL)

    for token_text in (FUTURE_VALID_TOKEN, EXPIRED_TOKEN, MALFORMED_TOKEN):
        assert token_text not in save_response.content.decode()
        assert token_text not in get_response.content.decode()
        assert token_text not in repr(save_response.json())
        assert token_text not in str(save_response.json())
        assert token_text not in repr(get_response.json())
        assert token_text not in str(get_response.json())

    for body in (save_response.json(), get_response.json()):
        assert "access_token" not in body
        assert set(body.keys()) == {
            "client_id_masked",
            "client_id_source",
            "access_token_configured",
            "access_token_source",
            "enabled",
            "updated_at",
            "updated_by_username",
            "token_state",
            "token_expires_at",
        }


# --- I/J: repository persists encrypted token; new instance sees it ---------


@requires_postgres
@pytest.mark.django_db
def test_repository_persists_encrypted_value_readable_only_via_decrypt() -> None:
    """Item I/9: proves the DATABASE row itself changed (not just an
    in-process cache) by reading the raw encrypted bytes through a
    brand-new repository instance and confirming they decrypt back to
    the synthetic token -- WITHOUT ever inspecting/printing the raw
    encrypted bytes themselves (only using them via the repository's
    own decrypt path, per the directive's "must not inspect the raw
    database token" -- this reads through the documented decrypt API,
    not a raw SQL/ORM field dump)."""
    client = _client_as_operator()
    client.post(
        SAVE_URL,
        data={"client_id": "9990000001", "access_token": FUTURE_VALID_TOKEN, "enabled": True},
        content_type="application/json",
    )

    fresh_repository = DjangoDhanCredentialRepository()
    record = fresh_repository.get()
    assert record.has_access_token is True

    decrypted = fresh_repository.get_decrypted_access_token()
    assert decrypted == FUTURE_VALID_TOKEN


@requires_postgres
@pytest.mark.django_db
def test_new_service_instance_after_save_sees_persisted_state_end_to_end() -> None:
    """Item J: request -> database -> new service instance -> lifecycle
    evaluation, all in one assertion chain, using only get_display()."""
    client = _client_as_operator()
    client.post(
        SAVE_URL,
        data={"client_id": "9990000001", "access_token": FUTURE_VALID_TOKEN, "enabled": True},
        content_type="application/json",
    )

    brand_new_service = DhanSettingsService(repository=DjangoDhanCredentialRepository())
    view = brand_new_service.get_display()

    assert view.token_state == TokenLifecycleState.VALID
    assert view.access_token_configured is True


# --- K: no network call occurs -----------------------------------------------


@requires_postgres
@pytest.mark.django_db
def test_save_and_get_display_never_invoke_dhan_connectivity_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Item K/11: proves save()/get_display() are pure local/DB
    operations -- neither the save endpoint nor the GET endpoint ever
    calls the outbound `check_dhan_connectivity` function. This is the
    mechanism-level guarantee that no live Dhan connection occurs
    anywhere in this checkpoint's test suite."""
    calls: list[object] = []
    monkeypatch.setattr(
        "intraday.infrastructure.api.settings_views.check_dhan_connectivity",
        lambda *a, **k: calls.append((a, k)),
    )

    client = _client_as_operator()
    client.post(
        SAVE_URL,
        data={"client_id": "9990000001", "access_token": FUTURE_VALID_TOKEN, "enabled": True},
        content_type="application/json",
    )
    client.get(GET_URL)

    assert calls == []
