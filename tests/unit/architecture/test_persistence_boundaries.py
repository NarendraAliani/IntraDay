# tests/unit/architecture/test_persistence_boundaries.py
#
# Supplementary architecture tests (Checkpoint 7 §22): confirms the
# domain layer remains ORM-free/infrastructure-free even after the
# persistence foundation was added, and that repository interfaces stay
# technology-neutral. Static analysis only — no database, no Django test
# client, always runs regardless of PostgreSQL availability.
from __future__ import annotations

import ast
from pathlib import Path

DOMAIN_PACKAGE = Path(__file__).resolve().parents[3] / "src" / "intraday" / "domain"
APPLICATION_REPOSITORIES = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "intraday"
    / "application"
    / "repositories"
    / "__init__.py"
)

FORBIDDEN_DOMAIN_IMPORT_PREFIXES = (
    "django",
    "rest_framework",
    "psycopg",
    "celery",
    "redis",
    "channels",
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


def test_domain_package_exists() -> None:
    assert DOMAIN_PACKAGE.is_dir()


def test_domain_remains_orm_and_infrastructure_free() -> None:
    """Re-verifies, after Checkpoint 7's persistence foundation was
    added, that no domain contract module imports Django, DRF, psycopg,
    Celery, Redis, or Channels — the same guarantee Checkpoint 5
    established, now re-checked as a regression guard."""
    violations: list[str] = []
    for source_file in DOMAIN_PACKAGE.rglob("*.py"):
        for module_name in _imported_module_names(source_file):
            if module_name.split(".")[0] in FORBIDDEN_DOMAIN_IMPORT_PREFIXES:
                violations.append(f"{source_file}: forbidden import of {module_name!r}")

    assert not violations, "domain/ must remain ORM- and infrastructure-free:\n" + "\n".join(
        violations
    )


def test_repository_interfaces_do_not_import_django() -> None:
    """The Protocol interfaces in application/repositories must stay
    technology-neutral — no Django import, no QuerySet/Model reference."""
    assert APPLICATION_REPOSITORIES.is_file()
    module_names = _imported_module_names(APPLICATION_REPOSITORIES)
    forbidden = {name for name in module_names if name.split(".")[0] == "django"}
    assert not forbidden, f"application/repositories must not import Django: {forbidden}"


def test_repository_interfaces_are_structural_protocols() -> None:
    """Every method on the three repository Protocols must be a stub
    (`...` body) — the interface defines, infrastructure implements."""
    source = APPLICATION_REPOSITORIES.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(APPLICATION_REPOSITORIES))
    protocol_classes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
        and any(isinstance(base, ast.Name) and base.id == "Protocol" for base in node.bases)
    ]
    assert protocol_classes, "expected at least one Protocol-based repository interface"
    for cls in protocol_classes:
        for item in cls.body:
            if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                assert len(item.body) == 1 and isinstance(
                    item.body[0], ast.Expr
                ), f"{cls.name}.{item.name} must be a stub (`...` body), not implemented"
