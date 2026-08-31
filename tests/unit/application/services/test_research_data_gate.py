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


def _gate(provenanced_bars: tuple[ProvenancedBar, ...]) -> ResearchDataGateService:
    repository = _FakeRepository(provenanced_bars)
    return ResearchDataGateService(
        repository=repository,
        coverage_service=HistoricalDataCoverageService(repository=repository),
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
def _full_day_bars(trading_date, provenance: str) -> tuple[ProvenancedBar, ...]:
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
