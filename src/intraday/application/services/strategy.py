# File: src/intraday/application/services/strategy.py
#
# Strategy-version application service (Checkpoint 8). See risk.py for
# the design rationale this mirrors. Identity here is the 3-tuple
# (specification_version, code_version, configuration_version), matching
# domain.strategy.StrategyVersion's own shape (Checkpoint 5).
from __future__ import annotations

from dataclasses import dataclass

from intraday.application.config_schema.records import StrategyVersionSnapshot
from intraday.application.repositories import StrategyVersionRepository
from intraday.application.services.errors import (
    InvalidActivationRequestError,
    ResourceNotFoundError,
)


@dataclass(frozen=True, slots=True)
class StrategyVersionService:
    repository: StrategyVersionRepository

    def get_version(
        self,
        strategy_id: str,
        specification_version: str,
        code_version: str,
        configuration_version: str,
    ) -> StrategyVersionSnapshot:
        snapshot = self.repository.get_version(
            strategy_id, specification_version, code_version, configuration_version
        )
        if snapshot is None:
            raise ResourceNotFoundError(
                f"strategy {strategy_id!r} has no version "
                f"({specification_version!r}, {code_version!r}, {configuration_version!r})"
            )
        return snapshot

    def list_versions(self, strategy_id: str) -> tuple[StrategyVersionSnapshot, ...]:
        return self.repository.list_versions(strategy_id)

    def get_active(self, strategy_id: str) -> StrategyVersionSnapshot:
        snapshot = self.repository.get_active(strategy_id)
        if snapshot is None:
            raise ResourceNotFoundError(f"strategy {strategy_id!r} has no active version")
        return snapshot

    def activate(
        self,
        strategy_id: str,
        specification_version: str,
        code_version: str,
        configuration_version: str,
        *,
        actor: str,
        actor_user_id: int,
        request_id: str,
    ) -> StrategyVersionSnapshot:
        """`actor`/`actor_user_id`/`request_id` (Checkpoint 13) are
        required, never optional or defaulted — see
        `RiskConfigurationService.activate()`'s docstring for the
        rationale this mirrors."""
        try:
            self.repository.activate(
                strategy_id,
                specification_version,
                code_version,
                configuration_version,
                actor=actor,
                actor_user_id=actor_user_id,
                request_id=request_id,
            )
        except ValueError as exc:
            raise InvalidActivationRequestError(str(exc)) from exc
        return self.get_version(
            strategy_id, specification_version, code_version, configuration_version
        )
