# File: src/intraday/domain/market_data/reconciliation.py
#
# Checkpoint 64.79: THE equity market-data reconciliation contract.
#
# 64.73 built the daily archive and deliberately stopped one step short:
# `ReconciliationStatus` was MODELLED there but never computed, and its
# own docstring says so plainly - "Checkpoint 64.73 MODELS this; it does
# not yet perform it". This module performs it, and nothing more.
#
# The single honesty rule that shapes every decision below:
#
#   A reconciliation is only meaningful when the reference series comes
#   from a genuinely INDEPENDENT pipeline. Re-deriving bar counts from
#   the same observations the archive already assessed is not
#   validation, and this module must never be usable to manufacture
#   that illusion. Hence:
#     * `evidence_source` is REQUIRED and must be non-empty - an
#       unattributed reference series cannot be reconciled against;
#     * an EMPTY reference series yields NOT_RECONCILED, never PASS
#       ("nothing disagreed with us" is not evidence of agreement);
#     * PASS requires full expected-bar coverage on BOTH sides plus
#       zero value mismatches - a partially-overlapping reference can
#       reach PARTIAL at best.
#
# This module composes, and never re-implements:
#   * `quality.expected_bar_timestamps` - the expected-interval series;
#   * `archive.is_completeness_supported` - whether an expected count is
#     even defensible for the timeframe against the NSE session.
#
# Pure domain: no Django, no provider knowledge, no I/O.
from __future__ import annotations

import enum
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from intraday.domain.market_data.archive import (
    TradingSessionIdentity,
    is_completeness_supported,
)
from intraday.domain.market_data.quality import expected_bar_timestamps
from intraday.domain.session.contracts import TradingSession
from intraday.domain.shared_kernel.contracts import Timeframe, ensure_utc


class ReconciliationOutcome(enum.StrEnum):
    """The verdict of comparing one archived (symbol, timeframe, day)
    cell against an independent reference series.

    Deliberately FOUR values, and deliberately NOT the same enum as
    `archive.ReconciliationStatus`: that one records what a stored
    archive row currently claims, this one is the computed result of an
    actual comparison run. `NOT_RECONCILED` is the honest value
    whenever no usable reference exists - it is a first-class outcome
    here, not an error."""

    NOT_RECONCILED = "NOT_RECONCILED"
    """No comparison was possible: no reference bars, or the timeframe
    has no defensible expected-bar series (see
    `archive.is_completeness_supported`). Carries a `reason`."""

    # noqa justification: `S105` is a hardcoded-password heuristic
    # firing on the literal "PASS". This is a reconciliation verdict,
    # not a credential.
    PASS = "PASS"  # noqa: S105
    """Every expected bar is present in BOTH series, every matched bar
    agrees within tolerance, and there are no duplicates. The only
    outcome that entitles a consumer to treat the archived day as
    independently validated."""

    PARTIAL = "PARTIAL"
    """Everything compared agreed within tolerance, but coverage is
    incomplete on at least one side (missing bars, or a reference that
    only overlaps part of the session). Agreement on a subset is real
    evidence - it is just not evidence about the whole day."""

    FAIL = "FAIL"
    """At least one matched bar disagreed beyond tolerance, or a
    duplicate timestamp was found. A value disagreement is never
    downgraded to PARTIAL by also having gaps - a wrong price is a
    stronger finding than a missing one."""


@dataclass(frozen=True, slots=True)
class ReconciliationTolerance:
    """How close two independently-produced series must be to count as
    agreeing.

    Non-zero defaults are deliberate and are NOT a weakening: a bar
    aggregated from a live quote stream and the same bar served by a
    provider's historical-candle API are built from different inputs
    (sampled quotes vs. the exchange's own consolidated candle), so
    demanding bit-identical Decimals would report FAIL on every healthy
    day and make the whole check useless. The tolerances are tight
    enough that a genuinely wrong bar still fails."""

    price: Decimal = Decimal("0.05")
    """Absolute price tolerance, in rupees, applied to each of O/H/L/C."""

    volume: Decimal = Decimal("0")
    """Absolute traded-volume tolerance. Defaults to ZERO deliberately:
    unlike price, volume has no sampling-noise excuse - but see
    `compare_volume`, which is OFF by default because this platform's
    live bars carry `Decimal("0")` volume for every quote source that
    never reported `cumulative_volume` (see `AggregatedBar.volume`).
    Comparing a known-unmeasured zero against a real reference volume
    would report a fabricated FAIL."""

    timestamp: timedelta = timedelta(0)
    """How far apart two bar-close instants may be and still be
    considered the same bar. Defaults to ZERO: both sides of this
    comparison are already normalised to UTC bar-CLOSE instants on the
    same interval grid, so any drift is a real finding, not noise."""

    compare_volume: bool = False
    """Whether volume participates in the verdict at all. See `volume`
    above for why this is opt-in rather than always-on."""

    def __post_init__(self) -> None:
        if self.price < 0:
            raise ValueError("ReconciliationTolerance.price must not be negative")
        if self.volume < 0:
            raise ValueError("ReconciliationTolerance.volume must not be negative")
        if self.timestamp < timedelta(0):
            raise ValueError("ReconciliationTolerance.timestamp must not be negative")


@dataclass(frozen=True, slots=True)
class ReferenceBar:
    """One bar from the INDEPENDENT reference series, reduced to exactly
    the fields a reconciliation compares.

    A deliberately narrow local shape rather than the canonical `Bar`:
    the reference side is whatever an independent pipeline can supply,
    and forcing it through `Bar`'s full invariants would mean a
    reference row this platform considers malformed could never be
    reported as a MISMATCH - it would raise instead, losing the
    finding."""

    timestamp: datetime  # bar CLOSE instant, UTC
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        ensure_utc(self.timestamp, field_name="ReferenceBar.timestamp")


@dataclass(frozen=True, slots=True)
class ObservedBar:
    """One bar from THIS platform's own archive, in the same reduced
    shape as `ReferenceBar` so the comparison is symmetric."""

    timestamp: datetime  # bar CLOSE instant, UTC
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        ensure_utc(self.timestamp, field_name="ObservedBar.timestamp")


@dataclass(frozen=True, slots=True)
class BarFieldMismatch:
    """One field of one bar disagreeing beyond tolerance. Keeps BOTH
    values and the delta - a reconciliation report that only said "3
    bars mismatched" would not be actionable evidence."""

    timestamp: datetime
    field_name: str
    observed: Decimal
    reference: Decimal

    @property
    def delta(self) -> Decimal:
        return self.observed - self.reference


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    """The complete, self-contained result of reconciling ONE
    (trading_date, symbol, timeframe) cell against one reference series.

    A pure VALUE - producing it writes nothing. Every field the 64.79
    contract requires is present explicitly rather than being derivable
    only by re-running the comparison."""

    identity: TradingSessionIdentity
    instrument_symbol: str
    timeframe: Timeframe
    evidence_source: str
    outcome: ReconciliationOutcome
    reason: str
    tolerance: ReconciliationTolerance
    expected_bar_count: int
    observed_bar_count: int
    reference_bar_count: int
    matched_bar_count: int
    observed_missing_timestamps: tuple[datetime, ...] = field(default_factory=tuple)
    reference_missing_timestamps: tuple[datetime, ...] = field(default_factory=tuple)
    observed_duplicate_timestamps: tuple[datetime, ...] = field(default_factory=tuple)
    reference_duplicate_timestamps: tuple[datetime, ...] = field(default_factory=tuple)
    unmatched_observed_timestamps: tuple[datetime, ...] = field(default_factory=tuple)
    unmatched_reference_timestamps: tuple[datetime, ...] = field(default_factory=tuple)
    mismatches: tuple[BarFieldMismatch, ...] = field(default_factory=tuple)
    observed_first_timestamp: datetime | None = None
    observed_last_timestamp: datetime | None = None
    reference_first_timestamp: datetime | None = None
    reference_last_timestamp: datetime | None = None

    @property
    def is_independently_validated(self) -> bool:
        """The single question a downstream research consumer actually
        asks. Only a PASS answers it YES - PARTIAL deliberately does
        not, because agreement on a subset of a day says nothing about
        the rest of it."""
        return self.outcome is ReconciliationOutcome.PASS

    @property
    def mismatch_count(self) -> int:
        return len(self.mismatches)


def _duplicates(timestamps: Sequence[datetime]) -> tuple[datetime, ...]:
    seen: set[datetime] = set()
    duplicated: set[datetime] = set()
    for stamp in timestamps:
        if stamp in seen:
            duplicated.add(stamp)
        seen.add(stamp)
    return tuple(sorted(duplicated))


def _match_reference(
    target: datetime,
    reference_by_timestamp: dict[datetime, ReferenceBar],
    tolerance: timedelta,
) -> ReferenceBar | None:
    """Finds the reference bar for `target`. An exact hit always wins;
    only when tolerance is non-zero does this fall back to the NEAREST
    reference bar within it, so a zero tolerance (the default) can never
    silently pair up two different intervals."""
    exact = reference_by_timestamp.get(target)
    if exact is not None:
        return exact
    if tolerance <= timedelta(0):
        return None
    best: ReferenceBar | None = None
    best_delta: timedelta | None = None
    for stamp, bar in reference_by_timestamp.items():
        delta = abs(stamp - target)
        if delta <= tolerance and (best_delta is None or delta < best_delta):
            best, best_delta = bar, delta
    return best


def reconcile_bar_series(
    *,
    identity: TradingSessionIdentity,
    instrument_symbol: str,
    timeframe: Timeframe,
    session: TradingSession,
    observed_bars: Sequence[ObservedBar],
    reference_bars: Sequence[ReferenceBar],
    evidence_source: str,
    tolerance: ReconciliationTolerance | None = None,
) -> ReconciliationReport:
    """Compares one archived bar series against one independent
    reference series.

    `evidence_source` names WHERE the reference came from (e.g.
    `"dhan_historical_intraday_api"`) and is required to be non-empty:
    an unattributed reference is not evidence, and a report that could
    not say what it compared against would be unauditable.

    Decision order (the honesty rules of this checkpoint):
      1. a timeframe with no defensible expected-bar series is
         NOT_RECONCILED - never PASS by vacuum;
      2. an empty reference series is NOT_RECONCILED - "nothing
         disagreed" is not agreement;
      3. any value disagreement beyond tolerance, or any duplicate
         timestamp on either side, is FAIL;
      4. incomplete coverage on either side is PARTIAL;
      5. PASS only when every expected bar is present on BOTH sides and
         every matched bar agrees.
    """
    if not evidence_source.strip():
        raise ValueError("reconcile_bar_series requires a non-empty evidence_source")

    effective_tolerance = tolerance or ReconciliationTolerance()

    # No re-validation of UTC-ness here: `ObservedBar`/`ReferenceBar`
    # both enforce it in `__post_init__`, so a non-UTC instant cannot
    # reach this function in the first place.
    observed_stamps = [bar.timestamp for bar in observed_bars]
    reference_stamps = [bar.timestamp for bar in reference_bars]
    supported = is_completeness_supported(timeframe)
    expected = expected_bar_timestamps(session, timeframe) if supported else ()

    observed_duplicates = _duplicates(observed_stamps)
    reference_duplicates = _duplicates(reference_stamps)

    observed_by_timestamp = {bar.timestamp: bar for bar in observed_bars}
    reference_by_timestamp = {bar.timestamp: bar for bar in reference_bars}

    def build(
        outcome: ReconciliationOutcome,
        reason: str,
        *,
        matched: int = 0,
        mismatches: tuple[BarFieldMismatch, ...] = (),
        unmatched_observed: tuple[datetime, ...] = (),
        unmatched_reference: tuple[datetime, ...] = (),
    ) -> ReconciliationReport:
        return ReconciliationReport(
            identity=identity,
            instrument_symbol=instrument_symbol,
            timeframe=timeframe,
            evidence_source=evidence_source,
            outcome=outcome,
            reason=reason,
            tolerance=effective_tolerance,
            expected_bar_count=len(expected),
            observed_bar_count=len(observed_by_timestamp),
            reference_bar_count=len(reference_by_timestamp),
            matched_bar_count=matched,
            observed_missing_timestamps=tuple(
                stamp for stamp in expected if stamp not in observed_by_timestamp
            ),
            reference_missing_timestamps=tuple(
                stamp for stamp in expected if stamp not in reference_by_timestamp
            ),
            observed_duplicate_timestamps=observed_duplicates,
            reference_duplicate_timestamps=reference_duplicates,
            unmatched_observed_timestamps=unmatched_observed,
            unmatched_reference_timestamps=unmatched_reference,
            mismatches=mismatches,
            observed_first_timestamp=min(observed_stamps) if observed_stamps else None,
            observed_last_timestamp=max(observed_stamps) if observed_stamps else None,
            reference_first_timestamp=min(reference_stamps) if reference_stamps else None,
            reference_last_timestamp=max(reference_stamps) if reference_stamps else None,
        )

    if not supported:
        return build(
            ReconciliationOutcome.NOT_RECONCILED,
            f"completeness_unsupported_timeframe:{timeframe.value}",
        )
    if not reference_bars:
        return build(
            ReconciliationOutcome.NOT_RECONCILED,
            "no_reference_bars_available",
        )
    if not observed_bars:
        return build(
            ReconciliationOutcome.NOT_RECONCILED,
            "no_observed_bars_to_reconcile",
        )

    mismatches: list[BarFieldMismatch] = []
    matched_reference_stamps: set[datetime] = set()
    unmatched_observed: list[datetime] = []
    matched = 0

    for stamp in sorted(observed_by_timestamp):
        observed = observed_by_timestamp[stamp]
        reference = _match_reference(stamp, reference_by_timestamp, effective_tolerance.timestamp)
        if reference is None:
            unmatched_observed.append(stamp)
            continue
        matched += 1
        matched_reference_stamps.add(reference.timestamp)
        for field_name in ("open", "high", "low", "close"):
            observed_value = getattr(observed, field_name)
            reference_value = getattr(reference, field_name)
            if abs(observed_value - reference_value) > effective_tolerance.price:
                mismatches.append(
                    BarFieldMismatch(
                        timestamp=stamp,
                        field_name=field_name,
                        observed=observed_value,
                        reference=reference_value,
                    )
                )
        if effective_tolerance.compare_volume and (
            abs(observed.volume - reference.volume) > effective_tolerance.volume
        ):
            mismatches.append(
                BarFieldMismatch(
                    timestamp=stamp,
                    field_name="volume",
                    observed=observed.volume,
                    reference=reference.volume,
                )
            )

    unmatched_reference = tuple(
        stamp for stamp in sorted(reference_by_timestamp) if stamp not in matched_reference_stamps
    )

    def verdict(outcome: ReconciliationOutcome, reason: str) -> ReconciliationReport:
        return build(
            outcome,
            reason,
            matched=matched,
            mismatches=tuple(mismatches),
            unmatched_observed=tuple(unmatched_observed),
            unmatched_reference=unmatched_reference,
        )

    if observed_duplicates or reference_duplicates:
        return verdict(
            ReconciliationOutcome.FAIL,
            f"duplicate_bar_timestamps:{len(observed_duplicates) + len(reference_duplicates)}",
        )
    if mismatches:
        return verdict(ReconciliationOutcome.FAIL, f"value_mismatches:{len(mismatches)}")

    observed_missing = [stamp for stamp in expected if stamp not in observed_by_timestamp]
    reference_missing = [stamp for stamp in expected if stamp not in reference_by_timestamp]
    if observed_missing or reference_missing or unmatched_observed or unmatched_reference:
        return verdict(
            ReconciliationOutcome.PARTIAL,
            (
                f"incomplete_coverage:observed_missing={len(observed_missing)}"
                f",reference_missing={len(reference_missing)}"
                f",unmatched_observed={len(unmatched_observed)}"
                f",unmatched_reference={len(unmatched_reference)}"
            ),
        )
    return verdict(ReconciliationOutcome.PASS, "full_session_agreement_within_tolerance")


__all__ = [
    "BarFieldMismatch",
    "ObservedBar",
    "ReconciliationOutcome",
    "ReconciliationReport",
    "ReconciliationTolerance",
    "ReferenceBar",
    "reconcile_bar_series",
]
