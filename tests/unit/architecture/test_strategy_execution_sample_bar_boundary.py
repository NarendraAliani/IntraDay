# tests/unit/architecture/test_strategy_execution_sample_bar_boundary.py
#
# Checkpoint 26 Part 15/17: mandatory, dedicated SAMPLE_BAR safety-gate
# test. Statically proves (ast-based import scan, same technique as
# test_signal_generation_boundaries.py) that neither
# `application.services.strategy_execution`
# (DiagnosticStrategyExecutionService, the only orchestration point that
# feeds bars into the strategy coordinator) nor
# `trading_engine.strategy_execution` itself ever imports anything from
# the live-market-data path. A future developer cannot accidentally wire
# SAMPLE_BAR live data into strategy execution without this test failing
# - the guarantee is structural (no import path exists), not merely
# documented.
from __future__ import annotations

import ast
from pathlib import Path

FORBIDDEN_PREFIXES = (
    "intraday.infrastructure.persistence.live_market_data_repositories",
    "intraday.application.services.bar_aggregation",
    "intraday.infrastructure.market_data_providers.dhan",
    "intraday.infrastructure.api.market_data_views",
)

REPO_ROOT = Path(__file__).resolve().parents[3]
STRATEGY_EXECUTION_PACKAGE = (
    REPO_ROOT / "src" / "intraday" / "trading_engine" / "strategy_execution"
)
DIAGNOSTIC_SERVICE_FILE = (
    REPO_ROOT / "src" / "intraday" / "application" / "services" / "strategy_execution.py"
)


def _imported_module_names(source_file: Path) -> set[str]:
    tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            for alias in node.names:
                names.add(f"{node.module}.{alias.name}")
    return names


def _scan(paths: list[Path]) -> list[str]:
    violations: list[str] = []
    for source_file in paths:
        for module_name in _imported_module_names(source_file):
            if any(
                module_name == prefix or module_name.startswith(prefix + ".")
                for prefix in FORBIDDEN_PREFIXES
            ):
                violations.append(
                    f"{source_file}: forbidden live-market-data import {module_name!r}"
                )
    return violations


def test_strategy_execution_package_exists() -> None:
    assert STRATEGY_EXECUTION_PACKAGE.is_dir()
    assert DIAGNOSTIC_SERVICE_FILE.is_file()


def test_strategy_execution_never_imports_live_market_data() -> None:
    files = list(STRATEGY_EXECUTION_PACKAGE.rglob("*.py")) + [DIAGNOSTIC_SERVICE_FILE]
    violations = _scan(files)
    assert not violations, (
        "SAMPLE_BAR safety gate violated - strategy execution must never import "
        "live market data:\n" + "\n".join(violations)
    )


def test_diagnostic_service_only_depends_on_historical_market_data_service() -> None:
    """Positive check: the diagnostic execution service's only bar
    source is `HistoricalMarketDataService` - the exact fixture/
    historical-only dependency `SignalGenerationService` (Checkpoint 18)
    already established, never `live_market_data`/`bar_aggregation`.
    Checks actual import statements (not comment text, which legitimately
    names the forbidden modules to explain why they are absent)."""
    imported = _imported_module_names(DIAGNOSTIC_SERVICE_FILE)
    assert any("HistoricalMarketDataService" in name for name in imported)
    assert not any("live_market_data" in name for name in imported)
    assert not any("bar_aggregation" in name for name in imported)
