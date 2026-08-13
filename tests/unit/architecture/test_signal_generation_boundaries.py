# tests/unit/architecture/test_signal_generation_boundaries.py
#
# Supplementary architecture test (Checkpoint 18 §19). `.importlinter`
# already mechanically enforces (contract #1/#2) that
# intraday.signal_intelligence may not depend on
# intraday.infrastructure/Django/etc. This test independently
# re-verifies, by statically scanning source files with the standard
# library `ast` module (same technique as
# test_narrow_dependency_exception.py, Checkpoint 4 §17), the SPECIFIC
# architectural point Checkpoint 18 exists to prove: that
# `signal_intelligence.signal_generation` consumes `FeatureValue`/`Bar`
# (domain-level outputs) and never imports
# `signal_intelligence.feature_engine`'s own compute functions/module -
# "the feature engine owns computation, signal generation owns
# interpretation" is a real, checked boundary, not just an assertion in
# a docstring.
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
)

SIGNAL_GENERATION_PACKAGE = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "intraday"
    / "signal_intelligence"
    / "signal_generation"
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


def test_signal_generation_package_exists() -> None:
    assert (
        SIGNAL_GENERATION_PACKAGE.is_dir()
    ), "expected src/intraday/signal_intelligence/signal_generation to exist"


def test_signal_generation_never_imports_feature_engine_or_infrastructure() -> None:
    """The core architectural claim of Checkpoint 18: Signal Generation
    consumes `FeatureValue`/`Bar` (already-computed domain outputs) -
    never `signal_intelligence.feature_engine`'s own compute functions,
    and never any infrastructure/framework module. Only
    `application/services/signal_generation.py` (a different layer) is
    permitted to import `feature_engine`, to compose it with
    `SignalGenerationService` - this test scans only the bounded
    context's own package, not application/."""
    violations: list[str] = []
    for source_file in SIGNAL_GENERATION_PACKAGE.rglob("*.py"):
        for module_name in _imported_module_names(source_file):
            if any(
                module_name == prefix or module_name.startswith(prefix + ".")
                for prefix in FORBIDDEN_PREFIXES
            ):
                violations.append(f"{source_file}: forbidden import of {module_name!r}")

    assert not violations, (
        "signal_intelligence.signal_generation must not import feature_engine "
        "or any infrastructure/framework module:\n" + "\n".join(violations)
    )


def test_signal_generation_only_imports_domain_feature_and_market_data() -> None:
    """Positive check: every `intraday.domain.*` import from this
    package must be exactly `domain.feature`/`domain.market_data`/
    `domain.shared_kernel` - catches an accidental new domain dependency
    that the forbidden-list check above would not know to reject."""
    allowed_domain_prefixes = (
        "intraday.domain.feature",
        "intraday.domain.market_data",
        "intraday.domain.shared_kernel",
    )
    violations: list[str] = []
    for source_file in SIGNAL_GENERATION_PACKAGE.rglob("*.py"):
        for module_name in _imported_module_names(source_file):
            if not module_name.startswith("intraday.domain"):
                continue
            if any(
                module_name == prefix or module_name.startswith(prefix + ".")
                for prefix in allowed_domain_prefixes
            ):
                continue
            violations.append(f"{source_file}: unexpected domain import {module_name!r}")

    assert not violations, "\n".join(violations)
