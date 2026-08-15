# tests/unit/domain/test_market_data_promotion.py
#
# Checkpoint 40 Part 6: proves the TRADING_GRADE_BAR promotion gate
# genuinely refuses to promote on every one of the six failure modes,
# and only promotes when ALL are satisfied - never a rename, never an
# inferred grade.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.aggregation import AggregatedBar, BarQualityGrade, BarStatus
from intraday.domain.market_data.promotion import (
    PromotionCondition,
    evaluate_bar_promotion,
)
from intraday.domain.session.calendar import build_session_for
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")

# 2026-01-05 is a Monday, not an NSE_HOLIDAYS_2026 date - a real trading day.
SESSION_DATE = datetime(2026, 1, 5).date()
OPEN_SESSION = build_session_for(SESSION_DATE, datetime(2026, 1, 5, 6, 0, tzinfo=UTC))
CLOSED_SESSION = build_session_for(SESSION_DATE, datetime(2026, 1, 5, 20, 0, tzinfo=UTC))


def _bar(
    *,
    interval_start: datetime,
    interval_end: datetime,
    status: BarStatus = BarStatus.CLOSED,
    observation_count: int = 5,
) -> AggregatedBar:
    return AggregatedBar(
        instrument_id=RELIANCE,
        timeframe=Timeframe.ONE_MINUTE,
        interval_start=interval_start,
        interval_end=interval_end,
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100.5"),
        status=status,
        observation_count=observation_count,
        data_source="dhan",
    )


def test_bar_meeting_every_condition_is_promoted_to_trading_grade() -> None:
    bar = _bar(
        interval_start=OPEN_SESSION.market_open,
        interval_end=OPEN_SESSION.market_open + timedelta(minutes=1),
    )
    result = evaluate_bar_promotion(
        bar=bar,
        session=OPEN_SESSION,
        preceding_bars=(),
        connection_is_healthy=True,
        now=datetime(2026, 1, 5, 6, 0, tzinfo=UTC),
    )
    assert result.grade is BarQualityGrade.TRADING_GRADE_BAR
    assert result.failed_conditions == ()


def test_forming_bar_is_never_promoted() -> None:
    bar = _bar(
        interval_start=OPEN_SESSION.market_open,
        interval_end=OPEN_SESSION.market_open + timedelta(minutes=1),
        status=BarStatus.FORMING,
    )
    result = evaluate_bar_promotion(
        bar=bar,
        session=OPEN_SESSION,
        preceding_bars=(),
        connection_is_healthy=True,
        now=datetime(2026, 1, 5, 6, 0, tzinfo=UTC),
    )
    assert result.grade is BarQualityGrade.SAMPLE_BAR
    assert PromotionCondition.BAR_IS_CLOSED in result.failed_conditions


def test_bar_outside_an_open_session_is_never_promoted() -> None:
    bar = _bar(
        interval_start=CLOSED_SESSION.market_open,
        interval_end=CLOSED_SESSION.market_open + timedelta(minutes=1),
    )
    result = evaluate_bar_promotion(
        bar=bar,
        session=CLOSED_SESSION,
        preceding_bars=(),
        connection_is_healthy=True,
        now=datetime(2026, 1, 5, 20, 0, tzinfo=UTC),
    )
    assert result.grade is BarQualityGrade.SAMPLE_BAR
    assert PromotionCondition.SESSION_IS_OPEN in result.failed_conditions


def test_unhealthy_connection_blocks_promotion() -> None:
    bar = _bar(
        interval_start=OPEN_SESSION.market_open,
        interval_end=OPEN_SESSION.market_open + timedelta(minutes=1),
    )
    result = evaluate_bar_promotion(
        bar=bar,
        session=OPEN_SESSION,
        preceding_bars=(),
        connection_is_healthy=False,
        now=datetime(2026, 1, 5, 6, 0, tzinfo=UTC),
    )
    assert result.grade is BarQualityGrade.SAMPLE_BAR
    assert PromotionCondition.CONNECTION_HEALTHY in result.failed_conditions


def test_insufficient_observations_blocks_promotion() -> None:
    bar = _bar(
        interval_start=OPEN_SESSION.market_open,
        interval_end=OPEN_SESSION.market_open + timedelta(minutes=1),
        observation_count=1,
    )
    result = evaluate_bar_promotion(
        bar=bar,
        session=OPEN_SESSION,
        preceding_bars=(),
        connection_is_healthy=True,
        now=datetime(2026, 1, 5, 6, 0, tzinfo=UTC),
    )
    assert result.grade is BarQualityGrade.SAMPLE_BAR
    assert PromotionCondition.SUFFICIENT_OBSERVATIONS in result.failed_conditions


def test_gap_before_this_bar_blocks_promotion() -> None:
    first = _bar(
        interval_start=OPEN_SESSION.market_open,
        interval_end=OPEN_SESSION.market_open + timedelta(minutes=1),
    )
    # Skips a minute - a genuine gap.
    second = _bar(
        interval_start=OPEN_SESSION.market_open + timedelta(minutes=2),
        interval_end=OPEN_SESSION.market_open + timedelta(minutes=3),
    )
    result = evaluate_bar_promotion(
        bar=second,
        session=OPEN_SESSION,
        preceding_bars=(first,),
        connection_is_healthy=True,
        now=datetime(2026, 1, 5, 6, 0, tzinfo=UTC),
    )
    assert result.grade is BarQualityGrade.SAMPLE_BAR
    assert PromotionCondition.NO_GAP_BEFORE_THIS_BAR in result.failed_conditions


def test_contiguous_second_bar_after_a_valid_first_bar_is_promoted() -> None:
    first = _bar(
        interval_start=OPEN_SESSION.market_open,
        interval_end=OPEN_SESSION.market_open + timedelta(minutes=1),
    )
    second = _bar(
        interval_start=OPEN_SESSION.market_open + timedelta(minutes=1),
        interval_end=OPEN_SESSION.market_open + timedelta(minutes=2),
    )
    result = evaluate_bar_promotion(
        bar=second,
        session=OPEN_SESSION,
        preceding_bars=(first,),
        connection_is_healthy=True,
        now=datetime(2026, 1, 5, 6, 0, tzinfo=UTC),
    )
    assert result.grade is BarQualityGrade.TRADING_GRADE_BAR


def test_duplicate_timestamp_blocks_promotion() -> None:
    first = _bar(
        interval_start=OPEN_SESSION.market_open,
        interval_end=OPEN_SESSION.market_open + timedelta(minutes=1),
    )
    duplicate = _bar(
        interval_start=OPEN_SESSION.market_open,
        interval_end=OPEN_SESSION.market_open + timedelta(minutes=1),
    )
    result = evaluate_bar_promotion(
        bar=duplicate,
        session=OPEN_SESSION,
        preceding_bars=(first,),
        connection_is_healthy=True,
        now=datetime(2026, 1, 5, 6, 0, tzinfo=UTC),
    )
    assert result.grade is BarQualityGrade.SAMPLE_BAR
    assert PromotionCondition.NO_DUPLICATE_OR_OUT_OF_ORDER in result.failed_conditions


def test_multiple_simultaneous_failures_are_all_reported() -> None:
    bar = _bar(
        interval_start=CLOSED_SESSION.market_open,
        interval_end=CLOSED_SESSION.market_open + timedelta(minutes=1),
        status=BarStatus.FORMING,
        observation_count=1,
    )
    result = evaluate_bar_promotion(
        bar=bar,
        session=CLOSED_SESSION,
        preceding_bars=(),
        connection_is_healthy=False,
        now=datetime(2026, 1, 5, 20, 0, tzinfo=UTC),
    )
    assert result.grade is BarQualityGrade.SAMPLE_BAR
    assert PromotionCondition.BAR_IS_CLOSED in result.failed_conditions
    assert PromotionCondition.SESSION_IS_OPEN in result.failed_conditions
    assert PromotionCondition.CONNECTION_HEALTHY in result.failed_conditions
    assert PromotionCondition.SUFFICIENT_OBSERVATIONS in result.failed_conditions
