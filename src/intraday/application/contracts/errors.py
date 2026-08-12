# File: src/intraday/application/contracts/errors.py
#
# Stable, machine-readable API error contract (Checkpoint 8 §10). Every
# error response the configuration API returns uses this exact shape —
# never a raw Django/DRF exception, SQL error, stack trace, or table
# name. `error_code` is a small, closed set of stable string tokens a
# frontend can switch on without parsing `message` (which is
# human-readable and may change wording between releases).
from __future__ import annotations

from rest_framework import serializers


class ApiErrorSerializer(serializers.Serializer[None]):
    error_code = serializers.CharField(
        help_text="Stable machine-readable error token, e.g. 'not_found', 'invalid_activation'."
    )
    message = serializers.CharField(help_text="Human-readable description, for logs/debugging.")
    details = serializers.DictField(
        required=False, help_text="Optional structured context (never a stack trace)."
    )
