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

import enum

from intraday.application.services.instrument_master import InstrumentMasterProvider
from intraday.domain.instrument.contracts import parse_instrument_id
from intraday.domain.market_data.contracts import Bar
from intraday.domain.market_data.provenance import PROVENANCE_REAL_DHAN
from intraday.domain.market_data.source_timestamp import (
    CANONICALIZATION_STATE_CANONICALIZED,
    CANONICALIZATION_STATE_NOT_APPLICABLE,
    CANONICALIZATION_STATE_UNKNOWN,
    SourceTimestampSemantics,
    canonicalize_close_timestamp,
)
from intraday.domain.session.calendar import CAS_EFFECTIVE_DATE
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

# Checkpoint 67.5 Parts 1-3 — THE FIX for the exact gap 67.4 itself left
# open: `_EMPIRICALLY_PROVEN_CANONICAL_TIMEFRAMES` (67.4's fix, now
# REMOVED) keyed proof off `timeframe` ALONE. That is still too coarse:
# 67.0's empirical proof (15/15 interior-bucket OPEN match) was run
# against RELIANCE, 2026-08-17, 5-minute, which POSTDATES
# `CAS_EFFECTIVE_DATE` (2026-08-03) — i.e. it proved 5m ONLY for the
# CAS-era, never for PRE-CAS 5m data. Under the 67.4 policy, a future
# ingestion request for PRE-CAS 5m data (e.g. 2026-07-20) would have
# been stamped OPEN/CANONICALIZED purely because it is 5-minute — even
# though 67.0 never tested a single PRE-CAS candle. This is "scope
# leakage": treating a narrower proof (5m, CAS-era) as if it covered a
# broader one (5m, any era).
#
# THE FIX: proof scope is now resolved from (provider, endpoint,
# timeframe, era) — see `_resolve_intraday_proof_scope` below — not from
# `timeframe` alone. `_PROVEN_INTRADAY_SCOPES` names the ONLY
# (timeframe, era) pairs 67.0 actually tested; every other combination
# (1m/15m/1h at any era, or 5m PRE-CAS/MIXED) resolves UNPROVEN and is
# reported UNKNOWN/NOT_RESEARCH_READY, exactly mirroring migration
# 0040's own CAS_EFFECTIVE_DATE-based classification of the 296
# PRE-CAS-5m rows and the 880 1m rows (see that migration's docstring —
# this is the ONGOING policy that migration's one-time reclassification
# already anticipated)."""
_ERA_CAS = "CAS_ERA"
_ERA_PRE_CAS = "PRE_CAS"
_ERA_MIXED_UNRESOLVED = "MIXED_UNRESOLVED"
"""A fetch request whose `[request_start, request_end]` window straddles
`CAS_EFFECTIVE_DATE` — part of the window is CAS-era, part is PRE-CAS.
Deliberately its OWN era value (not silently folded into either side):
resolving it to either CAS-era or PRE-CAS would either over-claim proof
for the PRE-CAS portion or under-claim it for the CAS-era portion. Fails
closed like every other UNKNOWN default in this module — treated as
UNPROVEN by `_resolve_intraday_proof_scope`."""


class ProofStatus(enum.Enum):
    """Whether 67.0-class empirical proof exists for a given
    (timeframe, era) scope. Exhaustive, no default member — mirrors
    `SourceTimestampSemantics`'s own "no silent default" discipline."""

    PROVEN = "PROVEN"
    UNPROVEN = "UNPROVEN"


@dataclass(frozen=True, slots=True)
class DhanTimestampProofScope:
    """Checkpoint 67.5 Part 1, CORRECTED 67.6 Part 1/2: the SMALLEST
    explicit structure that can represent every fact the directive
    requires (provider, endpoint, exchange segment, timeframe, era,
    semantics, canonicalization permitted, proof status) without
    becoming a generic rules engine — one frozen dataclass plus one
    resolver function (`_resolve_intraday_proof_scope`), not a new
    abstraction layer.

    THE 67.6 FIX: 67.5 left `segment` as a field that was carried but
    never consulted by the lookup (`_PROVEN_INTRADAY_SCOPES` was keyed
    only by `(timeframe, era)`) — a "field exists but isn't semantically
    active" bug. 67.0's empirical proof ran against RELIANCE on NSE_EQ
    ONLY; it says nothing about BSE_EQ. `segment` is now a REAL input to
    the proof lookup (see `_PROVEN_INTRADAY_SCOPES` and
    `_resolve_intraday_proof_scope` below): only `segment == "NSE_EQ"`
    can ever resolve PROVEN for the tested (timeframe, era) pair; every
    other segment value (including `"BSE_EQ"` and `None` — an instrument
    whose exchange this module doesn't recognize at all) fails closed to
    UNPROVEN, regardless of timeframe/era. No new empirical claim is
    made about BSE_EQ in either direction — it is simply never treated
    as proven from NSE-only evidence."""

    provider: str
    endpoint: str
    segment: str | None
    timeframe: Timeframe
    era: str
    semantics: SourceTimestampSemantics
    canonicalization_permitted: bool
    proof_status: ProofStatus


# The ONLY (segment, timeframe, era) triples 67.0 actually tested.
# Checkpoint 67.6: segment is now part of the key itself — adding a new
# entry (e.g. a future BSE_EQ diagnostic) requires an independent
# 67.0-style empirical diagnostic for that EXACT triple — never inferred
# from "it's the same endpoint", "it's a nearby timeframe/era", or "NSE
# and BSE share one Dhan candle-generation mechanism" (a plausibility
# argument, not a per-segment empirical proof).
_PROVEN_INTRADAY_SCOPES: frozenset[tuple[str, Timeframe, str]] = frozenset(
    {("NSE_EQ", Timeframe.FIVE_MINUTE, _ERA_CAS)}
)


def _dhan_intraday_era(request_start: datetime, request_end: datetime) -> str:
    """Checkpoint 67.5 Part 1: classifies a Dhan intraday FETCH REQUEST's
    date range against `CAS_EFFECTIVE_DATE` (`domain.session.calendar` —
    the SAME constant migration 0040 already used for its one-time
    per-row reclassification; no parallel date boundary is invented
    here). Applied to the REQUEST window (not a persisted row's
    `bar_timestamp`) because this function must run BEFORE any row
    exists — `historical_data_preparation.py` calls it with the exact
    `missing_range.start`/`.end` it is about to ask the provider for.

    A request whose window straddles `CAS_EFFECTIVE_DATE` resolves
    `MIXED_UNRESOLVED` rather than being guessed either way — fail
    closed, the same discipline every other UNKNOWN default in this
    module already follows."""
    start_is_cas_era = request_start.date() >= CAS_EFFECTIVE_DATE
    end_is_cas_era = request_end.date() >= CAS_EFFECTIVE_DATE
    if start_is_cas_era and end_is_cas_era:
        return _ERA_CAS
    if not start_is_cas_era and not end_is_cas_era:
        return _ERA_PRE_CAS
    return _ERA_MIXED_UNRESOLVED


def _resolve_intraday_proof_scope(
    timeframe: Timeframe,
    request_start: datetime,
    request_end: datetime,
    *,
    segment: str | None = None,
) -> DhanTimestampProofScope:
    """Checkpoint 67.5 Parts 2/3, CORRECTED 67.6 Part 2: the ONE place
    `canonicalization_state_for`/`source_timestamp_semantics_for` below
    consult to decide whether a given (segment, timeframe, era) fetch is
    allowed to be marked canonical. Not called for `Timeframe.DAY` (kept
    out of this transition entirely, unchanged from 67.3/67.4 Part 11 —
    daily is `NOT_APPLICABLE`, never resolved through this function).

    `segment` is keyword-only and defaults to `None` ONLY so this
    function's existing direct callers (tests probing era resolution in
    isolation) keep working without every call site needing to name a
    segment — `None` is itself a real, fail-closed segment value (an
    instrument whose exchange isn't in `_EXCHANGE_SEGMENTS`, or a caller
    that never supplied one), never a silent stand-in for "NSE_EQ" or
    "any segment". The two real production call sites
    (`canonicalization_state_for`/`source_timestamp_semantics_for`)
    always pass a concrete `segment` resolved from the instrument being
    fetched — see `_segment_for_instrument` below."""
    era = _dhan_intraday_era(request_start, request_end)
    proven = (segment, timeframe, era) in _PROVEN_INTRADAY_SCOPES
    return DhanTimestampProofScope(
        provider="DHAN",
        endpoint="INTRADAY",
        segment=segment,
        timeframe=timeframe,
        era=era,
        semantics=SourceTimestampSemantics.OPEN if proven else SourceTimestampSemantics.UNKNOWN,
        canonicalization_permitted=proven,
        proof_status=ProofStatus.PROVEN if proven else ProofStatus.UNPROVEN,
    )


def _segment_for_instrument(instrument_id: InstrumentId) -> str | None:
    """Checkpoint 67.6 Part 2: resolves the SAME `Exchange` ->
    `exchange_segment` mapping `fetch()` already uses
    (`_EXCHANGE_SEGMENTS`, module-level above) so the proof-scope lookup
    reuses this codebase's one existing NSE_EQ/BSE_EQ concept instead of
    inventing a parallel one. Returns `None` (fails closed to UNPROVEN,
    never guesses) for any exchange `_EXCHANGE_SEGMENTS` doesn't
    recognize — mirrors `fetch()`'s own `exchange_segment is None` guard,
    but as a plain lookup rather than a raised error, since these are
    advisory classification hooks, not the fetch call itself."""
    exchange, _symbol = parse_instrument_id(instrument_id)
    return _EXCHANGE_SEGMENTS.get(exchange)

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

    def canonicalization_state_for(
        self,
        instrument_id: InstrumentId,
        timeframe: Timeframe,
        request_start: datetime,
        request_end: datetime,
    ) -> str:
        """Checkpoint 67.3 Part 3/11, CORRECTED 67.4 Part 4, MADE
        ERA-AWARE 67.5 Parts 1-3, MADE SEGMENT-AWARE 67.6 Parts 1-2:
        tells `HistoricalDataPreparationService`
        whether the bars this provider is about to return for
        `timeframe`/`[request_start, request_end]` have already been
        canonicalized (`canonicalize_close_timestamp`) — a PURE
        PROCESSING-STATE fact, WITHOUT that caller needing to know
        Dhan's own timestamp-semantics table.

        DAY -> `NOT_APPLICABLE`, deliberately: Part 11 forbids encoding
        Dhan daily as canonicalized unless independently proven, so
        daily rows are kept OUT of this state transition entirely (era
        is irrelevant for DAY — `_resolve_intraday_proof_scope` is never
        even called for it).

        Every other timeframe is resolved through
        `_resolve_intraday_proof_scope(timeframe, request_start,
        request_end)` — 67.5's fix for the exact gap 67.4 left open:
        `timeframe` ALONE used to be the sole proof key, which meant a
        future PRE-CAS 5m request would have inherited the CAS-era-only
        67.0 proof merely because it is 5-minute. Now ONLY
        `(NSE_EQ, FIVE_MINUTE, CAS_ERA)` resolves `canonicalization_permitted`
        -> `CANONICALIZED` (67.6: `segment` is now a REAL input, resolved
        from `instrument_id` via `_segment_for_instrument` — a BSE_EQ
        instrument with the SAME timeframe/era resolves `UNKNOWN`, never
        `CANONICALIZED`, because 67.0's proof never touched BSE); 5m
        PRE-CAS/MIXED_UNRESOLVED and every other intraday timeframe at
        any era or segment resolve `UNKNOWN` — `fetch()`
        still runs the SAME `+interval` arithmetic on all of them (Dhan
        documents one shared candle-generation mechanism, so applying it
        is harmless/best-effort and keeps `Bar.timestamp` internally
        consistent), but that arithmetic having RUN is never, by itself,
        treated as proof it was semantically JUSTIFIED for a
        (timeframe, era) pair 67.0 never tested. Reporting `UNKNOWN` here
        (rather than `CANONICALIZED`) is what stops
        `ResearchDataGateService` from ever trusting an unproven scope as
        research-ready — see `source_timestamp_semantics_for` below for
        the companion SEMANTICS half of this same fix."""
        if timeframe is Timeframe.DAY:
            return CANONICALIZATION_STATE_NOT_APPLICABLE
        segment = _segment_for_instrument(instrument_id)
        scope = _resolve_intraday_proof_scope(
            timeframe, request_start, request_end, segment=segment
        )
        if scope.canonicalization_permitted:
            return CANONICALIZATION_STATE_CANONICALIZED
        return CANONICALIZATION_STATE_UNKNOWN

    def source_timestamp_semantics_for(
        self,
        instrument_id: InstrumentId,
        timeframe: Timeframe,
        request_start: datetime,
        request_end: datetime,
    ) -> str:
        """Checkpoint 67.4 Part 4, MADE ERA-AWARE 67.5 Parts 1-3, MADE
        SEGMENT-AWARE 67.6 Parts 1-2: the SEMANTICS-half companion to
        `canonicalization_state_for` above —
        tells `HistoricalDataPreparationService` whether this provider's
        raw timestamp CONVENTION (not merely whether the shift ran) has
        ever been empirically proven for this `timeframe`/era.

        DAY -> `NOT_APPLICABLE` (same Part 11 exclusion as above — never
        claimed proven or unproven by this state transition at all).

        Every other timeframe delegates to the SAME
        `_resolve_intraday_proof_scope` call `canonicalization_state_for`
        makes (both methods must always agree on proof status — they are
        two views of the one scope resolution, never independently
        computed) — only `(NSE_EQ, FIVE_MINUTE, CAS_ERA)` resolves `OPEN`,
        the literal 67.0-proven convention; every other
        (segment, timeframe, era) triple — including 5m PRE-CAS (67.5's
        fix) and BSE_EQ 5m CAS-era (67.6's fix — the exact "segment field
        exists but isn't looked up" bug this checkpoint closes) — resolves
        `UNKNOWN`, never `OPEN`, regardless of the shared-mechanism
        plausibility argument. Only actual per-(segment, timeframe, era)
        empirical proof (a future checkpoint's own diagnostic, mirroring
        67.0's) may promote a new entry into
        `_PROVEN_INTRADAY_SCOPES`."""
        if timeframe is Timeframe.DAY:
            return CANONICALIZATION_STATE_NOT_APPLICABLE
        segment = _segment_for_instrument(instrument_id)
        scope = _resolve_intraday_proof_scope(
            timeframe, request_start, request_end, segment=segment
        )
        return scope.semantics.value

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
    "DhanTimestampProofScope",
    "ProofStatus",
    "ProviderRequestEnvelope",
]
