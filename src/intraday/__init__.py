# src/intraday/__init__.py
#
# Root package of the IntraDay platform. Checkpoint 4 (Repository Bootstrap
# & Tooling): this file contains NO business logic. It exists only to:
#   1. Expose the single authoritative application version, read from the
#      installed package's metadata (which is itself sourced from
#      pyproject.toml's [tool.poetry] version field) — never hardcoded here
#      or anywhere else, per Checkpoint 3 §17 (Versioning) and Checkpoint 4
#      §12 ("do not invent a second version source").
#   2. Register the Celery application instance (`celery_app`) so Celery's
#      autodiscovery mechanism can find task modules declared under this
#      package in later checkpoints. No tasks are defined here.
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from .celery import app as celery_app

try:
    __version__ = version("intraday")
except PackageNotFoundError:  # pragma: no cover - only hit outside an installed env
    __version__ = "0.0.0+unknown"

__all__ = ("celery_app", "__version__")
