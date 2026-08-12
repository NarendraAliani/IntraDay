# File: src/intraday/application/config_schema/strategy.py
#
# Config schema and loader for domain.strategy.StrategyVersion
# (Checkpoint 6).
#
# Deliberately scoped: only the version/lineage/maturity shape is
# configurable here. Strategy PARAMETERS (e.g. indicator periods, entry
# thresholds) are NOT represented — no domain contract models them yet
# (Checkpoint 5 implemented only StrategyIdentity/StrategyVersion/
# StrategyMaturityState, not a parameter set). Inventing a generic
# "parameters" schema now would be exactly the "field not justified by
# current requirements" mistake Checkpoints 5 and 6 both warn against —
# that belongs to whichever future checkpoint first defines a concrete
# strategy specification shape.
from __future__ import annotations

from typing import Any

from intraday.application.config_schema.errors import ConfigValidationError
from intraday.application.config_schema.schema import ConfigSchema, build_schema_for
from intraday.domain.shared_kernel.contracts import Timeframe, Version
from intraday.domain.strategy.contracts import StrategyMaturityState, StrategyVersion

STRATEGY_VERSION_SCHEMA: ConfigSchema = build_schema_for(StrategyVersion)


def load_strategy_version(raw: dict[str, Any], *, source: str = "<config>") -> StrategyVersion:
    try:
        return StrategyVersion(
            strategy_id=raw["strategy_id"],
            specification_version=Version(value=raw["specification_version"]),
            code_version=Version(value=raw["code_version"]),
            configuration_version=Version(value=raw["configuration_version"]),
            universe_version=Version(value=raw["universe_version"]),
            timeframe=Timeframe(raw["timeframe"]),
            maturity_state=StrategyMaturityState(raw["maturity_state"]),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise ConfigValidationError(source=source, original=exc) from exc
