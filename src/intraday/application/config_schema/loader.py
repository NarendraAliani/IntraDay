# File: src/intraday/application/config_schema/loader.py
#
# Generic YAML-file-to-dict loading for configuration instances
# (Checkpoint 6). Deliberately minimal: reads and parses YAML only — it
# does NOT know about any specific domain contract; that is each schema
# module's (risk.py / universe.py / strategy.py) job. No database
# connection, no network access, no infrastructure dependency — this is
# local file I/O only, analogous to how Django's own settings modules
# read local files, not a persistence-technology adapter.
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_yaml_config(path: Path) -> dict[str, Any]:
    """Read and parse one YAML config file into a plain dict.

    Raises `FileNotFoundError` or `yaml.YAMLError` on missing/malformed
    input — callers (risk.py, universe.py, strategy.py) are responsible
    for turning that into a `ConfigValidationError` with contract-specific
    context, so this function stays contract-agnostic.
    """
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(
            f"{path}: expected a YAML mapping at the top level, got {type(data).__name__}"
        )
    return data
