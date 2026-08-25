# File: tests/unit/research/test_checkpoint_64_79_equity_reconciliation.py
#
# Checkpoint 64.79: proof tests for the equity market-data
# reconciliation contract.
#
# DETERMINISTIC and OFFLINE by construction - not one test opens a
# socket, contacts Dhan, starts the live worker, or touches the option
# (NSE_FNO) track, which is frozen as future scope.
#
# The tests are deliberately weighted toward the NEGATIVE cases. The
# risk this contract exists to eliminate is a FABRICATED PASS - a
# reconciliation that reports agreement it never observed - so the most
# important assertions here are the ones proving PASS is unreachable
# without real, complete, agreeing reference data.
from __future__ import annotations

import datetime as dt
from datetime import date, timedelta
from decimal import Decimal

import pytest

from intraday.domain.market_data.archive import TradingSessionIdentity
from intraday.domain.market_data.quality import expected_bar_timestamps
from intraday.domain.market_data.reconciliation import (
    ObservedBar,
    ReconciliationOutcome,
    ReconciliationTolerance,
    ReferenceBar,
    reconcile_bar_series,
)
from intraday.domain.session.calendar import build_session_for
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe

TRADING_DAY = date(2026, 8, 25)  # Tuesday, not an NSE 2026 holiday
AFTER_CLOSE = dt.datetime(2026, 8, 25, 12, 0, tzinfo=dt.UTC)  # 17:30 IST
EVIDENCE = "dhan_historical_candle_api"

IDENTITY = TradingSessionIdentity(exchange=Exchange.NSE, trading_date=TRADING_DAY)
SESSION = build_session_for(TRADING_DAY, AFTER_CLOSE)


def _full_expected(timeframe: Timeframe = Timeframe.FIVE_MINUTE) -> tuple[dt.datetime, ...]:
    return expected_bar_timestamps(SESSION, timeframe)


def _observed(stamp: dt.datetime, close: str = "100.00") -> ObservedBar:
    return ObservedBar(
        timestamp=stamp,
        open=Decimal("100.00"),
        high=Decimal("101.00"),
        low=Decimal("99.00"),
        close=Decimal(close),
        volume=Decimal("500"),
    )


def _reference(stamp: dt.datetime, close: str = "100.00") -> ReferenceBar:
    return ReferenceBar(
        timestamp=stamp,
        open=Decimal("100.00"),
        high=Decimal("101.00"),
        low=Decimal("99.00"),
        close=Decimal(close),
        volume=Decimal("500"),
    )


def _reconcile(observed, reference, *, timeframe=Timeframe.FIVE_MINUTE, tolerance=None):
    return reconcile_bar_series(
        identity=IDENTITY,
        instrument_symbol="TCS",
        timeframe=timeframe,
        session=SESSION,
        observed_bars=observed,
        reference_bars=reference,
        evidence_source=EVIDENCE,
        tolerance=tolerance,
    )


# ---------------------------------------------------------------------
# The central honesty rules: PASS must be unreachable without evidence
# ---------------------------------------------------------------------


def test_empty_reference_is_not_reconciled_never_pass() -> None:
    """ "Nothing disagreed with us" is not evidence of agreement. This is
    the single most important assertion in this file - it is the exact
    shape a fabricated PASS would take."""
    stamps = _full_expected()
    report = _reconcile(tuple(_observed(s) for s in stamps), ())
    assert report.outcome is ReconciliationOutcome.NOT_RECONCILED
    assert report.reason == "no_reference_bars_available"
    assert report.is_independently_validated is False


def test_empty_observed_is_not_reconciled() -> None:
    stamps = _full_expected()
    report = _reconcile((), tuple(_reference(s) for s in stamps))
    assert report.outcome is ReconciliationOutcome.NOT_RECONCILED
    assert report.reason == "no_observed_bars_to_reconcile"


def test_both_empty_is_not_reconciled_not_pass() -> None:
    report = _reconcile((), ())
    assert report.outcome is ReconciliationOutcome.NOT_RECONCILED


def test_unsupported_timeframe_is_not_reconciled() -> None:
    """30m has no defensible expected-bar count against the 375-minute
    NSE session (`is_completeness_supported`), so no reconciliation
    verdict can be earned for it - NOT_RECONCILED, never PASS."""
    stamps = _full_expected(Timeframe.THIRTY_MINUTE)
    report = _reconcile(
        tuple(_observed(s) for s in stamps),
        tuple(_reference(s) for s in stamps),
        timeframe=Timeframe.THIRTY_MINUTE,
    )
    assert report.outcome is ReconciliationOutcome.NOT_RECONCILED
    assert report.reason.startswith("completeness_unsupported_timeframe")


def test_empty_evidence_source_is_rejected() -> None:
    """An unattributed reference is not evidence and must not produce a
    report at all."""
    with pytest.raises(ValueError, match="evidence_source"):
        reconcile_bar_series(
            identity=IDENTITY,
            instrument_symbol="TCS",
            timeframe=Timeframe.FIVE_MINUTE,
            session=SESSION,
            observed_bars=(),
            reference_bars=(),
            evidence_source="   ",
        )


# ---------------------------------------------------------------------
# PASS is reachable only with full, agreeing coverage on both sides
# ---------------------------------------------------------------------


def test_full_agreement_passes() -> None:
    stamps = _full_expected()
    report = _reconcile(tuple(_observed(s) for s in stamps), tuple(_reference(s) for s in stamps))
    assert report.outcome is ReconciliationOutcome.PASS
    assert report.is_independently_validated is True
    assert report.matched_bar_count == len(stamps) == 75
    assert report.expected_bar_count == 75
    assert report.mismatch_count == 0
    assert report.evidence_source == EVIDENCE


def test_partial_observed_coverage_is_partial_not_pass() -> None:
    """Agreement on a subset is real evidence, but says nothing about
    the rest of the day."""
    stamps = _full_expected()
    report = _reconcile(
        tuple(_observed(s) for s in stamps[:40]), tuple(_reference(s) for s in stamps)
    )
    assert report.outcome is ReconciliationOutcome.PARTIAL
    assert report.is_independently_validated is False
    assert len(report.observed_missing_timestamps) == 35
    assert report.reference_missing_timestamps == ()


def test_partial_reference_coverage_is_partial() -> None:
    stamps = _full_expected()
    report = _reconcile(
        tuple(_observed(s) for s in stamps), tuple(_reference(s) for s in stamps[:40])
    )
    assert report.outcome is ReconciliationOutcome.PARTIAL
    assert len(report.reference_missing_timestamps) == 35
    assert len(report.unmatched_observed_timestamps) == 35


# ---------------------------------------------------------------------
# FAIL beats PARTIAL: a wrong price is a stronger finding than a gap
# ---------------------------------------------------------------------


def test_price_mismatch_beyond_tolerance_fails() -> None:
    stamps = _full_expected()
    observed = [_observed(s) for s in stamps]
    observed[7] = _observed(stamps[7], close="105.00")
    report = _reconcile(tuple(observed), tuple(_reference(s) for s in stamps))
    assert report.outcome is ReconciliationOutcome.FAIL
    assert report.reason == "value_mismatches:1"
    mismatch = report.mismatches[0]
    assert mismatch.field_name == "close"
    assert mismatch.observed == Decimal("105.00")
    assert mismatch.reference == Decimal("100.00")
    assert mismatch.delta == Decimal("5.00")


def test_price_difference_within_tolerance_still_passes() -> None:
    """Live-aggregated and provider-consolidated candles are built from
    different inputs; a 1-paisa difference is sampling reality, not a
    data-quality defect."""
    stamps = _full_expected()
    observed = [_observed(s) for s in stamps]
    observed[3] = _observed(stamps[3], close="100.01")
    report = _reconcile(tuple(observed), tuple(_reference(s) for s in stamps))
    assert report.outcome is ReconciliationOutcome.PASS


def test_mismatch_outranks_missing_coverage() -> None:
    """A day with BOTH a gap and a wrong price is FAIL, not PARTIAL."""
    stamps = _full_expected()
    observed = [_observed(s) for s in stamps[:40]]
    observed[2] = _observed(stamps[2], close="130.00")
    report = _reconcile(tuple(observed), tuple(_reference(s) for s in stamps))
    assert report.outcome is ReconciliationOutcome.FAIL


def test_duplicate_observed_timestamp_fails() -> None:
    stamps = _full_expected()
    observed = tuple(_observed(s) for s in stamps) + (_observed(stamps[0]),)
    report = _reconcile(observed, tuple(_reference(s) for s in stamps))
    assert report.outcome is ReconciliationOutcome.FAIL
    assert report.observed_duplicate_timestamps == (stamps[0],)


def test_duplicate_reference_timestamp_fails() -> None:
    stamps = _full_expected()
    reference = tuple(_reference(s) for s in stamps) + (_reference(stamps[5]),)
    report = _reconcile(tuple(_observed(s) for s in stamps), reference)
    assert report.outcome is ReconciliationOutcome.FAIL
    assert report.reference_duplicate_timestamps == (stamps[5],)


# ---------------------------------------------------------------------
# Tolerance semantics
# ---------------------------------------------------------------------


def test_zero_timestamp_tolerance_never_pairs_different_intervals() -> None:
    """The default zero timestamp tolerance must not silently pair a bar
    with its neighbour - drift is a real finding."""
    stamps = _full_expected()
    shifted = tuple(_reference(s + timedelta(minutes=1)) for s in stamps)
    report = _reconcile(tuple(_observed(s) for s in stamps), shifted)
    assert report.outcome is ReconciliationOutcome.PARTIAL
    assert report.matched_bar_count == 0
    assert len(report.unmatched_observed_timestamps) == len(stamps)


def test_timestamp_tolerance_matches_nearby_bar_when_configured() -> None:
    stamps = _full_expected()
    shifted = tuple(_reference(s + timedelta(seconds=2)) for s in stamps)
    report = _reconcile(
        tuple(_observed(s) for s in stamps),
        shifted,
        tolerance=ReconciliationTolerance(timestamp=timedelta(seconds=5)),
    )
    assert report.matched_bar_count == len(stamps)
    # Still PARTIAL, not PASS: the reference series does not itself
    # cover the expected grid, and that limitation must stay visible.
    assert report.outcome is ReconciliationOutcome.PARTIAL


def test_volume_is_not_compared_by_default() -> None:
    """This platform's live bars carry Decimal("0") volume for every
    quote source that never reported cumulative_volume. Comparing a
    known-unmeasured zero against a real reference volume would report a
    fabricated FAIL."""
    stamps = _full_expected()
    observed = tuple(
        ObservedBar(
            timestamp=s,
            open=Decimal("100.00"),
            high=Decimal("101.00"),
            low=Decimal("99.00"),
            close=Decimal("100.00"),
            volume=Decimal("0"),
        )
        for s in stamps
    )
    report = _reconcile(observed, tuple(_reference(s) for s in stamps))
    assert report.outcome is ReconciliationOutcome.PASS

    strict = _reconcile(
        observed,
        tuple(_reference(s) for s in stamps),
        tolerance=ReconciliationTolerance(compare_volume=True),
    )
    assert strict.outcome is ReconciliationOutcome.FAIL
    assert all(m.field_name == "volume" for m in strict.mismatches)


def test_negative_tolerances_are_rejected() -> None:
    with pytest.raises(ValueError):
        ReconciliationTolerance(price=Decimal("-1"))
    with pytest.raises(ValueError):
        ReconciliationTolerance(volume=Decimal("-1"))
    with pytest.raises(ValueError):
        ReconciliationTolerance(timestamp=timedelta(seconds=-1))


# ---------------------------------------------------------------------
# Report completeness: every field the 64.79 contract requires
# ---------------------------------------------------------------------


def test_report_carries_full_contract_surface() -> None:
    stamps = _full_expected()
    report = _reconcile(
        tuple(_observed(s) for s in stamps[:10]), tuple(_reference(s) for s in stamps[:10])
    )
    assert report.identity.trading_date == TRADING_DAY
    assert report.identity.key == "NSE:2026-08-25"
    assert report.instrument_symbol == "TCS"
    assert report.timeframe is Timeframe.FIVE_MINUTE
    assert report.observed_first_timestamp == stamps[0]
    assert report.observed_last_timestamp == stamps[9]
    assert report.reference_first_timestamp == stamps[0]
    assert report.reference_last_timestamp == stamps[9]
    assert report.observed_bar_count == 10
    assert report.reference_bar_count == 10
    assert report.tolerance.price == Decimal("0.05")


def test_naive_timestamps_are_rejected() -> None:
    with pytest.raises(ValueError):
        ObservedBar(
            timestamp=dt.datetime(2026, 8, 25, 4, 0),
            open=Decimal("1"),
            high=Decimal("1"),
            low=Decimal("1"),
            close=Decimal("1"),
        )
    with pytest.raises(ValueError):
        ReferenceBar(
            timestamp=dt.datetime(2026, 8, 25, 4, 0),
            open=Decimal("1"),
            high=Decimal("1"),
            low=Decimal("1"),
            close=Decimal("1"),
        )
