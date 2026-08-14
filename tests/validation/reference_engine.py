# tests/validation/reference_engine.py
#
# Checkpoint 30 Part 3: an INDEPENDENT reference implementation of the
# EMA-crossover backtest, deliberately written with a different code
# path and implementation style than
# `src/intraday/research/backtesting/engine.py` - a fresh top-to-bottom
# re-derivation from the DOCUMENTED specification (Checkpoint 26's EMA
# Crossover rule, Checkpoint 27's execution-timing rule, Checkpoint 29's
# cost schedule), never by importing or copy-pasting the engine's own
# code. This is NOT a second production engine - it lives under
# `tests/`, is used only by the validation tests in this directory, and
# is never imported by any `src/intraday` module (verified by
# `test_reference_engine_isolation.py`).
#
# Deliberate style differences from the production engine (to keep the
# two implementations genuinely independent, not a relabeled copy):
#   - EMA computed via a plain running-recurrence loop over plain
#     `list[Decimal]` closes, not `signal_intelligence.feature_engine`.
#   - Bars represented as plain `dict` records, not `domain.market_data.
#     contracts.Bar`.
#   - A single flat function (`run_reference_backtest`) rather than the
#     production engine's closures/nested-function structure.
#   - Cost formulas re-typed from the specification in
#     `docs/architecture/BACKTESTING_ARCHITECTURE.md`'s own documented
#     table, not imported from `cost_model.py`.
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal


@dataclass(frozen=True)
class ReferenceBar:
    timestamp: str  # ISO string - deliberately not a datetime, to avoid sharing domain types
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


@dataclass(frozen=True)
class ReferenceSignal:
    timestamp: str
    direction: str  # "BULLISH" | "BEARISH" | "NEUTRAL" | "NONE" (warm-up)
    fast_ema: Decimal | None
    slow_ema: Decimal | None


@dataclass
class ReferenceTrade:
    trade_id: int
    direction: str
    entry_timestamp: str
    entry_price: Decimal
    exit_timestamp: str
    exit_price: Decimal
    quantity: Decimal
    gross_pnl: Decimal
    brokerage: Decimal
    stt: Decimal
    exchange_charges: Decimal
    sebi_charges: Decimal
    gst: Decimal
    stamp_duty: Decimal
    total_costs: Decimal
    net_pnl: Decimal
    reason: str


@dataclass
class ReferenceEquityPoint:
    timestamp: str
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    total_equity: Decimal
    peak_equity: Decimal
    drawdown: Decimal


@dataclass
class ReferenceResult:
    signals: list[ReferenceSignal] = field(default_factory=list)
    trades: list[ReferenceTrade] = field(default_factory=list)
    equity_curve: list[ReferenceEquityPoint] = field(default_factory=list)


def _round2(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _compute_ema(closes: list[Decimal], lookback: int) -> list[Decimal | None]:
    """A plain, independent EMA recurrence: seed with a simple average
    of the first `lookback` closes, then apply the standard
    alpha = 2/(lookback+1) recurrence - the conventional EMA definition,
    derived from first principles here, not from `signal_intelligence.
    feature_engine.ema`."""
    result: list[Decimal | None] = [None] * len(closes)
    if len(closes) < lookback:
        return result
    alpha = Decimal(2) / Decimal(lookback + 1)
    seed = sum(closes[:lookback], Decimal(0)) / lookback
    result[lookback - 1] = seed
    prev = seed
    for i in range(lookback, len(closes)):
        current = (closes[i] - prev) * alpha + prev
        result[i] = current
        prev = current
    return result


def compute_reference_signals(
    bars: list[ReferenceBar], fast_lookback: int, slow_lookback: int
) -> list[ReferenceSignal]:
    """Independent re-derivation of the EMA Crossover rule (Checkpoint
    26's documented specification): BULLISH iff fast > slow AND
    price > fast; BEARISH iff fast < slow AND price < fast; else
    NEUTRAL. "NONE" during warm-up (either EMA not yet available)."""
    closes = [b.close for b in bars]
    fast_series = _compute_ema(closes, fast_lookback)
    slow_series = _compute_ema(closes, slow_lookback)

    signals: list[ReferenceSignal] = []
    for i, bar in enumerate(bars):
        fast = fast_series[i]
        slow = slow_series[i]
        if fast is None or slow is None:
            signals.append(ReferenceSignal(bar.timestamp, "NONE", fast, slow))
            continue
        price = bar.close
        if fast > slow and price > fast:
            direction = "BULLISH"
        elif fast < slow and price < fast:
            direction = "BEARISH"
        else:
            direction = "NEUTRAL"
        signals.append(ReferenceSignal(bar.timestamp, direction, fast, slow))
    return signals


def _cost_leg(*, is_buy: bool, notional: Decimal) -> dict[str, Decimal]:
    """Independently re-typed from the documented Checkpoint 29 schedule
    (docs/architecture/BACKTESTING_ARCHITECTURE.md's own table) - NOT
    imported from `research.backtesting.cost_model`."""
    brokerage_pct = Decimal("0.03") / 100
    cap = Decimal("20")
    brokerage = min(notional * brokerage_pct, cap)
    exchange = notional * (Decimal("0.00307") / 100)
    sebi = notional * (Decimal("0.0001") / 100)
    gst = (brokerage + exchange + sebi) * (Decimal("18") / 100)
    stt = notional * (Decimal("0.025") / 100) if not is_buy else Decimal("0")
    stamp = notional * (Decimal("0.003") / 100) if is_buy else Decimal("0")
    return {
        "brokerage": _round2(brokerage),
        "exchange": _round2(exchange),
        "sebi": _round2(sebi),
        "gst": _round2(gst),
        "stt": _round2(stt),
        "stamp": _round2(stamp),
    }


def run_reference_backtest(
    bars: list[ReferenceBar],
    fast_lookback: int,
    slow_lookback: int,
    initial_capital: Decimal,
    quantity: Decimal,
) -> ReferenceResult:
    """Independent whole-backtest reference: fixed-quantity sizing,
    next-bar-open execution (Checkpoint 27's documented rule), verified
    Indian cost schedule (re-typed, see `_cost_leg`), no slippage (a
    controlled, zero-slippage comparison isolates execution/cost logic
    from the separate slippage model)."""
    signals = compute_reference_signals(bars, fast_lookback, slow_lookback)
    trades: list[ReferenceTrade] = []
    trade_counter = 0

    open_direction: str | None = None
    open_entry_index: int | None = None
    open_entry_price: Decimal | None = None

    n = len(bars)
    for i, signal in enumerate(signals):
        is_last = i == n - 1
        if open_direction is None:
            if signal.direction in ("BULLISH", "BEARISH") and not is_last:
                open_direction = signal.direction
                open_entry_index = i + 1
                open_entry_price = bars[i + 1].open
        else:
            should_exit = (
                signal.direction not in ("NONE",)
                and signal.direction != open_direction
                and not is_last
            )
            if should_exit or is_last:
                exit_index = i + 1 if should_exit else i
                exit_price = bars[i + 1].open if should_exit else bars[i].close
                reason = "signal_reversal" if should_exit else "end_of_data"

                entry_notional = open_entry_price * quantity
                exit_notional = exit_price * quantity
                entry_is_buy = open_direction == "BULLISH"
                exit_is_buy = not entry_is_buy
                entry_costs = _cost_leg(is_buy=entry_is_buy, notional=entry_notional)
                exit_costs = _cost_leg(is_buy=exit_is_buy, notional=exit_notional)

                if open_direction == "BULLISH":
                    gross_pnl = (exit_price - open_entry_price) * quantity
                else:
                    gross_pnl = (open_entry_price - exit_price) * quantity

                brokerage = entry_costs["brokerage"] + exit_costs["brokerage"]
                stt = entry_costs["stt"] + exit_costs["stt"]
                exchange = entry_costs["exchange"] + exit_costs["exchange"]
                sebi = entry_costs["sebi"] + exit_costs["sebi"]
                gst = entry_costs["gst"] + exit_costs["gst"]
                stamp = entry_costs["stamp"] + exit_costs["stamp"]
                total_costs = brokerage + stt + exchange + sebi + gst + stamp
                net_pnl = gross_pnl - total_costs

                trade_counter += 1
                trades.append(
                    ReferenceTrade(
                        trade_id=trade_counter,
                        direction=open_direction,
                        entry_timestamp=bars[open_entry_index].timestamp,
                        entry_price=open_entry_price,
                        exit_timestamp=bars[exit_index].timestamp,
                        exit_price=exit_price,
                        quantity=quantity,
                        gross_pnl=gross_pnl,
                        brokerage=brokerage,
                        stt=stt,
                        exchange_charges=exchange,
                        sebi_charges=sebi,
                        gst=gst,
                        stamp_duty=stamp,
                        total_costs=total_costs,
                        net_pnl=net_pnl,
                        reason=reason,
                    )
                )
                open_direction = None
                open_entry_index = None
                open_entry_price = None

    # Mark-to-market equity curve, one point per bar - independent
    # derivation of the same "value open positions at bar close" rule.
    equity_curve: list[ReferenceEquityPoint] = []
    realized = Decimal(0)
    peak = initial_capital
    trade_pointer = 0
    trade_intervals = []
    for t in trades:
        entry_idx = next(idx for idx, b in enumerate(bars) if b.timestamp == t.entry_timestamp)
        exit_idx = next(idx for idx, b in enumerate(bars) if b.timestamp == t.exit_timestamp)
        trade_intervals.append((entry_idx, exit_idx, t))

    for i, bar in enumerate(bars):
        while trade_pointer < len(trade_intervals) and trade_intervals[trade_pointer][1] <= i:
            realized += trade_intervals[trade_pointer][2].net_pnl
            trade_pointer += 1
        unrealized = Decimal(0)
        if trade_pointer < len(trade_intervals):
            entry_idx, exit_idx, t = trade_intervals[trade_pointer]
            if entry_idx <= i < exit_idx:
                if t.direction == "BULLISH":
                    unrealized = (bar.close - t.entry_price) * t.quantity
                else:
                    unrealized = (t.entry_price - bar.close) * t.quantity
        total_equity = initial_capital + realized + unrealized
        peak = max(peak, total_equity)
        drawdown = peak - total_equity
        equity_curve.append(
            ReferenceEquityPoint(bar.timestamp, realized, unrealized, total_equity, peak, drawdown)
        )

    return ReferenceResult(signals=signals, trades=trades, equity_curve=equity_curve)


@dataclass
class ReferencePortfolioResult:
    trades: list[ReferenceTrade] = field(default_factory=list)
    rejected_entries: int = 0
    final_cash: Decimal = Decimal(0)


def run_reference_portfolio(
    bars_by_instrument: dict[str, list[ReferenceBar]],
    fast_lookback: int,
    slow_lookback: int,
    initial_capital: Decimal,
    quantity: Decimal,
    max_concurrent_positions: int,
) -> ReferencePortfolioResult:
    """Independent multi-instrument reference - a SEPARATE, small loop
    (not a generalization of `run_reference_backtest`) proving shared-
    cash and concurrent-position-cap accounting from first principles,
    for Checkpoint 30 Part 10's portfolio validation requirement."""
    instrument_ids = list(bars_by_instrument.keys())
    signals_by_instrument = {
        iid: compute_reference_signals(bars_by_instrument[iid], fast_lookback, slow_lookback)
        for iid in instrument_ids
    }
    n = len(next(iter(bars_by_instrument.values())))

    cash = initial_capital
    open_positions: dict[
        str, tuple[str, int, Decimal]
    ] = {}  # iid -> (direction, entry_index, entry_price)
    trades: list[ReferenceTrade] = []
    trade_counter = 0
    rejected = 0

    for i in range(n):
        is_last = i == n - 1
        for iid in instrument_ids:
            bars = bars_by_instrument[iid]
            signal = signals_by_instrument[iid][i]
            if iid not in open_positions:
                if signal.direction in ("BULLISH", "BEARISH") and not is_last:
                    if len(open_positions) >= max_concurrent_positions:
                        rejected += 1
                        continue
                    entry_price = bars[i + 1].open
                    notional = entry_price * quantity
                    if notional > cash:
                        rejected += 1
                        continue
                    cash -= notional
                    open_positions[iid] = (signal.direction, i + 1, entry_price)
            else:
                direction, entry_index, entry_price = open_positions[iid]
                should_exit = (
                    signal.direction != "NONE" and signal.direction != direction and not is_last
                )
                if should_exit or is_last:
                    exit_index = i + 1 if should_exit else i
                    exit_price = bars[i + 1].open if should_exit else bars[i].close
                    reason = "signal_reversal" if should_exit else "end_of_data"
                    entry_notional = entry_price * quantity
                    exit_notional = exit_price * quantity
                    entry_is_buy = direction == "BULLISH"
                    exit_is_buy = not entry_is_buy
                    entry_costs = _cost_leg(is_buy=entry_is_buy, notional=entry_notional)
                    exit_costs = _cost_leg(is_buy=exit_is_buy, notional=exit_notional)
                    if direction == "BULLISH":
                        gross_pnl = (exit_price - entry_price) * quantity
                    else:
                        gross_pnl = (entry_price - exit_price) * quantity
                    total_costs = sum(
                        (entry_costs[k] + exit_costs[k] for k in entry_costs), Decimal(0)
                    )
                    net_pnl = gross_pnl - total_costs
                    trade_counter += 1
                    trades.append(
                        ReferenceTrade(
                            trade_id=trade_counter,
                            direction=direction,
                            entry_timestamp=bars[entry_index].timestamp,
                            entry_price=entry_price,
                            exit_timestamp=bars[exit_index].timestamp,
                            exit_price=exit_price,
                            quantity=quantity,
                            gross_pnl=gross_pnl,
                            brokerage=entry_costs["brokerage"] + exit_costs["brokerage"],
                            stt=entry_costs["stt"] + exit_costs["stt"],
                            exchange_charges=entry_costs["exchange"] + exit_costs["exchange"],
                            sebi_charges=entry_costs["sebi"] + exit_costs["sebi"],
                            gst=entry_costs["gst"] + exit_costs["gst"],
                            stamp_duty=entry_costs["stamp"] + exit_costs["stamp"],
                            total_costs=total_costs,
                            net_pnl=net_pnl,
                            reason=reason,
                        )
                    )
                    cash += entry_notional + net_pnl
                    del open_positions[iid]

    return ReferencePortfolioResult(trades=trades, rejected_entries=rejected, final_cash=cash)
