# File: src/intraday/trading_engine/position_management/monitor.py
#
# Checkpoint 64.24: `evaluate_position_exit()` was relocated to
# `intraday.domain.position_exit.policy` (the one layer every part of
# this codebase - trading_engine, application, AND research - is
# permitted to import). This module is now a thin backward-
# compatibility re-export shim, kept (rather than deleted) so any
# import path this refactor's own grep audit might have missed still
# resolves correctly. Prefer importing directly from
# `intraday.domain.position_exit.policy` in new code.
from __future__ import annotations

from intraday.domain.position_exit.policy import (
    evaluate_position_exit as evaluate_position_exit,
)

__all__ = ["evaluate_position_exit"]
