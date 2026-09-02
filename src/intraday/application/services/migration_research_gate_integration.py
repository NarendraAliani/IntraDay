# File: src/intraday/application/services/migration_research_gate_integration.py
#
# Checkpoint 67.9 Part 8-9 — wires the mechanical mixed-grid rule
# (`domain.market_data.migration_research_gate`, standalone since 67.8)
# into the REAL research/backtest boundary,
# `ResearchDataGateService.get_research_eligible_bars`
# (`application.services.research_data_gate`), instead of leaving it a
# helper nothing calls.
#
# `resolve_migration_scope_status` is the one piece of I/O this module
# adds: a read-only query against the Part 4 audit tables
# (`MigrationUnit`/`MigrationRun`) for a given `(instrument_id,
# timeframe, trading_date)` unit. It returns exactly one of:
#
#   - `None` — NO `MigrationUnit` row exists for this unit at all, i.e.
#     no migration run has EVER touched this scope. This is the ONLY
#     case the mixed-grid rule treats as "unrestricted" (matching
#     `migration_research_gate.migration_scope_is_research_eligible`'s
#     own `scope_status is None -> True` branch) — and, since this
#     checkpoint populates zero rows in any of the three audit tables
#     (Part 4's schema-only guarantee), this IS the branch every real
#     call takes today. That is expected and stated up front in the
#     directive: "this gate should currently always report no
#     migration in flight ... but it must be structurally present and
#     tested now."
#   - a real `MigrationScopeStatus` — exactly one matching, well-formed
#     `MigrationUnit` row (+ its owning `MigrationRun`) was found.
#   - raises `MigrationStatusUndeterminable` — anything that is NOT a
#     clean "zero rows" or "exactly one well-formed row" result:
#     multiple ambiguous rows, a unit row whose owning run is missing,
#     a status string that doesn't parse as a known enum member, or any
#     other query-level anomaly. This is the fail-closed branch the
#     directive requires by name ("migration status cannot be
#     determined -> DENY, never ALLOW") — it is a DISTINCT return shape
#     from `None`, specifically so the two can never be confused: `None`
#     means "definitely no migration", the exception means "cannot
#     tell", and only the FORMER is treated as unrestricted.
from __future__ import annotations

from datetime import date

from intraday.domain.market_data.migration_research_gate import (
    MigrationScopeStatus,
    MixedGridResearchRejection,
    require_migration_scope_research_eligible,
)
from intraday.domain.market_data.migration_state import MigrationRunState
from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe


class MigrationStatusUndeterminable(RuntimeError):
    """The fail-closed sentinel: migration status for this unit could
    not be cleanly resolved. A caller MUST treat this the same as (or
    more strictly than) `MixedGridResearchRejection` — never as
    "assume unrestricted and continue"."""


def resolve_migration_scope_status(
    *,
    instrument_id: InstrumentId,
    timeframe: Timeframe,
    trading_date: date,
) -> MigrationScopeStatus | None:
    """Real DB-backed resolver against the Part 4 audit tables. Deferred
    import of the Django models (matching this codebase's existing
    convention of keeping `application`/`domain` modules free of a
    hard, module-level Django import where avoidable) - importing here,
    not at module load time, also means this module stays importable
    (e.g. for pure unit tests of the composition logic below) without
    Django's app registry being configured."""
    from intraday.infrastructure.persistence.models import MigrationUnit

    from intraday.domain.market_data.source_timestamp import (
        CANONICALIZATION_STATE_UNKNOWN,
    )

    unit_id = f"{instrument_id}:{timeframe.value}:{trading_date.isoformat()}"
    rows = list(
        MigrationUnit.objects.filter(
            instrument_id=str(instrument_id),
            timeframe=timeframe.value,
            trading_date=trading_date,
        )
    )
    if not rows:
        return None
    if len(rows) > 1:
        raise MigrationStatusUndeterminable(
            f"{len(rows)} ambiguous MigrationUnit rows found for unit {unit_id!r} - "
            "expected at most one; migration status cannot be safely determined"
        )
    unit_row = rows[0]
    try:
        from intraday.infrastructure.persistence.models import MigrationRun

        run_row = MigrationRun.objects.get(migration_id=unit_row.migration_id)
    except MigrationRun.DoesNotExist as exc:
        raise MigrationStatusUndeterminable(
            f"MigrationUnit {unit_id!r} references migration_id={unit_row.migration_id!r} "
            "with no matching MigrationRun row - orphaned audit state, cannot determine status"
        ) from exc

    try:
        run_state = MigrationRunState(run_row.status)
    except ValueError as exc:
        raise MigrationStatusUndeterminable(
            f"MigrationRun {run_row.migration_id!r} has unrecognized status "
            f"{run_row.status!r} - not a known MigrationRunState value, cannot determine status"
        ) from exc

    # Checkpoint 67.11 Part 24 corrective fix: `MigrationUnit` itself
    # carries no `canonicalization_state` column (that fact lives on
    # `HistoricalBar` rows, not the audit row) - the ORIGINAL 67.9
    # resolver hardcoded UNKNOWN here unconditionally, which made the
    # mixed-grid rule's COMPLETED+CANONICALIZED+COMPLETE -> ALLOW branch
    # STRUCTURALLY UNREACHABLE through this resolver (every COMPLETED
    # run would be denied research access forever, even once a unit is
    # genuinely fully migrated) - a real correctness defect discovered
    # by Checkpoint 67.11 Part 18's research-readiness stress test.
    # Fixed by actually looking up the real, current canonicalization
    # state of every HistoricalBar row this unit covers: CANONICALIZED
    # only if every such row is CANONICALIZED (and at least one exists),
    # UNKNOWN otherwise (fail-closed default preserved for the "no rows"
    # or "mixed state" cases) - never a parallel/duplicated definition
    # of canonicalization, just a direct read of the same field every
    # other consumer in this codebase already uses.
    from datetime import datetime as _datetime, time as _time, timezone as _dt_timezone

    from intraday.domain.session.calendar import INDIA_STANDARD_TIME
    from intraday.infrastructure.persistence.models import HistoricalBar

    # Same IST-local-day-to-UTC-bounds convention `migration_dry_run.
    # _cas_era_bounds` already uses elsewhere in this codebase - not a
    # parallel definition, just inlined here to avoid a cross-module
    # import of a private helper.
    day_start_utc = _datetime.combine(trading_date, _time.min).replace(
        tzinfo=INDIA_STANDARD_TIME
    ).astimezone(_dt_timezone.utc)
    day_end_utc = _datetime.combine(trading_date, _time.max).replace(
        tzinfo=INDIA_STANDARD_TIME
    ).astimezone(_dt_timezone.utc)

    bar_states = list(
        HistoricalBar.objects.filter(
            instrument_id=str(instrument_id),
            timeframe=timeframe.value,
            bar_timestamp__gte=day_start_utc,
            bar_timestamp__lte=day_end_utc,
        ).values_list("canonicalization_state", flat=True)
    )
    if bar_states and all(state == "CANONICALIZED" for state in bar_states):
        canonicalization_state = "CANONICALIZED"
    else:
        canonicalization_state = CANONICALIZATION_STATE_UNKNOWN

    return MigrationScopeStatus(
        instrument_id=instrument_id,
        timeframe=timeframe,
        trading_date=trading_date,
        run_state=run_state,
        canonicalization_state=canonicalization_state,
    )


def enforce_migration_scope_or_deny(
    *,
    instrument_id: InstrumentId,
    timeframe: Timeframe,
    trading_date: date,
    unit_is_complete: bool,
    resolver=resolve_migration_scope_status,
) -> None:
    """The single call `ResearchDataGateService` makes per distinct
    trading date. Fail-closed by construction: ANY exception from
    `resolver` (including `MigrationStatusUndeterminable`) propagates
    as-is rather than being caught and treated as "no migration" -
    there is no `except Exception: return` anywhere in this function.
    A clean `None` result (genuinely no migration ever touched this
    unit) is the only path that imposes no restriction."""
    scope_status = resolver(
        instrument_id=instrument_id, timeframe=timeframe, trading_date=trading_date
    )
    require_migration_scope_research_eligible(
        instrument_id=instrument_id,
        timeframe=timeframe,
        trading_date=trading_date,
        scope_status=scope_status,
        unit_is_complete=unit_is_complete,
    )


__all__ = [
    "MigrationStatusUndeterminable",
    "resolve_migration_scope_status",
    "enforce_migration_scope_or_deny",
]
