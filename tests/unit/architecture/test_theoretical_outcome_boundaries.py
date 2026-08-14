# tests/unit/architecture/test_theoretical_outcome_boundaries.py
#
# Supplementary architecture test (Checkpoint 21 §34). `.importlinter`
# already mechanically enforces (contract #1/#2) that
# intraday.signal_intelligence may not depend on
# intraday.infrastructure/Django/etc. This test independently
# re-verifies, by statically scanning source files with the standard
# library `ast` module (same technique as Checkpoints 18/19/20's own
# boundary tests), the SPECIFIC architectural point Checkpoint 21
# exists to prove: `signal_intelligence.theoretical_outcome` consumes
# `DirectionalIndication`/`Bar` and never imports `trading_engine`,
# infrastructure, `feature_engine`'s compute internals, `signal_verification`,
# or `signal_lifecycle` - deliberate independence (Checkpoint 21 §21-22).
from __future__ import annotations

import ast
from pathlib import Path

FORBIDDEN_PREFIXES = (
    "django",
    "rest_framework",
    "channels",
    "celery",
    "psycopg",
    "redis",
    "intraday.infrastructure",
    "intraday.trading_engine",
    "intraday.signal_intelligence.feature_engine",
    "intraday.signal_intelligence.signal_verification",
    "intraday.signal_intelligence.signal_lifecycle",
)

THEORETICAL_OUTCOME_PACKAGE = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "intraday"
    / "signal_intelligence"
    / "theoretical_outcome"
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


def test_theoretical_outcome_package_exists() -> None:
    assert (
        THEORETICAL_OUTCOME_PACKAGE.is_dir()
    ), "expected src/intraday/signal_intelligence/theoretical_outcome to exist"


def test_theoretical_outcome_never_imports_sibling_signal_modules_or_infrastructure() -> None:
    """The core architectural claim of Checkpoint 21: Theoretical
    Outcome consumes `DirectionalIndication`/`Bar` and measures price
    excursion independently - never `signal_verification` or
    `signal_lifecycle` (both evaluated and rejected as dependencies -
    see SIGNAL_THEORETICAL_OUTCOME_ARCHITECTURE.md), never
    `trading_engine`, `feature_engine`, or infrastructure."""
    violations: list[str] = []
    for source_file in THEORETICAL_OUTCOME_PACKAGE.rglob("*.py"):
        for module_name in _imported_module_names(source_file):
            if any(
                module_name == prefix or module_name.startswith(prefix + ".")
                for prefix in FORBIDDEN_PREFIXES
            ):
                violations.append(f"{source_file}: forbidden import of {module_name!r}")

    assert not violations, (
        "signal_intelligence.theoretical_outcome must not import signal_verification, "
        "signal_lifecycle, trading_engine, feature_engine, or any infrastructure/"
        "framework module:\n" + "\n".join(violations)
    )


def test_theoretical_outcome_only_imports_domain_market_data_and_signal_generation() -> None:
    """Positive check: every `intraday.domain.*` import must be exactly
    `domain.market_data`/`domain.shared_kernel` (no `domain.signal`),
    and the only `intraday.signal_intelligence.*` import outside this
    package itself must be `signal_intelligence.signal_generation`."""
    allowed_domain_prefixes = ("intraday.domain.market_data", "intraday.domain.shared_kernel")
    allowed_signal_intelligence_prefixes = (
        "intraday.signal_intelligence.signal_generation",
        "intraday.signal_intelligence.theoretical_outcome",
    )
    violations: list[str] = []
    for source_file in THEORETICAL_OUTCOME_PACKAGE.rglob("*.py"):
        for module_name in _imported_module_names(source_file):
            if module_name.startswith("intraday.domain"):
                if not any(
                    module_name == prefix or module_name.startswith(prefix + ".")
                    for prefix in allowed_domain_prefixes
                ):
                    violations.append(f"{source_file}: unexpected domain import {module_name!r}")
            elif module_name.startswith("intraday.signal_intelligence") and not any(
                module_name == prefix or module_name.startswith(prefix + ".")
                for prefix in allowed_signal_intelligence_prefixes
            ):
                violations.append(
                    f"{source_file}: unexpected signal_intelligence import {module_name!r}"
                )

    assert not violations, "\n".join(violations)
