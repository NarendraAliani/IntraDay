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
# the write-capability guard (`assert_write_capable_connection_is_test_
# database`) even agrees the connection is writable in the first place
# (in production that guard by design REFUSES — it only ever allows
# `test_`-prefixed databases, so it can never itself authorize a real
# production write; a genuine production execution path, if one is ever
# built, would need to replace/parameterize that guard, which is
# explicitly out of scope here and NOT done).
#
# This module composes the ENTIRE evidence chain the checkpoint
# directive lists — environment identity, database identity, intended
# target identity, scope fingerprint, evidence/snapshot requirements,
# and (for completeness of the honesty check, even though it always
# fails closed against this workspace) the existing write-capability
# guard — into ONE fail-closed decision function,
# `authorize_one_unit_execution`. It is intentionally narrow: one
# dataclass in, one dataclass out, no new framework, no persistence,
# no wiring into `migration_execute.py`'s actual write path (see the
# module-level rationale below `NOT_WIRED_RATIONALE`).
from __future__ import annotations

import enum
from dataclasses import dataclass

from intraday.application.services.migration_canary_backup import CanaryBackupArtifact
from intraday.application.services.migration_environment_identity import (
    EnvironmentIdentityReport,
    EnvironmentIdentityVerdict,
)
from intraday.application.services.migration_execute import (
    ProductionWriteGuardError,
    assert_write_capable_connection_is_test_database,
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

    # (5) The existing, untouched write-capability guard. This is
    # deliberately re-checked HERE too (not only inside the executor)
    # so that authorization itself, evaluated in isolation, already
    # reflects the same real-world fact the executor will independently
    # re-check at its own boundary — two independent evaluations of the
    # same invariant, not one trusted blindly by the other. This
    # function does not weaken, wrap, or catch-and-suppress that guard;
    # a `ProductionWriteGuardError` here is recorded as a denial reason,
    # never silently swallowed into an AUTHORIZED verdict.
    try:
        assert_write_capable_connection_is_test_database()
    except ProductionWriteGuardError as exc:
        reasons.append(f"write-capability guard refuses this connection: {exc}")

    if reasons:
        return ExecutionAuthorizationDecision(
            verdict=ExecutionAuthorizationVerdict.DENIED, reasons=tuple(reasons)
        )
    return ExecutionAuthorizationDecision(
        verdict=ExecutionAuthorizationVerdict.AUTHORIZED, reasons=()
    )


# ---------------------------------------------------------------------
# NOT_WIRED_RATIONALE — why `authorize_one_unit_execution` is NOT called
# from inside `migration_execute.py`'s actual write path in this
# checkpoint, even though the directive allows wiring it in "if
# trivially safe":
#
#   1. `assert_write_capable_connection_is_test_database()` is, BY
#      DESIGN, mutually exclusive with `VERIFIED_PRODUCTION` identity —
#      it only ever accepts a `test_`-prefixed database, and
#      `verify_environment_identity()` can only report
#      `VERIFIED_PRODUCTION` for a REAL production database name (the
#      marker env var must equal the live `current_database()`, and a
#      genuine production database is never named with a `test_`
#      prefix). Check (1) and check (5) above are therefore, in this
#      codebase's CURRENT configuration, structurally UNSATISFIABLE
#      together — `authorize_one_unit_execution` can never return
#      AUTHORIZED as this codebase is configured today. Wiring an
#      always-DENIED gate into `migration_execute.py`'s existing
#      disposable-test-database execution path (the ONLY path this
#      checkpoint is permitted to exercise) would either (a) silently
#      block that legitimate, already-proven-safe test path, which is
#      an unrelated regression this checkpoint must not introduce, or
#      (b) require inventing a bypass/parameterization for tests, which
#      is exactly the kind of new generic-framework complexity Part 7
#      forbids adding "for smallest correct fix" reasons.
#   2. A REAL production execution path does not exist in this
#      repository yet (`migration_execute.py`'s only caller is the
#      `--execute` management command gated to the disposable pytest
#      test database — see that module's own docstring). Wiring an
#      authorization boundary into a write path that has no legitimate
#      production caller would be authorization theater: it could never
#      be exercised against the scenario it exists to gate, so it would
#      add code with no test coverage of its actual intended purpose.
#   3. Instead, this checkpoint proves the boundary is REAL and
#      MEANINGFUL the honest way available today: focused unit tests
#      (Part 4, tests F-J below) exercise `authorize_one_unit_execution`
#      directly against real evidence objects (real `EnvironmentIdentityReport`
#      from `verify_environment_identity()`, real `CanaryBackupArtifact`
#      from `build_canary_backup()`) and prove it fails closed for
#      every single missing prerequisite, independently. When a real
#      production execution path is designed in a FUTURE checkpoint,
#      wiring this function in front of it becomes the trivial,
#      already-tested step — not a new one.
__all__ = [
    "ExecutionAuthorizationVerdict",
    "ExecutionAuthorizationRequest",
    "ExecutionAuthorizationDecision",
    "authorize_one_unit_execution",
]
