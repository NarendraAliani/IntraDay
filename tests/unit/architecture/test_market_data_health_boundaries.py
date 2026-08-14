# tests/unit/architecture/test_market_data_health_boundaries.py
#
# Supplementary architecture test (Checkpoint 23). `.importlinter`
# already mechanically enforces (contracts #1/#2/#4) that
# intraday.control_plane may not depend on infrastructure or on other
# bounded contexts (signal_intelligence, trading_engine, research,
# communication). This test independently re-verifies, by statically
# scanning source files with `ast` (same technique as the
# signal_intelligence checkpoints' own boundary tests), the SPECIFIC
# claim Checkpoint 23 exists to prove: `control_plane.market_data_health`
# is genuinely supervisory-only - it never imports a signal, order,
# trading-engine, or broker-order-placement module, and calls no live
# HTTP/Dhan/infrastructure code (it is pure).
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

MARKET_DATA_HEALTH_PACKAGE = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "intraday"
    / "control_plane"
    / "market_data_health"
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


def test_market_data_health_package_exists() -> None:
    assert (
        MARKET_DATA_HEALTH_PACKAGE.is_dir()
    ), "expected src/intraday/control_plane/market_data_health to exist"


def test_market_data_health_never_imports_trading_signal_or_infrastructure_code() -> None:
    """The core architectural claim of Checkpoint 23: market-data health
    is a pure, supervisory classifier - it never imports infrastructure
    (no HTTP, no Django, no Dhan), never imports trading_engine, and
    never imports signal_intelligence (Checkpoint 23 §13's "signals
    must remain off")."""
    violations: list[str] = []
    for source_file in MARKET_DATA_HEALTH_PACKAGE.rglob("*.py"):
        for module_name in _imported_module_names(source_file):
            if any(
                module_name == prefix or module_name.startswith(prefix + ".")
                for prefix in FORBIDDEN_PREFIXES
            ):
                violations.append(f"{source_file}: forbidden import of {module_name!r}")

    assert not violations, (
        "control_plane.market_data_health must not import infrastructure, "
        "trading_engine, signal_intelligence, communication, or research:\n" + "\n".join(violations)
    )


def test_market_data_health_only_imports_domain_session_and_shared_kernel() -> None:
    """Positive check: the only `intraday.domain.*` import this package
    needs is `domain.session` (for `SessionStatus`)."""
    allowed_domain_prefixes = ("intraday.domain.session", "intraday.domain.shared_kernel")
    violations: list[str] = []
    for source_file in MARKET_DATA_HEALTH_PACKAGE.rglob("*.py"):
        for module_name in _imported_module_names(source_file):
            if module_name.startswith("intraday.domain") and not any(
                module_name == prefix or module_name.startswith(prefix + ".")
                for prefix in allowed_domain_prefixes
            ):
                violations.append(f"{source_file}: unexpected domain import {module_name!r}")

    assert not violations, "\n".join(violations)
