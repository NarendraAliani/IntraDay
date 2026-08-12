# tests/unit/domain/test_strategy.py
#
# Unit tests for the StrategyIdentity/StrategyVersion contracts and the
# StrategyMaturityState lifecycle enum (Checkpoint 5).
from __future__ import annotations

import pytest

from intraday.domain.shared_kernel.contracts import Timeframe, Version
from intraday.domain.strategy.contracts import (
    StrategyIdentity,
    StrategyMaturityState,
    StrategyVersion,
)


def test_strategy_identity_requires_non_empty_fields() -> None:
    with pytest.raises(ValueError):
        StrategyIdentity(strategy_id="", name="Opening Range Breakout")


def test_strategy_version_bundles_all_lineage_versions() -> None:
    version = StrategyVersion(
        strategy_id="orb-v1",
        specification_version=Version(value="spec-1"),
        code_version=Version(value="git-abc123"),
        configuration_version=Version(value="cfg-1"),
        universe_version=Version(value="nifty50-2026-01"),
        timeframe=Timeframe.FIVE_MINUTE,
        maturity_state=StrategyMaturityState.RESEARCH,
    )
    assert version.maturity_state is StrategyMaturityState.RESEARCH


def test_maturity_state_covers_the_full_approved_lifecycle() -> None:
    """Checkpoint 1 Section 7 mandated exactly these 11 lifecycle states —
    verify none were dropped or renamed."""
    expected = {
        "IDEA",
        "RESEARCH",
        "IMPLEMENTED",
        "BACKTESTED",
        "VALIDATED",
        "PAPER",
        "LIMITED_LIVE",
        "PRODUCTION",
        "SUSPENDED",
        "REJECTED",
        "DEPRECATED",
    }
    assert {member.name for member in StrategyMaturityState} == expected
