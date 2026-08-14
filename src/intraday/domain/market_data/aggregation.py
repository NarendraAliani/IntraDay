# File: src/intraday/domain/market_data/aggregation.py
#
# Checkpoint 24A: pure, technology-neutral Quote -> Bar aggregation.
# Domain-layer, not application-layer, for the same reason
# `domain/market_data/quality.py` (Checkpoint 14) is: this rule is
# intrinsic to what "a bar built from observed quotes" means, not a
# provider- or infrastructure-specific concern - no HTTP, no Django, no
# Dhan knowledge, no persistence.
#
# ---------------------------------------------------------------------------
# Design: pure, replay-safe aggregation over a full observation history
# ---------------------------------------------------------------------------
# This checkpoint's data source (Checkpoint 23's explicit-trigger REST
# polling) produces isolated point-in-time `Quote` snapshots, never a
# continuous tick stream. There is therefore no live "bar close" event to
# react to, and no stateful, incrementally-updated accumulator is
# needed (or safe to build correctly without much more machinery than
# this checkpoint's scope justifies). Instead, `aggregate_quotes_into_bars()`
# is a PURE function over the complete set of already-persisted
# observations for a time range (Checkpoint 23's `LiveQuoteObservation`
# is already append-only and already the source of truth) - every call
# recomputes bars deterministically from scratch. This has one
# deliberate, documented consequence: a late-arriving observation for a
# past interval correctly REVISES that interval's OHLC the next time
# aggregation runs, since the underlying observed data has genuinely
# changed - this is not a bug, it is the direct consequence of treating
# the observation log as the single source of truth rather than
# maintaining separate, independently-mutable bar state.
from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from intraday.domain.market_data.contracts import Bar, MarketDataQuality, PriceAdjustment, Quote
from intraday.domain.market_data.quality import timeframe_to_timedelta
from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe, ensure_utc


class BarStatus(enum.Enum):
    """A bar's lifecycle state relative to `as_of` (Checkpoint 24A §6).
    `FORMING` bars must never be silently treated as `CLOSED` - the two
    are represented by distinct states specifically so a consumer cannot
    accidentally skip the check."""

    FORMING = "FORMING"
    CLOSED = "CLOSED"


class BarQualityGrade(enum.Enum):
    """Checkpoint 31 Part 5/4: the explicit, typed distinction between a
    bar this project honestly trusts for signal generation/live trading
    and one it does not - never inferred from documentation alone, and
    never silently defaulted to the trusted grade. See
    `docs/architecture/DHAN_MARKET_DATA_CAPABILITY_RESEARCH.md`'s
    six-condition acceptance definition for exactly what
    `TRADING_GRADE_BAR` requires; every bar this codebase has ever
    produced through Checkpoint 31 is `SAMPLE_BAR` - `TRADING_GRADE_BAR`
    is not yet reachable by any code path (see
    `docs/research/TRADING_GRADE_BAR_VALIDATION.md`)."""

    SAMPLE_BAR = "SAMPLE_BAR"
    TRADING_GRADE_BAR = "TRADING_GRADE_BAR"


@dataclass(frozen=True, slots=True)
class BarProvenance:
    """Checkpoint 31 Part 5: an explicit, typed record of where a bar
    came from and how much it can be trusted - so `SAMPLE_BAR` vs.
    `TRADING_GRADE_BAR` is a property carried by the data itself, not
    something only asserted in documentation. Attached to `AggregatedBar`
    as an optional field (`provenance`) so existing callers/tests that
    predate this checkpoint are unaffected (default `None`)."""

    source: str  # e.g. "dhan_marketfeed_quote_rest_poll"
    exchange: str
    timeframe: Timeframe
    timestamp: datetime  # canonical bar timestamp (close), UTC
    source_timestamp: datetime | None  # provider-reported timestamp, if distinct from timestamp
    ingestion_timestamp: datetime  # when THIS process observed/persisted it, UTC
    aggregation_method: str  # e.g. "point_sample_aggregation", "websocket_tick_aggregation"
    quality_grade: BarQualityGrade
    gap_count: int = 0  # missing intervals detected for this instrument's span

    def __post_init__(self) -> None:
        ensure_utc(self.timestamp, field_name="BarProvenance.timestamp")
        ensure_utc(self.ingestion_timestamp, field_name="BarProvenance.ingestion_timestamp")
        if self.source_timestamp is not None:
            ensure_utc(self.source_timestamp, field_name="BarProvenance.source_timestamp")
        if self.gap_count < 0:
            raise ValueError("BarProvenance.gap_count must not be negative")


@dataclass(frozen=True, slots=True)
class AggregatedBar:
    """A bar built from aggregated `Quote` observations. Unlike the
    canonical `Bar` (Checkpoint 5/14), this type can legitimately
    represent an in-progress interval (`status=FORMING`) whose `close`
    is provisional - `Bar` itself has no such concept and its
    invariants assume a genuinely completed interval. Only a `CLOSED`
    `AggregatedBar` can be converted to a real `Bar` (`to_bar()`)."""

    instrument_id: InstrumentId
    timeframe: Timeframe
    interval_start: datetime  # UTC
    interval_end: datetime  # UTC - equals the canonical Bar.timestamp once closed
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    status: BarStatus
    observation_count: int
    data_source: str
    provenance: BarProvenance | None = None

    def __post_init__(self) -> None:
        ensure_utc(self.interval_start, field_name="AggregatedBar.interval_start")
        ensure_utc(self.interval_end, field_name="AggregatedBar.interval_end")
        if self.interval_end <= self.interval_start:
            raise ValueError("AggregatedBar.interval_end must be after interval_start")
        for field_name, value in (
            ("open", self.open),
            ("high", self.high),
            ("low", self.low),
            ("close", self.close),
        ):
            if value <= 0:
                raise ValueError(f"AggregatedBar.{field_name} must be positive, got {value}")
        if not (self.low <= self.open <= self.high and self.low <= self.close <= self.high):
            raise ValueError(
                "AggregatedBar OHLC values are inconsistent: open and close must lie "
                "within [low, high]"
            )
        if self.observation_count < 1:
            raise ValueError("AggregatedBar.observation_count must be at least 1")

    def to_bar(self) -> Bar:
        """Converts a CLOSED `AggregatedBar` into the canonical `Bar`
        contract - raises `IncompleteBarError` if called on a FORMING
        bar (Checkpoint 24A §6's "the existing signal engine must never
        receive an incomplete bar"). `Bar.timestamp` (bar CLOSE time,
        per its own Checkpoint 5/14 convention) is this bar's
        `interval_end`. Volume is never fabricated (Checkpoint 24A §4) -
        `Bar.volume` is set to `Decimal("0")` only because `Bar` itself
        requires a non-negative volume field; this checkpoint's
        aggregation never claims to have measured real traded volume
        (see `docs/architecture/LIVE_BAR_AGGREGATION_ARCHITECTURE.md`'s
        volume-limitation section) - a real volume figure is a future
        increment, not a value this function invents."""
        if self.status is not BarStatus.CLOSED:
            raise IncompleteBarError(
                f"cannot convert a FORMING bar to a closed Bar "
                f"(instrument={self.instrument_id!r}, interval_end={self.interval_end.isoformat()})"
            )
        return Bar(
            instrument_id=self.instrument_id,
            timeframe=self.timeframe,
            timestamp=self.interval_end,
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=Decimal("0"),
            quality=MarketDataQuality.OK,
            adjustment=PriceAdjustment.RAW,
        )


class IncompleteBarError(ValueError):
    """Raised by `AggregatedBar.to_bar()` when called on a FORMING bar."""


@dataclass(frozen=True, slots=True)
class MissingInterval:
    """One expected-but-absent CLOSED interval (Checkpoint 24A §7) - no
    bar is fabricated for it; this is purely a diagnostic record."""

    instrument_id: InstrumentId
    interval_start: datetime
    interval_end: datetime


@dataclass(frozen=True, slots=True)
class AnomalousObservation:
    """A `Quote` excluded from aggregation because it could not be
    trusted (Checkpoint 24A §14's "the system must fail safely and
    visibly" - never silently dropped without a trace)."""

    instrument_id: InstrumentId
    source_timestamp: datetime
    reason: str


@dataclass(frozen=True, slots=True)
class BarAggregationResult:
    bars: tuple[AggregatedBar, ...]
    missing_intervals: tuple[MissingInterval, ...]
    anomalous_observations: tuple[AnomalousObservation, ...]


def _interval_start(timestamp: datetime, duration: timedelta) -> datetime:
    """Floors `timestamp` (UTC) to the start of its `duration`-wide
    interval, anchored at the UTC epoch (00:00:00) - a fixed, provider-
    and-session-independent anchor, so interval boundaries are
    deterministic regardless of when the observation universe happened
    to start being polled."""
    epoch = datetime(1970, 1, 1, tzinfo=timestamp.tzinfo)
    elapsed = timestamp - epoch
    duration_seconds = duration.total_seconds()
    floored_seconds = (elapsed.total_seconds() // duration_seconds) * duration_seconds
    return epoch + timedelta(seconds=floored_seconds)


def aggregate_quotes_into_bars(
    quotes: tuple[Quote, ...],
    *,
    timeframe: Timeframe,
    as_of: datetime,
    data_source: str,
) -> BarAggregationResult:
    """Deterministically aggregates `quotes` (any order, any instrument
    mix, may include duplicates/out-of-order/same-timestamp entries)
    into per-instrument, per-interval bars.

    Aggregation rule per interval (Checkpoint 24A §4):
        OPEN  = price of the earliest-by-(source_timestamp, arrival
                order) observation in the interval
        HIGH  = max observed price in the interval
        LOW   = min observed price in the interval
        CLOSE = price of the latest-by-(source_timestamp, arrival
                order) observation in the interval
        VOLUME = not computed (see `AggregatedBar.to_bar()`'s docstring)

    Ties at the exact same `source_timestamp` are broken by the
    observation's position in the input sequence (its "arrival order")
    - a deterministic, documented rule, not an arbitrary one (Checkpoint
    24A §8's "same timestamp/different value" case).

    Observations with `source_timestamp > as_of` are excluded as
    anomalous (a provider clock-skew/bad-data case, Checkpoint 24A §14)
    - never aggregated into a bar, always reported in
    `anomalous_observations`.

    At most one bar per instrument is `FORMING` (the interval containing
    `as_of`); every earlier interval with at least one observation is
    `CLOSED`. Intervals within an instrument's own observed span that
    have NO observation at all are reported in `missing_intervals` -
    never fabricated (Checkpoint 24A §7)."""
    ensure_utc(as_of, field_name="as_of")
    duration = timeframe_to_timedelta(timeframe)
    current_interval_start = _interval_start(as_of, duration)

    anomalies: list[AnomalousObservation] = []
    valid_quotes: list[Quote] = []
    for quote in quotes:
        if quote.timestamp > as_of:
            anomalies.append(
                AnomalousObservation(
                    instrument_id=quote.instrument_id,
                    source_timestamp=quote.timestamp,
                    reason="source_timestamp is after as_of (future timestamp)",
                )
            )
            continue
        valid_quotes.append(quote)

    by_instrument: dict[InstrumentId, list[Quote]] = {}
    for quote in valid_quotes:
        by_instrument.setdefault(quote.instrument_id, []).append(quote)

    bars: list[AggregatedBar] = []
    missing: list[MissingInterval] = []

    for instrument_id, instrument_quotes in by_instrument.items():
        # Stable sort by (source_timestamp, original arrival order) -
        # Python's sort is stable, so ties keep their input order,
        # giving the deterministic tie-break this function documents.
        ordered = sorted(instrument_quotes, key=lambda q: q.timestamp)

        buckets: dict[datetime, list[Quote]] = {}
        for quote in ordered:
            start = _interval_start(quote.timestamp, duration)
            buckets.setdefault(start, []).append(quote)

        observed_starts = sorted(buckets.keys())
        earliest_start = observed_starts[0]

        # Walk every interval from the earliest observed to the current
        # (forming) one, so a genuinely empty interval in between is
        # reported as missing rather than silently absent from the result.
        cursor = earliest_start
        gaps_so_far = 0
        while cursor <= current_interval_start:
            interval_end = cursor + duration
            bucket = buckets.get(cursor)
            is_forming = cursor == current_interval_start
            if bucket is None:
                if not is_forming:
                    missing.append(
                        MissingInterval(
                            instrument_id=instrument_id,
                            interval_start=cursor,
                            interval_end=interval_end,
                        )
                    )
                    gaps_so_far += 1
                cursor += duration
                continue

            open_price = bucket[0].last_price
            close_price = bucket[-1].last_price
            high_price = max(q.last_price for q in bucket)
            low_price = min(q.last_price for q in bucket)

            # Checkpoint 31 Part 5: every bar produced by THIS aggregation
            # path is explicitly, typedly SAMPLE_BAR - REST point-sample
            # polling, never continuous tick coverage - see
            # docs/research/TRADING_GRADE_BAR_VALIDATION.md. Never
            # defaulted or inferred; set here at the one place this
            # pipeline's bars are constructed.
            provenance = BarProvenance(
                source=data_source,
                exchange=str(instrument_id).split(":", 1)[0],
                timeframe=timeframe,
                timestamp=interval_end,
                source_timestamp=bucket[-1].timestamp,
                ingestion_timestamp=as_of,
                aggregation_method="point_sample_aggregation",
                quality_grade=BarQualityGrade.SAMPLE_BAR,
                gap_count=gaps_so_far,
            )

            bars.append(
                AggregatedBar(
                    instrument_id=instrument_id,
                    timeframe=timeframe,
                    interval_start=cursor,
                    interval_end=interval_end,
                    open=open_price,
                    high=high_price,
                    low=low_price,
                    close=close_price,
                    status=BarStatus.FORMING if is_forming else BarStatus.CLOSED,
                    observation_count=len(bucket),
                    data_source=data_source,
                    provenance=provenance,
                )
            )
            cursor += duration

    bars.sort(key=lambda b: (str(b.instrument_id), b.interval_start))
    missing.sort(key=lambda m: (str(m.instrument_id), m.interval_start))
    anomalies.sort(key=lambda a: (str(a.instrument_id), a.source_timestamp))

    return BarAggregationResult(
        bars=tuple(bars),
        missing_intervals=tuple(missing),
        anomalous_observations=tuple(anomalies),
    )
