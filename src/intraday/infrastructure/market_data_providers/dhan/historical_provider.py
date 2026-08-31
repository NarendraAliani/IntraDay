# File: src/intraday/infrastructure/market_data_providers/dhan/historical_provider.py
#
# The real Dhan adapter `synthetic_historical.py` predicted: "Swapping
# this for a real Dhan adapter later is a single-class substitution -
# nothing above this Protocol boundary... needs to change." Satisfies
# `HistoricalDataPreparationService`'s `HistoricalBarProvider` Protocol
# using the genuine `historical_client.py` REST client instead of
# generated fixture data.
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from intraday.application.services.instrument_master import InstrumentMasterProvider
from intraday.domain.instrument.contracts import parse_instrument_id
from intraday.domain.market_data.contracts import Bar
from intraday.domain.market_data.provenance import PROVENANCE_REAL_DHAN
from intraday.domain.market_data.source_timestamp import (
    SourceTimestampSemantics,
    canonicalize_close_timestamp,
)
from intraday.domain.shared_kernel.contracts import Exchange, InstrumentId, Timeframe
from intraday.infrastructure.market_data_providers.dhan.historical_client import (
    DhanHistoricalCandle,
    DhanHistoricalDataError,
    fetch_daily_candles,
    fetch_intraday_candles,
)

# Dhan's own documented exchange-segment vocabulary for cash equities -
# see `instruments.py`'s NSE_EQ_SEGMENT for the NSE precedent; BSE_EQ is
# the equivalent, symmetrically-named segment for BSE.
_EXCHANGE_SEGMENTS: dict[Exchange, str] = {Exchange.NSE: "NSE_EQ", Exchange.BSE: "BSE_EQ"}

# Dhan's intraday endpoint only supports these five interval values
# (see `historical_client.py`'s module docstring) - this project's
# Timeframe enum has two members (3m, 30m) with no matching Dhan
# interval. Those are an honest, named gap, not silently rounded to a
# neighboring interval.
_INTRADAY_INTERVAL_MINUTES: dict[Timeframe, int] = {
    Timeframe.ONE_MINUTE: 1,
    Timeframe.FIVE_MINUTE: 5,
    Timeframe.FIFTEEN_MINUTE: 15,
    Timeframe.ONE_HOUR: 60,
}

# Checkpoint 67.1 Part 3: Dhan's `/v2/charts/intraday` raw candle
# timestamp is OPEN-of-interval - PROVEN in Checkpoint 67.0 for 5m (15/15
# interior-bucket OPEN matches, 0/15 CLOSE matches, request-boundary
# confounding explicitly ruled out). The arithmetic this classification
# feeds (`canonicalize_close_timestamp`) is generic across every
# interval Dhan's intraday endpoint supports, but per Checkpoint 67.1's
# explicit instruction this is NOT an empirical claim that 1m/15m/1h
# were independently tested - only 5m (and, per 65.25's diagnostic
# batch, 1m raw-count behavior) has been. Classified OPEN for the whole
# intraday endpoint because Dhan documents ONE candle-generation
# mechanism (interval-bucketed OHLC aggregation) across all five of its
# interval values, not a per-interval-different one.
_DHAN_INTRADAY_TIMESTAMP_SEMANTICS = SourceTimestampSemantics.OPEN

# Dhan's DAILY endpoint (`/v2/charts/historical`) is UNCHANGED by this
# checkpoint - it was never part of 67.0's diagnostic (that experiment
# tested only the intraday endpoint's 5m interval) and its raw
# timestamp already round-trips into `Bar.timestamp` unchanged today,
# which is CLOSE semantics by definition (no shift needed). Classifying
# it OPEN or UNKNOWN here would either invent an untested claim or
# break existing, working daily ingestion - neither is this
# checkpoint's job.
_DHAN_DAILY_TIMESTAMP_SEMANTICS = SourceTimestampSemantics.CLOSE


@dataclass(frozen=True, slots=True)
class ProviderRequestEnvelope:
    """Checkpoint 66.7: the OUTBOUND request window this adapter sends to
    Dhan - deliberately a SEPARATE concept from the CANONICAL RESEARCH
    WINDOW (`fetch()`'s own `start`/`end` parameters, which are the
    application's bar-CLOSE timestamps per `HistoricalDataCoverageService.
    _expected_timestamps`). The envelope may be wider than the canonical
    window to protect it from Dhan's own undocumented request-boundary
    behavior; it is NEVER itself the set of bars the application accepts.
    `fetch()`'s pre-existing `start <= candle.timestamp <= end` post-filter
    (untouched by this checkpoint) is what reduces every provider response
    back down to exactly the canonical window - the envelope can only ever
    ask for MORE than the canonical window, never persist more."""

    from_time: datetime
    to_time: datetime


def _provider_request_envelope(
    canonical_start: datetime, canonical_end: datetime, interval_minutes: int
) -> ProviderRequestEnvelope:
    """Widen the canonical `[canonical_start, canonical_end]` bar-close
    window by exactly one bar-duration on each boundary before it becomes
    Dhan's `fromDate`/`toDate`. Pure bar-duration arithmetic derived only
    from `interval_minutes` - never a hard-coded symbol, category, or
    clock time - so it generalizes identically across
    CATEGORY_I_CAS/CATEGORY_II_NON_CAS/PRE_CAS/CAS_ERA and every supported
    intraday interval (1m/5m/15m/1h).

    Lower boundary (`from_time`): PROVEN this checkpoint's predecessor
    (66.6) - a controlled RELIANCE/2026-08-17/5m diagnostic showed the
    unwidened request missing the first expected bar (09:20 IST); widening
    `from_time` by one bar-duration recovered it, with the leading candle
    still excluded correctly by the unchanged post-filter below.

    Upper boundary (`to_time`): Checkpoint 66.7 widened this symmetrically
    on the (then-untested) INFERENCE that Dhan excludes `toDate` the same
    way it excludes `fromDate`. That inference was RUN TO GROUND and
    DISPROVEN by 66.7's own controlled diagnostic: sending `to_time` as
    canonical_end + one bar (15:20 IST for a 15:15 IST canonical end)
    produced the exact same response as the unwidened request - still 71
    candles, still ending at 15:10 IST, still missing a candle at 15:15.
    Widening `to_time` therefore has ZERO demonstrated effect on what
    Dhan returns for this endpoint; it is not a harmless-but-unproven
    abstraction, it is a DISPROVEN one. Checkpoint 66.8 removes it rather
    than keep dead production behavior - see that checkpoint's
    `taskReport.md` (Part 5/E/F) for the full reasoning, including the
    separate, still-open hypothesis (informed by a Checkpoint 44 curl
    finding on a different symbol/interval, `docs/research/
    TRADING_GRADE_BAR_VALIDATION.md`) that Dhan's raw candle timestamp may
    be OPEN-of-interval rather than CLOSE-of-interval, which would explain
    the "missing" 15:15 bar as a labeling mismatch rather than a genuinely
    absent candle - a question this envelope's boundary arithmetic cannot
    answer either way.

    Lower boundary (`from_time`) is UNCHANGED and remains widened by one
    bar - that effect (recovering the 09:20 IST candle) was independently
    proven in 66.6 and is not affected by this checkpoint's finding."""
    one_bar = timedelta(minutes=interval_minutes)
    return ProviderRequestEnvelope(
        from_time=canonical_start - one_bar,
        to_time=canonical_end,
    )


class DhanHistoricalBarProviderUnavailableError(RuntimeError):
    """Raised whenever this provider cannot serve a `fetch()` request -
    no credentials configured, an unsupported timeframe, an instrument
    absent from the scrip master, or any Dhan API failure. The ONE
    exception type `HistoricalDataPreparationService` needs to catch
    (mirrors `synthetic_historical.py`'s own
    `HistoricalBarProviderUnavailableError` contract exactly, so this
    real adapter is a genuine drop-in substitute for that stand-in)."""


def _candle_to_bar(
    instrument_id: InstrumentId,
    timeframe: Timeframe,
    candle: DhanHistoricalCandle,
    *,
    semantics: SourceTimestampSemantics,
    interval_duration: timedelta,
) -> Bar:
    """Checkpoint 67.1 Part 3/5: the ONE place a raw provider candle
    becomes a canonical `Bar` - and therefore the ONE place its
    timestamp is canonicalized (`canonicalize_close_timestamp`) BEFORE
    anything downstream (including `fetch()`'s own canonical
    `[start, end]` filter, applied to the returned `Bar.timestamp`, not
    to `candle.timestamp`) ever sees it. Previously this function
    copied `candle.timestamp` verbatim - the confirmed 67.0 mislabeling
    bug for Dhan intraday (OPEN raw timestamp treated as if it were
    already the CLOSE the rest of the application assumes)."""
    canonical_timestamp = canonicalize_close_timestamp(
        candle.timestamp, semantics, interval_duration
    )
    return Bar(
        instrument_id=instrument_id,
        timeframe=timeframe,
        timestamp=canonical_timestamp,
        open=Decimal(str(candle.open)),
        high=Decimal(str(candle.high)),
        low=Decimal(str(candle.low)),
        close=Decimal(str(candle.close)),
        volume=Decimal(str(candle.volume)),
    )


@dataclass
class DhanHistoricalBarProvider:
    """Satisfies `HistoricalDataPreparationService`'s `HistoricalBarProvider`
    Protocol using real Dhan REST calls. `client_id`/`access_token` are
    resolved by the caller (typically via `DhanSettingsService.
    effective_credentials()`, this codebase's one canonical credential
    source - see `market_data_ingestion_runtime.py`) and passed in
    explicitly, so this class has no direct Django/settings dependency
    of its own, matching every other provider in this package."""

    client_id: str
    access_token: str
    instrument_master: InstrumentMasterProvider
    provenance: str = field(default=PROVENANCE_REAL_DHAN, init=False)
    """Checkpoint 65.23: every bar this provider returns came from a
    genuine Dhan historical REST call - see module docstring. Mirrors
    `SyntheticHistoricalBarProvider.provenance`'s precedent exactly, so
    `HistoricalDataPreparationService` stamps `HistoricalBar.provenance
    = REAL_DHAN` instead of silently falling back to UNKNOWN (the exact
    defect 65.22-R identified: this attribute was previously absent)."""

    def _security_id(self, exchange: Exchange, symbol: str) -> int:
        for entry in self.instrument_master.list_instruments(exchange):
            if entry.symbol == symbol and entry.security_id is not None:
                return entry.security_id
        raise DhanHistoricalBarProviderUnavailableError(
            f"no verified Dhan security_id for {exchange.value}:{symbol} - "
            "not present in the current scrip master."
        )

    def fetch(
        self,
        instrument_id: InstrumentId,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> tuple[Bar, ...]:
        exchange, symbol = parse_instrument_id(instrument_id)
        exchange_segment = _EXCHANGE_SEGMENTS.get(exchange)
        if exchange_segment is None:
            raise DhanHistoricalBarProviderUnavailableError(
                f"Dhan historical data is not supported for exchange {exchange.value!r}."
            )
        security_id = self._security_id(exchange, symbol)

        try:
            if timeframe is Timeframe.DAY:
                candles = fetch_daily_candles(
                    client_id=self.client_id,
                    access_token=self.access_token,
                    security_id=security_id,
                    exchange_segment=exchange_segment,
                    from_date=start.date(),
                    to_date=end.date(),
                )
                semantics = _DHAN_DAILY_TIMESTAMP_SEMANTICS
                interval_duration = timedelta(0)
            else:
                interval_minutes = _INTRADAY_INTERVAL_MINUTES.get(timeframe)
                if interval_minutes is None:
                    raise DhanHistoricalBarProviderUnavailableError(
                        f"Dhan's intraday historical API has no {timeframe.value!r} interval - "
                        "only 1m/5m/15m/1h and daily bars are supported."
                    )
                # Checkpoint 66.8 (envelope shape last revised here;
                # concept introduced 66.7): `start`/`end` here are the
                # CANONICAL RESEARCH WINDOW - the caller's expected
                # bar-CLOSE timestamps (see `HistoricalDataCoverageService.
                # _expected_timestamps`) - and are never mutated. The
                # PROVIDER REQUEST ENVELOPE (`_provider_request_envelope`,
                # module-level above) is a separate, narrower concept:
                # the outbound `fromDate`/`toDate` Dhan actually receives.
                # `from_time` is widened by one bar-duration below the
                # canonical start - PROVEN (66.6) to recover a candle
                # Dhan otherwise omits at the raw request boundary.
                # `to_time` is sent as the UNWIDENED canonical end -
                # 66.7's own controlled diagnostic DISPROVED any benefit
                # from widening it (see `_provider_request_envelope`'s
                # docstring), so 66.8 removed that widening rather than
                # keep production behavior with a demonstrated null
                # effect. Whatever Dhan returns is still reduced to the
                # canonical window by the post-filter below - which,
                # since Checkpoint 67.1, runs on the CANONICALIZED
                # `bar.timestamp` (post OPEN->CLOSE shift), not on the
                # raw `candle.timestamp` - see Part 5 comment below.
                envelope = _provider_request_envelope(start, end, interval_minutes)
                candles = fetch_intraday_candles(
                    client_id=self.client_id,
                    access_token=self.access_token,
                    security_id=security_id,
                    exchange_segment=exchange_segment,
                    interval_minutes=interval_minutes,
                    from_time=envelope.from_time,
                    to_time=envelope.to_time,
                )
                semantics = _DHAN_INTRADAY_TIMESTAMP_SEMANTICS
                interval_duration = timedelta(minutes=interval_minutes)
        except DhanHistoricalDataError as exc:
            raise DhanHistoricalBarProviderUnavailableError(
                f"Dhan historical fetch failed for {instrument_id} {timeframe.value}: {exc}"
            ) from exc

        # Checkpoint 67.1 Part 5 (the crux of this checkpoint): every raw
        # candle is canonicalized (OPEN raw timestamp -> CLOSE canonical
        # timestamp, via `_candle_to_bar`) BEFORE the canonical
        # `[start, end]` filter runs. The filter below compares
        # `bar.timestamp` (already canonical) against the caller's
        # canonical `start`/`end` - NEVER `candle.timestamp` (raw). Doing
        # it in the opposite order (filter raw, then shift) was the
        # confirmed bug this checkpoint fixes: it would have discarded
        # the raw 09:15 candle (which is < canonical start 09:20) before
        # that candle ever got the chance to become the canonical 09:20
        # close - see this checkpoint's `taskReport.md` Part F for the
        # worked example.
        bars = tuple(
            _candle_to_bar(
                instrument_id,
                timeframe,
                candle,
                semantics=semantics,
                interval_duration=interval_duration,
            )
            for candle in candles
        )
        return tuple(bar for bar in bars if start <= bar.timestamp <= end)


__all__ = [
    "DhanHistoricalBarProvider",
    "DhanHistoricalBarProviderUnavailableError",
    "ProviderRequestEnvelope",
]
