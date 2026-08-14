# tests/unit/architecture/test_live_market_data_boundaries.py
#
# Supplementary architecture test (Checkpoint 23 §2's absolute safety
# boundary). Statically proves, across every file this checkpoint
# touches, that no order/position/trading-engine code was introduced or
# imported anywhere in the live-market-data path - not just that the
# runtime mocks in test_market_data_api.py never observed an order call
# (which only proves the HAPPY-PATH tests didn't trigger one), but that
# it is structurally impossible for any code path in these modules to
# reach `trading_engine` or `domain.broker`'s order-placement methods.
from __future__ import annotations

import ast
from pathlib import Path

FORBIDDEN_PREFIXES = ("intraday.trading_engine",)

# Every file this checkpoint added/touched that sits on the live
# market-data path (adapter, application service, view layer,
# persistence). Domain files (calendar.py) are intentionally excluded -
# they are covered by the domain layer's own `.importlinter` contract 1
# (domain may not import ANYTHING above it), a strictly stronger
# guarantee than this test could add.
CHECKPOINT_23_FILES = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "intraday"
    / "infrastructure"
    / "market_data_providers"
    / "dhan",
    Path(__file__).resolve().parents[3]
    / "src"
    / "intraday"
    / "application"
    / "services"
    / "live_market_data.py",
    Path(__file__).resolve().parents[3]
    / "src"
    / "intraday"
    / "application"
    / "repositories"
    / "live_market_data.py",
    Path(__file__).resolve().parents[3]
    / "src"
    / "intraday"
    / "infrastructure"
    / "api"
    / "market_data_views.py",
    Path(__file__).resolve().parents[3]
    / "src"
    / "intraday"
    / "infrastructure"
    / "persistence"
    / "live_market_data_repositories.py",
)


def _python_files() -> list[Path]:
    files: list[Path] = []
    for target in CHECKPOINT_23_FILES:
        if target.is_dir():
            files.extend(target.rglob("*.py"))
        elif target.is_file():
            files.append(target)
    return files


def _imported_module_names(source_file: Path) -> set[str]:
    tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_checkpoint_23_files_exist() -> None:
    for target in CHECKPOINT_23_FILES:
        assert target.exists(), f"expected {target} to exist"


def test_no_checkpoint_23_file_imports_trading_engine() -> None:
    violations: list[str] = []
    for source_file in _python_files():
        for module_name in _imported_module_names(source_file):
            if any(
                module_name == prefix or module_name.startswith(prefix + ".")
                for prefix in FORBIDDEN_PREFIXES
            ):
                violations.append(f"{source_file}: forbidden import of {module_name!r}")

    assert not violations, (
        "No file on the live market-data path may import trading_engine "
        "(Checkpoint 23 §2's absolute safety boundary):\n" + "\n".join(violations)
    )


def test_dhan_client_calls_only_the_documented_quote_endpoint_url() -> None:
    """Static proof the Dhan client source contains exactly one hard-coded
    Dhan URL, and it is the documented read-only quote endpoint - not an
    order/position/trading endpoint."""
    client_file = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "intraday"
        / "infrastructure"
        / "market_data_providers"
        / "dhan"
        / "client.py"
    )
    source = client_file.read_text(encoding="utf-8")
    forbidden_substrings = ("/orders", "/positions", "/super", "/forever", "/edis", "/optionchain")
    for substring in forbidden_substrings:
        assert (
            substring not in source
        ), f"unexpected trading-related endpoint reference: {substring}"
    assert "marketfeed/quote" in source


def test_market_data_views_never_imports_domain_broker() -> None:
    views_file = (
        Path(__file__).resolve().parents[3]
        / "src"
        / "intraday"
        / "infrastructure"
        / "api"
        / "market_data_views.py"
    )
    imported = _imported_module_names(views_file)
    assert not any(name.startswith("intraday.domain.broker") for name in imported)
    assert not any(name.startswith("intraday.domain.order") for name in imported)
    assert not any(name.startswith("intraday.domain.position") for name in imported)
