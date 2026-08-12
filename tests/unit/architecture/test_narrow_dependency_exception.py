# tests/unit/architecture/test_narrow_dependency_exception.py
#
# Supplementary architecture test (Checkpoint 4 §17). `.importlinter`
# already mechanically enforces, at CI time, that
# intraday.research.backtesting may depend on
# intraday.trading_engine.strategy_execution and nothing else inside
# trading_engine (contract #5). This test independently re-verifies the
# same invariant by statically scanning source files with the standard
# library `ast` module, as a second, tool-independent guard against the
# rule silently regressing if the import-linter config is ever edited
# incorrectly. Contains no business logic.
from __future__ import annotations

import ast
from pathlib import Path

FORBIDDEN_TRADING_ENGINE_SUBMODULES = {
    "risk_engine",
    "order_management",
    "execution_management",
    "broker_abstraction",
    "session_management",
}

BACKTESTING_PACKAGE = (
    Path(__file__).resolve().parents[3] / "src" / "intraday" / "research" / "backtesting"
)


def _imported_module_names(source_file: Path) -> set[str]:
    """Return every fully-qualified module path this file's import
    statements could plausibly reference.

    Handles both `import a.b.c` and `from a.b import c` — the latter must
    also contribute `a.b.c` as a candidate, since `from intraday.trading_engine
    import risk_engine` imports the *submodule* `risk_engine`, not merely a
    name from within `trading_engine`'s own namespace. Missing this form was
    caught by an adversarial test run during Checkpoint 4 (see
    taskReport.md's Checkpoint 4 "Known Issues / Deferred Items" for the
    record of that finding) — this function was fixed in response.
    """
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


def test_backtesting_package_exists() -> None:
    assert BACKTESTING_PACKAGE.is_dir(), "expected src/intraday/research/backtesting to exist"


def test_backtesting_does_not_import_forbidden_trading_engine_submodules() -> None:
    violations: list[str] = []
    for source_file in BACKTESTING_PACKAGE.rglob("*.py"):
        for module_name in _imported_module_names(source_file):
            if not module_name.startswith("intraday.trading_engine"):
                continue
            remainder = module_name.removeprefix("intraday.trading_engine.")
            submodule = remainder.split(".")[0] if remainder else ""
            if submodule in FORBIDDEN_TRADING_ENGINE_SUBMODULES:
                violations.append(f"{source_file}: forbidden import of {module_name!r}")

    assert not violations, (
        "research.backtesting must not import these trading_engine internals "
        "(only trading_engine.strategy_execution is permitted):\n" + "\n".join(violations)
    )


def test_backtesting_only_imports_strategy_execution_from_trading_engine() -> None:
    """Positive check: if backtesting imports trading_engine at all, it must
    be exactly the strategy_execution submodule — catches accidental typos
    or refactors that would otherwise slip past the forbidden-list check
    above (e.g. a new trading_engine submodule the forbidden list doesn't
    know about yet)."""
    allowed_prefix = "intraday.trading_engine.strategy_execution"
    allowed_exact = "intraday.trading_engine"  # importing the parent package itself is fine

    violations: list[str] = []
    for source_file in BACKTESTING_PACKAGE.rglob("*.py"):
        for module_name in _imported_module_names(source_file):
            if not module_name.startswith("intraday.trading_engine"):
                continue
            if module_name == allowed_exact or module_name.startswith(allowed_prefix):
                continue
            violations.append(f"{source_file}: unexpected trading_engine import {module_name!r}")

    assert not violations, "\n".join(violations)
