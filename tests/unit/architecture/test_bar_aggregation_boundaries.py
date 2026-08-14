# tests/unit/architecture/test_bar_aggregation_boundaries.py
#
# Supplementary architecture test (Checkpoint 24A). `.importlinter`
# already mechanically enforces the layering; this test independently
# re-verifies, via `ast`-based static scanning (same technique as every
# prior checkpoint's own boundary tests), the SPECIFIC claims CP24A
# makes: the aggregation domain module is pure (no infrastructure, no
# Django, no HTTP), and neither it nor the application service imports
# signal_intelligence or trading_engine - bars are NOT wired to signals
# or orders this checkpoint (Checkpoint 24A §15).
from __future__ import annotations

import ast
from pathlib import Path

FORBIDDEN_PREFIXES = (
    "django",
    "rest_framework",
    "httpx",
    "celery",
    "psycopg",
    "redis",
    "intraday.infrastructure",
    "intraday.trading_engine",
    "intraday.signal_intelligence",
    "intraday.communication",
    "intraday.research",
)

AGGREGATION_MODULE = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "intraday"
    / "domain"
    / "market_data"
    / "aggregation.py"
)
BAR_SERVICE_MODULE = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "intraday"
    / "application"
    / "services"
    / "bar_aggregation.py"
)
BAR_REPOSITORY_PROTOCOL_MODULE = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "intraday"
    / "application"
    / "repositories"
    / "live_market_data.py"
)


def _imported_module_names(source_file: Path) -> set[str]:
    tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_aggregation_and_bar_service_modules_exist() -> None:
    assert AGGREGATION_MODULE.is_file()
    assert BAR_SERVICE_MODULE.is_file()


def test_aggregation_module_is_pure_no_infrastructure_django_or_http() -> None:
    violations: list[str] = []
    for module_name in _imported_module_names(AGGREGATION_MODULE):
        if any(
            module_name == prefix or module_name.startswith(prefix + ".")
            for prefix in FORBIDDEN_PREFIXES
        ):
            violations.append(f"forbidden import of {module_name!r}")

    assert not violations, (
        "domain/market_data/aggregation.py must be pure - no infrastructure, "
        "Django, HTTP, or other bounded-context import:\n" + "\n".join(violations)
    )


def test_bar_aggregation_service_never_imports_infrastructure_trading_or_signal_code() -> None:
    violations: list[str] = []
    for module_name in _imported_module_names(BAR_SERVICE_MODULE):
        if any(
            module_name == prefix or module_name.startswith(prefix + ".")
            for prefix in FORBIDDEN_PREFIXES
        ):
            violations.append(f"forbidden import of {module_name!r}")

    assert not violations, (
        "application/services/bar_aggregation.py must not import infrastructure, "
        "trading_engine, or signal_intelligence (Checkpoint 24A - bars are not "
        "wired to signals or orders this checkpoint):\n" + "\n".join(violations)
    )


def test_bars_are_not_wired_to_signal_generation_anywhere() -> None:
    """The core claim of Checkpoint 24A §15: no file this checkpoint
    touches imports signal_intelligence.signal_generation."""
    checked_files = [AGGREGATION_MODULE, BAR_SERVICE_MODULE, BAR_REPOSITORY_PROTOCOL_MODULE]
    violations: list[str] = []
    for source_file in checked_files:
        for module_name in _imported_module_names(source_file):
            if "signal_intelligence" in module_name:
                violations.append(f"{source_file}: unexpected import of {module_name!r}")

    assert not violations, "\n".join(violations)
