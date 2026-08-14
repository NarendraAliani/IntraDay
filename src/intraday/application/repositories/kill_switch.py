# File: src/intraday/application/repositories/kill_switch.py
#
# Checkpoint 34 Part 11: the kill-switch repository Protocol - mirrors
# `application/repositories/provider_settings.py`'s own shape exactly
# (a Protocol here, a Django ORM implementation in
# `infrastructure/persistence`). Reuses `domain.risk.contracts.
# TradingHaltState`/`TradingHaltStatus` verbatim (Checkpoint 5) as the
# read-side shape - never a second, competing kill-switch state type.
from __future__ import annotations

from typing import Protocol

from intraday.domain.risk.contracts import TradingHaltState


class KillSwitchRepository(Protocol):
    def get(self) -> TradingHaltState: ...

    def engage(
        self, *, reason: str, actor: str, actor_user_id: int, request_id: str
    ) -> TradingHaltState: ...

    def reset(self, *, actor: str, actor_user_id: int, request_id: str) -> TradingHaltState: ...
