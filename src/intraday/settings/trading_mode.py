# src/intraday/settings/trading_mode.py
#
# Single authoritative TRADING_MODE safety mechanism (Checkpoint 4 §7).
# This module contains NO trading/business logic — it only classifies which
# of RESEARCH / PAPER / LIVE the current process is configured to run as,
# and enforces the mandatory invariant from
# docs/architecture/TECHNOLOGY_MAPPING.md §14:
#
#   LIVE trading requires production settings + TRADING_MODE=LIVE + valid
#   live broker configuration — all three simultaneously.
#
# Every settings module (development/testing/paper/production) calls
# `resolve_trading_mode()` exactly once, at import time, instead of
# scattering ad hoc environment checks throughout the codebase. If the
# invariant is violated, Django refuses to boot at all (an exception is
# raised while settings are being loaded) — this is what makes accidentally
# starting live trading from a development environment structurally
# impossible, not merely discouraged by convention.
from __future__ import annotations

import enum
import os


class TradingMode(str, enum.Enum):
    """The three modes the platform can run in. See TECHNOLOGY_MAPPING.md §14."""

    RESEARCH = "RESEARCH"
    PAPER = "PAPER"
    LIVE = "LIVE"


class UnsafeLiveConfigurationError(RuntimeError):
    """Raised when TRADING_MODE=LIVE is requested without every required
    safety condition met simultaneously, or when TRADING_MODE is set to an
    unrecognized value. Raising this during settings import halts Django
    startup entirely — the process never reaches a runnable state."""


def resolve_trading_mode(
    *,
    settings_module_is_production: bool,
    live_broker_credentials_present: bool,
) -> TradingMode:
    """Resolve and validate the TRADING_MODE for the current process.

    Args:
        settings_module_is_production: True only when called from
            intraday.settings.production. Every other settings module must
            pass False.
        live_broker_credentials_present: True only when live (not sandbox/
            paper) broker credentials are present in the environment. No
            broker calls are made here — this is a boolean presence check
            only, evaluated by the caller.

    Raises:
        UnsafeLiveConfigurationError: if TRADING_MODE is unrecognized, or is
            LIVE without both safety conditions holding simultaneously.
    """
    raw_value = os.environ.get("TRADING_MODE", TradingMode.RESEARCH.value).strip().upper()

    try:
        mode = TradingMode(raw_value)
    except ValueError as exc:
        allowed = ", ".join(m.value for m in TradingMode)
        raise UnsafeLiveConfigurationError(
            f"TRADING_MODE={raw_value!r} is not a recognized trading mode "
            f"(expected one of: {allowed}). Refusing to boot."
        ) from exc

    if mode is TradingMode.LIVE:
        if not settings_module_is_production:
            raise UnsafeLiveConfigurationError(
                "TRADING_MODE=LIVE was requested but the active Django settings "
                "module is not intraday.settings.production. Refusing to boot. "
                "This is the mechanism that makes accidental live trading from "
                "a development/testing/paper environment structurally impossible."
            )
        if not live_broker_credentials_present:
            raise UnsafeLiveConfigurationError(
                "TRADING_MODE=LIVE was requested under production settings, but "
                "live broker credentials are not present in the environment. "
                "Refusing to boot."
            )

    return mode
