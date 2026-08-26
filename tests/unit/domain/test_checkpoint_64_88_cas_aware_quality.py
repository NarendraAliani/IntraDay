# tests/unit/domain/test_checkpoint_64_88_cas_aware_quality.py
#
# Checkpoint 64.88: CAS-aware archive, missing-interval, reconciliation
# and quality-report coverage. Pure Python - no database, no Django.
#
# Includes the 64.85 REPLAY the checkpoint directive requires: 15:14:59
# IST -> CAS begins at 15:15 -> no continuous observations during CAS ->
# a provider observation arrives at 15:28:49 IST -> CAS ends at 15:35.
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from intraday.application.reporting.market_data_quality_report import (
    CasDataQualityLabel,
    classify_cas_data_quality,
)
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.archive import (
    ArchiveStatus,
    TradingSessionIdentity,
    assess_archive_day,
    is_continuous_completeness_supported,
)
from intraday.domain.market_data.contracts import Bar
from intraday.domain.market_data.quality import (
    CasWindowStatus,
    ObservationSessionClassification,
    classify_cas_window_status,
    classify_observation_session,
    missing_continuous_bar_timestamps,
)
from intraday.domain.market_data.reconciliation import (
    ObservedBar,
    ReconciliationOutcome,
    ReferenceBar,
    reconcile_bar_series,
)
from intraday.domain.session.calendar import build_cas_aware_session_for, build_session_for
from intraday.domain.session.contracts import InstrumentCategory, MarketSessionState
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe

TRADING_DAY = date(2026, 8, 25)  # Tuesday, a trading day
CATEGORY_I = InstrumentCategory.CATEGORY_I_CAS
CATEGORY_II = InstrumentCategory.CATEGORY_II_NON_CAS
RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
SBIN = make_instrument_id(Exchange.NSE, "SBIN")  # not in CATEGORY_I_CAS_SYMBOLS


def _ist(hour: int, minute: int, second: int = 0) -> datetime:
    naive_ist = datetime(2026, 8, 25, hour, minute, second)
    return (naive_ist + timedelta(hours=-5, minutes=-30)).replace(tzinfo=UTC)


def _cas_session(category: InstrumentCategory, as_of: datetime):
    return build_cas_aware_session_for(category, TRADING_DAY, as_of)


def _bar(instrument, minute_close: datetime) -> Bar:
    return Bar(
        instrument_id=instrument,
        timeframe=Timeframe.ONE_MINUTE,
        timestamp=minute_close,
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100.5"),
        volume=Decimal("0"),
    )


# --- Category-I continuous completeness ---------------------------------


def test_category_i_continuous_completeness_stops_at_1515() -> None:
    session = _cas_session(CATEGORY_I, _ist(17, 30))
    assert session.expected_continuous_bar_timestamps(timedelta(minutes=1))[-1] == _ist(15, 15)
    assert len(session.expected_continuous_bar_timestamps(timedelta(minutes=1))) == 360


def test_category_i_missing_continuous_bars_excludes_cas_window() -> None:
    session = _cas_session(CATEGORY_I, _ist(17, 30))
    # Full continuous coverage 09:15-15:15, nothing else.
    expected = session.expected_continuous_bar_timestamps(timedelta(minutes=1))
    bars = tuple(_bar(RELIANCE, ts) for ts in expected)
    missing = missing_continuous_bar_timestamps(bars, session, Timeframe.ONE_MINUTE)
    assert missing == ()


def test_category_i_genuine_continuous_gap_still_detected() -> None:
    """A real gap WITHIN continuous trading must still be flagged - CAS
    awareness must never suppress a genuine defect."""
    session = _cas_session(CATEGORY_I, _ist(17, 30))
    expected = session.expected_continuous_bar_timestamps(timedelta(minutes=1))
    bars = tuple(_bar(RELIANCE, ts) for ts in expected if ts != _ist(10, 0))
    missing = missing_continuous_bar_timestamps(bars, session, Timeframe.ONE_MINUTE)
    assert missing == (_ist(10, 0),)


# --- Category-I CAS expected-non-continuous ------------------------------


@pytest.mark.parametrize("hour,minute,second", [(15, 15, 0), (15, 20, 0), (15, 34, 59)])
def test_category_i_cas_window_status_expected_non_continuous(
    hour: int, minute: int, second: int
) -> None:
    session = _cas_session(CATEGORY_I, _ist(hour, minute, second))
    assert session.state is MarketSessionState.CAS
    assert classify_cas_window_status(session) is CasWindowStatus.EXPECTED_NON_CONTINUOUS


def test_category_i_post_cas_is_provider_behavior_unknown() -> None:
    session = _cas_session(CATEGORY_I, _ist(15, 35, 0))
    assert session.state is MarketSessionState.POST_CAS_TRANSITION
    assert classify_cas_window_status(session) is CasWindowStatus.PROVIDER_BEHAVIOR_UNKNOWN


def test_category_i_continuous_trading_cas_status_not_applicable() -> None:
    session = _cas_session(CATEGORY_I, _ist(12, 0, 0))
    assert classify_cas_window_status(session) is CasWindowStatus.NOT_APPLICABLE


# --- Category-II unchanged ------------------------------------------------


def test_category_ii_continuous_completeness_unchanged_through_1530() -> None:
    session = _cas_session(CATEGORY_II, _ist(17, 30))
    stamps = session.expected_continuous_bar_timestamps(timedelta(minutes=1))
    assert stamps[-1] == _ist(15, 30)
    assert len(stamps) == 375


def test_category_ii_never_reports_cas_window_status() -> None:
    for hour, minute in ((9, 15), (12, 0), (15, 20), (15, 30), (16, 0)):
        session = _cas_session(CATEGORY_II, _ist(hour, minute))
        assert classify_cas_window_status(session) is CasWindowStatus.NOT_APPLICABLE


def test_category_ii_close_behavior_unchanged() -> None:
    session = _cas_session(CATEGORY_II, _ist(15, 30, 1))
    assert session.state is MarketSessionState.CLOSED


# --- Archive: assess_archive_day CAS-aware --------------------------------


def _identity() -> TradingSessionIdentity:
    return TradingSessionIdentity(exchange=Exchange.NSE, trading_date=TRADING_DAY)


def test_archive_category_i_complete_continuous_session_without_cas_bars() -> None:
    as_of = _ist(17, 30)
    session = build_session_for(TRADING_DAY, as_of)
    cas_session = _cas_session(CATEGORY_I, as_of)
    closed = cas_session.expected_continuous_bar_timestamps(timedelta(minutes=1))

    assessment = assess_archive_day(
        identity=_identity(),
        instrument_symbol="RELIANCE",
        timeframe=Timeframe.ONE_MINUTE,
        data_source="dhan",
        session=session,
        closed_bar_timestamps=closed,
        forming_bar_count=0,
        quote_observation_count=len(closed),
        first_observation_at=closed[0],
        last_observation_at=closed[-1],
        as_of=as_of,
        cas_session=cas_session,
    )
    # Only 360 continuous bars ever existed for this symbol - COMPLETE,
    # never PARTIAL merely because no CAS-window bars were archived.
    assert assessment.status is ArchiveStatus.COMPLETE
    assert assessment.expected_bar_count == 360
    assert assessment.missing_bar_count == 0
    assert assessment.cas_window_status is CasWindowStatus.PROVIDER_BEHAVIOR_UNKNOWN


def test_archive_category_i_without_cas_session_keeps_old_375_behavior() -> None:
    """Omitting `cas_session` (every pre-64.88 call site) is unchanged -
    the 64.87-era 09:15-15:30 expectation is still applied."""
    as_of = _ist(17, 30)
    session = build_session_for(TRADING_DAY, as_of)
    stamps = session_expected_1m(session)

    assessment = assess_archive_day(
        identity=_identity(),
        instrument_symbol="RELIANCE",
        timeframe=Timeframe.ONE_MINUTE,
        data_source="dhan",
        session=session,
        closed_bar_timestamps=stamps,
        forming_bar_count=0,
        quote_observation_count=len(stamps),
        first_observation_at=stamps[0],
        last_observation_at=stamps[-1],
        as_of=as_of,
    )
    assert assessment.expected_bar_count == 375
    assert assessment.cas_window_status is CasWindowStatus.NOT_APPLICABLE


def session_expected_1m(session):
    from intraday.domain.market_data.quality import expected_bar_timestamps

    return expected_bar_timestamps(session, Timeframe.ONE_MINUTE)


def test_is_continuous_completeness_supported_category_i() -> None:
    cas_session = _cas_session(CATEGORY_I, _ist(17, 30))
    assert is_continuous_completeness_supported(Timeframe.ONE_MINUTE, cas_session)
    assert is_continuous_completeness_supported(Timeframe.FIVE_MINUTE, cas_session)


def test_is_continuous_completeness_supported_category_ii_matches_plain() -> None:
    cas_session = _cas_session(CATEGORY_II, _ist(17, 30))
    assert is_continuous_completeness_supported(Timeframe.ONE_MINUTE, cas_session)
    assert is_continuous_completeness_supported(Timeframe.THIRTY_MINUTE, cas_session) is False


# --- Reconciliation exclusion during CAS ----------------------------------


def _reconcile_bars(stamps):
    ohlc = {
        "open": Decimal("100"),
        "high": Decimal("101"),
        "low": Decimal("99"),
        "close": Decimal("100"),
    }
    observed = tuple(ObservedBar(timestamp=s, **ohlc) for s in stamps)
    reference = tuple(ReferenceBar(timestamp=s, **ohlc) for s in stamps)
    return observed, reference


def test_reconciliation_category_i_full_continuous_agreement_passes() -> None:
    as_of = _ist(17, 30)
    session = build_session_for(TRADING_DAY, as_of)
    cas_session = _cas_session(CATEGORY_I, as_of)
    stamps = cas_session.expected_continuous_bar_timestamps(timedelta(minutes=1))
    observed, reference = _reconcile_bars(stamps)

    report = reconcile_bar_series(
        identity=_identity(),
        instrument_symbol="RELIANCE",
        timeframe=Timeframe.ONE_MINUTE,
        session=session,
        observed_bars=observed,
        reference_bars=reference,
        evidence_source="test_reference",
        cas_session=cas_session,
    )
    assert report.outcome is ReconciliationOutcome.PASS
    assert report.expected_bar_count == 360


def test_reconciliation_category_i_without_cas_session_uses_old_375_expectation() -> None:
    as_of = _ist(17, 30)
    session = build_session_for(TRADING_DAY, as_of)
    stamps = session_expected_1m(session)
    observed, reference = _reconcile_bars(stamps)

    report = reconcile_bar_series(
        identity=_identity(),
        instrument_symbol="RELIANCE",
        timeframe=Timeframe.ONE_MINUTE,
        session=session,
        observed_bars=observed,
        reference_bars=reference,
        evidence_source="test_reference",
    )
    assert report.expected_bar_count == 375
    assert report.outcome is ReconciliationOutcome.PASS


# --- 64.85 replay -----------------------------------------------------


def test_64_85_replay_cas_quiet_then_provider_observation_at_1528_49() -> None:
    """The exact 64.85 incident shape: continuous trading ends 15:14:59,
    CAS begins 15:15:00, no continuous bars during CAS, a provider
    observation arrives at 15:28:49 IST, CAS ends 15:35:00."""
    as_of_1514_59 = _ist(15, 14, 59)
    as_of_during_cas = _ist(15, 28, 49)
    as_of_after_cas = _ist(15, 35, 0)

    session_before = _cas_session(CATEGORY_I, as_of_1514_59)
    assert session_before.state is MarketSessionState.CONTINUOUS_TRADING

    session_during = _cas_session(CATEGORY_I, as_of_during_cas)
    assert session_during.state is MarketSessionState.CAS
    assert classify_cas_window_status(session_during) is CasWindowStatus.EXPECTED_NON_CONTINUOUS

    # No continuous bars during CAS -> no false missing-bar defect: the
    # continuous window's own expectation (09:15-15:15) is fully
    # satisfiable with zero bars during 15:15-15:35, because the CAS
    # window never appears in `expected_continuous_bar_timestamps` at all.
    continuous_stamps = session_during.expected_continuous_bar_timestamps(timedelta(minutes=1))
    assert all(ts <= _ist(15, 15) for ts in continuous_stamps)
    bars_through_cas_quiet = tuple(_bar(RELIANCE, ts) for ts in continuous_stamps)
    missing = missing_continuous_bar_timestamps(
        bars_through_cas_quiet, session_during, Timeframe.ONE_MINUTE
    )
    assert missing == ()

    # The 15:28:49 provider observation is classified by SESSION STATE,
    # never auto-treated as continuous trading merely because it exists.
    classification = classify_observation_session(session_during)
    assert classification is ObservationSessionClassification.PROVIDER_OBSERVATION_DURING_CAS
    # And its label is explicitly NOT any invented semantic meaning.
    assert classification.name not in {
        "REFERENCE_PRICE",
        "AUCTION_PRICE",
        "LTP",
        "TRADE_PRINT",
        "CONFIRMATION",
    }

    session_after = _cas_session(CATEGORY_I, as_of_after_cas)
    assert session_after.state is MarketSessionState.POST_CAS_TRANSITION
    assert classify_cas_window_status(session_after) is CasWindowStatus.PROVIDER_BEHAVIOR_UNKNOWN


# --- Boundary tests --------------------------------------------------


@pytest.mark.parametrize(
    "hour,minute,second,expected_state",
    [
        (15, 14, 59, MarketSessionState.CONTINUOUS_TRADING),
        (15, 15, 0, MarketSessionState.CAS),
        (15, 35, 0, MarketSessionState.POST_CAS_TRANSITION),
    ],
)
def test_boundary_instants(hour, minute, second, expected_state) -> None:
    session = _cas_session(CATEGORY_I, _ist(hour, minute, second))
    assert session.state is expected_state


# --- classify_observation_session outside session -------------------


def test_observation_outside_session_classification() -> None:
    pre_open = _cas_session(CATEGORY_I, _ist(9, 0, 0))
    assert (
        classify_observation_session(pre_open)
        is ObservationSessionClassification.OBSERVATION_OUTSIDE_SESSION
    )
    continuous = _cas_session(CATEGORY_I, _ist(11, 0, 0))
    assert (
        classify_observation_session(continuous)
        is ObservationSessionClassification.CONTINUOUS_TRADING_OBSERVATION
    )


# --- Quality report CAS taxonomy --------------------------------------


def test_quality_report_true_missing_data() -> None:
    assert (
        classify_cas_data_quality(
            cas_window_status=CasWindowStatus.NOT_APPLICABLE, is_missing_continuous_bar=True
        )
        is CasDataQualityLabel.TRUE_MISSING_DATA
    )


def test_quality_report_expected_cas_non_continuous() -> None:
    assert (
        classify_cas_data_quality(
            cas_window_status=CasWindowStatus.EXPECTED_NON_CONTINUOUS,
            is_missing_continuous_bar=False,
        )
        is CasDataQualityLabel.EXPECTED_CAS_NON_CONTINUOUS
    )


def test_quality_report_provider_data_present() -> None:
    assert (
        classify_cas_data_quality(
            cas_window_status=CasWindowStatus.NOT_APPLICABLE, is_missing_continuous_bar=False
        )
        is CasDataQualityLabel.PROVIDER_DATA_PRESENT
    )


def test_quality_report_provider_behavior_unknown() -> None:
    assert (
        classify_cas_data_quality(
            cas_window_status=CasWindowStatus.PROVIDER_BEHAVIOR_UNKNOWN,
            is_missing_continuous_bar=True,
        )
        is CasDataQualityLabel.PROVIDER_BEHAVIOR_UNKNOWN
    )
