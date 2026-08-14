# tests/unit/domain/market_data/test_aggregation.py
#
# Checkpoint 24A: comprehensive + adversarial coverage for
# `domain/market_data/aggregation.py` - the pure Quote -> Bar
# aggregation function this checkpoint's entire safety story rests on.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.aggregation import (
    AggregatedBar,
    BarStatus,
    IncompleteBarError,
    aggregate_quotes_into_bars,
)
from intraday.domain.market_data.contracts import Quote
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
TCS = make_instrument_id(Exchange.NSE, "TCS")
BASE = datetime(2026, 1, 5, 6, 0, 0, tzinfo=UTC)  # exact minute boundary


def q(instrument, offset_seconds: int, price: str) -> Quote:
    return Quote(
        instrument_id=instrument,
        timestamp=BASE + timedelta(seconds=offset_seconds),
        last_price=Decimal(price),
    )


# --- Basic aggregation -------------------------------------------------


def test_first_quote_creates_a_forming_bar() -> None:
    quotes = (q(RELIANCE, 0, "100.00"),)
    as_of = BASE + timedelta(seconds=10)

    result = aggregate_quotes_into_bars(
        quotes, timeframe=Timeframe.ONE_MINUTE, as_of=as_of, data_source="dhan"
    )

    assert len(result.bars) == 1
    bar = result.bars[0]
    assert bar.status is BarStatus.FORMING
    assert bar.open == bar.high == bar.low == bar.close == Decimal("100.00")
    assert bar.observation_count == 1


def test_subsequent_quotes_update_high_low_close_but_not_open() -> None:
    quotes = (
        q(RELIANCE, 0, "100.00"),
        q(RELIANCE, 10, "105.00"),  # new high
        q(RELIANCE, 20, "98.00"),  # new low
        q(RELIANCE, 30, "101.00"),  # new close
    )
    as_of = BASE + timedelta(seconds=40)

    result = aggregate_quotes_into_bars(
        quotes, timeframe=Timeframe.ONE_MINUTE, as_of=as_of, data_source="dhan"
    )

    bar = result.bars[0]
    assert bar.open == Decimal("100.00")
    assert bar.high == Decimal("105.00")
    assert bar.low == Decimal("98.00")
    assert bar.close == Decimal("101.00")
    assert bar.observation_count == 4


def test_interval_transition_closes_the_previous_bar() -> None:
    quotes = (
        q(RELIANCE, 0, "100.00"),  # interval 06:00-06:01
        q(RELIANCE, 70, "102.00"),  # interval 06:01-06:02
    )
    as_of = BASE + timedelta(seconds=80)

    result = aggregate_quotes_into_bars(
        quotes, timeframe=Timeframe.ONE_MINUTE, as_of=as_of, data_source="dhan"
    )

    assert len(result.bars) == 2
    first, second = result.bars
    assert first.status is BarStatus.CLOSED
    assert second.status is BarStatus.FORMING


def test_closed_bar_converts_to_canonical_bar_with_close_time_as_interval_end() -> None:
    quotes = (q(RELIANCE, 0, "100.00"), q(RELIANCE, 70, "102.00"))
    as_of = BASE + timedelta(seconds=80)

    result = aggregate_quotes_into_bars(
        quotes, timeframe=Timeframe.ONE_MINUTE, as_of=as_of, data_source="dhan"
    )
    closed = next(b for b in result.bars if b.status is BarStatus.CLOSED)

    bar = closed.to_bar()
    assert bar.timestamp == closed.interval_end
    assert bar.open == Decimal("100.00")
    assert bar.volume == Decimal("0")  # never fabricated


def test_forming_bar_cannot_be_converted_to_canonical_bar() -> None:
    quotes = (q(RELIANCE, 0, "100.00"),)
    as_of = BASE + timedelta(seconds=10)

    result = aggregate_quotes_into_bars(
        quotes, timeframe=Timeframe.ONE_MINUTE, as_of=as_of, data_source="dhan"
    )
    forming = result.bars[0]

    with pytest.raises(IncompleteBarError):
        forming.to_bar()


# --- Duplicate / out-of-order / same-timestamp handling ----------------


def test_duplicate_quote_does_not_double_count_or_corrupt_ohlc() -> None:
    identical = q(RELIANCE, 0, "100.00")
    quotes = (identical, identical)
    as_of = BASE + timedelta(seconds=10)

    result = aggregate_quotes_into_bars(
        quotes, timeframe=Timeframe.ONE_MINUTE, as_of=as_of, data_source="dhan"
    )

    bar = result.bars[0]
    assert bar.observation_count == 2  # both counted, but OHLC is stable
    assert bar.open == bar.high == bar.low == bar.close == Decimal("100.00")


def test_out_of_order_quotes_are_sorted_before_aggregation() -> None:
    # Fed in reverse chronological order.
    quotes = (q(RELIANCE, 30, "101.00"), q(RELIANCE, 10, "105.00"), q(RELIANCE, 0, "100.00"))
    as_of = BASE + timedelta(seconds=40)

    result = aggregate_quotes_into_bars(
        quotes, timeframe=Timeframe.ONE_MINUTE, as_of=as_of, data_source="dhan"
    )

    bar = result.bars[0]
    assert bar.open == Decimal("100.00")  # earliest by timestamp, not input order
    assert bar.close == Decimal("101.00")  # latest by timestamp


def test_same_timestamp_different_value_breaks_tie_by_arrival_order() -> None:
    """Checkpoint 24A §8: deterministic, documented tie-break -
    arrival/input order, not undefined behavior."""
    same_ts = BASE
    first_arrival = Quote(instrument_id=RELIANCE, timestamp=same_ts, last_price=Decimal("100.00"))
    second_arrival = Quote(instrument_id=RELIANCE, timestamp=same_ts, last_price=Decimal("200.00"))
    as_of = BASE + timedelta(seconds=10)

    result = aggregate_quotes_into_bars(
        (first_arrival, second_arrival),
        timeframe=Timeframe.ONE_MINUTE,
        as_of=as_of,
        data_source="dhan",
    )

    bar = result.bars[0]
    assert bar.open == Decimal("100.00")  # first arrival wins the open
    assert bar.close == Decimal("200.00")  # second arrival wins the close
    assert bar.high == Decimal("200.00")
    assert bar.low == Decimal("100.00")


def test_delayed_quote_for_a_past_interval_revises_that_bars_ohlc() -> None:
    """Documented, intended behavior (not a bug) - see the module's own
    docstring: a late-arriving observation for a CLOSED interval
    correctly revises it on the next aggregation run."""
    as_of = BASE + timedelta(seconds=80)
    first_pass = aggregate_quotes_into_bars(
        (q(RELIANCE, 0, "100.00"),),
        timeframe=Timeframe.ONE_MINUTE,
        as_of=as_of,
        data_source="dhan",
    )
    closed_before = next(b for b in first_pass.bars if b.status is BarStatus.CLOSED)
    assert closed_before.high == Decimal("100.00")

    # A delayed observation for the SAME (already-closed) interval,
    # with a higher price, arrives and is included in a re-run.
    delayed = q(RELIANCE, 45, "150.00")
    second_pass = aggregate_quotes_into_bars(
        (q(RELIANCE, 0, "100.00"), delayed),
        timeframe=Timeframe.ONE_MINUTE,
        as_of=as_of,
        data_source="dhan",
    )
    closed_after = next(b for b in second_pass.bars if b.status is BarStatus.CLOSED)
    assert closed_after.high == Decimal("150.00")


def test_quote_arriving_after_interval_closure_is_still_included_in_that_intervals_bucket() -> None:
    """A quote whose source_timestamp falls in a past interval is bucketed
    by its OWN timestamp, not by when aggregation happened to run."""
    as_of = BASE + timedelta(seconds=200)
    quotes = (q(RELIANCE, 0, "100.00"), q(RELIANCE, 55, "999.00"))  # both interval 0

    result = aggregate_quotes_into_bars(
        quotes, timeframe=Timeframe.ONE_MINUTE, as_of=as_of, data_source="dhan"
    )
    first_interval_bar = next(
        b for b in result.bars if b.interval_start == BASE and b.status is BarStatus.CLOSED
    )
    assert first_interval_bar.close == Decimal("999.00")


# --- Gap detection -------------------------------------------------------


def test_missing_interval_is_detected_never_fabricated() -> None:
    # Observations in interval 0 and interval 3 (minutes 0 and 3) - 1, 2 missing.
    quotes = (
        q(RELIANCE, 0, "100.00"),
        q(RELIANCE, 190, "103.00"),  # 190s = interval 3 (180-240s)
    )
    as_of = BASE + timedelta(seconds=200)

    result = aggregate_quotes_into_bars(
        quotes, timeframe=Timeframe.ONE_MINUTE, as_of=as_of, data_source="dhan"
    )

    closed_intervals = {b.interval_start for b in result.bars if b.status is BarStatus.CLOSED}
    assert BASE in closed_intervals  # interval 0 present
    missing_starts = {m.interval_start for m in result.missing_intervals}
    assert BASE + timedelta(seconds=60) in missing_starts  # interval 1
    assert BASE + timedelta(seconds=120) in missing_starts  # interval 2
    # No bar was fabricated for the missing intervals.
    bar_starts = {b.interval_start for b in result.bars}
    assert BASE + timedelta(seconds=60) not in bar_starts
    assert BASE + timedelta(seconds=120) not in bar_starts


def test_no_gap_reported_when_every_interval_has_data() -> None:
    quotes = (q(RELIANCE, 0, "100.00"), q(RELIANCE, 65, "101.00"))
    as_of = BASE + timedelta(seconds=130)

    result = aggregate_quotes_into_bars(
        quotes, timeframe=Timeframe.ONE_MINUTE, as_of=as_of, data_source="dhan"
    )

    assert result.missing_intervals == ()


def test_the_currently_forming_interval_is_never_reported_as_missing() -> None:
    quotes = (q(RELIANCE, 0, "100.00"),)  # only interval 0 has data
    as_of = BASE + timedelta(seconds=10)  # still within interval 0

    result = aggregate_quotes_into_bars(
        quotes, timeframe=Timeframe.ONE_MINUTE, as_of=as_of, data_source="dhan"
    )

    assert result.missing_intervals == ()


# --- Anomalous / adversarial observations -------------------------------


def test_future_timestamp_observation_is_excluded_and_reported_never_silently_dropped() -> None:
    future = Quote(
        instrument_id=RELIANCE, timestamp=BASE + timedelta(hours=1), last_price=Decimal("100.00")
    )
    as_of = BASE + timedelta(seconds=10)

    result = aggregate_quotes_into_bars(
        (future,), timeframe=Timeframe.ONE_MINUTE, as_of=as_of, data_source="dhan"
    )

    assert result.bars == ()
    assert len(result.anomalous_observations) == 1
    assert result.anomalous_observations[0].instrument_id == RELIANCE
    assert "future" in result.anomalous_observations[0].reason.lower()


def test_empty_input_produces_empty_result_not_an_error() -> None:
    result = aggregate_quotes_into_bars(
        (), timeframe=Timeframe.ONE_MINUTE, as_of=BASE, data_source="dhan"
    )

    assert result.bars == ()
    assert result.missing_intervals == ()
    assert result.anomalous_observations == ()


def test_as_of_must_be_utc() -> None:
    from datetime import timezone

    non_utc = BASE.astimezone(timezone(timedelta(hours=3)))
    with pytest.raises(ValueError, match="UTC"):
        aggregate_quotes_into_bars(
            (q(RELIANCE, 0, "100.00"),),
            timeframe=Timeframe.ONE_MINUTE,
            as_of=non_utc,
            data_source="dhan",
        )


# --- Multi-instrument independence --------------------------------------


def test_instruments_are_aggregated_independently() -> None:
    quotes = (
        q(RELIANCE, 0, "100.00"),
        q(TCS, 0, "3000.00"),
        q(TCS, 10, "3010.00"),
    )
    as_of = BASE + timedelta(seconds=20)

    result = aggregate_quotes_into_bars(
        quotes, timeframe=Timeframe.ONE_MINUTE, as_of=as_of, data_source="dhan"
    )

    reliance_bar = next(b for b in result.bars if b.instrument_id == RELIANCE)
    tcs_bar = next(b for b in result.bars if b.instrument_id == TCS)
    assert reliance_bar.observation_count == 1
    assert tcs_bar.observation_count == 2
    assert tcs_bar.close == Decimal("3010.00")


def test_missing_interval_for_one_instrument_does_not_affect_another() -> None:
    quotes = (
        q(RELIANCE, 0, "100.00"),
        q(RELIANCE, 190, "103.00"),  # RELIANCE has a gap
        q(TCS, 0, "3000.00"),
        q(TCS, 65, "3010.00"),
        q(TCS, 125, "3020.00"),  # TCS has no gap
    )
    as_of = BASE + timedelta(seconds=200)

    result = aggregate_quotes_into_bars(
        quotes, timeframe=Timeframe.ONE_MINUTE, as_of=as_of, data_source="dhan"
    )

    tcs_missing = [m for m in result.missing_intervals if m.instrument_id == TCS]
    reliance_missing = [m for m in result.missing_intervals if m.instrument_id == RELIANCE]
    assert tcs_missing == []
    assert len(reliance_missing) == 2


# --- AggregatedBar's own invariants (adversarial construction) ---------


def test_aggregated_bar_rejects_non_positive_price() -> None:
    with pytest.raises(ValueError, match="positive"):
        AggregatedBar(
            instrument_id=RELIANCE,
            timeframe=Timeframe.ONE_MINUTE,
            interval_start=BASE,
            interval_end=BASE + timedelta(minutes=1),
            open=Decimal("0"),
            high=Decimal("100"),
            low=Decimal("50"),
            close=Decimal("75"),
            status=BarStatus.CLOSED,
            observation_count=1,
            data_source="dhan",
        )


def test_aggregated_bar_rejects_inconsistent_ohlc() -> None:
    with pytest.raises(ValueError, match="inconsistent"):
        AggregatedBar(
            instrument_id=RELIANCE,
            timeframe=Timeframe.ONE_MINUTE,
            interval_start=BASE,
            interval_end=BASE + timedelta(minutes=1),
            open=Decimal("100"),
            high=Decimal("90"),  # high < open - invalid
            low=Decimal("50"),
            close=Decimal("75"),
            status=BarStatus.CLOSED,
            observation_count=1,
            data_source="dhan",
        )


def test_aggregated_bar_rejects_interval_end_before_start() -> None:
    with pytest.raises(ValueError, match="interval_end"):
        AggregatedBar(
            instrument_id=RELIANCE,
            timeframe=Timeframe.ONE_MINUTE,
            interval_start=BASE,
            interval_end=BASE - timedelta(minutes=1),
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
            status=BarStatus.CLOSED,
            observation_count=1,
            data_source="dhan",
        )


def test_aggregated_bar_rejects_zero_observation_count() -> None:
    with pytest.raises(ValueError, match="observation_count"):
        AggregatedBar(
            instrument_id=RELIANCE,
            timeframe=Timeframe.ONE_MINUTE,
            interval_start=BASE,
            interval_end=BASE + timedelta(minutes=1),
            open=Decimal("100"),
            high=Decimal("100"),
            low=Decimal("100"),
            close=Decimal("100"),
            status=BarStatus.CLOSED,
            observation_count=0,
            data_source="dhan",
        )
