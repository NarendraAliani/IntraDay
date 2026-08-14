# File: src/intraday/application/services/kill_switch.py
#
# Checkpoint 34 Part 11: application-layer orchestration for the kill
# switch - mirrors `application/services/provider_settings.py`'s own
# thin-wrapper-over-a-repository shape. `engage()` requires a non-empty
# `reason` (Part 11's "reason" requirement) - the repository itself
# does not enforce this (it is an application-level validation rule,
# not a persistence-level one, matching this project's established
# split).
from __future__ import annotations

from intraday.application.repositories.kill_switch import KillSwitchRepository
from intraday.domain.risk.contracts import TradingHaltState


class EmptyKillSwitchReasonError(ValueError):
    """Raised when `engage()` is called with an empty/whitespace-only
    reason - a kill switch engaged for no stated reason is not
    auditable (Part 11's own explicit requirement)."""


class KillSwitchService:
    def __init__(self, repository: KillSwitchRepository) -> None:
        self._repository = repository

    def status(self) -> TradingHaltState:
        return self._repository.get()

    def engage(
        self, *, reason: str, actor: str, actor_user_id: int, request_id: str
    ) -> TradingHaltState:
        if not reason.strip():
            raise EmptyKillSwitchReasonError("A reason is required to engage the kill switch.")
        return self._repository.engage(
            reason=reason.strip(), actor=actor, actor_user_id=actor_user_id, request_id=request_id
        )

    def reset(self, *, actor: str, actor_user_id: int, request_id: str) -> TradingHaltState:
        return self._repository.reset(
            actor=actor, actor_user_id=actor_user_id, request_id=request_id
        )
