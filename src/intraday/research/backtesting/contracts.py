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

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum

from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe, ensure_utc
from intraday.research.backtesting import StrategyDirection
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


@dataclass(frozen=True, slots=True)
class EquityPoint:
    timestamp: datetime
    balance: Decimal
    cumulative_pnl: Decimal
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
    max_drawdown_percent: Decimal
    average_trade: Decimal
    average_winner: Decimal | None
    average_loser: Decimal | None
    sharpe_ratio_trade_level: Decimal | None
    sortino_ratio_trade_level: Decimal | None
    final_capital: Decimal
    return_percent: Decimal


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
    deterministically from the configuration + data identity (Part 10/11
    reproducibility), never a random UUID - re-running the same
    configuration against the same data always yields the same
    `backtest_id`."""

    backtest_id: str
    configuration: BacktestConfiguration
    trades: tuple[SimulatedTrade, ...]
    equity_curve: tuple[EquityPoint, ...]
    metrics: BacktestMetrics
    data_quality: DataQualityDisclosure
    generated_at: datetime

    def __post_init__(self) -> None:
        ensure_utc(self.generated_at, field_name="BacktestResult.generated_at")
