# File: src/intraday/application/services/strategy_research_status.py
#
# Checkpoint 27 Part 20: research-monitor pause/resume state. A
# deliberately SEPARATE, small state set from
# `domain.strategy.StrategyMaturityState` - "is this strategy currently
# included in research/backtesting activity", never a live-trading
# control. Valid states are exactly RESEARCH_ACTIVE/RESEARCH_PAUSED/
# DISABLED - no other value is ever written or accepted.
from __future__ import annotations

from dataclasses import dataclass

from intraday.application.repositories import StrategyResearchStatusRepository
from intraday.trading_engine.strategy_execution.registry import StrategyRegistry

VALID_STATUSES = ("RESEARCH_ACTIVE", "RESEARCH_PAUSED", "DISABLED")
DEFAULT_STATUS = "RESEARCH_ACTIVE"


@dataclass
class StrategyResearchStatusService:
    repository: StrategyResearchStatusRepository
    registry: StrategyRegistry

    def get_status(self, strategy_id: str) -> str:
        self.registry.get(strategy_id)  # raises UnknownStrategyError if absent
        return self.repository.get_status(strategy_id) or DEFAULT_STATUS

    def set_status(self, strategy_id: str, status: str, *, updated_by: str) -> str:
        self.registry.get(strategy_id)
        if status not in VALID_STATUSES:
            raise ValueError(f"invalid research status {status!r}: must be one of {VALID_STATUSES}")
        self.repository.set_status(strategy_id, status, updated_by=updated_by)
        return status

    def list_all(self) -> dict[str, str]:
        statuses = self.repository.list_all()
        return {
            strategy.strategy_id: statuses.get(strategy.strategy_id, DEFAULT_STATUS)
            for strategy in self.registry.list()
        }
