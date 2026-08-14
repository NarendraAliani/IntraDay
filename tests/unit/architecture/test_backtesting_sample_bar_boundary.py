# tests/unit/architecture/test_backtesting_sample_bar_boundary.py
#
# Checkpoint 27: mandatory SAMPLE_BAR safety-gate test for backtesting,
# mirroring Checkpoint 26's
# test_strategy_execution_sample_bar_boundary.py exactly. Proves neither
# `research.backtesting` nor `application.services.backtesting` ever
# imports live-market-data or broker-execution modules.
from __future__ import annotations

import ast
from pathlib import Path

FORBIDDEN_PREFIXES = (
    "intraday.infrastructure.persistence.live_market_data_repositories",
    "intraday.application.services.bar_aggregation",
    "intraday.infrastructure.market_data_providers.dhan",
    "intraday.infrastructure.api.market_data_views",
    "intraday.trading_engine.risk_engine",
    "intraday.trading_engine.order_management",
    "intraday.trading_engine.execution_management",
    "intraday.trading_engine.broker_abstraction",
    "intraday.trading_engine.session_management",
)

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKTESTING_PACKAGE = REPO_ROOT / "src" / "intraday" / "research" / "backtesting"
BACKTESTING_SERVICE_FILE = (
    REPO_ROOT / "src" / "intraday" / "application" / "services" / "backtesting.py"
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
                violations.append(f"{source_file}: forbidden import {module_name!r}")
    return violations


def test_backtesting_package_exists() -> None:
    assert BACKTESTING_PACKAGE.is_dir()
    assert BACKTESTING_SERVICE_FILE.is_file()


def test_backtesting_never_imports_live_data_or_order_execution() -> None:
    files = list(BACKTESTING_PACKAGE.rglob("*.py")) + [BACKTESTING_SERVICE_FILE]
    violations = _scan(files)
    assert not violations, (
        "SAMPLE_BAR / live-execution safety gate violated in backtesting:\n" + "\n".join(violations)
    )


def test_backtesting_service_only_depends_on_historical_market_data_service() -> None:
    imported = _imported_module_names(BACKTESTING_SERVICE_FILE)
    assert any("HistoricalMarketDataService" in name for name in imported)
    assert not any("live_market_data" in name for name in imported)
    assert not any("bar_aggregation" in name for name in imported)


def test_backtesting_never_places_orders() -> None:
    """Repo-wide textual scan of the backtesting package for order/
    broker-execution vocabulary - a second, independent check alongside
    the import-based one above."""
    forbidden_terms = (
        "place_order",
        "cancel_order",
        "modify_order",
        "submit_order",
        "broker_client",
    )
    violations: list[str] = []
    for source_file in list(BACKTESTING_PACKAGE.rglob("*.py")) + [BACKTESTING_SERVICE_FILE]:
        text = source_file.read_text(encoding="utf-8").lower()
        for term in forbidden_terms:
            if term in text:
                violations.append(f"{source_file}: forbidden term {term!r}")
    assert not violations, "\n".join(violations)
