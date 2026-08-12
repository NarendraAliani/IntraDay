# File: src/intraday/application/config_schema/errors.py
#
# Config-layer error wrapping (Checkpoint 6). Adds WHERE a bad
# configuration value came from (source file/key) without re-implementing
# WHAT is wrong with it — that validation stays exclusively inside the
# domain contract's own `__post_init__`. This module never duplicates a
# domain invariant.
from __future__ import annotations


class ConfigValidationError(ValueError):
    """Raised when a raw configuration instance fails schema-level
    checks (missing required field) or is rejected by the domain contract
    it is being parsed into. Always wraps the original exception so the
    domain-level reason is never lost."""

    def __init__(self, *, source: str, original: Exception) -> None:
        super().__init__(f"Invalid configuration in {source}: {original}")
        self.source = source
        self.original = original
