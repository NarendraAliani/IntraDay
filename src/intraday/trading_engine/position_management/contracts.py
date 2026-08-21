# File: src/intraday/trading_engine/position_management/contracts.py
#
# Checkpoint 64.24: `ExitPlan`/`ManagedPosition`/`ExitDecision`/
# `ExitReason`/`PositionLifecycleStatus` were relocated to
# `intraday.domain.position_exit.contracts` (the one layer every part
# of this codebase - trading_engine, application, AND research - is
# permitted to import). This module is now a thin backward-
# compatibility re-export shim, kept (rather than deleted) so any
# import path this refactor's own grep audit might have missed still
# resolves correctly. Prefer importing directly from
# `intraday.domain.position_exit.contracts` in new code.
from __future__ import annotations

from intraday.domain.position_exit.contracts import (
    ExitDecision as ExitDecision,
)
from intraday.domain.position_exit.contracts import (
    ExitPlan as ExitPlan,
)
from intraday.domain.position_exit.contracts import (
    ExitReason as ExitReason,
)
from intraday.domain.position_exit.contracts import (
    ManagedPosition as ManagedPosition,
)
from intraday.domain.position_exit.contracts import (
    PositionLifecycleStatus as PositionLifecycleStatus,
)

__all__ = [
    "ExitDecision",
    "ExitPlan",
    "ExitReason",
    "ManagedPosition",
    "PositionLifecycleStatus",
]
