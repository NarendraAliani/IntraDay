# File: src/intraday/application/services/migration_execution_authorization.py
#
# Checkpoint 67.12.2 Part 3 — PRE-EXECUTION AUTHORIZATION BOUNDARY.
#
# `verify_environment_identity()` (67.12.1) answers one narrow question
# honestly: does settings-module identity + a live `current_database()`
# round-trip + an out-of-band env-var marker together provide POSITIVE
# evidence this process is connected to production? On its own that is
# NOT sufficient authorization to execute a real one-unit migration
# write — it says nothing about which unit is being targeted, whether
# that unit's scope is still what it was planned against, or whether
# the write-capability guard even agrees the connection is writable in
# the first place.
#
# CHECKPOINT_83 UPDATE (implementing `SINGLE_ENV_AUTHORIZATION_
# PROPOSAL.md` §2.3(a), operator-approved): check (5) below used to
# re-invoke `assert_write_capable_connection_is_test_database()` — the
# guard `migration_67_10`'s own TEST-ONLY execution path was built
# for, which by design only ever accepts a `test_`-prefixed database.
# This function's own ONLY real caller in this codebase is
# `migration_production_execute.py` (`67.13-C`) — the genuine
# production entry point, which by definition never connects to a
# `test_`-prefixed database — so reusing that guard here made check (5)
# structurally unsatisfiable forever (`CHECKPOINT_82` confirmed this
# live). Check (5) now calls
# `assert_write_capable_connection_is_verified_production()` instead —
# re-deriving legitimacy from the SAME positive-evidence chain check
# (1) above already establishes, not a database-naming convention.
# `migration_67_10.py`'s own test-only command never calls this
# function at all (confirmed directly — grepped its own source), so
# this change affects the production path only, exactly as approved.
#
# This module composes the ENTIRE evidence chain the checkpoint
# directive lists — environment identity, database identity, intended
# target identity, scope fingerprint, evidence/snapshot requirements,
# and the write-capability guard — into ONE fail-closed decision
# function, `authorize_one_unit_execution`. It is intentionally narrow:
# one dataclass in, one dataclass out, no new framework, no
# persistence.
from __future__ import annotations

import enum
from dataclasses import dataclass

from intraday.application.services.migration_canary_backup import CanaryBackupArtifact
from intraday.application.services.migration_environment_identity import (
    EnvironmentIdentityReport,
    EnvironmentIdentityVerdict,
)
from intraday.application.services.migration_execute import (
    VerifiedProductionWriteGuardError,
    assert_write_capable_connection_is_verified_production,
)
from intraday.application.services.migration_dry_run import MigrationUnitKey
from intraday.domain.market_data.migration_scope_fingerprint import compute_scope_fingerprint


class ExecutionAuthorizationVerdict(enum.Enum):
    AUTHORIZED = "AUTHORIZED"
    DENIED = "DENIED"


@dataclass(frozen=True, slots=True)
class ExecutionAuthorizationRequest:
    """Everything a caller must supply for a decision to be made. No
    field here is optional/defaulted to a permissive value — a caller
    that omits evidence gets DENIED, never AUTHORIZED-by-omission."""

    environment_identity: EnvironmentIdentityReport
    intended_target_unit: MigrationUnitKey
    backup_artifact: CanaryBackupArtifact
    expected_scope_fingerprint: str


@dataclass(frozen=True, slots=True)
class ExecutionAuthorizationDecision:
    verdict: ExecutionAuthorizationVerdict
    reasons: tuple[str, ...]

    def fail_closed_ok_to_proceed(self) -> bool:
        """Same fail-closed pattern as `EnvironmentIdentityReport` — a
        future caller MUST gate on this method, not on `verdict`
        directly, so a caller that only pattern-matches one enum member
        and forgets the `else` branch still fails closed."""
        return self.verdict is ExecutionAuthorizationVerdict.AUTHORIZED and not self.reasons


def authorize_one_unit_execution(
    request: ExecutionAuthorizationRequest,
) -> ExecutionAuthorizationDecision:
    """Composes, in order, EVERY safety invariant the checkpoint
    directive lists for pre-execution authorization. Every check below
    is independent and additive — a single failing check is sufficient
    to DENY, and denial reasons accumulate rather than short-circuit,
    so a caller sees the FULL set of unmet prerequisites in one call
    rather than having to fix one and re-run repeatedly to discover the
    next.

    This function NEVER raises for an ordinary denied outcome — DENIED
    is an expected, valid answer reported honestly via the verdict, the
    same pattern `verify_environment_identity` uses. It DOES let a
    genuine infrastructure failure (e.g. the write-capability guard's
    own DB introspection erroring) propagate, since that is not this
    function's to interpret."""
    reasons: list[str] = []

    # (1) Environment identity must be POSITIVELY established — not
    # merely absent-of-evidence-against.
    if request.environment_identity.verdict is not EnvironmentIdentityVerdict.VERIFIED_PRODUCTION:
        reasons.append(
            "environment identity is not VERIFIED_PRODUCTION "
            f"(verdict={request.environment_identity.verdict.value}); reasons: "
            f"{'; '.join(request.environment_identity.reasons) or 'none recorded'}"
        )
    if not request.environment_identity.fail_closed_ok_to_proceed():
        reasons.append(
            "environment identity report's own fail_closed_ok_to_proceed() is False"
        )

    # (2) Intended target identity must match the identity recorded in
    # the evidence (backup artifact) actually being relied on. A
    # mismatch here means the caller is about to execute against a DIFFERENT
    # unit than the one the presented evidence describes.
    target_key = (
        str(request.intended_target_unit.instrument_id),
        request.intended_target_unit.timeframe.value,
        request.intended_target_unit.trading_date.isoformat(),
    )
    artifact_key = (
        request.backup_artifact.unit_identity.get("instrument_id"),
        request.backup_artifact.unit_identity.get("timeframe"),
        request.backup_artifact.unit_identity.get("trading_date"),
    )
    if target_key != artifact_key:
        reasons.append(
            f"intended target unit {target_key} does not match the backup artifact's "
            f"recorded unit_identity {artifact_key}"
        )

    # (3) Scope fingerprint must match the caller's independently
    # supplied expectation. This function does not recompute scope
    # fingerprints itself (that remains `migration_execute.py`'s own
    # revalidation responsibility at the real lock/transaction
    # boundary) — it only checks that the evidence being presented as
    # authorization basis has NOT already silently drifted relative to
    # the caller's own expectation before authorization is even granted.
    if request.backup_artifact.scope_fingerprint != request.expected_scope_fingerprint:
        reasons.append(
            f"backup artifact scope_fingerprint {request.backup_artifact.scope_fingerprint!r} "
            f"does not match caller's expected_scope_fingerprint "
            f"{request.expected_scope_fingerprint!r}"
        )

    # (4) Evidence/snapshot requirement: the backup artifact's own
    # before/after drift check must have passed (source_before ==
    # source_after) — `build_canary_backup` already refuses to
    # construct an artifact where these disagree
    # (`SourceChangedDuringExportError`), so this is defense-in-depth
    # against a caller passing a hand-built/tampered artifact object
    # rather than one produced by `build_canary_backup` itself.
    if request.backup_artifact.source_before_fingerprint != request.backup_artifact.source_after_fingerprint:
        reasons.append(
            "backup artifact's source_before_fingerprint and source_after_fingerprint "
            "disagree — this artifact should never have been constructible; refusing to "
            "treat it as valid evidence regardless"
        )
    if request.backup_artifact.payload_fingerprint != request.backup_artifact.source_before_fingerprint:
        reasons.append(
            "backup artifact's payload_fingerprint does not match its own "
            "source_before_fingerprint — internally inconsistent evidence"
        )

    # (5) CHECKPOINT_83: the write-capability guard appropriate for THIS
    # function's own real caller (the production entry point) — see the
    # module-level comment above for why this is no longer
    # `assert_write_capable_connection_is_test_database()`. Deliberately
    # re-checked HERE too (not only inside the executor) so that
    # authorization itself, evaluated in isolation, already reflects
    # the same real-world fact the executor will independently re-check
    # at its own boundary — two independent evaluations of the same
    # invariant, not one trusted blindly by the other. This function
    # does not weaken, wrap, or catch-and-suppress that guard; a
    # `VerifiedProductionWriteGuardError` here is recorded as a denial
    # reason, never silently swallowed into an AUTHORIZED verdict.
    try:
        assert_write_capable_connection_is_verified_production()
    except VerifiedProductionWriteGuardError as exc:
        reasons.append(f"write-capability guard refuses this connection: {exc}")

    if reasons:
        return ExecutionAuthorizationDecision(
            verdict=ExecutionAuthorizationVerdict.DENIED, reasons=tuple(reasons)
        )
    return ExecutionAuthorizationDecision(
        verdict=ExecutionAuthorizationVerdict.AUTHORIZED, reasons=()
    )


# ---------------------------------------------------------------------
# NOT_WIRED_RATIONALE — HISTORICAL, SUPERSEDED BY CHECKPOINT_83.
#
# This comment originally explained why `authorize_one_unit_execution`
# was not wired to any real write path as of `67.12.2-B`: check (5)
# then called `assert_write_capable_connection_is_test_database()`,
# which is BY DESIGN mutually exclusive with `VERIFIED_PRODUCTION`
# identity (check 1) — the two could never both pass, so this function
# could never return AUTHORIZED against a real database, and no
# genuine production write path existed yet to wire it into anyway.
#
# `CHECKPOINT_83` (`SINGLE_ENV_AUTHORIZATION_PROPOSAL.md` §2.3(a))
# resolved this: check (5) now calls
# `assert_write_capable_connection_is_verified_production()` instead —
# see the module-level comment at the top of this file. This function
# IS now wired to a real write path:
# `migration_production_execute.py` (`67.13-C`) calls it as its own
# gate 3, and — only after it returns AUTHORIZED — constructs
# `HistoricalBarMigrationExecutor(..., allow_non_test_database=True)`.
# `migration_67_10.py`'s disposable-test-database path is untouched:
# it never calls `authorize_one_unit_execution` at all (confirmed
# directly, grepped its own source), so nothing above affects it.
# Kept here, rather than deleted, as an honest record of the earlier
# deadlock and how it was actually resolved — not as current guidance.
__all__ = [
    "ExecutionAuthorizationVerdict",
    "ExecutionAuthorizationRequest",
    "ExecutionAuthorizationDecision",
    "authorize_one_unit_execution",
]
