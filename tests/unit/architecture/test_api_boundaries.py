# tests/unit/architecture/test_api_boundaries.py
#
# Supplementary architecture tests (Checkpoint 8 §17): confirms the API
# delivery layer does not import Django models directly, and that
# application/services and application/contracts stay infrastructure-free
# — re-verifying, at the API layer, the same discipline Checkpoint 7's
# test_persistence_boundaries.py established for the domain layer. Static
# analysis only — no database, no Django test client, always runs.
from __future__ import annotations

import ast
from pathlib import Path

API_VIEW_FILES = (
    "risk_views.py",
    "universe_views.py",
    "strategy_views.py",
)

API_PACKAGE = Path(__file__).resolve().parents[3] / "src" / "intraday" / "infrastructure" / "api"
APPLICATION_SERVICES = (
    Path(__file__).resolve().parents[3] / "src" / "intraday" / "application" / "services"
)
APPLICATION_CONTRACTS = (
    Path(__file__).resolve().parents[3] / "src" / "intraday" / "application" / "contracts"
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


def test_api_views_never_import_persistence_models_directly() -> None:
    """Views must go through infrastructure.persistence.repositories (the
    repository implementations), never touch
    infrastructure.persistence.models directly — that would put ORM/query
    logic in the delivery layer (Checkpoint 8 §2)."""
    violations: list[str] = []
    for filename in API_VIEW_FILES:
        source_file = API_PACKAGE / filename
        assert source_file.is_file(), f"expected {source_file} to exist"
        for module_name in _imported_module_names(source_file):
            if (
                module_name == "intraday.infrastructure.persistence.models"
                or module_name.startswith("intraday.infrastructure.persistence.models.")
            ):
                violations.append(f"{source_file}: imports Django models directly: {module_name}")
    assert not violations, "\n".join(violations)


def test_application_services_and_contracts_stay_infrastructure_free() -> None:
    """Belt-and-suspenders re-check of `.importlinter` contract #6
    ('application must not depend on infrastructure') at the specific
    subpackages Checkpoint 8 added."""
    violations: list[str] = []
    for package in (APPLICATION_SERVICES, APPLICATION_CONTRACTS):
        assert package.is_dir(), f"expected {package} to exist"
        for source_file in package.rglob("*.py"):
            for module_name in _imported_module_names(source_file):
                if module_name.split(".")[:2] == ["intraday", "infrastructure"]:
                    violations.append(f"{source_file}: imports infrastructure: {module_name}")
    assert not violations, "\n".join(violations)
