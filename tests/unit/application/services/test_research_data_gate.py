# tests/unit/application/services/test_research_data_gate.py
#
# Checkpoint 66.1 Part 11: LIMITED, TARGETED tests for
# `ResearchDataGateService` - the backtest research-data eligibility
# gate. Pure unit tests - an in-memory fake `HistoricalBarReadRepository`
# (satisfying both `get_existing_timestamps` and the new
# `get_bars_with_provenance`), no database. Covers exactly the 10
# checkpoint-directive test cases, no more.
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from intraday.application.services.historical_data_coverage import HistoricalDataCoverageService
from intraday.application.services.research_data_gate import (
    ResearchDataGateService,
    ResearchDataRejectedError,
    ResearchRejectionReason,
)
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.contracts import Bar
from intraday.domain.market_data.provenance import (
    PROVENANCE_REAL_DHAN,
    PROVENANCE_SYNTHETIC_TEST,
    PROVENANCE_UNKNOWN,
)
from intraday.domain.market_data.research_bar import ProvenancedBar
from intraday.domain.market_data.source_timestamp import (
    CANONICALIZATION_STATE_CANONICALIZED,
    CANONICALIZATION_STATE_NOT_APPLICABLE,
    CANONICALIZATION_STATE_UNCANONICALIZED,
    CANONICALIZATION_STATE_UNKNOWN,
    SourceTimestampSemantics,
)
from intraday.domain.session.calendar import CAS_EFFECTIVE_DATE
from intraday.domain.session.resolver import HistoricalEligibility, Regime
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe

# RELIANCE is CATEGORY_I_CAS (domain.session.calendar.CATEGORY_I_CAS_SYMBOLS)
# - used to exercise both PRE_CAS and CAS_ERA resolver context. SBIN is
# CATEGORY_II_NON_CAS - a control for the "no CAS regime confusion"
# concern, matching 65.27's own test precedent.
RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
TIMEFRAME = Timeframe.FIVE_MINUTE


def _bar(minute_offset: int, base: datetime) -> Bar:
    from datetime import timedelta
    from decimal import Decimal

    ts = base + timedelta(minutes=5 * minute_offset)
    return Bar(
        instrument_id=RELIANCE,
        timeframe=TIMEFRAME,
        timestamp=ts,
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100.5"),
        volume=Decimal("1000"),
    )


class _FakeRepository:
    """In-memory fake satisfying `HistoricalBarReadRepository` (both
    `get_existing_timestamps` and `get_bars_with_provenance`) - mirrors
    the `_FakeReadRepository` pattern already used by
    `test_historical_data_coverage.py`, extended with a provenance
    label per bar."""

    def __init__(self, provenanced_bars: tuple[ProvenancedBar, ...]) -> None:
        self._bars = provenanced_bars

    def get_existing_timestamps(self, instrument_id, timeframe, start, end):
        return frozenset(
            pb.bar.timestamp for pb in self._bars if start <= pb.bar.timestamp <= end
        )

    def get_bars_with_provenance(self, instrument_id, timeframe, start, end):
        return tuple(pb for pb in self._bars if start <= pb.bar.timestamp <= end)


def _no_migration_in_flight(**_kwargs):
    """Checkpoint 67.9: this file tests ONLY the pre-existing 66.1/67.3/
    67.4 completeness/provenance/canonicalization gates, never migration
    status - injecting this trivial resolver keeps every test here a
    pure in-memory unit test (no PostgreSQL needed) while still
    exercising the REAL Part 8/9 wiring code path in
    `get_research_eligible_bars` (it always calls the injected resolver;
    this fake just always answers "no migration has ever touched this
    scope", which is what `migration_research_gate_integration.
    resolve_migration_scope_status` also currently answers for every
    real scope today, since this checkpoint populates zero MigrationUnit
    rows). Migration-status wiring itself is proven separately, against
    a REAL resolver and a REAL disposable-DB fixture, in
    `test_checkpoint_67_9_research_gate_migration_wiring.py`."""
    return None


def _gate(provenanced_bars: tuple[ProvenancedBar, ...]) -> ResearchDataGateService:
    repository = _FakeRepository(provenanced_bars)
    return ResearchDataGateService(
        repository=repository,
        coverage_service=HistoricalDataCoverageService(repository=repository),
        migration_status_resolver=_no_migration_in_flight,
    )


# A CAS_ERA trading day (on/after CAS_EFFECTIVE_DATE) with a full RELIANCE
# CATEGORY_I_CAS continuous session's worth of 5-minute bars generated
# via the coverage service's own expected-timestamp logic would be
# elaborate to hand-build; instead these tests use a CATEGORY_II_NON_CAS-
# shaped session by picking a date and relying on `_expected_timestamps`
# exactly as `HistoricalDataCoverageService` computes it, then supplying
# EXACTLY those timestamps as "complete" or deliberately omitting one as
# "incomplete" - so completeness is asserted against the real domain
# logic, never a hand-rolled parallel definition.
def _full_day_bars(
    trading_date,
    provenance: str,
    canonicalization_state: str = CANONICALIZATION_STATE_CANONICALIZED,
    source_timestamp_semantics: str = SourceTimestampSemantics.OPEN.value,
) -> tuple[ProvenancedBar, ...]:
    """`canonicalization_state`/`source_timestamp_semantics` (Checkpoint
    67.3/67.4) default to `CANONICALIZED`/`OPEN` so every PRE-67.4 test
    in this file (which only ever varied `provenance`) keeps its
    original REAL_DHAN-accepted / non-REAL_DHAN-rejected meaning
    unchanged - it now represents "new, already-canonicalized,
    proven-OPEN REAL_DHAN data", the state the corrected 67.4 Dhan
    5m-CAS-era ingestion path actually produces."""
    from intraday.application.services.historical_data_coverage import _expected_timestamps

    start = datetime.combine(trading_date, datetime.min.time(), tzinfo=UTC)
    end = datetime.combine(trading_date, datetime.max.time(), tzinfo=UTC)
    expected = _expected_timestamps(start, end, TIMEFRAME, RELIANCE)
    bars = []
    for ts in expected:
        bars.append(
            ProvenancedBar(
                bar=Bar(
                    instrument_id=RELIANCE,
                    timeframe=TIMEFRAME,
                    timestamp=ts,
                    open=__import__("decimal").Decimal("100"),
                    high=__import__("decimal").Decimal("101"),
                    low=__import__("decimal").Decimal("99"),
                    close=__import__("decimal").Decimal("100.5"),
                    volume=__import__("decimal").Decimal("1000"),
                ),
                provenance=provenance,
                canonicalization_state=canonicalization_state,
                source_timestamp_semantics=source_timestamp_semantics,
            )
        )
    return tuple(bars), start, end


# --- 1. REAL_DHAN -> accepted -----------------------------------------
def test_real_dhan_provenance_is_accepted() -> None:
    bars, start, end = _full_day_bars(CAS_EFFECTIVE_DATE, PROVENANCE_REAL_DHAN)
    gate = _gate(bars)
    result = gate.get_research_eligible_bars(
        RELIANCE, TIMEFRAME, start, end, exchange=Exchange.NSE, segment="CASH_EQUITY", symbol="RELIANCE"
    )
    assert len(result.bars) == len(bars)
    assert result.coverage.is_complete


# --- 2. UNKNOWN -> rejected ---------------------------------------------
def test_unknown_provenance_is_rejected() -> None:
    bars, start, end = _full_day_bars(CAS_EFFECTIVE_DATE, PROVENANCE_UNKNOWN)
    gate = _gate(bars)
    with pytest.raises(ResearchDataRejectedError) as exc_info:
        gate.get_research_eligible_bars(
            RELIANCE, TIMEFRAME, start, end, exchange=Exchange.NSE, segment="CASH_EQUITY", symbol="RELIANCE"
        )
    assert exc_info.value.reason is ResearchRejectionReason.INELIGIBLE_PROVENANCE
    assert "UNKNOWN" in exc_info.value.detail


# --- 3. SYNTHETIC_TEST -> rejected --------------------------------------
def test_synthetic_test_provenance_is_rejected() -> None:
    bars, start, end = _full_day_bars(CAS_EFFECTIVE_DATE, PROVENANCE_SYNTHETIC_TEST)
    gate = _gate(bars)
    with pytest.raises(ResearchDataRejectedError) as exc_info:
        gate.get_research_eligible_bars(
            RELIANCE, TIMEFRAME, start, end, exchange=Exchange.NSE, segment="CASH_EQUITY", symbol="RELIANCE"
        )
    assert exc_info.value.reason is ResearchRejectionReason.INELIGIBLE_PROVENANCE
    assert "SYNTHETIC_TEST" in exc_info.value.detail


# --- 4. incomplete range -> rejected -------------------------------------
def test_incomplete_range_is_rejected() -> None:
    bars, start, end = _full_day_bars(CAS_EFFECTIVE_DATE, PROVENANCE_REAL_DHAN)
    incomplete = bars[:-1]  # drop the last expected bar
    gate = _gate(incomplete)
    with pytest.raises(ResearchDataRejectedError) as exc_info:
        gate.get_research_eligible_bars(
            RELIANCE, TIMEFRAME, start, end, exchange=Exchange.NSE, segment="CASH_EQUITY", symbol="RELIANCE"
        )
    assert exc_info.value.reason is ResearchRejectionReason.INCOMPLETE_COVERAGE


# --- 5. complete range -> accepted (duplicate-safe restatement) --------
def test_complete_range_is_accepted() -> None:
    bars, start, end = _full_day_bars(CAS_EFFECTIVE_DATE, PROVENANCE_REAL_DHAN)
    gate = _gate(bars)
    result = gate.get_research_eligible_bars(
        RELIANCE, TIMEFRAME, start, end, exchange=Exchange.NSE, segment="CASH_EQUITY", symbol="RELIANCE"
    )
    assert result.coverage.is_complete
    assert len(result.bars) == result.coverage.expected_bar_count


# --- 6. PRE_CAS resolver context ----------------------------------------
def test_pre_cas_resolver_context_is_attached() -> None:
    from datetime import timedelta

    # 21 days = exactly 3 weeks before CAS_EFFECTIVE_DATE (a Monday) -
    # same weekday, and not in NSE_HOLIDAYS_2026, so it is a genuine
    # trading day the coverage service's own calendar logic recognizes.
    pre_cas_date = CAS_EFFECTIVE_DATE - timedelta(days=21)
    bars, start, end = _full_day_bars(pre_cas_date, PROVENANCE_REAL_DHAN)
    gate = _gate(bars)
    result = gate.get_research_eligible_bars(
        RELIANCE, TIMEFRAME, start, end, exchange=Exchange.NSE, segment="CASH_EQUITY", symbol="RELIANCE"
    )
    assert pre_cas_date in result.sessions_by_date
    assert result.sessions_by_date[pre_cas_date].regime is Regime.PRE_CAS


# --- 7. CAS_ERA resolver context -----------------------------------------
def test_cas_era_resolver_context_is_attached() -> None:
    bars, start, end = _full_day_bars(CAS_EFFECTIVE_DATE, PROVENANCE_REAL_DHAN)
    gate = _gate(bars)
    result = gate.get_research_eligible_bars(
        RELIANCE, TIMEFRAME, start, end, exchange=Exchange.NSE, segment="CASH_EQUITY", symbol="RELIANCE"
    )
    assert CAS_EFFECTIVE_DATE in result.sessions_by_date
    assert result.sessions_by_date[CAS_EFFECTIVE_DATE].regime is Regime.CAS_ERA


# --- 8. historical eligibility UNKNOWN behavior --------------------------
def test_historical_eligibility_is_unknown_historical_for_backtest_reads() -> None:
    bars, start, end = _full_day_bars(CAS_EFFECTIVE_DATE, PROVENANCE_REAL_DHAN)
    gate = _gate(bars)
    result = gate.get_research_eligible_bars(
        RELIANCE, TIMEFRAME, start, end, exchange=Exchange.NSE, segment="CASH_EQUITY", symbol="RELIANCE"
    )
    session = result.sessions_by_date[CAS_EFFECTIVE_DATE]
    assert session.historical_eligibility is HistoricalEligibility.UNKNOWN_HISTORICAL
    assert session.historical_eligibility_unknown is True


# --- 9. no silent gap filling --------------------------------------------
def test_incomplete_range_never_returns_a_gap_filled_result() -> None:
    bars, start, end = _full_day_bars(CAS_EFFECTIVE_DATE, PROVENANCE_REAL_DHAN)
    incomplete = bars[:-1]
    gate = _gate(incomplete)
    try:
        gate.get_research_eligible_bars(
            RELIANCE, TIMEFRAME, start, end, exchange=Exchange.NSE, segment="CASH_EQUITY", symbol="RELIANCE"
        )
        raised = False
    except ResearchDataRejectedError:
        raised = True
    # The gate must reject outright - it must never have returned a
    # `ResearchEligibleBars` with a synthesized/interpolated bar in
    # place of the missing one.
    assert raised is True


# --- 10. rejection reason is observable ----------------------------------
def test_rejection_reason_and_detail_are_observable_on_the_exception() -> None:
    bars, start, end = _full_day_bars(CAS_EFFECTIVE_DATE, PROVENANCE_UNKNOWN)
    gate = _gate(bars)
    with pytest.raises(ResearchDataRejectedError) as exc_info:
        gate.get_research_eligible_bars(
            RELIANCE, TIMEFRAME, start, end, exchange=Exchange.NSE, segment="CASH_EQUITY", symbol="RELIANCE"
        )
    error = exc_info.value
    assert isinstance(error.reason, ResearchRejectionReason)
    assert isinstance(error.detail, str) and len(error.detail) > 0
    assert error.reason.value in str(error)


# --- Checkpoint 67.4: split semantics/canonicalization-state gate --------
# The Part 9 eligibility matrix, plus the double-canonicalization proof.
# `_full_day_bars` defaults to CANONICALIZED/OPEN so only the dimension
# under test needs to be overridden per case.


def test_open_uncanonicalized_is_rejected() -> None:
    """Matrix row 2: REAL_DHAN, OPEN semantics, UNCANONICALIZED state ->
    NO. Proven semantics alone is not enough - the shift must have
    actually run."""
    bars, start, end = _full_day_bars(
        CAS_EFFECTIVE_DATE,
        PROVENANCE_REAL_DHAN,
        canonicalization_state=CANONICALIZATION_STATE_UNCANONICALIZED,
        source_timestamp_semantics=SourceTimestampSemantics.OPEN.value,
    )
    gate = _gate(bars)
    with pytest.raises(ResearchDataRejectedError) as exc_info:
        gate.get_research_eligible_bars(
            RELIANCE, TIMEFRAME, start, end, exchange=Exchange.NSE, segment="CASH_EQUITY", symbol="RELIANCE"
        )
    assert exc_info.value.reason is ResearchRejectionReason.UNCANONICALIZED_TIMESTAMP
    assert "UNCANONICALIZED" in exc_info.value.detail


def test_open_canonicalized_is_accepted() -> None:
    """Matrix row 1: REAL_DHAN, OPEN semantics, CANONICALIZED state ->
    YES. This is `_full_day_bars`'s default; restated explicitly here."""
    bars, start, end = _full_day_bars(CAS_EFFECTIVE_DATE, PROVENANCE_REAL_DHAN)
    gate = _gate(bars)
    result = gate.get_research_eligible_bars(
        RELIANCE, TIMEFRAME, start, end, exchange=Exchange.NSE, segment="CASH_EQUITY", symbol="RELIANCE"
    )
    assert len(result.bars) == len(bars)


def test_unknown_semantics_canonicalized_is_rejected() -> None:
    """Matrix row 3, and Checkpoint 67.4's core fix / Part 13 test 3:
    REAL_DHAN, UNKNOWN semantics, CANONICALIZED state -> NO. This is
    EXACTLY the bug 67.3's review found: the `+interval` arithmetic
    having run (`canonicalization_state=CANONICALIZED`) must never be
    treated as proof the shift was semantically justified when
    `source_timestamp_semantics` is still UNKNOWN - the real-world
    manifestation being 1m/PRE-CAS-5m Dhan data."""
    bars, start, end = _full_day_bars(
        CAS_EFFECTIVE_DATE,
        PROVENANCE_REAL_DHAN,
        canonicalization_state=CANONICALIZATION_STATE_CANONICALIZED,
        source_timestamp_semantics=SourceTimestampSemantics.UNKNOWN.value,
    )
    gate = _gate(bars)
    with pytest.raises(ResearchDataRejectedError) as exc_info:
        gate.get_research_eligible_bars(
            RELIANCE, TIMEFRAME, start, end, exchange=Exchange.NSE, segment="CASH_EQUITY", symbol="RELIANCE"
        )
    assert exc_info.value.reason is ResearchRejectionReason.UNCANONICALIZED_TIMESTAMP
    assert "source_timestamp_semantics=UNKNOWN" in exc_info.value.detail


def test_unknown_semantics_uncanonicalized_is_rejected() -> None:
    """Matrix row 4: REAL_DHAN, UNKNOWN semantics, UNCANONICALIZED state
    -> NO. Both dimensions fail simultaneously - the worst case, still
    rejected outright."""
    bars, start, end = _full_day_bars(
        CAS_EFFECTIVE_DATE,
        PROVENANCE_REAL_DHAN,
        canonicalization_state=CANONICALIZATION_STATE_UNCANONICALIZED,
        source_timestamp_semantics=SourceTimestampSemantics.UNKNOWN.value,
    )
    gate = _gate(bars)
    with pytest.raises(ResearchDataRejectedError) as exc_info:
        gate.get_research_eligible_bars(
            RELIANCE, TIMEFRAME, start, end, exchange=Exchange.NSE, segment="CASH_EQUITY", symbol="RELIANCE"
        )
    assert exc_info.value.reason is ResearchRejectionReason.UNCANONICALIZED_TIMESTAMP


def test_close_canonicalized_is_accepted() -> None:
    """Matrix row 5: REAL_DHAN, CLOSE semantics, CANONICALIZED state ->
    YES (only if independently supported - CLOSE semantics require no
    shift by definition, so a row genuinely carrying that proven
    classification is accepted, exactly like OPEN)."""
    bars, start, end = _full_day_bars(
        CAS_EFFECTIVE_DATE,
        PROVENANCE_REAL_DHAN,
        canonicalization_state=CANONICALIZATION_STATE_CANONICALIZED,
        source_timestamp_semantics=SourceTimestampSemantics.CLOSE.value,
    )
    gate = _gate(bars)
    result = gate.get_research_eligible_bars(
        RELIANCE, TIMEFRAME, start, end, exchange=Exchange.NSE, segment="CASH_EQUITY", symbol="RELIANCE"
    )
    assert len(result.bars) == len(bars)


def test_unknown_provenance_unknown_everything_is_rejected() -> None:
    """Matrix row 6: UNKNOWN provenance, UNKNOWN semantics, UNKNOWN
    state -> NO. Rejected at the provenance gate before the
    canonicalization gate is even reached."""
    bars, start, end = _full_day_bars(
        CAS_EFFECTIVE_DATE,
        PROVENANCE_UNKNOWN,
        canonicalization_state=CANONICALIZATION_STATE_UNKNOWN,
        source_timestamp_semantics=SourceTimestampSemantics.UNKNOWN.value,
    )
    gate = _gate(bars)
    with pytest.raises(ResearchDataRejectedError) as exc_info:
        gate.get_research_eligible_bars(
            RELIANCE, TIMEFRAME, start, end, exchange=Exchange.NSE, segment="CASH_EQUITY", symbol="RELIANCE"
        )
    assert exc_info.value.reason is ResearchRejectionReason.INELIGIBLE_PROVENANCE


def test_synthetic_test_not_applicable_is_rejected() -> None:
    """Matrix row 7: SYNTHETIC_TEST provenance, N/A semantics, N/A state
    -> NO. Rejected at the provenance gate."""
    bars, start, end = _full_day_bars(
        CAS_EFFECTIVE_DATE,
        PROVENANCE_SYNTHETIC_TEST,
        canonicalization_state=CANONICALIZATION_STATE_NOT_APPLICABLE,
        source_timestamp_semantics=SourceTimestampSemantics.NOT_APPLICABLE.value,
    )
    gate = _gate(bars)
    with pytest.raises(ResearchDataRejectedError) as exc_info:
        gate.get_research_eligible_bars(
            RELIANCE, TIMEFRAME, start, end, exchange=Exchange.NSE, segment="CASH_EQUITY", symbol="RELIANCE"
        )
    assert exc_info.value.reason is ResearchRejectionReason.INELIGIBLE_PROVENANCE


def test_not_applicable_canonicalization_state_real_dhan_is_rejected() -> None:
    """A REAL_DHAN row somehow marked NOT_APPLICABLE (a state reserved
    for non-REAL_DHAN rows) must still be rejected, never treated as
    research-ready by default."""
    bars, start, end = _full_day_bars(
        CAS_EFFECTIVE_DATE,
        PROVENANCE_REAL_DHAN,
        canonicalization_state=CANONICALIZATION_STATE_NOT_APPLICABLE,
        source_timestamp_semantics=SourceTimestampSemantics.NOT_APPLICABLE.value,
    )
    gate = _gate(bars)
    with pytest.raises(ResearchDataRejectedError) as exc_info:
        gate.get_research_eligible_bars(
            RELIANCE, TIMEFRAME, start, end, exchange=Exchange.NSE, segment="CASH_EQUITY", symbol="RELIANCE"
        )
    assert exc_info.value.reason is ResearchRejectionReason.UNCANONICALIZED_TIMESTAMP


def test_canonical_row_is_never_double_shifted() -> None:
    """Part 7/13 test 7: the gate must be a pure PASS-THROUGH of
    `bar.timestamp` for CANONICALIZED+OPEN rows - it must never re-apply
    any shift of its own. Every returned bar's timestamp is asserted
    byte-identical to the corresponding input `ProvenancedBar.bar.
    timestamp`."""
    bars, start, end = _full_day_bars(CAS_EFFECTIVE_DATE, PROVENANCE_REAL_DHAN)
    gate = _gate(bars)
    result = gate.get_research_eligible_bars(
        RELIANCE, TIMEFRAME, start, end, exchange=Exchange.NSE, segment="CASH_EQUITY", symbol="RELIANCE"
    )
    input_timestamps = sorted(pb.bar.timestamp for pb in bars)
    output_timestamps = sorted(bar.timestamp for bar in result.bars)
    assert output_timestamps == input_timestamps


def test_synthetic_test_provenance_remains_not_applicable_semantics() -> None:
    """Part 13 test 8: SYNTHETIC_TEST rows stay N/A on both dimensions
    and are rejected purely on the provenance gate - never promoted to
    research-ready via the canonicalization gate."""
    bars, start, end = _full_day_bars(
        CAS_EFFECTIVE_DATE,
        PROVENANCE_SYNTHETIC_TEST,
        canonicalization_state=CANONICALIZATION_STATE_NOT_APPLICABLE,
        source_timestamp_semantics=SourceTimestampSemantics.NOT_APPLICABLE.value,
    )
    for pb in bars:
        assert pb.source_timestamp_semantics == SourceTimestampSemantics.NOT_APPLICABLE.value
        assert pb.canonicalization_state == CANONICALIZATION_STATE_NOT_APPLICABLE
    gate = _gate(bars)
    with pytest.raises(ResearchDataRejectedError):
        gate.get_research_eligible_bars(
            RELIANCE, TIMEFRAME, start, end, exchange=Exchange.NSE, segment="CASH_EQUITY", symbol="RELIANCE"
        )


def test_unknown_provenance_row_stays_unknown_semantics_unless_proven() -> None:
    """Part 13 test 9: an UNKNOWN-provenance row's
    source_timestamp_semantics stays UNKNOWN (never silently proven) -
    verified directly on the `ProvenancedBar`, independent of the gate's
    rejection (already covered by the provenance gate)."""
    bars, _, _ = _full_day_bars(
        CAS_EFFECTIVE_DATE,
        PROVENANCE_UNKNOWN,
        canonicalization_state=CANONICALIZATION_STATE_UNKNOWN,
        source_timestamp_semantics=SourceTimestampSemantics.UNKNOWN.value,
    )
    for pb in bars:
        assert pb.source_timestamp_semantics == SourceTimestampSemantics.UNKNOWN.value
