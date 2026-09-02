# File: src/intraday/application/services/migration_environment_identity.py
#
# Checkpoint 67.12.1 Task 3 — smallest possible EXECUTION-TIME
# environment-identity verification.
#
# This module answers exactly one question, honestly: "right now, in
# this process, can we POSITIVELY establish that the connected database
# is the intended real-production target for a one-unit canary write?"
# It is READ-ONLY (settings introspection + `SELECT current_database()`
# only — no writes, no schema changes) and is NOT wired into
# `migration_execute.py`'s write path. `assert_write_capable_connection_
# is_test_database()` in `migration_execute.py` is untouched and is not
# imported or modified here.
#
# Per the 67.12-PRE Deliverable I finding this checkpoint was told to
# act on: a database merely being reachable and named plausibly (e.g.
# `intraday`) is NOT evidence it is production. This function requires
# an explicit, independently configured, positive marker — not an
# inference from a name or a settings-module string alone — before it
# will report VERIFIED. Absent that marker (as is the case in every
# environment this checkpoint can reach), it reports CANNOT_VERIFY and
# fails closed: a caller MUST treat CANNOT_VERIFY as "do not proceed."
#
# No new generic framework: this is one dataclass and one function,
# built entirely from information this codebase's existing settings/DB
# layer already exposes (`django.conf.settings.SETTINGS_MODULE`,
# `django.db.connection.settings_dict`, `django.db.connection` itself).
# Nothing new is added to `settings/*.py`.
from __future__ import annotations

import enum
import os
from dataclasses import dataclass

from django.conf import settings
from django.db import connection

# The name of the ONE environment variable this function treats as a
# positive, explicit production marker. This is deliberately NOT any
# value this codebase's settings modules set for themselves (base.py /
# development.py / production.py never set this) - an operator running
# in a genuine, separately deployed production environment would need
# to set it explicitly and deliberately, out-of-band from Django
# settings, precisely so that no development/test/CI environment can
# ever satisfy this check by accident.
PRODUCTION_IDENTITY_MARKER_ENV_VAR = "INTRADAY_VERIFIED_PRODUCTION_IDENTITY"


class EnvironmentIdentityVerdict(enum.Enum):
    VERIFIED_PRODUCTION = "VERIFIED_PRODUCTION"
    CANNOT_VERIFY = "CANNOT_VERIFY"


@dataclass(frozen=True, slots=True)
class EnvironmentIdentityReport:
    verdict: EnvironmentIdentityVerdict
    settings_module: str
    database_alias: str
    database_name: str
    database_host: str
    production_marker_present: bool
    reasons: tuple[str, ...]

    def fail_closed_ok_to_proceed(self) -> bool:
        """A future write-capable caller MUST gate on this, not on
        `verdict` directly, so the fail-closed default cannot be
        bypassed by a caller that only checks for a specific enum
        member and forgets the `else` branch."""
        return self.verdict is EnvironmentIdentityVerdict.VERIFIED_PRODUCTION


def verify_environment_identity() -> EnvironmentIdentityReport:
    """Read-only. Never raises for a normal "cannot verify" outcome —
    that is an expected, valid answer, reported honestly via the
    returned verdict, not an exception. Only genuine infrastructure
    failure (e.g. no DB connection at all) propagates as an exception,
    same as any other read against `connection`.
    """
    reasons: list[str] = []

    settings_module = os.environ.get("DJANGO_SETTINGS_MODULE", "") or getattr(
        settings, "SETTINGS_MODULE", ""
    )
    is_production_settings = settings_module.endswith(".production")
    if not is_production_settings:
        reasons.append(
            f"DJANGO_SETTINGS_MODULE={settings_module!r} does not end with "
            "'.production' — this process was not booted with the production "
            "settings module."
        )

    db_alias = connection.alias
    db_settings = connection.settings_dict
    db_name_configured = str(db_settings.get("NAME", ""))
    db_host_configured = str(db_settings.get("HOST", ""))

    # A real, live round-trip to the connected database - not just the
    # configured settings dict - so a report reflects what is ACTUALLY
    # connected right now, not merely what Django was told to connect to.
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database()")
        (db_name_live,) = cursor.fetchone()

    if db_name_live != db_name_configured:
        reasons.append(
            f"configured database NAME={db_name_configured!r} does not match the "
            f"live connection's current_database()={db_name_live!r}."
        )

    marker_value = os.environ.get(PRODUCTION_IDENTITY_MARKER_ENV_VAR, "")
    marker_present = bool(marker_value) and marker_value == db_name_live
    if not marker_present:
        reasons.append(
            f"no positive production-identity marker found: environment variable "
            f"{PRODUCTION_IDENTITY_MARKER_ENV_VAR!r} is not set to the live "
            f"connected database name ({db_name_live!r}). A database being "
            "reachable and plausibly named is NOT treated as evidence of "
            "production identity by this function."
        )

    if is_production_settings and marker_present and not reasons:
        verdict = EnvironmentIdentityVerdict.VERIFIED_PRODUCTION
    else:
        verdict = EnvironmentIdentityVerdict.CANNOT_VERIFY
        if not reasons:
            reasons.append("insufficient positive evidence to verify production identity.")

    return EnvironmentIdentityReport(
        verdict=verdict,
        settings_module=settings_module,
        database_alias=db_alias,
        database_name=db_name_live,
        database_host=db_host_configured,
        production_marker_present=marker_present,
        reasons=tuple(reasons),
    )


__all__ = [
    "PRODUCTION_IDENTITY_MARKER_ENV_VAR",
    "EnvironmentIdentityVerdict",
    "EnvironmentIdentityReport",
    "verify_environment_identity",
]
