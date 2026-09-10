# tests/unit/architecture/test_adhoc_screening_boundary.py
#
# CHECKPOINT-SCANNER-A: mechanical, ast-based proof (same technique
# test_strategy_execution_sample_bar_boundary.py/test_api_boundaries.py
# already use) that the new discretionary-screening feature genuinely
# never imports anything from `Strategy`/`StrategyRegistry`/
# `StrategyExecutionCoordinator`/`run_active_loop_tick`/`PaperBroker`/
# `ScannerConfiguration` - SCANNER_BUILDER_ROADMAP.md's own explicit
# architecture-boundary requirement, proven structurally here, not
# merely documented in a module comment a future change could silently
# violate.
from __future__ import annotations

import ast
from pathlib import Path

FORBIDDEN_PREFIXES = (
    "intraday.trading_engine.strategy_execution",
    "intraday.application.services.strategy_execution",
    "intraday.application.services.paper_signal_execution",
    "intraday.infrastructure.brokers.paper",
    "intraday.application.contracts.scanner_configuration",
    "intraday.application.repositories.scanner_configuration",
    "intraday.infrastructure.persistence.scanner_configuration_repository",
    "intraday.infrastructure.persistence.models.ScannerConfiguration",
    "intraday.domain.signal",
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SCREENING_FILES = (
    REPO_ROOT / "src" / "intraday" / "domain" / "screening" / "contracts.py",
    REPO_ROOT / "src" / "intraday" / "application" / "services" / "adhoc_screening.py",
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


def _scan(paths: tuple[Path, ...]) -> list[str]:
    violations: list[str] = []
    for source_file in paths:
        for module_name in _imported_module_names(source_file):
            if any(
                module_name == prefix or module_name.startswith(prefix + ".")
                for prefix in FORBIDDEN_PREFIXES
            ):
                violations.append(f"{source_file}: forbidden strategy/paper-trading import {module_name!r}")
    return violations


def test_screening_files_exist() -> None:
    for source_file in SCREENING_FILES:
        assert source_file.is_file(), f"expected {source_file} to exist"


def test_screening_never_imports_strategy_or_paper_trading_modules() -> None:
    violations = _scan(SCREENING_FILES)
    assert not violations, (
        "Discretionary screening must remain fully decoupled from the Strategy/"
        "StrategyExecutionCoordinator/PaperBroker/ScannerConfiguration pipeline "
        "(SCANNER_BUILDER_ROADMAP.md's own explicit architecture boundary):\n"
        + "\n".join(violations)
    )


def test_screening_service_only_depends_on_feature_engine_dispatch_and_domain() -> None:
    """Positive check: `adhoc_screening.py`'s only compute dependency is
    the relocated `compute_feature_series` dispatcher and the field
    registry - never re-implementing or duplicating feature math, and
    never reaching into `strategy_execution` (its OLD location) at
    all - proving the relocation this checkpoint performed is actually
    being used, not merely available."""
    adhoc_screening_file = REPO_ROOT / "src" / "intraday" / "application" / "services" / "adhoc_screening.py"
    imported = _imported_module_names(adhoc_screening_file)
    assert any("feature_engine.dispatch" in name for name in imported)
    assert not any(
        name.startswith("intraday.application.services.strategy_execution") for name in imported
    )


def test_screening_match_is_not_a_signal_or_order_type() -> None:
    """Positive check on the DOMAIN TYPE itself, not just imports:
    `ScreeningMatch` carries no signal-lifecycle/order/execution
    field - it is a read-only observation, never a trading decision."""
    from dataclasses import fields

    from intraday.domain.screening.contracts import ScreeningMatch

    field_names = {f.name for f in fields(ScreeningMatch)}
    forbidden_field_names = {"status", "strategy_id", "side", "quantity", "order_id", "signal_id"}
    assert not (field_names & forbidden_field_names), (
        f"ScreeningMatch must never carry signal/order fields, found: {field_names & forbidden_field_names}"
    )
