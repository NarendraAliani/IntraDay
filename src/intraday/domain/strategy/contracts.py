# File: src/intraday/domain/strategy/contracts.py
#
# Canonical strategy identity/specification-version contracts (Checkpoint
# 5). Distinguishes the concepts Checkpoint 2's review required kept
# separate: Identity, Specification/Version (declarative, reproducibility-
# oriented), and — deliberately NOT represented here — Runtime
# Implementation, which is real executable Python code living in
# trading_engine/strategy_execution in a later checkpoint, never a domain
# dataclass (Checkpoint 5 Section 11).
from __future__ import annotations

import enum
from dataclasses import dataclass

from intraday.domain.shared_kernel.contracts import StrategyId, Timeframe, Version


class StrategyMaturityState(enum.Enum):
    """Lifecycle states approved at Checkpoint 1 Section 7. This enum is
    the shared vocabulary `trading_engine/strategy_registry` (authoritative
    current state) and `research/strategy_promotion` (transition evidence)
    both reference — it contains no transition RULES, only the finite set
    of valid states."""

    IDEA = "IDEA"
    RESEARCH = "RESEARCH"
    IMPLEMENTED = "IMPLEMENTED"
    BACKTESTED = "BACKTESTED"
    VALIDATED = "VALIDATED"
    PAPER = "PAPER"
    LIMITED_LIVE = "LIMITED_LIVE"
    PRODUCTION = "PRODUCTION"
    SUSPENDED = "SUSPENDED"
    REJECTED = "REJECTED"
    DEPRECATED = "DEPRECATED"


@dataclass(frozen=True, slots=True)
class StrategyIdentity:
    """Who a strategy IS, independent of any particular version — a stable
    handle `research/strategy_specifications` and
    `trading_engine/strategy_registry` both refer to."""

    strategy_id: StrategyId
    name: str

    def __post_init__(self) -> None:
        if not self.strategy_id.strip():
            raise ValueError("StrategyIdentity.strategy_id must be non-empty")
        if not self.name.strip():
            raise ValueError("StrategyIdentity.name must be non-empty")


@dataclass(frozen=True, slots=True)
class StrategyVersion:
    """A specific, reproducible version of a strategy's SPECIFICATION
    (declarative, `research/strategy_specifications` — Checkpoint 2 §4) —
    not the executable implementation, which cannot be represented as a
    dataclass. Bundles every version identifier Checkpoint 3 §17/§21-22
    requires for reproducibility, so "exactly which code + strategy +
    configuration + dataset produced this result?" is answerable from
    these fields together with a `research/experiments` record that
    references this `StrategyVersion`.
    """

    strategy_id: StrategyId
    specification_version: Version
    code_version: Version
    configuration_version: Version
    universe_version: Version
    timeframe: Timeframe
    maturity_state: StrategyMaturityState

    def __post_init__(self) -> None:
        if not self.strategy_id.strip():
            raise ValueError("StrategyVersion.strategy_id must be non-empty")
