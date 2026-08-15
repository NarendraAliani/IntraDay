# File: src/intraday/domain/market_data/promotion.py
#
# Checkpoint 40 Part 6: the explicit TRADING_GRADE_BAR promotion gate.
# Pure, technology-neutral (mirrors `quality.py`/`aggregation.py`'s own
# domain-layer discipline - no I/O, no provider knowledge). This is the
# ONE place a bar's `BarQualityGrade` (Checkpoint 31) is DECIDED, never
# inferred ad hoc by a caller - every one of the six conditions
# `DHAN_MARKET_DATA_CAPABILITY_RESEARCH.md`/`TRADING_GRADE_BAR_VALIDATION.md`
# already named must be genuinely satisfied, or the bar stays
# `SAMPLE_BAR`. Never silently promoted (Checkpoint 31's own governing
# principle, unchanged).
from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime

from intraday.domain.market_data.aggregation import AggregatedBar, BarQualityGrade, BarStatus
from intraday.domain.market_data.quality import (
    DuplicateBarTimestampError,
    OutOfOrderBarError,
    ensure_chronological,
)
from intraday.domain.session.contracts import SessionStatus, TradingSession
from intraday.domain.shared_kernel.contracts import ensure_utc


class PromotionCondition(enum.Enum):
    """The six conditions this gate checks, named so a
    `PromotionResult.failed_conditions` is always machine-readable, not
    a free-text explanation only."""

    BAR_IS_CLOSED = "BAR_IS_CLOSED"
    SESSION_IS_OPEN = "SESSION_IS_OPEN"
    NO_DUPLICATE_OR_OUT_OF_ORDER = "NO_DUPLICATE_OR_OUT_OF_ORDER"
    NO_GAP_BEFORE_THIS_BAR = "NO_GAP_BEFORE_THIS_BAR"
    CONNECTION_HEALTHY = "CONNECTION_HEALTHY"
    SUFFICIENT_OBSERVATIONS = "SUFFICIENT_OBSERVATIONS"


@dataclass(frozen=True, slots=True)
class PromotionResult:
    grade: BarQualityGrade
    failed_conditions: tuple[PromotionCondition, ...]
    evaluated_at: datetime

    def __post_init__(self) -> None:
        ensure_utc(self.evaluated_at, field_name="PromotionResult.evaluated_at")
        if self.grade is BarQualityGrade.TRADING_GRADE_BAR and self.failed_conditions:
            raise ValueError(
                "PromotionResult cannot be TRADING_GRADE_BAR with failed_conditions present"
            )


# A bar-quality gate genuinely requires more than one bar's worth of
# observations to prove "no gap before this bar" - the minimum this
# checkpoint enforces is that at least this many quotes fed the bar
# being evaluated (Checkpoint 24A's own `observation_count` field).
MINIMUM_OBSERVATIONS_FOR_TRADING_GRADE = 2


def evaluate_bar_promotion(
    *,
    bar: AggregatedBar,
    session: TradingSession,
    preceding_bars: tuple[AggregatedBar, ...],
    connection_is_healthy: bool,
    now: datetime,
) -> PromotionResult:
    """Checkpoint 40's real promotion gate - never called by the
    strategy path directly on a `SAMPLE_BAR`-classified series (see
    `application.services.active_loop`). `preceding_bars` is every
    CLOSED bar for the same instrument/timeframe already accepted this
    session, chronologically before `bar` - used to detect duplicates/
    out-of-order/gaps without this function performing any I/O itself
    (the caller is responsible for supplying the real prior history)."""
    ensure_utc(now, field_name="now")
    failed: list[PromotionCondition] = []

    if bar.status is not BarStatus.CLOSED:
        failed.append(PromotionCondition.BAR_IS_CLOSED)

    if session.status is not SessionStatus.OPEN:
        failed.append(PromotionCondition.SESSION_IS_OPEN)

    try:
        ensure_chronological(
            (*[b.to_bar() for b in preceding_bars if b.status is BarStatus.CLOSED], bar.to_bar())
        )
    except (DuplicateBarTimestampError, OutOfOrderBarError):
        failed.append(PromotionCondition.NO_DUPLICATE_OR_OUT_OF_ORDER)
    except ValueError:
        # to_bar() itself raises IncompleteBarError for a FORMING bar -
        # already captured by BAR_IS_CLOSED above; do not double-report.
        pass

    if preceding_bars:
        last_closed = max(
            (b for b in preceding_bars if b.status is BarStatus.CLOSED),
            key=lambda b: b.interval_end,
            default=None,
        )
        if last_closed is not None and bar.interval_start != last_closed.interval_end:
            failed.append(PromotionCondition.NO_GAP_BEFORE_THIS_BAR)

    if not connection_is_healthy:
        failed.append(PromotionCondition.CONNECTION_HEALTHY)

    if bar.observation_count < MINIMUM_OBSERVATIONS_FOR_TRADING_GRADE:
        failed.append(PromotionCondition.SUFFICIENT_OBSERVATIONS)

    grade = BarQualityGrade.SAMPLE_BAR if failed else BarQualityGrade.TRADING_GRADE_BAR
    return PromotionResult(grade=grade, failed_conditions=tuple(failed), evaluated_at=now)
