# tests/unit/application/services/test_kill_switch.py
#
# Checkpoint 34 Part 11/18: KillSwitchService against an in-memory fake
# repository - proves the service's own validation (non-empty reason)
# without needing a database.
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from intraday.application.services.kill_switch import EmptyKillSwitchReasonError, KillSwitchService
from intraday.domain.risk.contracts import TradingHaltState, TradingHaltStatus

NOW = datetime(2026, 1, 5, 4, 0, tzinfo=UTC)


class FakeKillSwitchRepository:
    def __init__(self) -> None:
        self._state = TradingHaltState(status=TradingHaltStatus.ACTIVE)
        self.engage_calls: list[dict[str, object]] = []
        self.reset_calls: list[dict[str, object]] = []

    def get(self) -> TradingHaltState:
        return self._state

    def engage(
        self, *, reason: str, actor: str, actor_user_id: int, request_id: str
    ) -> TradingHaltState:
        self.engage_calls.append({"reason": reason, "actor": actor, "actor_user_id": actor_user_id})
        self._state = TradingHaltState(
            status=TradingHaltStatus.HALTED, reason=reason, changed_at=NOW
        )
        return self._state

    def reset(self, *, actor: str, actor_user_id: int, request_id: str) -> TradingHaltState:
        self.reset_calls.append({"actor": actor, "actor_user_id": actor_user_id})
        self._state = TradingHaltState(status=TradingHaltStatus.ACTIVE, changed_at=NOW)
        return self._state


def test_status_reflects_default_active_state() -> None:
    service = KillSwitchService(FakeKillSwitchRepository())
    assert service.status().status is TradingHaltStatus.ACTIVE


def test_engage_requires_non_empty_reason() -> None:
    service = KillSwitchService(FakeKillSwitchRepository())
    with pytest.raises(EmptyKillSwitchReasonError):
        service.engage(reason="   ", actor="operator", actor_user_id=1, request_id="req-1")


def test_engage_with_valid_reason_halts() -> None:
    repo = FakeKillSwitchRepository()
    service = KillSwitchService(repo)
    result = service.engage(
        reason="manual halt", actor="operator", actor_user_id=1, request_id="req-1"
    )
    assert result.status is TradingHaltStatus.HALTED
    assert repo.engage_calls == [{"reason": "manual halt", "actor": "operator", "actor_user_id": 1}]


def test_reset_reactivates() -> None:
    repo = FakeKillSwitchRepository()
    service = KillSwitchService(repo)
    service.engage(reason="halt", actor="operator", actor_user_id=1, request_id="req-1")
    result = service.reset(actor="operator", actor_user_id=1, request_id="req-2")
    assert result.status is TradingHaltStatus.ACTIVE
    assert repo.reset_calls == [{"actor": "operator", "actor_user_id": 1}]


def test_engage_reason_is_stripped() -> None:
    repo = FakeKillSwitchRepository()
    service = KillSwitchService(repo)
    service.engage(reason="  halt now  ", actor="operator", actor_user_id=1, request_id="req-1")
    assert repo.engage_calls[0]["reason"] == "halt now"
