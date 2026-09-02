# File: src/intraday/domain/market_data/migration_research_gate.py
#
# Checkpoint 67.8 Part 10 — MIXED-GRID PROTECTION, mechanical research
# gate rule tied to migration run-state. Deliberately a small,
# standalone, pure-function module rather than a modification to
# `application.services.research_data_gate.ResearchDataGateService`
# itself: `ResearchDataGateService` is the live backtest/research read
# boundary this codebase already depends on (66.1, unchanged per this
# checkpoint's own hard rules), and wiring a migration-state check
# directly into it is exactly the kind of cross-cutting change to an
# already-relied-upon path this checkpoint's own directive says to
# avoid without very high confidence. This module is the CONTRACT a
# future integration would call from inside that service (one `if not
# migration_scope_is_research_eligible(...): raise
# ResearchDataRejectedError(...)` at the top of
# `ResearchDataGateService.get_research_bars`) - safe to design and
# fully test now, safe to wire in later once a real, persisted
# `MigrationRunAuditRecord`/`MigrationUnitAuditRecord` source exists to
# query (this checkpoint populates neither - see `migration_audit.py`).
#
# THE RULE (mechanical, not "dry-run didn't mutate anything" as the
# only protection - Part 10's explicit requirement):
#   - RUNNING or PARTIALLY_COMPLETED run state for a unit whose
#     (instrument_id, timeframe, trading_date) matches the requested
#     research scope -> REJECT, unconditionally, regardless of the
#     row's own `canonicalization_state`/completeness.
#   - COMPLETED run state -> research may proceed ONLY for units that
#     are ALSO individually CANONICALIZED and COMPLETE (this module
#     does not itself compute completeness - it composes with
#     `HistoricalDataCoverageService.is_complete`, already unchanged
#     and passed in verbatim as `unit_is_complete`).
#   - PLANNED or ABORTED (or no migration touching this scope at all)
#     -> this gate imposes no restriction; the existing 66.1 provenance
#     /completeness gate rules alone.
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from intraday.domain.market_data.migration_state import MigrationRunState
from intraday.domain.market_data.source_timestamp import (
    CANONICALIZATION_STATE_CANONICALIZED,
)
from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe


@dataclass(frozen=True, slots=True)
class MigrationScopeStatus:
    """The minimum a caller must know about a migration unit's current
    state to apply the mixed-grid rule - deliberately narrow (no
    dependency on the audit dataclasses' full shape) so this module has
    no import-time coupling to how/whether audit records are ever
    persisted."""

    instrument_id: InstrumentId
    timeframe: Timeframe
    trading_date: date
    run_state: MigrationRunState
    canonicalization_state: str


class MixedGridResearchRejection(RuntimeError):
    """Raised (never a silent empty result) when the mechanical
    mixed-grid rule rejects a requested research scope."""

    def __init__(self, reason: str, *, detail: str) -> None:
        super().__init__(f"{reason}: {detail}")
        self.reason = reason
        self.detail = detail


def migration_scope_is_research_eligible(
    *,
    instrument_id: InstrumentId,
    timeframe: Timeframe,
    trading_date: date,
    scope_status: MigrationScopeStatus | None,
    unit_is_complete: bool,
) -> bool:
    """Pure predicate, no I/O. `scope_status` is `None` when no
    migration run has ever touched this (instrument_id, timeframe,
    trading_date) unit — in that case the mixed-grid rule imposes no
    restriction (the pre-existing 66.1 provenance/completeness gate is
    the only applicable rule)."""
    if scope_status is None:
        return True
    if (
        scope_status.instrument_id != instrument_id
        or scope_status.timeframe != timeframe
        or scope_status.trading_date != trading_date
    ):
        # a status for a DIFFERENT unit was passed in by mistake - fail
        # closed rather than silently ignore the mismatch.
        raise ValueError(
            "scope_status does not describe the requested "
            f"({instrument_id}, {timeframe}, {trading_date}) unit"
        )
    if scope_status.run_state in (
        MigrationRunState.RUNNING,
        MigrationRunState.PARTIALLY_COMPLETED,
    ):
        return False
    if scope_status.run_state is MigrationRunState.COMPLETED:
        return (
            scope_status.canonicalization_state == CANONICALIZATION_STATE_CANONICALIZED
            and unit_is_complete
        )
    # PLANNED / ABORTED: no restriction from this gate.
    return True


def require_migration_scope_research_eligible(
    *,
    instrument_id: InstrumentId,
    timeframe: Timeframe,
    trading_date: date,
    scope_status: MigrationScopeStatus | None,
    unit_is_complete: bool,
) -> None:
    """Raising counterpart of `migration_scope_is_research_eligible` -
    the shape a real `ResearchDataGateService` integration would call
    (matching that service's existing raise-on-rejection convention
    rather than returning a bool the caller might forget to check)."""
    if migration_scope_is_research_eligible(
        instrument_id=instrument_id,
        timeframe=timeframe,
        trading_date=trading_date,
        scope_status=scope_status,
        unit_is_complete=unit_is_complete,
    ):
        return
    if scope_status is not None and scope_status.run_state in (
        MigrationRunState.RUNNING,
        MigrationRunState.PARTIALLY_COMPLETED,
    ):
        raise MixedGridResearchRejection(
            "MIGRATION_IN_PROGRESS",
            detail=(
                f"unit ({instrument_id}, {timeframe.value}, {trading_date}) is "
                f"{scope_status.run_state.value} - rejected unconditionally"
            ),
        )
    raise MixedGridResearchRejection(
        "MIGRATION_COMPLETED_BUT_UNIT_NOT_CANONICALIZED_AND_COMPLETE",
        detail=(
            f"unit ({instrument_id}, {timeframe.value}, {trading_date}) migration is "
            "COMPLETED but this unit is not both CANONICALIZED and COMPLETE"
        ),
    )


__all__ = [
    "MigrationScopeStatus",
    "MixedGridResearchRejection",
    "migration_scope_is_research_eligible",
    "require_migration_scope_research_eligible",
]
