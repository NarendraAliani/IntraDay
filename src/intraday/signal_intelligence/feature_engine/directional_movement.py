# File: src/intraday/signal_intelligence/feature_engine/directional_movement.py
#
# Checkpoint 64.49: +DI / -DI / ADX - the canonical directional-movement
# feature family, addressing 64.48's discovered gap (RSI/ADX/+DI/-DI/etc.
# missing from the feature registry). PLATFORM feature, not Gainz-
# specific - no Gainz reference source exists in this repository (see
# `field_registry.py` module docstring and taskReport.md).
#
# ---------------------------------------------------------------------------
# FORMULA SOURCE - CRITICAL
# ---------------------------------------------------------------------------
#
# Convention: Wilder's ORIGINAL directional-movement system (J. Welles
# Wilder Jr., "New Concepts in Technical Trading Systems", 1978) - the
# same source this project's `atr.py` already cites, and ADX/+DI/-DI are
# defined in that SAME book, sharing True Range as a building block. This
# is the STANDARD, universally-meant convention for "+DI/-DI/ADX" - it is
# NOT verified against any Gainz reference implementation (none exists).
#
#     +DM_t = high_t - high_(t-1)   if that value > (low_(t-1) - low_t)
#                                       and > 0, else 0
#     -DM_t = low_(t-1) - low_t     if that value > (high_t - high_(t-1))
#                                       and > 0, else 0
#     TR_t  = max(high_t - low_t, |high_t - close_(t-1)|,
#                 |low_t - close_(t-1)|)                (identical to atr.py)
#
#     avg_TR_t, avg_+DM_t, avg_-DM_t: each independently Wilder-smoothed
#         over period N exactly like `atr.py`'s ATR recurrence (seed =
#         simple mean of the first N observations; then
#         `avg_t = (avg_(t-1) * (N-1) + new_t) / N`).
#
#     +DI_t = 100 * avg_+DM_t / avg_TR_t   (0 if avg_TR_t == 0)
#     -DI_t = 100 * avg_-DM_t / avg_TR_t   (0 if avg_TR_t == 0)
#     DX_t  = 100 * |+DI_t - -DI_t| / (+DI_t + -DI_t)   (0 if denom == 0)
#     ADX_t = Wilder-smoothed average of DX over the SAME period N (seed
#             = simple mean of the first N DX values; then the identical
#             Wilder recurrence applied to the DX series).
#
# Single `lookback` parameter (Checkpoint 64.49 Part 7's own instruction
# to keep the identity pattern to one positive-integer parameter, as
# SMA/EMA/ATR already do): the DI smoothing period and the ADX smoothing
# period are the SAME N - the standard convention (e.g. "ADX(14)" means
# both the directional-index and the ADX-of-DX smoothing use period 14).
#
# ---------------------------------------------------------------------------
# Shared internal calculation (Checkpoint 64.49 Part 7's "avoid
# recomputing the same intermediate values")
# ---------------------------------------------------------------------------
#
# `_compute_directional_series` is the ONE private function that computes
# TR/+DM/-DM, +DI/-DI, and DX/ADX. All three public entry points
# (`compute_plus_directional_index`, `compute_minus_directional_index`,
# `compute_average_directional_index`) call this SAME helper and simply
# select the field they need - no separate ADX-specific mini framework,
# no triplicated smoothing logic. Known limitation (documented honestly,
# not hidden): if a coordinator run requests all three fields
# (`plus_di_14`, `minus_di_14`, `adx_14`) in the same cycle, each
# `field_id` is still dispatched (and this helper re-run) independently,
# because the coordinator's shared-feature cache in
# `coordinator.py` is keyed per `field_id`, not per underlying
# calculation - a genuine, named opportunity for a future optimization,
# not solved this checkpoint (out of scope: "avoid a second indicator
# framework" takes priority over a cross-field_id calculation cache).
#
# ---------------------------------------------------------------------------
# Warm-up
# ---------------------------------------------------------------------------
#
# +DI/-DI's first value requires `N + 1` bars (identical shape to ATR:
# bar 0 supplies only the previous high/low/close, N more bars produce
# the N TR/+DM/-DM observations that seed the Wilder average).
# ADX additionally needs N DX observations to seed ITS OWN Wilder
# average, so ADX's first value requires `2N + 1` bars total. Fewer bars
# than a feature's own requirement -> empty tuple, never a fabricated or
# partial-window value.
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from intraday.domain.feature.contracts import FeatureValue
from intraday.domain.market_data.contracts import Bar
from intraday.domain.market_data.quality import ensure_chronological
from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe
from intraday.signal_intelligence.feature_engine.definitions import (
    DirectionalMovementDefinition,
)
from intraday.signal_intelligence.feature_engine.errors import (
    MixedInstrumentSeriesError,
    MixedTimeframeSeriesError,
)

_HUNDRED = Decimal(100)


@dataclass(frozen=True, slots=True)
class _DirectionalPoint:
    timestamp: datetime
    plus_di: Decimal
    minus_di: Decimal
    dx: Decimal
    adx: Decimal | None  # None until the ADX-of-DX Wilder seed is reached


def _validate_series(bars: tuple[Bar, ...]) -> tuple[InstrumentId, Timeframe]:
    instrument_id = bars[0].instrument_id
    timeframe = bars[0].timeframe
    for bar in bars:
        if bar.instrument_id != instrument_id:
            raise MixedInstrumentSeriesError(
                f"bar series mixes instruments {instrument_id!r} and "
                f"{bar.instrument_id!r} - a feature series must come from one instrument"
            )
        if bar.timeframe != timeframe:
            raise MixedTimeframeSeriesError(
                f"bar series mixes timeframes {timeframe!r} and {bar.timeframe!r} "
                "- a feature calculation must never blend timeframes"
            )
    return instrument_id, timeframe


def _compute_directional_series(
    lookback: int, bars: tuple[Bar, ...]
) -> tuple[InstrumentId, Timeframe, list[_DirectionalPoint]]:
    ensure_chronological(bars)
    instrument_id, timeframe = _validate_series(bars)

    if len(bars) < lookback + 1:
        return instrument_id, timeframe, []

    # tr/plus_dm/minus_dm[i] corresponds to bars[i + 1] (first-bar policy,
    # identical to atr.py).
    triples: list[tuple[Bar, Decimal, Decimal, Decimal]] = []
    for previous, current in zip(bars, bars[1:], strict=False):
        up_move = current.high - previous.high
        down_move = previous.low - current.low
        plus_dm = up_move if (up_move > down_move and up_move > 0) else Decimal(0)
        minus_dm = down_move if (down_move > up_move and down_move > 0) else Decimal(0)
        tr = max(
            current.high - current.low,
            abs(current.high - previous.close),
            abs(current.low - previous.close),
        )
        triples.append((current, tr, plus_dm, minus_dm))

    n = Decimal(lookback)
    n_minus_1 = Decimal(lookback - 1)

    seed_window = triples[:lookback]
    avg_tr = sum((tr for _, tr, _, _ in seed_window), Decimal(0)) / lookback
    avg_plus = sum((p for _, _, p, _ in seed_window), Decimal(0)) / lookback
    avg_minus = sum((m for _, _, _, m in seed_window), Decimal(0)) / lookback

    def _di_dx(
        avg_tr_: Decimal, avg_plus_: Decimal, avg_minus_: Decimal
    ) -> tuple[Decimal, Decimal, Decimal]:
        if avg_tr_ == 0:
            plus_di = Decimal(0)
            minus_di = Decimal(0)
        else:
            plus_di = _HUNDRED * avg_plus_ / avg_tr_
            minus_di = _HUNDRED * avg_minus_ / avg_tr_
        denom = plus_di + minus_di
        dx = (_HUNDRED * abs(plus_di - minus_di) / denom) if denom != 0 else Decimal(0)
        return plus_di, minus_di, dx

    di_dx_series: list[tuple[Bar, Decimal, Decimal, Decimal]] = []
    plus_di, minus_di, dx = _di_dx(avg_tr, avg_plus, avg_minus)
    di_dx_series.append((seed_window[-1][0], plus_di, minus_di, dx))

    for bar, tr, plus_dm, minus_dm in triples[lookback:]:
        avg_tr = ((avg_tr * n_minus_1) + tr) / n
        avg_plus = ((avg_plus * n_minus_1) + plus_dm) / n
        avg_minus = ((avg_minus * n_minus_1) + minus_dm) / n
        plus_di, minus_di, dx = _di_dx(avg_tr, avg_plus, avg_minus)
        di_dx_series.append((bar, plus_di, minus_di, dx))

    # ADX: Wilder-smoothed average of the DX series above, seeded once
    # `lookback` DX values exist.
    points: list[_DirectionalPoint] = []
    if len(di_dx_series) < lookback:
        for bar, p_di, m_di, dx_val in di_dx_series:
            points.append(_DirectionalPoint(bar.timestamp, p_di, m_di, dx_val, None))
        return instrument_id, timeframe, points

    for bar, p_di, m_di, dx_val in di_dx_series[: lookback - 1]:
        points.append(_DirectionalPoint(bar.timestamp, p_di, m_di, dx_val, None))

    dx_seed_window = di_dx_series[:lookback]
    avg_adx = sum((dx_val for _, _, _, dx_val in dx_seed_window), Decimal(0)) / lookback
    seed_bar, seed_pdi, seed_mdi, seed_dx = dx_seed_window[-1]
    points.append(_DirectionalPoint(seed_bar.timestamp, seed_pdi, seed_mdi, seed_dx, avg_adx))

    for bar, p_di, m_di, dx_val in di_dx_series[lookback:]:
        avg_adx = ((avg_adx * n_minus_1) + dx_val) / n
        points.append(_DirectionalPoint(bar.timestamp, p_di, m_di, dx_val, avg_adx))

    return instrument_id, timeframe, points


def compute_plus_directional_index(
    definition: DirectionalMovementDefinition, bars: tuple[Bar, ...]
) -> tuple[FeatureValue, ...]:
    """+DI(lookback) - see module docstring for the full Wilder
    directional-movement formula and warm-up. No look-ahead: derived
    purely from a forward-only Wilder recurrence over already-iterated
    bars (`ensure_chronological()` enforced)."""
    if not bars:
        return ()
    instrument_id, timeframe, points = _compute_directional_series(definition.lookback, bars)
    return tuple(
        FeatureValue(
            feature_name=definition.plus_di_feature_name,
            feature_version=definition.feature_version,
            instrument_id=instrument_id,
            timeframe=timeframe,
            timestamp=p.timestamp,
            value=p.plus_di,
        )
        for p in points
    )


def compute_minus_directional_index(
    definition: DirectionalMovementDefinition, bars: tuple[Bar, ...]
) -> tuple[FeatureValue, ...]:
    """-DI(lookback) - see `compute_plus_directional_index` / module
    docstring."""
    if not bars:
        return ()
    instrument_id, timeframe, points = _compute_directional_series(definition.lookback, bars)
    return tuple(
        FeatureValue(
            feature_name=definition.minus_di_feature_name,
            feature_version=definition.feature_version,
            instrument_id=instrument_id,
            timeframe=timeframe,
            timestamp=p.timestamp,
            value=p.minus_di,
        )
        for p in points
    )


def compute_average_directional_index(
    definition: DirectionalMovementDefinition, bars: tuple[Bar, ...]
) -> tuple[FeatureValue, ...]:
    """ADX(lookback) - Wilder-smoothed average of DX, only emitted once
    the ADX-of-DX seed itself is reached (`2*lookback + 1` bars minimum -
    see module docstring)."""
    if not bars:
        return ()
    instrument_id, timeframe, points = _compute_directional_series(definition.lookback, bars)
    return tuple(
        FeatureValue(
            feature_name=definition.adx_feature_name,
            feature_version=definition.feature_version,
            instrument_id=instrument_id,
            timeframe=timeframe,
            timestamp=p.timestamp,
            value=p.adx,
        )
        for p in points
        if p.adx is not None
    )
