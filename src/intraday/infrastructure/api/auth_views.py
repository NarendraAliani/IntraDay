# File: src/intraday/infrastructure/api/auth_views.py
#
# DRF views for the Checkpoint 11 authentication API. Uses Django's
# built-in `django.contrib.auth` (User model, `authenticate()`,
# `login()`, `logout()`) directly - no custom user model, no bespoke
# password handling, no repository/service indirection. Authentication
# is inherently a framework concern here, unlike the business
# configuration resources (risk/universe/strategy), which is why this
# module talks to `django.contrib.auth` directly instead of going through
# an application/services use case.
from __future__ import annotations

from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import AbstractBaseUser, AnonymousUser
from django.middleware.csrf import get_token
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from intraday.application.contracts.auth import (
    CurrentUserResponseSerializer,
    LoginRequestSerializer,
)
from intraday.application.contracts.errors import ApiErrorSerializer
from intraday.infrastructure.api.errors import invalid_credentials
from intraday.infrastructure.api.permissions import user_capabilities


def _current_user_body(user: AbstractBaseUser | AnonymousUser) -> dict[str, object]:
    return {
        "is_authenticated": bool(user.is_authenticated),
        "username": user.get_username() if user.is_authenticated else None,
        "capabilities": user_capabilities(user),
    }


@extend_schema(
    request=LoginRequestSerializer,
    responses={
        200: CurrentUserResponseSerializer,
        401: OpenApiResponse(ApiErrorSerializer),
        403: OpenApiResponse(ApiErrorSerializer),
    },
)
@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([ScopedRateThrottle])
def login_view(request: Request) -> Response:
    """Authenticates a username/password pair and starts a session.

    Brute-force protection: throttled to 5 requests/minute per client IP
    (`DEFAULT_THROTTLE_RATES["login"]`, settings/base.py) via DRF's
    cache-backed `ScopedRateThrottle` - see this view's `.cls.throttle_scope`
    assignment below (function-based views can't set a class attribute
    inline).

    Login-CSRF protection (Checkpoint 12 - closes the gap Checkpoint 11
    deliberately deferred): DRF's `APIView.as_view()` wraps every view in
    Django's `csrf_exempt()` by default, delegating CSRF enforcement to
    `SessionAuthentication.enforce_csrf()` - which only runs once a
    session user is already resolved, so an anonymous login POST was
    never checked. This view's `.csrf_exempt` attribute is explicitly
    reset to `False` below (see after the function), re-enabling Django's
    real `CsrfViewMiddleware` for this one view - the same, real,
    framework-provided CSRF mechanism used everywhere else, not a
    hand-rolled scheme and never `@csrf_exempt`. This requires no
    frontend change: the frontend already calls `GET
    /api/v1/auth/session/` on load (which sets the `csrftoken` cookie via
    `get_token()`, see `session_view` below) before a user can submit the
    login form, and `client.ts` already attaches `X-CSRFToken` to every
    `POST`, login included.
    """
    serializer = LoginRequestSerializer(data=request.data)
    if not serializer.is_valid():
        return invalid_credentials()

    user = authenticate(
        request,
        username=serializer.validated_data["username"],
        password=serializer.validated_data["password"],
    )
    if user is None or not user.is_active:
        # Same response whether the username doesn't exist, the password
        # is wrong, or the account is inactive - never lets a caller
        # distinguish "no such user" from "wrong password" (Checkpoint 11
        # §17: no user-enumeration leakage).
        return invalid_credentials()

    # `login()` rotates the session key (Django's own session-fixation
    # protection - a new session identifier is issued on every successful
    # authentication, never reusing whatever anonymous session existed
    # before).
    login(request, user)
    return Response(_current_user_body(user))


login_view.cls.throttle_scope = "login"  # type: ignore[attr-defined]
# Re-enable real Django CSRF enforcement for this specific view (see the
# docstring above) - `@api_view`/`APIView.as_view()` set this attribute
# to True by default; flipping it back to False is the documented way to
# opt a single DRF view back into CsrfViewMiddleware's normal check.
login_view.csrf_exempt = False


@extend_schema(request=None, responses={200: CurrentUserResponseSerializer})
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def logout_view(request: Request) -> Response:
    """Ends the current session. Requires an authenticated session (so an
    anonymous POST is rejected by `IsAuthenticated`) and, because the
    caller is session-authenticated, DRF's `SessionAuthentication` enforces
    the CSRF header on this request - see docs/architecture/
    AUTHENTICATION_AUTHORIZATION.md's CSRF section.

    Django's `logout()` flushes the session store entry itself (not just
    clearing the cookie), so the old session id is invalid server-side
    immediately - a leaked/cached cookie from before logout cannot be
    replayed.
    """
    logout(request)
    return Response(_current_user_body(AnonymousUser()))


@extend_schema(responses={200: CurrentUserResponseSerializer})
@api_view(["GET"])
@permission_classes([AllowAny])
def session_view(request: Request) -> Response:
    """Reports the current authentication state. Deliberately returns
    `200` for anonymous callers too (`is_authenticated: false`), not
    `401` - this endpoint's entire purpose is "let the frontend safely
    ask, with no prior assumption," so treating "not logged in" as a
    request failure would force every caller to special-case it.

    Also the frontend's mechanism for obtaining a CSRF cookie before its
    first state-changing request: `get_token(request)` guarantees Django's
    CSRF middleware sets the `csrftoken` cookie on this response, per
    Django's own documented pattern for SPA/AJAX clients that never
    render a `{% csrf_token %}` template tag.
    """
    get_token(request)
    return Response(_current_user_body(request.user))
