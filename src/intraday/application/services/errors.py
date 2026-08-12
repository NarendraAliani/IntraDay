# File: src/intraday/application/services/errors.py
#
# Application-level service errors (Checkpoint 8). These are the ONLY
# exception types the API delivery layer (infrastructure/api) needs to
# catch to build a stable error response — no Django exception, SQL
# error, or repository-internal detail crosses this boundary.
from __future__ import annotations


class ResourceNotFoundError(Exception):
    """Raised when a requested configuration id/version does not exist."""


class InvalidActivationRequestError(Exception):
    """Raised when an activation request references a version that does
    not exist for the given configuration id."""
