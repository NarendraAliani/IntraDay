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
    client = Client()

    response = client.get("/api/v1/config/risk/default/")

    assert response.status_code in (401, 403)


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
    client = Client(enforce_csrf_checks=True)
    _create_operator()
    # Login itself is exempt from CSRF enforcement (no session user exists
    # yet at authenticate() time - see auth_views.py's login_view
    # docstring / docs/architecture/AUTHENTICATION_AUTHORIZATION.md).
    login_response = client.post(
        "/api/v1/auth/login/", {"username": OPERATOR_USERNAME, "password": PASSWORD}
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
