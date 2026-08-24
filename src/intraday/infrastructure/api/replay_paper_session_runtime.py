# File: src/intraday/infrastructure/api/replay_paper_session_runtime.py
#
# Checkpoint 64.68: the composition root for the REPLAY PAPER SESSION.
# Lives in `infrastructure/api/` for exactly the reason
# `paper_trading_runtime.py`'s own docstring gives (Decision 153):
# `.importlinter` contract 6 forbids `application/services/*` from
# importing `infrastructure.brokers` / `infrastructure.persistence` /
# `infrastructure.market_data_providers`, so the concrete wiring must
# happen here.
#
# SAFETY (Checkpoint 64.68's own non-negotiable rules):
#   - There is NO Dhan client, NO WebSocket, NO HTTP call and NO live
#     market-data path anywhere in this module or anything it composes.
#     Bars come from the EXISTING `SyntheticHistoricalBarProvider`
#     (Checkpoint 63.x) fed into the EXISTING
#     `DeterministicReplayBarSource` (Checkpoint 52) - both of which
#     already carry their own explicit "NOT real broker data" disclosure.
#   - The broker is the EXISTING `PaperBroker`, built with the SAME
#     verified NSE cash-equity intraday cost model
#     `paper_trading_runtime.py` already injects. No new broker.
#   - The risk limits and kill-switch provider are the SAME ones
#     `paper_trading_runtime.py` already defines - imported, not
#     re-declared, so a replay paper session can never run against
#     looser limits than a manual paper order.
#   - The strategy registry is the EXISTING `build_default_registry()`,
#     which contains ONLY the three long-established safe strategies.
#     No not-yet-productized research strategy is registered there, and
#     none is activated here.
from __future__ import annotations

import datetime as dt
import itertools
from collections.abc import Callable
from decimal import Decimal

from intraday.application.repositories.paper_session import PaperSessionRecord
from intraday.application.services.kill_switch import KillSwitchService
from intraday.application.services.replay_paper_session import (
    ReplayPaperBroker,
    ReplayPaperSessionService,
)
from intraday.application.services.strategy_execution import build_coordinator
from intraday.domain.market_data.contracts import Bar
from intraday.domain.risk.contracts import TradingHaltStatus
from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe
from intraday.infrastructure.api.paper_trading_runtime import (
    DEFAULT_MAX_CONCURRENT_POSITIONS,
    DEFAULT_MAX_TOTAL_EXPOSURE,
    DEFAULT_RISK_LIMITS,
    RISK_CONFIGURATION_VERSION,
    compute_paper_cost,
)
from intraday.infrastructure.brokers.paper.broker import PaperBroker
from intraday.infrastructure.market_data_providers.replay.deterministic_bar_source import (
    DeterministicReplayBarSource,
)
from intraday.infrastructure.market_data_providers.synthetic_historical import (
    SyntheticHistoricalBarProvider,
)
from intraday.infrastructure.persistence.kill_switch_repository import DjangoKillSwitchRepository
from intraday.infrastructure.persistence.paper_session_repository import (
    DjangoPaperSessionRepository,
)
from intraday.trading_engine.strategy_execution.contracts import default_configuration_values
from intraday.trading_engine.strategy_execution.coordinator import StrategyExecutionCoordinator
from intraday.trading_engine.strategy_execution.registry import build_default_registry

DEFAULT_SESSION_ID = "default"
"""§12: ONE controlled paper session, not a session-management product.
A multi-session UI is deliberately out of scope for this MVP."""

DEFAULT_STARTING_CAPITAL = Decimal("1000000")
DEFAULT_QUANTITY = Decimal("10")
DEFAULT_TIMEFRAME = Timeframe.FIVE_MINUTE
"""§13: 5m - already a supported timeframe; no new timeframe
infrastructure was added."""


def available_strategy_ids() -> tuple[str, ...]:
    """§11: exactly the strategies the EXISTING registry already
    contains. Never a hand-maintained second list, so a strategy can
    never appear in the paper-session UI without being genuinely
    registered."""
    return tuple(s.strategy_id for s in build_default_registry().list())


def deterministic_id_factory() -> Callable[[], str]:
    """§17: a monotonic, per-broker-instance identifier sequence, so the
    SURROGATE ids `PaperBroker` mints (event/fill/position/trade) are
    reproducible across two runs of the same replay. Purely an identity
    concern - it cannot and does not change any price, quantity, cost or
    P&L figure."""
    counter = itertools.count(1)
    return lambda: f"replay-{next(counter):06d}"


def build_broker(initial_capital: Decimal, clock: Callable[[], dt.datetime]) -> ReplayPaperBroker:
    """A FRESH `PaperBroker` per projection - see
    `replay_paper_session.py`'s "projection, not a live mutable engine"
    decision. Never the process-wide singleton from
    `paper_trading_runtime.get_paper_broker()`: a replay session must
    never mutate, or be contaminated by, the manual paper-order account.
    """
    return PaperBroker(
        initial_capital=initial_capital,
        compute_cost=compute_paper_cost,
        clock=clock,
        id_factory=deterministic_id_factory(),
    )


def load_replay_bars(record: PaperSessionRecord) -> tuple[Bar, ...]:
    """§5: the deterministic replay market-data path. Composes two
    EXISTING components and adds no market-data logic of its own:
    `SyntheticHistoricalBarProvider` (deterministic, seeded from each
    bar's own identity, session-grid aligned, explicitly NOT real broker
    data) -> `DeterministicReplayBarSource` (the existing `BarSource`
    boundary). The SAME canonical `Bar` contract flows end to end - no
    parallel bar type is introduced anywhere.
    """
    if not record.instrument_ids:
        return ()
    instrument_id = InstrumentId(record.instrument_ids[0])
    timeframe = Timeframe(record.timeframe)
    start = dt.datetime.combine(record.replay_date, dt.time.min, tzinfo=dt.UTC)
    end = dt.datetime.combine(record.replay_date, dt.time.max, tzinfo=dt.UTC)
    provider = SyntheticHistoricalBarProvider()
    bars = provider.fetch(instrument_id, timeframe, start, end)
    source = DeterministicReplayBarSource.seeded(bars)
    return source.get_bars(instrument_id=instrument_id, timeframe=timeframe, as_of=end)


def build_coordinator_for(strategy_id: str) -> StrategyExecutionCoordinator:
    """§11: activates exactly ONE already-registered strategy on the
    EXISTING default registry. An unregistered id raises
    `UnknownStrategyError` from the registry itself - this function
    never silently falls back to some other strategy."""
    registry = build_default_registry()
    registry.activate(strategy_id)
    return build_coordinator(registry)


def configuration_values_for(strategy_id: str) -> dict[str, object]:
    """§11: the strategy's OWN schema defaults, from the EXISTING
    registry - never a hardcoded parameter dictionary in this module, so
    a paper session always runs the same starting parameters the
    Strategy Configuration screen already shows for that strategy."""
    strategy = build_default_registry().get(strategy_id)
    return default_configuration_values(strategy.parameter_schema())


def _kill_switch_status() -> TradingHaltStatus:
    return KillSwitchService(DjangoKillSwitchRepository()).status().status


def get_replay_paper_session_service() -> ReplayPaperSessionService:
    return ReplayPaperSessionService(
        repository=DjangoPaperSessionRepository(),
        broker_factory=build_broker,
        bar_loader=load_replay_bars,
        coordinator_factory=build_coordinator_for,
        configuration_values_factory=configuration_values_for,
        risk_limits=DEFAULT_RISK_LIMITS,
        risk_configuration_version=RISK_CONFIGURATION_VERSION,
        max_concurrent_positions=DEFAULT_MAX_CONCURRENT_POSITIONS,
        max_total_exposure=DEFAULT_MAX_TOTAL_EXPOSURE,
        kill_switch_status_provider=_kill_switch_status,
    )


def default_replay_date(today: dt.date | None = None) -> dt.date:
    """The most recent NSE trading day on or before `today` - a real,
    deterministic calendar answer from the EXISTING
    `domain.session.calendar.is_trading_day`, never a hardcoded date and
    never a live market query."""
    from intraday.domain.session.calendar import is_trading_day

    day = today or dt.datetime.now(tz=dt.UTC).date()
    for _ in range(14):
        if is_trading_day(day):
            return day
        day -= dt.timedelta(days=1)
    return day


__all__ = [
    "DEFAULT_QUANTITY",
    "DEFAULT_SESSION_ID",
    "DEFAULT_STARTING_CAPITAL",
    "DEFAULT_TIMEFRAME",
    "available_strategy_ids",
    "build_broker",
    "build_coordinator_for",
    "configuration_values_for",
    "default_replay_date",
    "deterministic_id_factory",
    "get_replay_paper_session_service",
    "load_replay_bars",
]
