# tests/unit/research/test_checkpoint_64_84_reconciliation_persistence.py
#
# Checkpoint 64.84: proof that a reconciliation VERDICT can be persisted
# onto the existing archive cell, and - far more importantly - proof
# that persistence cannot manufacture one.
#
# The tests below are organised around the single rule this checkpoint
# exists to enforce: calling the persistence service is never evidence
# of reconciliation. A NOT_RECONCILED verdict must survive the round
# trip as NOT_RECONCILED with a NULL `reconciled_at`, and RECONCILED
# must be reachable ONLY from a genuine full-coverage agreement.
#
# No provider connection, no live worker, no order path.
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from intraday.application.services.market_data_reconciliation import (
    MarketDataReconciliationService,
)
from intraday.application.services.market_data_reconciliation_persistence import (
    MarketDataReconciliationPersistenceService,
    ReconciliationPersistenceResult,
)
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.aggregation import AggregatedBar, BarStatus
from intraday.domain.market_data.archive import ReconciliationStatus
from intraday.domain.market_data.contracts import Quote
from intraday.domain.market_data.quality import expected_bar_timestamps
from intraday.domain.market_data.reconciliation import (
    ReconciliationOutcome,
    ReferenceBar,
    persisted_status_for,
    was_comparison_executed,
)
from intraday.domain.session.calendar import build_session_for
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
TRADING_DAY = date(2026, 8, 25)
AS_OF = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)  # 17:30 IST, session closed


# ---------------------------------------------------------------------
# The vocabulary bridge (pure domain - no database)
# ---------------------------------------------------------------------


def test_pass_is_the_only_outcome_that_persists_as_reconciled() -> None:
    """The bridge between the four-valued computed verdict and the
    three-valued stored status. RECONCILED is reachable from PASS and
    from nothing else - this is the assertion that would fail first if
    anyone ever tried to make a partial or empty result look validated.
    """
    assert persisted_status_for(ReconciliationOutcome.PASS) is ReconciliationStatus.RECONCILED
    assert persisted_status_for(ReconciliationOutcome.FAIL) is ReconciliationStatus.MISMATCH
    assert (
        persisted_status_for(ReconciliationOutcome.PARTIAL) is ReconciliationStatus.NOT_RECONCILED
    )
    assert (
        persisted_status_for(ReconciliationOutcome.NOT_RECONCILED)
        is ReconciliationStatus.NOT_RECONCILED
    )


def test_only_not_reconciled_means_no_comparison_executed() -> None:
    """`reconciled_at` is stamped from this predicate, so it decides
    whether a timestamp is a claim about real evidence."""
    assert not was_comparison_executed(ReconciliationOutcome.NOT_RECONCILED)
    for outcome in (
        ReconciliationOutcome.PASS,
        ReconciliationOutcome.PARTIAL,
        ReconciliationOutcome.FAIL,
    ):
        assert was_comparison_executed(outcome)


# ---------------------------------------------------------------------
# In-memory doubles - the persistence RULE, independent of Django
# ---------------------------------------------------------------------


class _StubArchiveRepository:
    """Records what `save_reconciliation_result` was asked to write,
    without a database, so the persistence RULE can be asserted
    separately from the SQL that carries it out."""

    def __init__(self, bars: tuple[AggregatedBar, ...] = (), *, cells_matched: int = 1) -> None:
        self._bars = bars
        self._cells_matched = cells_matched
        self.writes: list[dict[str, object]] = []
        self.assessments: list[object] = []

    def list_bars(self, **_: object) -> tuple[AggregatedBar, ...]:
        return self._bars

    def archived_symbols_for_trading_date(self, **_: object) -> tuple[str, ...]:
        return ("RELIANCE",)

    def save_reconciliation_result(self, **kwargs: object) -> int:
        self.writes.append(kwargs)
        return self._cells_matched

    # Unused by the persistence path; present so the double satisfies
    # the Protocol's shape rather than a convenient subset of it.
    def quote_summaries_for_trading_date(self, **_: object) -> tuple[object, ...]:
        return ()

    def bar_cells_for_trading_date(self, **_: object) -> tuple[object, ...]:
        return ()

    def save_assessment(self, assessment: object, **_: object) -> None:
        self.assessments.append(assessment)

    def list_archive_days(self, **_: object) -> tuple[object, ...]:
        return ()

    def list_quote_observations(self, **_: object) -> tuple[Quote, ...]:
        return ()


class _StubReferenceRepository:
    def __init__(self, bars: tuple[ReferenceBar, ...] = ()) -> None:
        self._bars = bars

    def reference_bars_for(self, **_: object) -> tuple[ReferenceBar, ...]:
        return self._bars

    def describe_source(self) -> str:
        return "test_reference_pipeline"


def _full_session_timestamps() -> tuple[datetime, ...]:
    return expected_bar_timestamps(build_session_for(TRADING_DAY, AS_OF), Timeframe.ONE_MINUTE)


def _observed(close_timestamps: tuple[datetime, ...]) -> tuple[AggregatedBar, ...]:
    return tuple(
        AggregatedBar(
            instrument_id=RELIANCE,
            timeframe=Timeframe.ONE_MINUTE,
            interval_start=stamp - timedelta(minutes=1),
            interval_end=stamp,
            open=Decimal("100.00"),
            high=Decimal("100.00"),
            low=Decimal("100.00"),
            close=Decimal("100.00"),
            volume=Decimal("0"),
            observation_count=1,
            data_source="test",
            status=BarStatus.CLOSED,
        )
        for stamp in close_timestamps
    )


def _reference(
    close_timestamps: tuple[datetime, ...], *, close: str = "100.00"
) -> tuple[ReferenceBar, ...]:
    return tuple(
        ReferenceBar(
            timestamp=stamp,
            open=Decimal("100.00"),
            high=Decimal("100.00"),
            low=Decimal("100.00"),
            close=Decimal(close),
            volume=Decimal("0"),
        )
        for stamp in close_timestamps
    )


def _service(
    archive: _StubArchiveRepository, reference: _StubReferenceRepository
) -> MarketDataReconciliationPersistenceService:
    return MarketDataReconciliationPersistenceService(
        MarketDataReconciliationService(archive, reference),  # type: ignore[arg-type]
        archive,  # type: ignore[arg-type]
    )


def _persist(
    archive: _StubArchiveRepository, reference: _StubReferenceRepository
) -> tuple[ReconciliationPersistenceResult, dict[str, object]]:
    result = _service(archive, reference).reconcile_and_persist_cell(
        trading_date=TRADING_DAY,
        instrument_symbol="RELIANCE",
        timeframe=Timeframe.ONE_MINUTE,
        as_of=AS_OF,
    )
    return result, archive.writes[-1]


def test_no_reference_bars_persists_not_reconciled_with_null_reconciled_at() -> None:
    """The state of the real database today, and the case the whole
    checkpoint is written to protect: an archived day with NO reference
    series is persisted as NOT_RECONCILED and is NOT stamped with a
    reconciliation time."""
    archive = _StubArchiveRepository(_observed(_full_session_timestamps()))
    result, write = _persist(archive, _StubReferenceRepository(()))

    assert result.report.outcome is ReconciliationOutcome.NOT_RECONCILED
    assert result.report.reason == "no_reference_bars_available"
    assert write["status"] is ReconciliationStatus.NOT_RECONCILED
    assert write["outcome"] is ReconciliationOutcome.NOT_RECONCILED
    assert write["reconciled_at"] is None
    assert result.reconciled_at is None
    assert not result.comparison_executed


def test_full_agreement_persists_reconciled_with_a_real_timestamp() -> None:
    """The positive case, so the negative ones above cannot be passing
    merely because the writer is inert. RECONCILED requires full
    expected-bar coverage on BOTH sides plus zero mismatches."""
    stamps = _full_session_timestamps()
    archive = _StubArchiveRepository(_observed(stamps))
    result, write = _persist(archive, _StubReferenceRepository(_reference(stamps)))

    assert result.report.outcome is ReconciliationOutcome.PASS
    assert write["status"] is ReconciliationStatus.RECONCILED
    assert write["reconciled_at"] == AS_OF
    assert write["evidence_source"] == "test_reference_pipeline"
    assert result.persisted


def test_partial_coverage_never_persists_as_reconciled() -> None:
    """Agreement on a subset is real evidence, but not about the whole
    day. It is stored as NOT_RECONCILED, with the exact PARTIAL verdict
    preserved in the outcome column so nothing is lost."""
    stamps = _full_session_timestamps()
    archive = _StubArchiveRepository(_observed(stamps[:100]))
    result, write = _persist(archive, _StubReferenceRepository(_reference(stamps[:100])))

    assert result.report.outcome is ReconciliationOutcome.PARTIAL
    assert write["status"] is ReconciliationStatus.NOT_RECONCILED
    assert write["outcome"] is ReconciliationOutcome.PARTIAL
    # A comparison DID execute here, so the timestamp is earned.
    assert write["reconciled_at"] == AS_OF


def test_value_disagreement_persists_as_mismatch() -> None:
    stamps = _full_session_timestamps()
    archive = _StubArchiveRepository(_observed(stamps))
    result, write = _persist(archive, _StubReferenceRepository(_reference(stamps, close="180.00")))

    assert result.report.outcome is ReconciliationOutcome.FAIL
    assert write["status"] is ReconciliationStatus.MISMATCH
    assert write["reconciled_at"] == AS_OF


def test_a_failed_calculation_writes_nothing() -> None:
    """Phase 4 atomicity: if the comparison raises, no status is
    recorded. A half-written 'success' is the one outcome worse than a
    crash."""

    class _ExplodingReference(_StubReferenceRepository):
        def reference_bars_for(self, **_: object) -> tuple[ReferenceBar, ...]:
            raise RuntimeError("reference pipeline unavailable")

    archive = _StubArchiveRepository(_observed(_full_session_timestamps()))
    with pytest.raises(RuntimeError):
        _service(archive, _ExplodingReference()).reconcile_and_persist_cell(
            trading_date=TRADING_DAY,
            instrument_symbol="RELIANCE",
            timeframe=Timeframe.ONE_MINUTE,
            as_of=AS_OF,
        )
    assert archive.writes == []


def test_persistence_never_writes_archive_assessment_fields() -> None:
    """The two assessments stay independent: persisting a
    reconciliation must not re-run or re-write the archive status."""
    archive = _StubArchiveRepository(_observed(_full_session_timestamps()))
    _persist(archive, _StubReferenceRepository(()))

    assert archive.assessments == []
    assert set(archive.writes[-1]) == {
        "exchange",
        "trading_date",
        "instrument_symbol",
        "timeframe",
        "status",
        "outcome",
        "reason",
        "evidence_source",
        "reconciled_at",
    }


def test_result_reports_when_no_archive_cell_matched() -> None:
    """A truthful verdict that landed nowhere is reported as not
    persisted rather than silently creating a cell - an archive row
    conjured by a reconciliation would assert observation that never
    happened."""
    archive = _StubArchiveRepository(_observed(_full_session_timestamps()), cells_matched=0)
    result, _ = _persist(archive, _StubReferenceRepository(()))

    assert not result.persisted
    assert result.archive_cells_updated == 0
