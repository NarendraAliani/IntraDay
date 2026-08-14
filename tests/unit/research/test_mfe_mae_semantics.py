# tests/unit/research/test_mfe_mae_semantics.py
#
# Checkpoint 28 Part 25: proves `research.backtesting`'s trade-level
# MFE/MAE and `signal_intelligence.theoretical_outcome`'s
# signal-horizon MFE/MAE remain semantically distinct - a mechanical
# guard against ever accidentally conflating the two computation bases,
# not just a documentation claim.
from __future__ import annotations

import ast
from pathlib import Path

from intraday.research.backtesting.execution import mfe_mae
from intraday.signal_intelligence.theoretical_outcome.outcome import compute_theoretical_outcome

REPO_ROOT = Path(__file__).resolve().parents[3]
EXECUTION_FILE = REPO_ROOT / "src" / "intraday" / "research" / "backtesting" / "execution.py"


def test_backtest_mfe_mae_never_imports_theoretical_outcome() -> None:
    """The two computations must never share code - a structural
    guarantee, not just a naming convention."""
    tree = ast.parse(EXECUTION_FILE.read_text(encoding="utf-8"), filename=str(EXECUTION_FILE))
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)
    assert not any("theoretical_outcome" in name for name in imported_modules)


def test_backtest_mfe_mae_and_theoretical_outcome_are_distinct_functions() -> None:
    """The two callables are simply different objects - proves no
    accidental aliasing (e.g. `mfe_mae = compute_theoretical_outcome`)
    was ever introduced."""
    assert mfe_mae is not compute_theoretical_outcome
    assert mfe_mae.__module__ != compute_theoretical_outcome.__module__


def test_backtest_mfe_mae_signature_is_holding_period_based_not_horizon_based() -> None:
    """`research.backtesting.execution.mfe_mae` takes the trade's own
    holding-period bars (a variable-length, trade-defined window) -
    `theoretical_outcome.compute_theoretical_outcome` takes a fixed
    `horizon_bars` integer parameter counted from one signal. Different
    parameter shapes prove the different computation basis at the API
    level, not merely in a docstring."""
    import inspect

    mfe_mae_params = list(inspect.signature(mfe_mae).parameters)
    outcome_params = list(inspect.signature(compute_theoretical_outcome).parameters)
    assert "holding_bars" in mfe_mae_params
    assert "horizon_bars" in outcome_params
    assert "holding_bars" not in outcome_params
    assert "horizon_bars" not in mfe_mae_params
