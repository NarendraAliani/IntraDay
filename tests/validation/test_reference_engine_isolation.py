# tests/validation/test_reference_engine_isolation.py
#
# Checkpoint 30 Part 19: proves `tests.validation.reference_engine`
# never becomes a second production engine - no `src/intraday` module
# imports it, mechanically verified (ast-based scan, matching this
# project's established architecture-boundary-test pattern).
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src" / "intraday"


def _imported_module_names(source_file: Path) -> set[str]:
    tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_no_src_module_imports_the_reference_engine() -> None:
    violations: list[str] = []
    for source_file in SRC_ROOT.rglob("*.py"):
        for module_name in _imported_module_names(source_file):
            if "reference_engine" in module_name or module_name.startswith("tests."):
                violations.append(f"{source_file}: imports {module_name!r}")
    assert not violations, (
        "reference_engine.py must remain test-only, never imported by src/intraday:\n"
        + "\n".join(violations)
    )


def test_reference_engine_does_not_import_the_production_engine() -> None:
    """The independent reference must not secretly delegate to the real
    engine - proves the two code paths are genuinely separate."""
    reference_file = Path(__file__).resolve().parent / "reference_engine.py"
    imported = _imported_module_names(reference_file)
    assert not any("research.backtesting" in name for name in imported)
    assert not any(name.startswith("intraday") for name in imported)
