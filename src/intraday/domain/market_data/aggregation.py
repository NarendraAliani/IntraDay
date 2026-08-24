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
    volume: Decimal = Decimal("0")
    """Checkpoint 64.64: real per-bar traded volume, derived by
    `aggregate_quotes_into_bars()` (the ONE place this is computed - see
    that function's own docstring for the exact differencing rule) by
    differencing consecutive `Quote.cumulative_volume` readings.
    `Decimal("0")` remains the honest default for every bar built from
    quotes that never carried a `cumulative_volume` at all (e.g. every
    REST point-sample quote, and every Dhan Ticker-packet-sourced quote)
    - unchanged, not a regression: this field was ALWAYS `Decimal("0")`
    for those sources before this checkpoint, and still is, because no
    volume was ever measured for them. Defaulted (rather than required)
    so every pre-existing direct `AggregatedBar(...)` construction in
    this codebase's own tests remains valid unchanged."""
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
        if self.volume < 0:
            raise ValueError("AggregatedBar.volume must not be negative")

    def to_bar(self) -> Bar:
        """Converts a CLOSED `AggregatedBar` into the canonical `Bar`
        contract - raises `IncompleteBarError` if called on a FORMING
        bar (Checkpoint 24A §6's "the existing signal engine must never
        receive an incomplete bar"). `Bar.timestamp` (bar CLOSE time,
        per its own Checkpoint 5/14 convention) is this bar's
        `interval_end`. Checkpoint 64.64: `Bar.volume` now carries THIS
        `AggregatedBar`'s own `volume` field - real, differenced traded
        volume when the underlying quotes carried `cumulative_volume`,
        or the honest `Decimal("0")` default when they did not (see
        `AggregatedBar.volume`'s own docstring, and
        `aggregate_quotes_into_bars()`'s differencing rule). Volume is
        still never fabricated here - this method only forwards whatever
        `aggregate_quotes_into_bars()` already, legitimately computed."""
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
            volume=self.volume,
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
        VOLUME = Checkpoint 64.64: differenced from `Quote.
                cumulative_volume` (see the dedicated "Volume" section
                below) when present; `Decimal("0")`, honestly, when the
                underlying quotes never carried one at all (unchanged
                from before this checkpoint for those sources).

    Volume (Checkpoint 64.64): per instrument, quotes are walked in the
    SAME chronologically-sorted order used for OHLC above, tracking a
    running `baseline` = the last real (non-`None`) `cumulative_volume`
    seen so far for this instrument, across the ENTIRE observed span
    (not reset per-bucket) - this is what lets a bucket with no volume-
    carrying quotes of its own still correctly diff against the last
    real reading from an earlier bucket, rather than losing volume at
    every ordinary bucket boundary. For each interval:
      - if no quote in the bucket carries a `cumulative_volume`, this
        bar's `volume` is `Decimal("0")` (nothing was measured) and
        `baseline` is left unchanged.
      - else, `latest` = the LAST (by the same chronological order)
        `cumulative_volume` observed in the bucket:
          - FIRST OBSERVATION EVER for this instrument (`baseline is
            None`): `volume = Decimal("0")` - there is no prior reading
            to difference against, so nothing is fabricated; `baseline`
            becomes `latest`.
          - `latest >= baseline` (the ordinary case): `volume = latest -
            baseline`. A `Quote` observed a SECOND time with the exact
            same `cumulative_volume` (a duplicate event, or two packets
            in the same bucket with no new trades between them)
            contributes `0` to this difference, correctly.
          - `latest < baseline` (a genuine DECREASE): treated as a
            SESSION RESET / provider restart / bad-packet recovery,
            per this project's own documented rule - the cumulative
            series is treated as having restarted from zero at this
            point, so `volume = latest` (never `latest - baseline`,
            which would be negative). `baseline` becomes `latest`
            either way, so the NEXT bucket diffs against the new,
            lower series correctly rather than against the stale
            pre-reset value.
      - Out-of-order and duplicate quotes are handled by the SAME
        chronological sort/bucketing OHLC already relies on - volume
        differencing never sees its own separate, divergent ordering.
      - `AggregatedBar.volume` (hence `Bar.volume` via `to_bar()`) is
        NEVER negative - enforced both by this differencing rule (the
        reset branch above) and, redundantly, by `AggregatedBar.
        __post_init__`'s own explicit check.

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
        # Checkpoint 64.64: the running cumulative-volume baseline for
        # THIS instrument, tracked across the whole chronological walk
        # (buckets are visited in ascending `cursor` order, which is the
        # same chronological order `ordered`/`buckets` were built from
        # above) - see this function's own "Volume" docstring section
        # for the exact rule.
        volume_baseline: Decimal | None = None
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

            bucket_cumulative_readings = [
                q.cumulative_volume for q in bucket if q.cumulative_volume is not None
            ]
            if not bucket_cumulative_readings:
                bar_volume = Decimal("0")
            else:
                latest_cumulative = bucket_cumulative_readings[-1]
                if volume_baseline is None:
                    # First real cumulative-volume observation ever seen
                    # for this instrument - nothing to difference against
                    # yet, so this bar's own volume is honestly 0, not
                    # the whole day's cumulative total.
                    bar_volume = Decimal("0")
                elif latest_cumulative >= volume_baseline:
                    bar_volume = latest_cumulative - volume_baseline
                else:
                    # A genuine decrease - session reset / provider
                    # restart / bad packet, per this project's own
                    # documented rule (see the "Volume" docstring
                    # section above): treat the series as restarted from
                    # zero, never produce a negative volume.
                    bar_volume = latest_cumulative
                volume_baseline = latest_cumulative

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
                    volume=bar_volume,
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
