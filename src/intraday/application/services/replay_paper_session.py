# File: src/intraday/application/services/replay_paper_session.py
#
# Checkpoint 64.68 (MILESTONE 2 - PAPER TRADING MVP, OFFLINE/REPLAY
# FIRST): the session/lifecycle layer that WIRES the already-existing
# paper-trading pieces into an operable, reproducible, persistable
# session. It adds NO strategy logic, NO fill logic, NO risk logic and
# NO P&L logic of its own.
#
# WHAT ALREADY EXISTED AND IS REUSED VERBATIM (§1's "reuse first"):
#   - `StrategyExecutionCoordinator` (Checkpoint 26)  -> the ONE strategy
#     evaluator, shared with Backtest.
#   - `PaperSignalExecutionService` (Checkpoint 36)   -> the ONE
#     StrategySignal -> TradePlan -> OrderIntent bridge.
#   - `PaperTradingService` (Checkpoint 34)           -> the ONE
#     non-bypassable kill-switch + `evaluate_order_risk()` gate.
#   - `PaperBroker` (Checkpoint 34/64.37/64.38/64.42) -> the ONE fill /
#     Position / Trade / Fill / Funds / equity engine.
#   - `BarSource` (Checkpoint 52)                     -> the ONE
#     market-data boundary; this checkpoint drives it with the EXISTING
#     `DeterministicReplayBarSource`, never a new market-data engine.
#   - `domain.paper_session.contracts`                -> the state machine.
#
# NOTHING here is named *V2, and no PaperOrderEngine or
# PaperMarketDataEngine exists. No not-yet-productized research strategy
# is activated by this module either: it only ever evaluates whichever
# strategy the injected `StrategyRegistry` already contains, and the
# default registry contains only the three long-established safe
# strategies.
#
# THE ONE ARCHITECTURAL DECISION THIS MODULE MAKES - "PROJECTION, NOT A
# LIVE MUTABLE ENGINE":
# `project()` replays steps `0..cursor` from scratch into a FRESHLY
# CONSTRUCTED `PaperBroker` every time state is requested. Consequences,
# all deliberate:
#   * Reproducibility (§17) is structural, not aspirational - the same
#     (spec, cursor) can only ever produce one answer.
#   * Restart-safety (§18) is structural - the persisted record IS the
#     whole session; nothing lives only in process memory.
#   * Cost is O(steps^2) in broker work. Acceptable and disclosed: a
#     single NSE trading day at 5m is 75 bars. This is a REPLAY MVP, not
#     a hot live path.
#
# EXECUTION TIMING (§20's "document any unavoidable difference"): at
# step `i` the strategy is evaluated on bars[0..i] ONLY (never a later
# bar - no look-ahead), and the resulting MARKET order fills against the
# price observed at bars[i+1].open. That is the SAME next-bar-open fill
# rule `research/backtesting/engine.py` already uses, reached here via
# `PaperBroker.record_price()` rather than by reimplementing it.
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

from intraday.application.repositories.paper_session import (
    PaperSessionRecord,
    PaperSessionRepository,
)
from intraday.application.services.paper_signal_execution import PaperSignalExecutionService
from intraday.application.services.paper_trading import PaperTradingService
from intraday.domain.broker.contracts import BrokerOrderStatusReport, Funds
from intraday.domain.market_data.contracts import Bar
from intraday.domain.order.contracts import OrderIntent
from intraday.domain.paper_session.contracts import (
    InvalidPaperSessionTransitionError,
    PaperAccountSnapshot,
    PaperSessionCommand,
    PaperSessionStatus,
    apply_command,
    is_idempotent_no_op,
)
from intraday.domain.position.contracts import Position, PositionStatus
from intraday.domain.risk.contracts import RiskDecisionOutcome, RiskLimits, TradingHaltStatus
from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe
from intraday.domain.trade.contracts import Trade
from intraday.trading_engine.strategy_execution.contracts import StrategyConfigurationValues
from intraday.trading_engine.strategy_execution.coordinator import StrategyExecutionCoordinator

ZERO = Decimal("0")


class ReplayPaperBroker(Protocol):
    """The exact surface this service uses from the EXISTING
    `infrastructure.brokers.paper.PaperBroker`. Declared structurally so
    `application` never imports `infrastructure` (contract 6) - the same
    injection discipline `PaperTradingService` itself already uses for
    `BrokerGateway`. This is NOT a new broker: it is a narrowing VIEW of
    the one that already exists."""

    def submit_order(self, order: OrderIntent) -> BrokerOrderStatusReport: ...

    def get_orders(self) -> tuple[BrokerOrderStatusReport, ...]: ...

    def get_positions(self) -> tuple[Position, ...]: ...

    def get_trades(self) -> tuple[Trade, ...]: ...

    def get_funds(self) -> Funds: ...

    def get_equity(self) -> Decimal: ...

    def get_total_unrealized_pnl(self) -> Decimal: ...

    def record_price(
        self, instrument_id: InstrumentId, price: Decimal, timestamp: datetime
    ) -> None: ...

    def force_expire_end_of_session(self) -> None: ...


BrokerFactory = Callable[[Decimal, Callable[[], datetime]], ReplayPaperBroker]
"""`(initial_capital, clock) -> a fresh PaperBroker`. Injected by the
composition root (`infrastructure/api/replay_paper_session_runtime.py`),
which builds the SAME `PaperBroker` with the SAME verified NSE cost
model `paper_trading_runtime.py` already uses.

The `clock` this service supplies is the REPLAY CLOCK, not wall-clock
time: it returns the timestamp of the bar currently being replayed. That
is both more truthful (a replayed trade is stamped with the market
instant it would have happened at, never "whenever the operator happened
to click") and what makes the whole session reproducible - a wall clock
would make every re-projection of the same cursor produce different
`Trade.opened_at`/`Position.opened_at` values (§17)."""

BarLoader = Callable[[PaperSessionRecord], tuple[Bar, ...]]
"""`(record) -> the deterministic replay bar series`. Injected so this
service never chooses or generates market data itself (§5: no
`PaperMarketDataEngine`)."""

CoordinatorFactory = Callable[[str], StrategyExecutionCoordinator]
"""`(strategy_id) -> a coordinator with exactly that strategy active`,
built from the EXISTING `StrategyRegistry` by the composition root."""

ConfigurationValuesFactory = Callable[[str], dict[str, object]]
"""`(strategy_id) -> the strategy's parameter values`. Injected so this
service never hardcodes a strategy parameter: the composition root
supplies them from the strategy's OWN schema defaults
(`trading_engine.strategy_execution.contracts.default_configuration_values`),
the same canonical defaults the configuration API and the frontend
already display."""


@dataclass(frozen=True, slots=True)
class ReplaySignalRow:
    """One evaluated replay step, as it happened. Purely a report of what
    the existing services returned - never a re-decision."""

    step: int
    bar_timestamp: datetime
    instrument_id: str
    strategy_id: str
    direction: str | None
    signal_id: str | None
    skipped_reason: str | None
    risk_outcome: str | None
    risk_reason_code: str | None
    order_status: str | None


@dataclass(frozen=True, slots=True)
class ReplayPaperSessionView:
    """Everything the API/UI needs for one session, in one object."""

    record: PaperSessionRecord
    status: PaperSessionStatus
    account: PaperAccountSnapshot
    open_positions: tuple[Position, ...]
    closed_positions: tuple[Position, ...]
    closed_trades: tuple[Trade, ...]
    signals: tuple[ReplaySignalRow, ...]
    equity_curve: tuple[tuple[datetime, Decimal], ...]


@dataclass(frozen=True, slots=True)
class ReplayPaperSessionResult:
    """Returned by every lifecycle command. `accepted=False` means the
    command was REFUSED as an idempotent no-op (double-START, double-
    STOP) - never an exception, never a state mutation (§15)."""

    accepted: bool
    view: ReplayPaperSessionView
    message: str


class ReplayPaperSessionService:
    def __init__(
        self,
        *,
        repository: PaperSessionRepository,
        broker_factory: BrokerFactory,
        bar_loader: BarLoader,
        coordinator_factory: CoordinatorFactory,
        configuration_values_factory: ConfigurationValuesFactory,
        risk_limits: RiskLimits,
        risk_configuration_version: str,
        max_concurrent_positions: int,
        max_total_exposure: Decimal,
        kill_switch_status_provider: Callable[[], TradingHaltStatus],
        clock: Callable[[], datetime] = lambda: datetime.now(tz=UTC),
    ) -> None:
        self._repository = repository
        self._broker_factory = broker_factory
        self._bar_loader = bar_loader
        self._coordinator_factory = coordinator_factory
        self._configuration_values_factory = configuration_values_factory
        self._risk_limits = risk_limits
        self._risk_configuration_version = risk_configuration_version
        self._max_concurrent_positions = max_concurrent_positions
        self._max_total_exposure = max_total_exposure
        self._kill_switch_status_provider = kill_switch_status_provider
        self._clock = clock

    # --- creation ---------------------------------------------------------

    def create(
        self,
        *,
        session_id: str,
        strategy_id: str,
        instrument_ids: Sequence[str],
        timeframe: Timeframe,
        starting_capital: Decimal,
        quantity: Decimal,
        replay_date: object,
        playback_speed: int = 1,
    ) -> ReplayPaperSessionResult:
        """Creates (or re-specifies, while STOPPED) a session. A session
        that is RUNNING or PAUSED is NEVER re-specified - the caller must
        STOP it first, so an in-flight session's own identity can never
        change under it."""
        if starting_capital <= 0:
            raise ValueError("starting_capital must be positive")
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        if playback_speed < 1:
            raise ValueError("playback_speed must be >= 1")
        if not instrument_ids:
            raise ValueError("at least one instrument must be selected")

        existing = self._repository.get(session_id)
        if existing is not None and existing.status in (
            PaperSessionStatus.RUNNING.value,
            PaperSessionStatus.PAUSED.value,
        ):
            return ReplayPaperSessionResult(
                accepted=False,
                view=self._view(existing),
                message=(
                    "This paper session is currently "
                    f"{existing.status} - stop it before re-specifying it."
                ),
            )

        now = self._clock()
        draft = PaperSessionRecord(
            session_id=session_id,
            status=PaperSessionStatus.STOPPED.value,
            strategy_id=strategy_id,
            timeframe=timeframe.value,
            instrument_ids=tuple(instrument_ids),
            starting_capital=starting_capital,
            quantity=quantity,
            replay_date=replay_date,  # type: ignore[arg-type]
            replay_cursor=0,
            replay_total_steps=0,
            playback_speed=playback_speed,
            created_at=existing.created_at if existing is not None else now,
            updated_at=now,
            last_error="",
        )
        total = self._total_steps(draft)
        saved = self._repository.save(replace(draft, replay_total_steps=total))
        return ReplayPaperSessionResult(
            accepted=True,
            view=self._view(saved),
            message="Paper session specified. It is STOPPED until you start paper trading.",
        )

    # --- lifecycle commands (§14) ----------------------------------------

    def start(self, session_id: str) -> ReplayPaperSessionResult:
        return self._command(session_id, PaperSessionCommand.START)

    def pause(self, session_id: str) -> ReplayPaperSessionResult:
        return self._command(session_id, PaperSessionCommand.PAUSE)

    def resume(self, session_id: str) -> ReplayPaperSessionResult:
        return self._command(session_id, PaperSessionCommand.RESUME)

    def stop(self, session_id: str) -> ReplayPaperSessionResult:
        return self._command(session_id, PaperSessionCommand.STOP)

    def reset(self, session_id: str) -> ReplayPaperSessionResult:
        """RESET rewinds `replay_cursor` to 0 - and, per
        `RESET_WHILE_RUNNING_SEMANTICS`, is REJECTED (raises
        `InvalidPaperSessionTransitionError`) while RUNNING or PAUSED."""
        return self._command(session_id, PaperSessionCommand.RESET)

    def _command(self, session_id: str, command: PaperSessionCommand) -> ReplayPaperSessionResult:
        record = self._require(session_id)
        status = PaperSessionStatus(record.status)

        if is_idempotent_no_op(status, command):
            return ReplayPaperSessionResult(
                accepted=False,
                view=self._view(record),
                message=(
                    f"{command.value} ignored - this paper session is already {status.value}. "
                    "No second session was created and no state was changed."
                ),
            )

        new_status = apply_command(status, command)
        updated = replace(
            record,
            status=new_status.value,
            replay_cursor=0 if command is PaperSessionCommand.RESET else record.replay_cursor,
            last_error="" if command is PaperSessionCommand.RESET else record.last_error,
            updated_at=self._clock(),
        )
        saved = self._repository.save(updated)
        return ReplayPaperSessionResult(
            accepted=True,
            view=self._view(saved),
            message=f"Paper session {status.value} -> {new_status.value}.",
        )

    # --- replay controls (§6) --------------------------------------------

    def step(self, session_id: str, *, steps: int = 1) -> ReplayPaperSessionResult:
        """Advances the replay by `steps` (default 1). Only a RUNNING
        session advances - a PAUSED/STOPPED/COMPLETED/FAILED session is
        refused without mutation, which is what makes PAUSE actually
        mean something."""
        if steps < 1:
            raise ValueError("steps must be >= 1")
        record = self._require(session_id)
        status = PaperSessionStatus(record.status)
        if status is not PaperSessionStatus.RUNNING:
            return ReplayPaperSessionResult(
                accepted=False,
                view=self._view(record),
                message=f"A {status.value} paper session does not advance. Start or resume it.",
            )

        total = record.replay_total_steps
        target = min(record.replay_cursor + steps, total)
        if target == record.replay_cursor:
            completed = replace(
                record,
                status=apply_command(status, PaperSessionCommand.COMPLETE).value,
                updated_at=self._clock(),
            )
            saved = self._repository.save(completed)
            return ReplayPaperSessionResult(
                accepted=True,
                view=self._view(saved),
                message="Replay data exhausted - paper session COMPLETED.",
            )

        advanced = replace(record, replay_cursor=target, updated_at=self._clock())
        if target >= total:
            advanced = replace(
                advanced, status=apply_command(status, PaperSessionCommand.COMPLETE).value
            )
        saved = self._repository.save(advanced)
        return ReplayPaperSessionResult(
            accepted=True,
            view=self._view(saved),
            message=f"Replay advanced to step {target} of {total}.",
        )

    def tick(self, session_id: str) -> ReplayPaperSessionResult:
        """One playback tick - advances by the session's own
        `playback_speed`. This is the entry point a poller/scheduler
        calls; `step()` is the manual single-step control."""
        record = self._require(session_id)
        return self.step(session_id, steps=max(1, record.playback_speed))

    def run_to_completion(self, session_id: str) -> ReplayPaperSessionResult:
        """Deterministic full playback - the form automated tests use
        (§6: "for automated tests the playback must be deterministic")."""
        record = self._require(session_id)
        return self.step(session_id, steps=max(1, record.replay_total_steps))

    # --- read -------------------------------------------------------------

    def get(self, session_id: str) -> ReplayPaperSessionView | None:
        record = self._repository.get(session_id)
        return None if record is None else self._view(record)

    def _require(self, session_id: str) -> PaperSessionRecord:
        record = self._repository.get(session_id)
        if record is None:
            raise UnknownPaperSessionError(f"unknown paper session {session_id!r}")
        return record

    # --- the projection ---------------------------------------------------

    def _total_steps(self, record: PaperSessionRecord) -> int:
        """One step per bar that has a SUCCESSOR bar to fill against (see
        this module's docstring on next-bar-open execution) - so a series
        of N bars yields N-1 steps, never a step that would need a bar
        the replay does not have."""
        bars = self._bar_loader(record)
        return max(0, len(bars) - 1)

    def _view(self, record: PaperSessionRecord) -> ReplayPaperSessionView:
        return self.project(record)

    def project(self, record: PaperSessionRecord) -> ReplayPaperSessionView:
        """Deterministically re-derives the ENTIRE session state from
        `(record, record.replay_cursor)`. Pure with respect to
        persistence: it never writes."""
        bars = self._bar_loader(record)
        replay_instant = _ReplayClock(bars[0].timestamp if bars else self._clock())
        broker = self._broker_factory(record.starting_capital, replay_instant.now)
        trading_service = PaperTradingService(
            broker=broker,  # type: ignore[arg-type]
            risk_limits=self._risk_limits,
            risk_configuration_version=self._risk_configuration_version,
            max_concurrent_positions=self._max_concurrent_positions,
            max_total_exposure=self._max_total_exposure,
            kill_switch_status_provider=self._kill_switch_status_provider,
            clock=replay_instant.now,
            ledger=None,
        )
        execution = PaperSignalExecutionService(
            coordinator=self._coordinator_factory(record.strategy_id),
            paper_trading_service=trading_service,
            quantity=record.quantity,
        )
        configuration = StrategyConfigurationValues(
            strategy_id=record.strategy_id,
            specification_version="replay-1",
            code_version="replay-1",
            configuration_version=f"replay-{record.session_id}",
            values=self._configuration_values_factory(record.strategy_id),
        )
        instrument_id = InstrumentId(record.instrument_ids[0]) if record.instrument_ids else None

        signals: list[ReplaySignalRow] = []
        equity_curve: list[tuple[datetime, Decimal]] = []
        peak_equity = record.starting_capital
        processed_signal_ids: set[str] = set()
        submitted_keys: set[str] = set()

        steps = min(record.replay_cursor, max(0, len(bars) - 1))
        for index in range(steps):
            decision_bars = tuple(bars[: index + 1])
            execution_bar = bars[index + 1]
            replay_instant.set(execution_bar.timestamp)
            # Fill reference price FIRST, at the NEXT bar's open - the
            # same next-bar-open rule the backtest engine uses. The
            # strategy below never sees this bar, so this is not
            # look-ahead in the DECISION, only in the FILL PRICE, which
            # is exactly the intended semantic.
            broker.record_price(
                execution_bar.instrument_id, execution_bar.open, execution_bar.timestamp
            )
            if instrument_id is None:
                continue
            outcome = execution.evaluate_and_submit(
                bars=decision_bars,
                instrument_id=instrument_id,
                strategy_id=record.strategy_id,
                configuration=configuration,
                strategy_is_active=True,
                # Replay bars are generated on the NSE session grid for a
                # real trading date (see the injected bar loader), so this
                # is the session state that genuinely applied to the bar
                # being replayed - not a blanket "pretend it is open".
                market_session_is_open=True,
                data_quality_is_stale=False,
                already_processed_signal_ids=frozenset(processed_signal_ids),
                already_submitted_idempotency_keys=frozenset(submitted_keys),
            )
            if outcome.signal_id is not None:
                processed_signal_ids.add(str(outcome.signal_id))
                submitted_keys.add(str(outcome.signal_id))
            signals.append(_to_signal_row(index, decision_bars[-1], record, outcome))
            equity = broker.get_equity()
            peak_equity = max(peak_equity, equity)
            equity_curve.append((execution_bar.timestamp, equity))

        if steps > 0 and steps >= max(0, len(bars) - 1):
            # END-OF-REPLAY (§7 "EOD close if supported"): the EXISTING
            # `force_expire_end_of_session()` is what closes out resting
            # orders - never a new end-of-day routine. Open POSITIONS are
            # deliberately NOT auto-squared-off here; see this
            # checkpoint's report for that honest limitation.
            replay_instant.set(bars[-1].timestamp)
            broker.record_price(bars[-1].instrument_id, bars[-1].close, bars[-1].timestamp)
            broker.force_expire_end_of_session()

        positions = broker.get_positions()
        funds = broker.get_funds()
        equity = broker.get_equity()
        peak_equity = max(peak_equity, equity)
        account = PaperAccountSnapshot(
            starting_capital=record.starting_capital,
            available_capital=funds.available_balance,
            utilized_margin=funds.utilized_margin,
            realized_pnl=sum((p.realized_net_pnl or ZERO for p in positions), ZERO),
            unrealized_pnl=broker.get_total_unrealized_pnl(),
            equity=equity,
            peak_equity=peak_equity,
        )
        return ReplayPaperSessionView(
            record=record,
            status=PaperSessionStatus(record.status),
            account=account,
            open_positions=tuple(p for p in positions if p.status is PositionStatus.OPEN),
            closed_positions=tuple(p for p in positions if p.status is PositionStatus.CLOSED),
            closed_trades=broker.get_trades(),
            signals=tuple(signals),
            equity_curve=tuple(equity_curve),
        )


class _ReplayClock:
    """The replay's own advancing clock - a tiny mutable holder so the
    injected `PaperBroker` and `PaperTradingService` both read the SAME
    market instant without either of them needing to know it is a
    replay. Deliberately NOT a new time abstraction: both consumers
    already accept a `Callable[[], datetime]`."""

    __slots__ = ("_instant",)

    def __init__(self, instant: datetime) -> None:
        self._instant = instant

    def set(self, instant: datetime) -> None:
        self._instant = instant

    def now(self) -> datetime:
        return self._instant


class UnknownPaperSessionError(KeyError):
    """Raised when a lifecycle command names a session that was never
    created - never silently auto-created, which would be exactly the
    "starting twice creates two sessions" failure §15 forbids."""


def _to_signal_row(
    index: int,
    decision_bar: Bar,
    record: PaperSessionRecord,
    outcome: object,
) -> ReplaySignalRow:
    direction = getattr(outcome, "direction", None)
    signal_id = getattr(outcome, "signal_id", None)
    order_result = getattr(outcome, "order_result", None)
    risk_outcome: str | None = None
    risk_reason: str | None = None
    order_status: str | None = None
    if order_result is not None:
        decision = order_result.risk_decision
        risk_outcome = decision.outcome.value
        risk_reason = decision.reason_code.value if decision.reason_code else None
        if decision.outcome is RiskDecisionOutcome.APPROVED and order_result.broker_report:
            order_status = order_result.broker_report.status.value
    return ReplaySignalRow(
        step=index,
        bar_timestamp=decision_bar.timestamp,
        instrument_id=str(decision_bar.instrument_id),
        strategy_id=record.strategy_id,
        direction=direction.value if direction is not None else None,
        signal_id=str(signal_id) if signal_id is not None else None,
        skipped_reason=getattr(outcome, "skipped_reason", None),
        risk_outcome=risk_outcome,
        risk_reason_code=risk_reason,
        order_status=order_status,
    )


__all__ = [
    "InvalidPaperSessionTransitionError",
    "ReplayPaperSessionResult",
    "ReplayPaperSessionService",
    "ReplayPaperSessionView",
    "ReplaySignalRow",
    "UnknownPaperSessionError",
]
