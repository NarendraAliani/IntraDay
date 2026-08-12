# File: src/intraday/infrastructure/api/errors.py
#
# Maps application-level service exceptions to stable, machine-readable
# HTTP error responses (Checkpoint 8 §10). The ONLY place in the
# codebase that translates `ResourceNotFoundError` /
# `InvalidActivationRequestError` (application/services/errors.py) or
# `DuplicateVersionError` (application/repositories) into an HTTP status
# code + `ApiErrorSerializer` body. Never leaks a Django exception, SQL
# error, stack trace, or table name — any unexpected exception is caught
# by `handle_unexpected` and rendered as a generic, safe 500 body while
# the real exception is logged via structlog (server-side only).
from __future__ import annotations

import structlog
from rest_framework import status
from rest_framework.response import Response

from intraday.application.repositories import DuplicateVersionError
from intraday.application.services.errors import (
    InvalidActivationRequestError,
    ResourceNotFoundError,
)

logger = structlog.get_logger(__name__)


def _error_response(*, status_code: int, error_code: str, message: str) -> Response:
    # Plain dict, not an ApiErrorSerializer instance — the serializer
    # exists to declare the OpenAPI response shape (see
    # infrastructure/api/*_views.py's @extend_schema decorators), the
    # same pattern established at Checkpoint 4's health.py.
    return Response({"error_code": error_code, "message": message}, status=status_code)


def not_found(exc: ResourceNotFoundError) -> Response:
    return _error_response(
        status_code=status.HTTP_404_NOT_FOUND, error_code="not_found", message=str(exc)
    )


def invalid_activation(exc: InvalidActivationRequestError) -> Response:
    return _error_response(
        status_code=status.HTTP_404_NOT_FOUND,
        error_code="invalid_activation",
        message=str(exc),
    )


def duplicate_version(exc: DuplicateVersionError) -> Response:
    return _error_response(
        status_code=status.HTTP_409_CONFLICT, error_code="duplicate_version", message=str(exc)
    )


def unexpected(exc: Exception) -> Response:
    """Catch-all for anything not explicitly handled above. Logs the real
    exception server-side (structured, no secrets) and returns a generic,
    safe message — never the exception's own text, which could leak
    infrastructure details (Checkpoint 8 §10, §21)."""
    logger.error("api.unexpected_error", error=repr(exc))
    return _error_response(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        error_code="internal_error",
        message="An unexpected error occurred.",
    )
