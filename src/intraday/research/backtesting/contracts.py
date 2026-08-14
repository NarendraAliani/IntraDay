# File: src/intraday/research/backtesting/contracts.py
#
# Checkpoint 27: canonical backtesting contracts. Provider-neutral - no
# Dhan, no Django ORM, no broker knowledge anywhere in this module.
# `TradeDirection` is DELIBERATELY `trading_engine.strategy_execution.
# contracts.StrategyDirection`, reused rather than duplicated - this is
# the one legal cross-bounded-context import for `research.backtesting`
# (`.importlinter` contract 4's `ignore_imports` exception, Checkpoint 2
# §4 / Checkpoint 3 §16), so no third BULLISH/BEARISH/NEUTRAL-shaped enum
# is introduced.
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe, ensure_utc
from intraday.research.backtesting import StrategyDirection
from intraday.research.backtesting.cost_model import CostBreakdown
from intraday.research.backtesting.errors import InvalidBacktestConfigurationError

TradeDirection = StrategyDirection


class PositionSizingMode(str, Enum):
    """Two deliberately simple, explicit sizing models - a POC scope
    (Part 3/15), not a general portfolio-sizing framework."""

    FIXED_QUANTITY = "FIXED_QUANTITY"
    PERCENT_OF_EQUITY = "PERCENT_OF_EQUITY"


class DataQualityLabel(str, Enum):
    """Reuses the SAMPLE_BAR/TRADING_GRADE_BAR vocabulary established in
    `docs/architecture/MARKET_DATA_QUALITY_ASSESSMENT.md` and
    `field_registry.FieldAvailability` rather than inventing a parallel
    one. Every backtest today runs on fixture/historical data - never
    live SAMPLE_BAR - see `application.services.backtesting`'s own
    safety-gate docstring."""

    FIXTURE_OR_HISTORICAL = "FIXTURE_OR_HISTORICAL"
    SAMPLE_BAR = "SAMPLE_BAR"


@dataclass(frozen=True, slots=True)
class BacktestConfiguration:
    """Everything the engine needs, and nothing it does not (Part 3).
    Brokerage/slippage are flat percentage MODEL ASSUMPTIONS - not a
    verified Indian brokerage/STT/GST formula (none was available to
    verify against an authoritative source this checkpoint) - documented
    in `docs/architecture/BACKTESTING_ARCHITECTURE.md`'s own "Cost Model
    Assumptions" section and surfaced verbatim in every `BacktestResult`.
    """

    instrument_id: InstrumentId
    timeframe: Timeframe
    start: datetime
    end: datetime
    strategy_id: str
    specification_version: str
    code_version: str
    configuration_version: str
    initial_capital: Decimal
    position_sizing_mode: PositionSizingMode
    position_size_value: Decimal
    """FIXED_QUANTITY: an integer share count (as Decimal).
    PERCENT_OF_EQUITY: a fraction of current equity, e.g. Decimal("0.1")
    for 10% - MODEL ASSUMPTION: whole-share rounding down, no margin/
    leverage modeled."""
    max_concurrent_positions: int = 1
    """POC scope: only 1 is currently supported by the engine (Part 3's
    own instruction to keep only genuinely-required fields; the field
    exists for forward-compatibility and is validated against, not
    silently ignored)."""
    brokerage_percent: Decimal = Decimal("0")
    slippage_percent: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        ensure_utc(self.start, field_name="BacktestConfiguration.start")
        ensure_utc(self.end, field_name="BacktestConfiguration.end")
        if self.end <= self.start:
            raise InvalidBacktestConfigurationError("end must be after start")
        if self.initial_capital <= 0:
            raise InvalidBacktestConfigurationError("initial_capital must be positive")
        if self.position_size_value <= 0:
            raise InvalidBacktestConfigurationError("position_size_value must be positive")
        if self.max_concurrent_positions != 1:
            raise InvalidBacktestConfigurationError(
                "max_concurrent_positions: only 1 is supported by this POC engine"
            )
        if self.brokerage_percent < 0 or self.slippage_percent < 0:
            raise InvalidBacktestConfigurationError("costs must not be negative")
        if not self.strategy_id.strip():
            raise InvalidBacktestConfigurationError("strategy_id must be non-empty")


@dataclass(frozen=True, slots=True)
class SimulatedTrade:
    """One immutable simulated round-trip trade. Never mutated after
    creation - a closed trade is a historical fact of the simulation."""

    trade_id: str
    strategy_id: str
    specification_version: str
    code_version: str
    configuration_version: str
    instrument_id: InstrumentId
    timeframe: Timeframe
    direction: TradeDirection
    entry_timestamp: datetime
    entry_price: Decimal
    exit_timestamp: datetime
    exit_price: Decimal
    quantity: Decimal
    gross_pnl: Decimal
    costs: Decimal
    net_pnl: Decimal
    reason: str
    """Why the trade closed - e.g. "signal_reversal", "end_of_data"."""
    mfe: Decimal | None = None
    """Maximum Favorable Excursion over the holding period, in price
    terms from entry (Part 9) - None only if the holding period was a
    single bar with no intermediate bars to measure."""
    mae: Decimal | None = None
    """Maximum Adverse Excursion - see `mfe`."""
    cost_breakdown: CostBreakdown = field(default_factory=CostBreakdown)
    """Checkpoint 29 Part 5: the itemized entry+exit cost breakdown
    whose `.total` equals `costs` above - never only gross/net."""


@dataclass(frozen=True, slots=True)
class EquityPoint:
    """Realized-only equity, sampled at each trade-close event (Checkpoint
    27's original curve) - kept unchanged and still authoritative for
    "what did the account actually realize and when". Superseded for
    DRAWDOWN PURPOSES by `MarkToMarketPoint` below (Checkpoint 28 Part
    5), but never removed (Part 4's own explicit instruction)."""

    timestamp: datetime
    balance: Decimal
    cumulative_pnl: Decimal
    drawdown: Decimal
    drawdown_percent: Decimal


@dataclass(frozen=True, slots=True)
class MarkToMarketPoint:
    """Checkpoint 28 Part 4: one point per bar in the series (not just
    trade-close events), separating REALIZED from UNREALIZED P&L.

    Mark-price convention (Part 6, explicit): unrealized P&L on an open
    position is valued at that bar's own CLOSE price - the same
    close-time convention `domain.market_data.contracts.Bar` already
    documents for the bar itself. No intrabar high/low mark is used
    (would silently pick a favorable/adverse price, not the bar's
    settled price). Unrealized valuation excludes exit costs (those are
    only ever realized when a trade actually closes) - a documented
    simplification, not a hidden one.
    """

    timestamp: datetime
    realized_pnl: Decimal
    """Cumulative P&L from all trades closed up to and including this bar."""
    unrealized_pnl: Decimal
    """0 when no position is open at this bar (Part 6)."""
    total_equity: Decimal
    """initial_capital + realized_pnl + unrealized_pnl - the identity
    Part 6 requires holds at every point (proven by
    `test_equity_identity_holds_at_every_bar`)."""
    peak_equity: Decimal
    drawdown: Decimal
    drawdown_percent: Decimal


@dataclass(frozen=True, slots=True)
class BacktestMetrics:
    """Only mathematically justified metrics (Part 8). Sharpe/Sortino
    are computed on a PER-TRADE return series (net_pnl / capital-at-
    entry for each trade) - NOT an annualized, daily-return industry-
    standard Sharpe ratio, since trade timestamps are irregular and no
    daily-return series exists. Labeled explicitly as
    "trade-level, non-annualized" everywhere they are surfaced (API,
    UI, docs) to avoid a misleading number. `None` when fewer than 2
    trades exist (a single data point has no variance)."""

    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_percent: Decimal
    gross_profit: Decimal
    gross_loss: Decimal
    net_pnl: Decimal
    profit_factor: Decimal | None
    """gross_profit / abs(gross_loss) - None if gross_loss is zero
    (undefined, never reported as infinity or 0)."""
    max_drawdown: Decimal
    """Checkpoint 28 Part 5: computed from the MARK-TO-MARKET equity
    curve, not merely from trade-close points - captures an intrabar
    adverse excursion even on a position that ultimately closes at
    break-even or a profit."""
    max_drawdown_percent: Decimal
    max_drawdown_duration_bars: int
    """Number of consecutive bars equity spent below its prior peak, at
    the longest such episode - 0 if equity never fell below its running
    peak."""
    average_trade: Decimal
    average_winner: Decimal | None
    average_loser: Decimal | None
    sharpe_ratio_trade_level: Decimal | None
    sortino_ratio_trade_level: Decimal | None
    final_capital: Decimal
    return_percent: Decimal


class BacktestTrustLevel(str, Enum):
    """Checkpoint 28 Part 3: how much weight a backtest result should be
    given - deliberately NOT inferred from "all tests pass". See
    `docs/architecture/BACKTESTING_ARCHITECTURE.md`'s "Backtest Trust
    Level" section for the full, measurable promotion criteria per
    level. Every result produced by this engine today is `POC` -
    promotion is a documented, future, evidence-based decision, never
    automatic."""

    POC = "POC"
    RESEARCH_READY = "RESEARCH_READY"
    VALIDATION_READY = "VALIDATION_READY"
    PRODUCTION_RESEARCH_READY = "PRODUCTION_RESEARCH_READY"


@dataclass(frozen=True, slots=True)
class ResultValidationSummary:
    """Checkpoint 28 Part 15: research-quality diagnostics attached to
    every result - essential for explaining why two seemingly similar
    backtests differ. Every field here is COUNTED from the actual
    simulated path, never estimated."""

    bar_count: int
    signal_count: int
    """Bars where the strategy produced a non-NEUTRAL/non-None signal."""
    trade_count: int
    warmup_bars: int
    """Bars where a required feature was not yet available (indicator
    warm-up) - the strategy could not evaluate at all."""
    skipped_signals: int
    """Non-NEUTRAL signals that did not result in a new entry because a
    position was already open in the same direction."""
    rejected_trades: int
    """Entry signals that computed a zero quantity (insufficient
    capital for the configured sizing) and were therefore never opened."""
    data_gaps_note: str
    """Gap detection requires an explicit session calendar cross-check,
    not performed by this engine - honestly stated as not computed,
    never fabricated as 0 with false confidence."""


@dataclass(frozen=True, slots=True)
class CostModelIdentity:
    """Checkpoint 29 Part 9: which cost schedule produced a result -
    `name`/`version`/`effective_from` mirror the same fields every
    `CostModel` implementation carries (`cost_model.CostModel`), copied
    into the result so it survives serialization independently of the
    live `CostModel` object that computed it."""

    name: str
    version: str
    effective_from: date
    is_verified: bool
    """True for a verified statutory/exchange schedule
    (`IndianCashEquityIntradayCostModel`), False for a MODEL ASSUMPTION
    (`FlatPercentageCostModel`) - surfaced directly so the frontend never
    has to infer this from the name string."""


@dataclass(frozen=True, slots=True)
class DataQualityDisclosure:
    """Part 24: mandatory, explicit disclosure attached to every
    `BacktestResult` - never left implicit."""

    data_source: str
    data_quality: DataQualityLabel
    bar_count: int
    missing_bar_note: str
    transaction_cost_assumption: str
    slippage_assumption: str
    survivorship_bias_note: str


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """Canonical, immutable backtest result. `backtest_id` is derived
    deterministically from the configuration + data identity + cost
    model identity (Part 10/11/Checkpoint 29 Part 9/19 reproducibility),
    never a random UUID - re-running the same configuration against the
    same data AND the same cost model always yields the same
    `backtest_id`; changing only the cost model changes it."""

    backtest_id: str
    configuration: BacktestConfiguration
    trades: tuple[SimulatedTrade, ...]
    equity_curve: tuple[EquityPoint, ...]
    mark_to_market_curve: tuple[MarkToMarketPoint, ...]
    metrics: BacktestMetrics
    data_quality: DataQualityDisclosure
    validation: ResultValidationSummary
    cost_model_identity: CostModelIdentity
    generated_at: datetime
    trust_level: BacktestTrustLevel = BacktestTrustLevel.POC

    def __post_init__(self) -> None:
        ensure_utc(self.generated_at, field_name="BacktestResult.generated_at")
