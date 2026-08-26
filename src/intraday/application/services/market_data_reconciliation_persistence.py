# File: src/intraday/application/services/market_data_reconciliation_persistence.py
#
# Checkpoint 64.84: the ONE place a reconciliation verdict becomes a
# stored claim.
#
# 64.79 deliberately stopped one step short of this: it COMPUTES a
# `ReconciliationReport` and writes nothing, because flipping
# `MarketDataArchiveDay.reconciliation_status` is a claim about stored
# data that must not be made until a comparison has actually run. This
# module takes that final step, and takes ONLY that step - it owns no
# comparison logic, no session logic and no status vocabulary of its
# own. It calls the existing 64.79 service, and records exactly what
# came back.
#
# THE RULE THIS MODULE EXISTS TO ENFORCE, stated before any code so it
# cannot be lost in the details:
#
#   Calling this service is NEVER evidence of reconciliation. The
#   verdict persisted is the verdict the domain computed, unmodified.
#   A `NOT_RECONCILED` result is persisted AS `NOT_RECONCILED`, with
#   `reconciled_at` left NULL - it is never promoted to RECONCILED or
#   PASS because the persistence path ran successfully. Success of the
#   write says nothing whatsoever about agreement of the data.
#
# There is NO reconciliation table. The archive cell is the persistence
# boundary (Phase 7/12): re-running a reconciliation UPDATES the same
# row, so the stored result is a current verdict rather than an
# append-only history that could disagree with itself.
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from intraday.application.repositories.market_data_archive import MarketDataArchiveRepository
from intraday.application.services.market_data_reconciliation import (
    MarketDataReconciliationService,
)
from intraday.domain.market_data.archive import ReconciliationStatus
from intraday.domain.market_data.reconciliation import (
    ReconciliationReport,
    persisted_status_for,
    was_comparison_executed,
)
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe, ensure_utc


@dataclass(frozen=True, slots=True)
class ReconciliationPersistenceResult:
    """What one persist attempt did - the report it recorded, and
    whether it actually landed anywhere.

    `persisted` and `archive_cells_updated` are separate on purpose: a
    truthful verdict that matched no archive cell is NOT a failure (the
    day simply is not archived at that timeframe), but it is also not a
    persisted result, and a caller must be able to tell those apart
    without re-querying."""

    report: ReconciliationReport
    persisted_status: ReconciliationStatus
    reconciled_at: datetime | None
    archive_cells_updated: int

    @property
    def persisted(self) -> bool:
        return self.archive_cells_updated > 0

    @property
    def comparison_executed(self) -> bool:
        """Whether bars were genuinely compared. Exactly equivalent to
        `reconciled_at is not None` by construction below - kept as a
        named property because that equivalence is the checkpoint's
        central honesty invariant and deserves to be assertable."""
        return was_comparison_executed(self.report.outcome)


class MarketDataReconciliationPersistenceService:
    def __init__(
        self,
        reconciliation_service: MarketDataReconciliationService,
        archive_repository: MarketDataArchiveRepository,
        *,
        exchange: Exchange = Exchange.NSE,
    ) -> None:
        self._reconciliation = reconciliation_service
        self._archive = archive_repository
        self._exchange = exchange

    def reconcile_and_persist_cell(
        self,
        *,
        trading_date: date,
        instrument_symbol: str,
        timeframe: Timeframe,
        as_of: datetime,
    ) -> ReconciliationPersistenceResult:
        """Reconciles one cell and records the verdict on its archive
        row(s).

        The sequence is fixed by Phase 4 and is the whole design:

          1. COMPUTE first, through the untouched 64.79 service. If the
             comparison raises, this method propagates and NOTHING is
             written - a failed calculation must never leave a
             successful-looking status behind. There is no `except`
             here by design: swallowing the error would produce exactly
             that.
          2. Project the verdict onto the stored vocabulary.
          3. Stamp `reconciled_at` ONLY when a comparison executed.
          4. Write the five reconciliation columns, and only those.

        `as_of` is both the session-shape reference for the comparison
        and the recorded `reconciled_at`, so the stored instant is the
        moment the evidence was evaluated - not the moment a row
        happened to be written."""
        ensure_utc(as_of, field_name="as_of")

        report = self._reconciliation.reconcile_cell(
            trading_date=trading_date,
            instrument_symbol=instrument_symbol,
            timeframe=timeframe,
            as_of=as_of,
        )
        return self._persist(report=report, timeframe=timeframe, as_of=as_of)

    def reconcile_and_persist_trading_date(
        self, *, trading_date: date, timeframe: Timeframe, as_of: datetime
    ) -> tuple[ReconciliationPersistenceResult, ...]:
        """Every archived symbol for the day, each persisted onto its own
        cell. Symbols with no reference data are persisted as
        NOT_RECONCILED rather than skipped - an un-reconcilable cell and
        an un-attempted one must not look identical in storage."""
        ensure_utc(as_of, field_name="as_of")
        reports = self._reconciliation.reconcile_trading_date(
            trading_date=trading_date, timeframe=timeframe, as_of=as_of
        )
        return tuple(
            self._persist(report=report, timeframe=timeframe, as_of=as_of) for report in reports
        )

    def _persist(
        self, *, report: ReconciliationReport, timeframe: Timeframe, as_of: datetime
    ) -> ReconciliationPersistenceResult:
        status = persisted_status_for(report.outcome)
        # The single most important line in this checkpoint: the stamp
        # is conditioned on the DOMAIN's verdict, never on the success
        # of the write below.
        reconciled_at = as_of if was_comparison_executed(report.outcome) else None
        updated = self._archive.save_reconciliation_result(
            exchange=self._exchange,
            trading_date=report.identity.trading_date,
            instrument_symbol=report.instrument_symbol,
            timeframe=timeframe,
            status=status,
            outcome=report.outcome,
            reason=report.reason,
            evidence_source=report.evidence_source,
            reconciled_at=reconciled_at,
        )
        return ReconciliationPersistenceResult(
            report=report,
            persisted_status=status,
            reconciled_at=reconciled_at,
            archive_cells_updated=updated,
        )


__all__ = [
    "MarketDataReconciliationPersistenceService",
    "ReconciliationPersistenceResult",
]
