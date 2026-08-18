# File: src/intraday/application/services/strategy_configuration.py
#
# Checkpoint 26: application-layer orchestration for strategy
# configuration values. Sits between the API layer and:
#   - `trading_engine.strategy_execution.registry.StrategyRegistry`
#     (authoritative list of executable strategies + their schemas)
#   - `signal_intelligence.feature_engine.field_registry`
#     (authoritative field/feature list, for FIELD_REFERENCE validation)
#   - `application.repositories.StrategyConfigurationRepository`
#     (persistence of validated values)
#
# Deliberately does NOT read Django, env vars, or the ORM directly - only
# the injected repository Protocol, matching every other application
# service in this codebase (`StrategyVersionService`, `RiskConfigurationService`).
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass

from intraday.application.config_schema.records import StrategyConfigurationSnapshot
from intraday.application.repositories import StrategyConfigurationRepository
from intraday.application.services.errors import ResourceNotFoundError
from intraday.signal_intelligence.feature_engine.field_registry import list_fields
from intraday.trading_engine.strategy_execution.contracts import (
    coerce_configuration_values,
    validate_configuration,
)
from intraday.trading_engine.strategy_execution.registry import StrategyRegistry


@dataclass
class StrategyConfigurationService:
    repository: StrategyConfigurationRepository
    registry: StrategyRegistry

    def _known_field_ids(self) -> frozenset[str]:
        return frozenset(f.field_id for f in list_fields())

    def save_configuration(
        self,
        strategy_id: str,
        specification_version: str,
        code_version: str,
        configuration_version: str,
        values: dict[str, object],
        *,
        created_by: str,
    ) -> StrategyConfigurationSnapshot:
        """Validates `values` against the strategy's own parameter
        schema (single canonical validation path -
        `trading_engine.strategy_execution.contracts.validate_configuration`,
        never duplicated here), then persists an immutable snapshot.
        Raises whatever `validate_configuration` raises on an invalid
        value, and `DuplicateVersionError` if this exact identity already
        exists (Part 11/12: configurations are immutable once saved)."""
        strategy = self.registry.get(strategy_id)  # raises UnknownStrategyError if absent
        schema = strategy.parameter_schema()
        # Same real bug found and fixed in application.services.backtesting
        # - `values` arrives here straight from an API request (JSON has
        # no native Decimal type), so a DECIMAL-typed parameter is still
        # a bare str/float at this point. Coerce ONLY for validation -
        # `parameter_values` below is persisted through a plain
        # `models.JSONField` with no Decimal-aware encoder, so the
        # ORIGINAL, JSON-safe `values` (never the coerced Decimal
        # objects) is what actually gets stored; a Decimal would raise
        # its own, separate "not JSON serializable" error at save time.
        coerced_values = coerce_configuration_values(schema, values)
        validate_configuration(schema, coerced_values, known_field_ids=self._known_field_ids())

        snapshot = StrategyConfigurationSnapshot(
            strategy_id=strategy_id,
            specification_version=specification_version,
            code_version=code_version,
            configuration_version=configuration_version,
            parameter_values=values,
            created_at=_dt.datetime.now(tz=_dt.UTC),
            created_by=created_by,
        )
        self.repository.save(snapshot)
        return snapshot

    def get_configuration(
        self,
        strategy_id: str,
        specification_version: str,
        code_version: str,
        configuration_version: str,
    ) -> StrategyConfigurationSnapshot:
        snapshot = self.repository.get(
            strategy_id, specification_version, code_version, configuration_version
        )
        if snapshot is None:
            raise ResourceNotFoundError(
                f"no configuration found for {strategy_id!r} "
                f"{specification_version}:{code_version}:{configuration_version}"
            )
        return snapshot

    def list_configurations(self, strategy_id: str) -> tuple[StrategyConfigurationSnapshot, ...]:
        self.registry.get(strategy_id)  # raises UnknownStrategyError if absent
        return self.repository.list_for_strategy(strategy_id)
