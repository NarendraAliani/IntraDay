# File: src/intraday/application/services/universe.py
#
# Universe application service (Checkpoint 8). See risk.py for the
# design rationale this mirrors.
from __future__ import annotations

from dataclasses import dataclass

from intraday.application.config_schema.records import UniverseRecord
from intraday.application.repositories import UniverseRepository
from intraday.application.services.errors import (
    InvalidActivationRequestError,
    ResourceNotFoundError,
)


@dataclass(frozen=True, slots=True)
class UniverseService:
    repository: UniverseRepository

    def get_version(self, universe_id: str, version: str) -> UniverseRecord:
        record = self.repository.get_version(universe_id, version)
        if record is None:
            raise ResourceNotFoundError(f"universe {universe_id!r} has no version {version!r}")
        return record

    def list_versions(self, universe_id: str) -> tuple[UniverseRecord, ...]:
        return self.repository.list_versions(universe_id)

    def get_active(self, universe_id: str) -> UniverseRecord:
        record = self.repository.get_active(universe_id)
        if record is None:
            raise ResourceNotFoundError(f"universe {universe_id!r} has no active version")
        return record

    def activate(
        self, universe_id: str, version: str, *, actor: str, actor_user_id: int, request_id: str
    ) -> UniverseRecord:
        """`actor`/`actor_user_id`/`request_id` (Checkpoint 13) are
        required, never optional or defaulted — see
        `RiskConfigurationService.activate()`'s docstring for the
        rationale this mirrors."""
        try:
            self.repository.activate(
                universe_id,
                version,
                actor=actor,
                actor_user_id=actor_user_id,
                request_id=request_id,
            )
        except ValueError as exc:
            raise InvalidActivationRequestError(str(exc)) from exc
        return self.get_version(universe_id, version)
