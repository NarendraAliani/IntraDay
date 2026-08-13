# File: src/intraday/infrastructure/api/authentication.py
#
# Checkpoint 17.2: fixes the authentication/authorization status-code
# contract. Root cause (found via real end-to-end HTTP testing at
# Checkpoint 17.1, not visible from either side's own unit tests in
# isolation): DRF's stock `rest_framework.authentication.
# SessionAuthentication.authenticate_header()` deliberately returns
# `None` - this is documented DRF behavior whose purpose is to make an
# unauthenticated request return 403 instead of 401 specifically to stop
# a *browser* from popping its native HTTP Basic-Auth dialog when a
# `WWW-Authenticate` header is present on a top-level page navigation.
#
# That concern does not apply here: every consumer of this API is a JSON
# fetch() call from the SPA (see frontend/src/common/api/client.ts) or a
# test client - never a full-page browser navigation - so there is no
# native browser auth dialog to protect against. Meanwhile this project's
# frontend contract (`AuthContext`'s `setSessionExpiredHandler`,
# Checkpoint 11) explicitly relies on a real 401 to distinguish "you are
# not authenticated" (session expired/absent - drop to the login screen)
# from "you are authenticated but not authorized" (403 from
# `IsConfigurationOperator` - stay on the current screen, show the
# error). DRF's default downgrade-to-403 behavior silently broke that
# distinction: both cases returned 403, and the frontend's 401-only
# handler could never fire for a real expired session.
#
# Fix: supply a non-`None` `authenticate_header()` so
# `APIView.handle_exception()` (DRF's own logic - see
# `rest_framework.views.APIView.handle_exception`) leaves an
# unauthenticated request's `NotAuthenticated` exception at its natural
# 401 status instead of downgrading it. This is the SMALLEST correct
# fix - it changes nothing about session/cookie/CSRF behavior (still
# exactly Django's `SessionAuthentication`, only `authenticate_header`
# differs), and does not touch `IsConfigurationOperator` or any
# authorization logic at all: an authenticated-but-forbidden request
# still reaches `PermissionDenied` (403) via
# `APIView.permission_denied()`'s own `else` branch (see that method's
# source - the 401-vs-403 choice happens BEFORE authorization is even
# evaluated, driven entirely by whether `request.successful_authenticator`
# is set, which is untouched by this class).
from __future__ import annotations

from typing import Any

from django.conf import settings
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from rest_framework.authentication import SessionAuthentication
from rest_framework.request import Request


class Http401SessionAuthentication(SessionAuthentication):
    """Identical to DRF's `SessionAuthentication` in every respect except
    `authenticate_header()` - see module docstring for the full
    rationale. Session cookie handling, CSRF enforcement
    (`enforce_csrf()`), and the actual authentication logic
    (`authenticate()`) are all inherited unchanged."""

    def authenticate_header(self, request: Request) -> str:
        return "Session"


class Http401SessionAuthenticationScheme(OpenApiAuthenticationExtension):  # type: ignore[no-untyped-call]
    """drf-spectacular does not recognize custom `SessionAuthentication`
    subclasses automatically (only the built-in class name is matched -
    `drf_spectacular.authentication.SessionScheme`, which has no
    `match_subclasses`). Without this registration, `manage.py
    spectacular --fail-on-warn` fails on an "could not resolve
    authenticator" warning for every endpoint - this extension supplies
    the identical `cookieAuth` security-scheme definition the stock
    class would have produced, since authentication itself is byte-for-
    byte unchanged (only the HTTP status code on failure differs, which
    is not part of the OpenAPI security-scheme description)."""

    target_class = "intraday.infrastructure.api.authentication.Http401SessionAuthentication"
    name = "cookieAuth"
    priority = -1

    def get_security_definition(self, auto_schema: Any) -> dict[str, str]:
        return {
            "type": "apiKey",
            "in": "cookie",
            "name": settings.SESSION_COOKIE_NAME,
        }
