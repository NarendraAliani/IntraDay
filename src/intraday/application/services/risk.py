# File: src/intraday/application/services/risk.py
#
# Risk-configuration application service (Checkpoint 8) — the use-case
# layer between the API delivery mechanism (infrastructure/api) and the
# repository Protocol (application/repositories). Depends only on
# `RiskConfigurationRepository` (a Protocol) — never on a concrete Django
# implementation, so this class is fully testable with an in-memory fake
# repository (see tests/unit/application/services/).
from __future__ import annotations

from dataclasses import dataclass

from intraday.application.config_schema.records import RiskConfigurationRecord
from intraday.application.repositories import RiskConfigurationRepository
from intraday.application.services.errors import (
    InvalidActivationRequestError,
    ResourceNotFoundError,
)


@dataclass(frozen=True, slots=True)
class RiskConfigurationService:
    """Use cases for the risk-configuration resource. Contains no
    persistence logic and no domain business rules of its own — it only
    orchestrates calls to the injected repository and translates
    "not found"/"invalid" conditions into the application-level
    exceptions the API layer knows how to render."""

    repository: RiskConfigurationRepository

    def get_version(self, configuration_id: str, version: str) -> RiskConfigurationRecord:
        record = self.repository.get_version(configuration_id, version)
        if record is None:
            raise ResourceNotFoundError(
                f"risk configuration {configuration_id!r} has no version {version!r}"
            )
        return record

    def list_versions(self, configuration_id: str) -> tuple[RiskConfigurationRecord, ...]:
        return self.repository.list_versions(configuration_id)

    def get_active(self, configuration_id: str) -> RiskConfigurationRecord:
        record = self.repository.get_active(configuration_id)
        if record is None:
            raise ResourceNotFoundError(
                f"risk configuration {configuration_id!r} has no active version"
            )
        return record

    def activate(
        self,
        configuration_id: str,
        version: str,
        *,
        actor: str,
        actor_user_id: int,
        request_id: str,
    ) -> RiskConfigurationRecord:
        """Idempotent: activating an already-active version simply
        re-confirms it (Checkpoint 8 §8) — `repository.activate()`'s
        `get_or_create` makes this naturally idempotent at the database
        level.

        `actor`/`actor_user_id`/`request_id` (Checkpoint 12) are required,
        never optional or defaulted to a placeholder like `"system"` -
        this service has no anonymous code path (the API view rejects an
        unauthenticated request before this method is ever called), so a
        real caller identity is always available. The repository records
        the resulting audit event atomically with the state change - see
        `RiskConfigurationRepository.activate()`."""
        try:
            self.repository.activate(
                configuration_id,
                version,
                actor=actor,
                actor_user_id=actor_user_id,
                request_id=request_id,
            )
        except ValueError as exc:
            raise InvalidActivationRequestError(str(exc)) from exc
        return self.get_version(configuration_id, version)
