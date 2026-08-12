# File: src/intraday/application/contracts/auth.py
#
# DRF serializers for the Checkpoint 11 authentication API
# (/api/v1/auth/). Schema-only, same pattern as risk.py/universe.py/
# strategy.py: views return plain dicts (Response(body)), these
# serializers exist solely to declare the OpenAPI shape via
# `@extend_schema`.
from __future__ import annotations

from rest_framework import serializers


class LoginRequestSerializer(serializers.Serializer[None]):
    """Request body for `POST /api/v1/auth/login/`. `password` is
    `write_only` purely for schema documentation purposes - the view
    never echoes any request field back in a response body regardless."""

    username = serializers.CharField()
    password = serializers.CharField(write_only=True, style={"input_type": "password"})


class CurrentUserResponseSerializer(serializers.Serializer[None]):
    """Response shape for `GET /api/v1/auth/session/` and the successful
    result of `POST /api/v1/auth/login/`. Never includes a password,
    session key, or any other credential material - only what the
    frontend needs to answer "am I logged in, as whom, and what can I
    do."""

    is_authenticated = serializers.BooleanField()
    username = serializers.CharField(allow_null=True)
    capabilities = serializers.ListField(child=serializers.CharField())
