# tests/unit/infrastructure/api/test_auth_api.py
#
# Checkpoint 11: authentication/authorization test matrix, run through
# real Django/DRF integration (Django's test `Client` against the actual
# URLconf), not mocks — the same pattern as test_risk_api.py's "full
# vertical slice" tests. Gated by `requires_postgres` since it needs the
# real Django auth tables (User, Group, Session).
from __future__ import annotations

import pytest
from django.contrib.auth.models import Group, User
from django.test import Client

from intraday.infrastructure.api.permissions import CONFIGURATION_OPERATOR_GROUP
from tests.postgres_utils import requires_postgres

USERNAME = "reader"  # noqa: S105 - test fixture username, not a secret
PASSWORD = "correct-horse-battery-staple"  # noqa: S105 - test-only fixture credential
OPERATOR_USERNAME = "operator"  # noqa: S105 - test fixture username, not a secret


def _create_user(username: str = USERNAME, password: str = PASSWORD) -> User:
    return User.objects.create_user(username=username, password=password)


def _create_operator(username: str = OPERATOR_USERNAME, password: str = PASSWORD) -> User:
    user = User.objects.create_user(username=username, password=password)
    group, _ = Group.objects.get_or_create(name=CONFIGURATION_OPERATOR_GROUP)
    user.groups.add(group)
    return user


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.django_db
def test_anonymous_current_user_request() -> None:
    client = Client()

    response = client.get("/api/v1/auth/session/")

    assert response.status_code == 200
    body = response.json()
    assert body["is_authenticated"] is False
    assert body["username"] is None
    assert body["capabilities"] == []


@requires_postgres
@pytest.mark.django_db
def test_successful_login() -> None:
    _create_user()
    client = Client()

    response = client.post("/api/v1/auth/login/", {"username": USERNAME, "password": PASSWORD})

    assert response.status_code == 200
    body = response.json()
    assert body["is_authenticated"] is True
    assert body["username"] == USERNAME
    assert body["capabilities"] == ["configuration.read"]


@requires_postgres
@pytest.mark.django_db
def test_login_invalid_password() -> None:
    _create_user()
    client = Client()

    response = client.post("/api/v1/auth/login/", {"username": USERNAME, "password": "wrong"})

    assert response.status_code == 401
    assert response.json()["error_code"] == "invalid_credentials"


@requires_postgres
@pytest.mark.django_db
def test_login_unknown_user_returns_identical_response_to_wrong_password() -> None:
    _create_user()
    client = Client()

    unknown = client.post(
        "/api/v1/auth/login/", {"username": "does-not-exist", "password": PASSWORD}
    )
    wrong_password = client.post("/api/v1/auth/login/", {"username": USERNAME, "password": "wrong"})

    # No user-enumeration leakage: identical status and body regardless of
    # which failure mode occurred.
    assert unknown.status_code == wrong_password.status_code == 401
    assert unknown.json() == wrong_password.json()


@requires_postgres
@pytest.mark.django_db
def test_logout() -> None:
    _create_user()
    client = Client()
    client.post("/api/v1/auth/login/", {"username": USERNAME, "password": PASSWORD})

    response = client.post("/api/v1/auth/logout/")

    assert response.status_code == 200
    assert response.json()["is_authenticated"] is False


@requires_postgres
@pytest.mark.django_db
def test_session_invalidated_after_logout() -> None:
    _create_user()
    client = Client()
    client.post("/api/v1/auth/login/", {"username": USERNAME, "password": PASSWORD})
    client.post("/api/v1/auth/logout/")

    # The same client (same cookies) can no longer read a protected resource.
    response = client.get("/api/v1/config/risk/default/")

    assert response.status_code in (401, 403)


@requires_postgres
@pytest.mark.django_db
def test_current_user_after_logout_reports_anonymous() -> None:
    _create_user()
    client = Client()
    client.post("/api/v1/auth/login/", {"username": USERNAME, "password": PASSWORD})
    client.post("/api/v1/auth/logout/")

    response = client.get("/api/v1/auth/session/")

    assert response.json()["is_authenticated"] is False


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.django_db
def test_anonymous_configuration_read_rejected() -> None:
    """Checkpoint 17.2: tightened from `in (401, 403)` to exactly 401 now
    that `Http401SessionAuthentication` (infrastructure/api/authentication.py)
    fixes DRF's default 403-downgrade for unauthenticated requests - see
    `test_authentication_vs_authorization_status_codes_are_distinct`
    below for the full contract this enforces."""
    client = Client()

    response = client.get("/api/v1/config/risk/default/")

    assert response.status_code == 401


@requires_postgres
@pytest.mark.django_db
def test_anonymous_activation_attempt_rejected_with_401_not_403() -> None:
    """An anonymous (no session at all) activation attempt is an
    AUTHENTICATION failure, not an authorization one - must be 401, the
    same status a real expired/invalidated session produces, so the
    frontend's session-expiry handler (401-only, by design - see
    frontend/src/common/api/client.ts) can react to it."""
    client = Client()

    response = client.post("/api/v1/config/risk/default/v1/activate/")

    assert response.status_code == 401


@requires_postgres
@pytest.mark.django_db
def test_authenticated_read_user_can_read() -> None:
    _create_user()
    client = Client()
    client.post("/api/v1/auth/login/", {"username": USERNAME, "password": PASSWORD})

    response = client.get("/api/v1/config/risk/default/")

    assert response.status_code == 200


@requires_postgres
@pytest.mark.django_db
def test_authenticated_read_user_cannot_activate() -> None:
    _create_user()
    client = Client()
    client.post("/api/v1/auth/login/", {"username": USERNAME, "password": PASSWORD})

    response = client.post("/api/v1/config/risk/default/v1/activate/")

    assert response.status_code == 403


@requires_postgres
@pytest.mark.django_db
def test_configuration_operator_can_activate_permission_layer() -> None:
    """Proves the *permission* layer allows an operator through (a 404 here
    means "no such version" reached the application layer, which is only
    possible once the permission check itself has already passed - a
    403 would mean the permission check rejected it, which this test
    rules out)."""
    _create_operator()
    client = Client()
    client.post("/api/v1/auth/login/", {"username": OPERATOR_USERNAME, "password": PASSWORD})

    response = client.post("/api/v1/config/risk/default/v1/activate/")

    assert response.status_code != 403


@requires_postgres
@pytest.mark.django_db
def test_unauthorized_activation_returns_safe_response() -> None:
    _create_user()
    client = Client()
    client.post("/api/v1/auth/login/", {"username": USERNAME, "password": PASSWORD})

    response = client.post("/api/v1/config/risk/default/v1/activate/")

    assert response.status_code == 403
    serialized = str(response.content).lower()
    for forbidden in ("traceback", "django.db", "select ", "integrityerror"):
        assert forbidden not in serialized


@requires_postgres
@pytest.mark.django_db
def test_permission_cannot_be_bypassed_by_direct_api_request() -> None:
    """A non-operator cannot self-elevate by any means available through
    the public API surface - no request header, query parameter, or body
    field grants the `configuration.activate` capability. Only real Group
    membership (or `is_superuser`), checked server-side, does."""
    _create_user()
    client = Client()
    client.post("/api/v1/auth/login/", {"username": USERNAME, "password": PASSWORD})

    response = client.post(
        "/api/v1/config/risk/default/v1/activate/",
        {"is_operator": "true", "role": "admin", "capabilities": "configuration.activate"},
        HTTP_X_ADMIN="true",
    )

    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.django_db
def test_csrf_protects_state_changing_requests_once_authenticated() -> None:
    """Checkpoint 17.2: this test's own prior comment ("Login itself is
    exempt from CSRF enforcement") was stale and factually wrong -
    `login_view.csrf_exempt = False` (Checkpoint 12 re-enabled real CSRF
    enforcement on login specifically). Login requires a CSRF cookie
    fetched first, exactly like every other login test in this file
    (`test_legitimate_login_succeeds_with_a_valid_csrf_token`) - fixed to
    match the real, documented flow instead of an incorrect assumption."""
    client = Client(enforce_csrf_checks=True)
    _create_operator()
    csrf_token = client.get("/api/v1/auth/session/").cookies["csrftoken"].value
    login_response = client.post(
        "/api/v1/auth/login/",
        {"username": OPERATOR_USERNAME, "password": PASSWORD},
        HTTP_X_CSRFTOKEN=csrf_token,
    )
    assert login_response.status_code == 200

    # Now session-authenticated: a state-changing POST without the CSRF
    # header must be rejected.
    unprotected = client.post("/api/v1/config/risk/default/v1/activate/")
    assert unprotected.status_code == 403

    # The same request succeeds once given a valid CSRF token.
    session_response = client.get("/api/v1/auth/session/")
    csrf_token = session_response.cookies["csrftoken"].value
    protected = client.post("/api/v1/config/risk/default/v1/activate/", HTTP_X_CSRFTOKEN=csrf_token)
    assert protected.status_code != 403


@requires_postgres
@pytest.mark.django_db
def test_login_response_never_contains_password() -> None:
    _create_user()
    client = Client()

    response = client.post("/api/v1/auth/login/", {"username": USERNAME, "password": PASSWORD})

    assert PASSWORD not in str(response.content)
    assert "password" not in response.json()


@requires_postgres
@pytest.mark.django_db
def test_login_failure_never_leaks_internal_details() -> None:
    client = Client()

    response = client.post("/api/v1/auth/login/", {"username": "anyone", "password": "anything"})

    serialized = str(response.content).lower()
    for forbidden in ("traceback", "django.db", "select ", "integrityerror", "operationalerror"):
        assert forbidden not in serialized


# ---------------------------------------------------------------------------
# Login-CSRF (Checkpoint 12 - closes the gap Checkpoint 11 deliberately
# deferred: DRF's default CSRF exemption for API views only enforces CSRF
# once a session user is already resolved, so a POST /login/ was never
# checked. `login_view.csrf_exempt = False` (auth_views.py) re-enables
# Django's real CsrfViewMiddleware for this one view.
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.django_db
def test_login_is_rejected_without_a_csrf_token() -> None:
    """A cross-site login attempt - a POST with no CSRF cookie/header
    pair at all - must be rejected by Django's real CSRF middleware, not
    merely "would have failed authentication anyway". This is checked
    BEFORE `authenticate()` runs (middleware runs ahead of the view), so
    it fails the same way regardless of whether the submitted credentials
    are valid."""
    _create_user()
    client = Client(enforce_csrf_checks=True)

    response = client.post("/api/v1/auth/login/", {"username": USERNAME, "password": PASSWORD})

    assert response.status_code == 403


@requires_postgres
@pytest.mark.django_db
def test_legitimate_login_succeeds_with_a_valid_csrf_token() -> None:
    """The real, intended flow: fetch the CSRF cookie first (exactly what
    the frontend's AuthProvider does on every page load via
    `GET /api/v1/auth/session/`), then submit login with the matching
    `X-CSRFToken` header - succeeds even under strict CSRF enforcement."""
    _create_user()
    client = Client(enforce_csrf_checks=True)
    session_response = client.get("/api/v1/auth/session/")
    csrf_token = session_response.cookies["csrftoken"].value

    response = client.post(
        "/api/v1/auth/login/",
        {"username": USERNAME, "password": PASSWORD},
        HTTP_X_CSRFTOKEN=csrf_token,
    )

    assert response.status_code == 200
    assert response.json()["is_authenticated"] is True


# ---------------------------------------------------------------------------
# Authentication vs. authorization status-code contract (Checkpoint 17.2)
#
# Root cause of the Checkpoint 17.1 finding: DRF's stock
# `SessionAuthentication.authenticate_header()` returns `None`, which
# makes `APIView.handle_exception()` downgrade an unauthenticated
# request's `NotAuthenticated` (401) to 403 - indistinguishable from a
# genuine `PermissionDenied` (also 403). This silently broke the
# frontend's session-expiry contract (`setSessionExpiredHandler` fires
# only on 401). Fixed by `Http401SessionAuthentication`
# (infrastructure/api/authentication.py). These tests prove the fix
# without weakening authorization: a real permission denial must remain
# 403, never become a false session-expiry signal.
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.django_db
def test_authentication_vs_authorization_status_codes_are_distinct() -> None:
    """The single test that proves the whole point of the fix: an
    AUTHENTICATION failure (no session at all) and an AUTHORIZATION
    failure (real session, insufficient capability) must produce
    DIFFERENT status codes - 401 vs 403 - never the same one. Before
    Checkpoint 17.2 both cases returned 403, making them
    indistinguishable to any client."""
    anonymous_client = Client()
    unauthenticated_response = anonymous_client.post("/api/v1/config/risk/default/v1/activate/")
    assert unauthenticated_response.status_code == 401

    _create_user()
    reader_client = Client()
    reader_client.post("/api/v1/auth/login/", {"username": USERNAME, "password": PASSWORD})
    unauthorized_response = reader_client.post("/api/v1/config/risk/default/v1/activate/")
    assert unauthorized_response.status_code == 403

    assert unauthenticated_response.status_code != unauthorized_response.status_code


@requires_postgres
@pytest.mark.django_db
def test_session_expiry_produces_401_not_403() -> None:
    """Simulates a real expired/invalidated session (the exact scenario
    `setSessionExpiredHandler` exists for): a previously-valid,
    authenticated session whose server-side Session row no longer
    exists (evicted/expired) must still produce 401 on the next
    protected request - not 403, which the frontend would not treat as
    a session-expiry signal."""
    from django.contrib.sessions.models import Session

    _create_user()
    client = Client()
    client.post("/api/v1/auth/login/", {"username": USERNAME, "password": PASSWORD})

    # Confirm the session really is authenticated first.
    assert client.get("/api/v1/auth/session/").json()["is_authenticated"] is True

    # Simulate expiry: delete every server-side session row directly,
    # exactly what happens when Django's session-cleanup or a natural
    # SESSION_COOKIE_AGE expiry removes the row but the browser still
    # holds the (now-invalid) cookie.
    Session.objects.all().delete()

    response = client.get("/api/v1/config/risk/default/")

    assert response.status_code == 401


@requires_postgres
@pytest.mark.django_db
def test_operator_permission_denial_still_returns_403_after_the_fix() -> None:
    """Regression guard for the fix itself: a real, authenticated,
    insufficiently-privileged request must NOT be affected by the 401
    fix - it must remain exactly 403, never accidentally become 401
    (which would incorrectly look like a session-expiry event to the
    frontend and log the user out for what is actually a permission
    problem, not an authentication one)."""
    _create_user()
    client = Client()
    client.post("/api/v1/auth/login/", {"username": USERNAME, "password": PASSWORD})

    response = client.post("/api/v1/config/risk/default/v1/activate/")

    assert response.status_code == 403
    assert response.status_code != 401
