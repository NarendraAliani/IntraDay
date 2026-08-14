# tests/unit/documentation/test_user_guide.py
#
# Checkpoint 25: thin pytest wrapper around
# docs/user-guide/validate.py, so the digital tutorial guide's own
# lightweight validation runs as part of the normal `pytest` suite
# (and therefore CI) without duplicating its logic here. Deliberately
# does not re-implement the checks - imports and calls the real
# validation module directly.
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

GUIDE_DIR = Path(__file__).resolve().parents[3] / "docs" / "user-guide"
VALIDATE_MODULE_PATH = GUIDE_DIR / "validate.py"


def _load_validate_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("user_guide_validate", VALIDATE_MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["user_guide_validate"] = module
    spec.loader.exec_module(module)
    return module


def test_user_guide_directory_exists() -> None:
    assert GUIDE_DIR.is_dir(), "expected docs/user-guide to exist"
    assert (GUIDE_DIR / "index.html").is_file()
    assert (GUIDE_DIR / "css" / "style.css").is_file()
    assert (GUIDE_DIR / "js" / "main.js").is_file()


def test_user_guide_validation_passes() -> None:
    """No broken internal links, no missing local assets, no
    credential-shaped strings, no leftover TODO/FIXME markers -
    see docs/user-guide/validate.py for the exact checks."""
    module = _load_validate_module()
    errors = module.validate()

    assert errors == [], "docs/user-guide validation failures:\n" + "\n".join(errors)
