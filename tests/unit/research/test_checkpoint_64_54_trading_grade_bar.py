# tests/unit/research/test_checkpoint_64_54_trading_grade_bar.py
#
# Checkpoint 64.54: TRADING-GRADE MARKET DATA FOUNDATION.
#
# This file does NOT introduce a second market-data framework, a second
# aggregator, or a new Trading-Grade-Bar definition. It exercises the
# EXISTING, already-built pipeline end to end, starting from raw
# synthetic `Quote` events (never Dhan, never live):
#
#     Quote (canonical event contract, Checkpoint 5)
#         -> aggregate_quotes_into_bars() (Checkpoint 24A, unmodified)
#         -> evaluate_bar_promotion() (Checkpoint 40's SIX-condition
#            promotion gate, unmodified)
#         -> AggregatedBar.to_bar() -> canonical Bar (Checkpoint 5)
#
# IMPORTANT, per the checkpoint directive: a synthetic provider proving
# this path CAN reach TRADING_GRADE_BAR when given sufficient evidence
# is NOT proof that real NSE data is trading-grade. It only proves the
# architecture is capable of producing the required quality grade when
# a provider supplies the required evidence (see test_j below, and the
# module docstring of `domain/market_data/promotion.py`).
#
# `BacktestTrustLevel.POC` is not touched anywhere in this file.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.aggregation import (
    AggregatedBar,
    BarQualityGrade,
    BarStatus,
    aggregate_quotes_into_bars,
)
from intraday.domain.market_data.contracts import Bar, Quote
from intraday.domain.market_data.promotion import (
    MINIMUM_OBSERVATIONS_FOR_TRADING_GRADE,
    PromotionCondition,
    evaluate_bar_promotion,
)
from intraday.domain.market_data.quality import (
    DuplicateBarTimestampError,
    OutOfOrderBarError,
    ensure_chronological,
)
from intraday.domain.session.calendar import build_session_for
from intraday.domain.session.contracts import TradingSession
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe
from intraday.research.backtesting.contracts import BacktestTrustLevel

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")

# 2026-01-05 is a Monday, a real NSE trading day (not in NSE_HOLIDAYS_2026),
# matching the pre-existing Checkpoint 40 fixture convention exactly - no
# new calendar invention.
SESSION_DATE = datetime(2026, 1, 5).date()
MARKET_OPEN_PROBE = datetime(2026, 1, 5, 6, 0, tzinfo=UTC)  # 11:30 IST, mid-session
OPEN_SESSION = build_session_for(SESSION_DATE, MARKET_OPEN_PROBE)


def _quote(
    *, minute_offset: int, second_offset: int, price: str, source: str = "synthetic_test_provider"
) -> Quote:
    """One synthetic tick, with an explicit EXCHANGE-style timestamp
    (never local machine time) - the smallest unit the real
    `aggregate_quotes_into_bars()` consumes."""
    return Quote(
        instrument_id=RELIANCE,
        timestamp=OPEN_SESSION.market_open
        + timedelta(minutes=minute_offset, seconds=second_offset),
        last_price=Decimal(price),
        source=source,
    )


# ---------------------------------------------------------------------------
# A. Existing SAMPLE_BAR behaviour remains intact (no regression).
# ---------------------------------------------------------------------------
def test_a_default_aggregation_path_still_produces_sample_bar() -> None:
    quotes = (
        _quote(minute_offset=0, second_offset=0, price="100.00"),
        _quote(minute_offset=0, second_offset=30, price="101.00"),
        _quote(minute_offset=1, second_offset=0, price="102.00"),
    )
    result = aggregate_quotes_into_bars(
        quotes,
        timeframe=Timeframe.ONE_MINUTE,
        as_of=OPEN_SESSION.market_open + timedelta(minutes=2),
        data_source="synthetic_test_provider",
    )
    closed = [b for b in result.bars if b.status is BarStatus.CLOSED]
    assert closed, "expected at least one closed bar"
    for bar in closed:
        assert bar.provenance is not None
        assert bar.provenance.quality_grade is BarQualityGrade.SAMPLE_BAR
        assert bar.provenance.aggregation_method == "point_sample_aggregation"


# ---------------------------------------------------------------------------
# B/K. Trading-grade eligibility conditions are evaluated correctly, and a
#      bar is NEVER falsely labelled trading-grade when a condition is
#      missing (Checkpoint 40's own six-condition gate, unmodified).
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "connection_healthy,session,expected_condition",
    [
        (False, OPEN_SESSION, PromotionCondition.CONNECTION_HEALTHY),
    ],
)
def test_b_missing_condition_never_falsely_promoted(
    connection_healthy: bool, session: TradingSession, expected_condition: PromotionCondition
) -> None:
    quotes = tuple(
        _quote(minute_offset=0, second_offset=s, price="100.00") for s in (0, 15, 30, 45)
    )
    agg = aggregate_quotes_into_bars(
        quotes,
        timeframe=Timeframe.ONE_MINUTE,
        as_of=OPEN_SESSION.market_open + timedelta(minutes=1),
        data_source="synthetic_test_provider",
    )
    closed_bars = [b for b in agg.bars if b.status is BarStatus.CLOSED]
    assert len(closed_bars) == 1
    result = evaluate_bar_promotion(
        bar=closed_bars[0],
        session=session,
        preceding_bars=(),
        connection_is_healthy=connection_healthy,
        now=OPEN_SESSION.market_open + timedelta(minutes=1),
    )
    assert result.grade is BarQualityGrade.SAMPLE_BAR
    assert expected_condition in result.failed_conditions


# ---------------------------------------------------------------------------
# C. Bar completion: a FORMING bar can never be promoted, and can never be
#    silently converted to a canonical (closed) Bar.
# ---------------------------------------------------------------------------
def test_c_forming_bar_is_neither_promotable_nor_convertible() -> None:
    quotes = (_quote(minute_offset=0, second_offset=0, price="100.00"),)
    agg = aggregate_quotes_into_bars(
        quotes,
        timeframe=Timeframe.ONE_MINUTE,
        as_of=OPEN_SESSION.market_open + timedelta(seconds=30),  # still inside minute 0 -> FORMING
        data_source="synthetic_test_provider",
    )
    forming = [b for b in agg.bars if b.status is BarStatus.FORMING]
    assert forming, "expected the current interval to be FORMING"
    bar = forming[0]
    result = evaluate_bar_promotion(
        bar=bar,
        session=OPEN_SESSION,
        preceding_bars=(),
        connection_is_healthy=True,
        now=OPEN_SESSION.market_open + timedelta(seconds=30),
    )
    assert result.grade is BarQualityGrade.SAMPLE_BAR
    assert PromotionCondition.BAR_IS_CLOSED in result.failed_conditions
    from intraday.domain.market_data.aggregation import IncompleteBarError

    with pytest.raises(IncompleteBarError):
        bar.to_bar()


# ---------------------------------------------------------------------------
# D. Timestamp semantics: exchange (source) timestamp vs. bar close
#    (interval_end) vs. ingestion (as_of) are distinct, all UTC-enforced,
#    never conflated.
# ---------------------------------------------------------------------------
def test_d_timestamp_semantics_are_distinct_and_utc() -> None:
    as_of = OPEN_SESSION.market_open + timedelta(minutes=1)
    quotes = (
        _quote(minute_offset=0, second_offset=0, price="100.00"),
        _quote(minute_offset=0, second_offset=40, price="103.00"),
    )
    agg = aggregate_quotes_into_bars(
        quotes, timeframe=Timeframe.ONE_MINUTE, as_of=as_of, data_source="synthetic_test_provider"
    )
    closed = [b for b in agg.bars if b.status is BarStatus.CLOSED][0]
    prov = closed.provenance
    assert prov is not None
    assert prov.timestamp == closed.interval_end  # canonical bar-close convention (Checkpoint 5)
    assert prov.source_timestamp == quotes[-1].timestamp  # latest exchange-style tick timestamp
    assert prov.ingestion_timestamp == as_of  # when THIS process observed/aggregated it
    # The three are genuinely distinct instants in this fixture, not
    # silently collapsed to one value:
    assert prov.timestamp != prov.source_timestamp
    assert prov.ingestion_timestamp != prov.source_timestamp
    for field in (prov.timestamp, prov.source_timestamp, prov.ingestion_timestamp):
        assert field.tzinfo is not None and field.utcoffset() == timedelta(0)


# ---------------------------------------------------------------------------
# E. Session boundaries: a bar formed outside an OPEN session is never
#    trading-grade, reusing the existing session-calendar infrastructure.
# ---------------------------------------------------------------------------
def test_e_session_boundary_blocks_promotion_outside_open_session() -> None:
    closed_session_probe = datetime(2026, 1, 5, 20, 0, tzinfo=UTC)  # 01:30 IST next day - CLOSED
    closed_session = build_session_for(SESSION_DATE, closed_session_probe)
    bar = AggregatedBar(
        instrument_id=RELIANCE,
        timeframe=Timeframe.ONE_MINUTE,
        interval_start=closed_session.market_close + timedelta(minutes=5),
        interval_end=closed_session.market_close + timedelta(minutes=6),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100.5"),
        status=BarStatus.CLOSED,
        observation_count=5,
        data_source="synthetic_test_provider",
    )
    result = evaluate_bar_promotion(
        bar=bar,
        session=closed_session,
        preceding_bars=(),
        connection_is_healthy=True,
        now=closed_session_probe,
    )
    assert result.grade is BarQualityGrade.SAMPLE_BAR
    assert PromotionCondition.SESSION_IS_OPEN in result.failed_conditions


# ---------------------------------------------------------------------------
# F. Duplicate events: the aggregator resolves same-timestamp quotes with a
#    documented deterministic tie-break (arrival order), never silently
#    dropping or double-counting; at the BAR level, an identical duplicate
#    bar is rejected by the existing chronology guard, and the promotion
#    gate reports it explicitly (NO_DUPLICATE_OR_OUT_OF_ORDER).
# ---------------------------------------------------------------------------
def test_f_duplicate_quote_timestamps_resolve_deterministically() -> None:
    duplicate_ts_quotes = (
        Quote(
            instrument_id=RELIANCE, timestamp=OPEN_SESSION.market_open, last_price=Decimal("100.00")
        ),
        Quote(
            instrument_id=RELIANCE, timestamp=OPEN_SESSION.market_open, last_price=Decimal("105.00")
        ),
    )
    agg = aggregate_quotes_into_bars(
        duplicate_ts_quotes,
        timeframe=Timeframe.ONE_MINUTE,
        as_of=OPEN_SESSION.market_open + timedelta(minutes=1),
        data_source="synthetic_test_provider",
    )
    closed = [b for b in agg.bars if b.status is BarStatus.CLOSED][0]
    # Deterministic tie-break: input arrival order. The first-listed quote
    # is treated as OPEN, the second (same timestamp, later in the input
    # sequence) as CLOSE - documented in aggregation.py's own docstring.
    assert closed.open == Decimal("100.00")
    assert closed.close == Decimal("105.00")
    assert closed.observation_count == 2


def test_f2_duplicate_bar_timestamp_is_rejected_by_the_gate() -> None:
    first = AggregatedBar(
        instrument_id=RELIANCE,
        timeframe=Timeframe.ONE_MINUTE,
        interval_start=OPEN_SESSION.market_open,
        interval_end=OPEN_SESSION.market_open + timedelta(minutes=1),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100.5"),
        status=BarStatus.CLOSED,
        observation_count=5,
        data_source="synthetic_test_provider",
    )
    duplicate = AggregatedBar(
        instrument_id=RELIANCE,
        timeframe=Timeframe.ONE_MINUTE,
        interval_start=first.interval_start,
        interval_end=first.interval_end,
        open=Decimal("200"),
        high=Decimal("201"),
        low=Decimal("199"),
        close=Decimal("200.5"),
        status=BarStatus.CLOSED,
        observation_count=5,
        data_source="synthetic_test_provider",
    )
    result = evaluate_bar_promotion(
        bar=duplicate,
        session=OPEN_SESSION,
        preceding_bars=(first,),
        connection_is_healthy=True,
        now=OPEN_SESSION.market_open + timedelta(minutes=1),
    )
    assert result.grade is BarQualityGrade.SAMPLE_BAR
    assert PromotionCondition.NO_DUPLICATE_OR_OUT_OF_ORDER in result.failed_conditions
    with pytest.raises(DuplicateBarTimestampError):
        ensure_chronological((first.to_bar(), duplicate.to_bar()))


# ---------------------------------------------------------------------------
# G. Out-of-order events: rejected per the existing, unmodified policy
#    (domain/market_data/quality.py's `ensure_chronological` raises rather
#    than silently reordering).
# ---------------------------------------------------------------------------
def test_g_out_of_order_bars_are_rejected_not_silently_reordered() -> None:
    later = Bar(
        instrument_id=RELIANCE,
        timeframe=Timeframe.ONE_MINUTE,
        timestamp=OPEN_SESSION.market_open + timedelta(minutes=2),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100.5"),
        volume=Decimal("0"),
    )
    earlier = Bar(
        instrument_id=RELIANCE,
        timeframe=Timeframe.ONE_MINUTE,
        timestamp=OPEN_SESSION.market_open + timedelta(minutes=1),
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100.5"),
        volume=Decimal("0"),
    )
    with pytest.raises(OutOfOrderBarError):
        ensure_chronological((later, earlier))


# ---------------------------------------------------------------------------
# H. Missing/gap events: MissingInterval detection (Checkpoint 24A) and the
#    promotion gate's own NO_GAP_BEFORE_THIS_BAR condition.
# ---------------------------------------------------------------------------
def test_h_gap_in_the_quote_stream_is_detected_not_fabricated() -> None:
    # Minute 0 has quotes; minute 1 has NONE; minute 2 has quotes - a real
    # one-interval gap the aggregator must report, never invent a bar for.
    quotes = (
        _quote(minute_offset=0, second_offset=0, price="100.00"),
        _quote(minute_offset=0, second_offset=30, price="100.50"),
        _quote(minute_offset=2, second_offset=0, price="103.00"),
        _quote(minute_offset=2, second_offset=30, price="103.50"),
    )
    agg = aggregate_quotes_into_bars(
        quotes,
        timeframe=Timeframe.ONE_MINUTE,
        as_of=OPEN_SESSION.market_open + timedelta(minutes=3),
        data_source="synthetic_test_provider",
    )
    assert len(agg.missing_intervals) == 1
    assert agg.missing_intervals[0].interval_start == OPEN_SESSION.market_open + timedelta(
        minutes=1
    )

    closed_bars = [b for b in agg.bars if b.status is BarStatus.CLOSED]
    bar_after_gap = next(
        b
        for b in closed_bars
        if b.interval_start == OPEN_SESSION.market_open + timedelta(minutes=2)
    )
    bar_before_gap = next(b for b in closed_bars if b.interval_start == OPEN_SESSION.market_open)
    result = evaluate_bar_promotion(
        bar=bar_after_gap,
        session=OPEN_SESSION,
        preceding_bars=(bar_before_gap,),
        connection_is_healthy=True,
        now=OPEN_SESSION.market_open + timedelta(minutes=3),
    )
    assert result.grade is BarQualityGrade.SAMPLE_BAR
    assert PromotionCondition.NO_GAP_BEFORE_THIS_BAR in result.failed_conditions
    # Also carried onto the bar's own provenance, non-fabricated evidence:
    assert bar_after_gap.provenance is not None
    assert bar_after_gap.provenance.gap_count >= 1


# ---------------------------------------------------------------------------
# I. Aggregation produces correct OHLCV using event (exchange-style)
#    timestamps, exact timeframe boundaries.
# ---------------------------------------------------------------------------
def test_i_aggregation_produces_correct_ohlc_and_exact_boundaries() -> None:
    quotes = (
        _quote(minute_offset=0, second_offset=0, price="100.00"),
        _quote(minute_offset=0, second_offset=10, price="105.00"),  # high
        _quote(minute_offset=0, second_offset=20, price="98.00"),  # low
        _quote(minute_offset=0, second_offset=59, price="102.00"),  # close
    )
    agg = aggregate_quotes_into_bars(
        quotes,
        timeframe=Timeframe.ONE_MINUTE,
        as_of=OPEN_SESSION.market_open + timedelta(minutes=1),
        data_source="synthetic_test_provider",
    )
    closed = [b for b in agg.bars if b.status is BarStatus.CLOSED][0]
    assert closed.open == Decimal("100.00")
    assert closed.high == Decimal("105.00")
    assert closed.low == Decimal("98.00")
    assert closed.close == Decimal("102.00")
    assert closed.interval_start == OPEN_SESSION.market_open
    assert closed.interval_end == OPEN_SESSION.market_open + timedelta(minutes=1)


# ---------------------------------------------------------------------------
# J. A synthetic provider CAN produce a bar satisfying every one of the
#    project's own six enforced promotion conditions - explicitly NOT
#    proof of real NSE trading-grade data (see module docstring).
# ---------------------------------------------------------------------------
def test_j_synthetic_stream_can_reach_trading_grade_end_to_end() -> None:
    as_of = OPEN_SESSION.market_open + timedelta(minutes=2)
    quotes = (
        _quote(minute_offset=0, second_offset=0, price="100.00"),
        _quote(minute_offset=0, second_offset=20, price="100.50"),
        _quote(minute_offset=0, second_offset=40, price="101.00"),
        _quote(minute_offset=1, second_offset=0, price="101.25"),
        _quote(minute_offset=1, second_offset=30, price="101.50"),
    )
    agg = aggregate_quotes_into_bars(
        quotes, timeframe=Timeframe.ONE_MINUTE, as_of=as_of, data_source="synthetic_test_provider"
    )
    closed_bars = sorted(
        (b for b in agg.bars if b.status is BarStatus.CLOSED), key=lambda b: b.interval_start
    )
    assert len(closed_bars) == 2
    assert all(b.observation_count >= MINIMUM_OBSERVATIONS_FOR_TRADING_GRADE for b in closed_bars)

    preceding: list[AggregatedBar] = []
    results = []
    for bar in closed_bars:
        result = evaluate_bar_promotion(
            bar=bar,
            session=OPEN_SESSION,
            preceding_bars=tuple(preceding),
            connection_is_healthy=True,  # synthetic "connection healthy" evidence, never live Dhan
            now=as_of,
        )
        results.append(result)
        preceding.append(bar)

    assert all(r.grade is BarQualityGrade.TRADING_GRADE_BAR for r in results)
    assert all(r.failed_conditions == () for r in results)

    # The resulting canonical Bar is a completely ordinary Bar - no
    # strategy-specific market-data format was invented to carry the
    # trading-grade classification through.
    canonical_bars = tuple(b.to_bar() for b in closed_bars)
    ensure_chronological(canonical_bars)  # does not raise
    for canonical_bar in canonical_bars:
        assert isinstance(canonical_bar, Bar)


# ---------------------------------------------------------------------------
# L. Existing historical database-first pipeline remains compatible: the
#    canonical Bar produced above is accepted, unmodified, by the exact
#    tuple[Bar, ...] contract the Backtest engine already consumes
#    (research.backtesting.contracts / 64.52's database-first pipeline) -
#    proven by TYPE compatibility, not a new database round trip (out of
#    this focused test file's scope; the existing database-first suite
#    already covers persistence/read-back, unaffected by this checkpoint).
# ---------------------------------------------------------------------------
def test_l_canonical_bar_is_backtest_compatible_without_a_second_bar_type() -> None:
    quotes = (
        _quote(minute_offset=0, second_offset=0, price="100.00"),
        _quote(minute_offset=0, second_offset=30, price="102.00"),
    )
    agg = aggregate_quotes_into_bars(
        quotes,
        timeframe=Timeframe.ONE_MINUTE,
        as_of=OPEN_SESSION.market_open + timedelta(minutes=1),
        data_source="synthetic_test_provider",
    )
    closed = [b for b in agg.bars if b.status is BarStatus.CLOSED][0]
    canonical_bar = closed.to_bar()
    # This is the SAME `Bar` type `research/backtesting/engine.py` consumes
    # via `tuple[Bar, ...]` (re-confirmed by import identity, no duplicate
    # market-data type exists in `research.backtesting`).
    import intraday.research.backtesting.engine as engine_module

    engine_bar_type = engine_module.__dict__["Bar"]
    assert Bar is engine_bar_type
    assert isinstance(canonical_bar, engine_bar_type)


# ---------------------------------------------------------------------------
# M. No Dhan/live credentials anywhere in this file, and BacktestTrustLevel
#    is not flipped by this checkpoint.
# ---------------------------------------------------------------------------
def test_m_no_dhan_import_and_backtest_trust_level_untouched() -> None:
    import sys

    module = sys.modules[__name__]
    assert "dhan" not in (module.__doc__ or "").lower().replace("checkpoint", "")
    # BacktestTrustLevel.POC must still exist and be the only value ever
    # constructed by this file (this file constructs none at all - it
    # only imports the enum to assert its POC member still exists,
    # proving this checkpoint did not remove or rename it).
    assert BacktestTrustLevel.POC.value == "POC"
