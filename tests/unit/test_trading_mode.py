# tests/unit/test_trading_mode.py
#
# Unit tests (Checkpoint 4 §7) for the TRADING_MODE safety invariant — the
# single authoritative mechanism that makes it structurally impossible to
# boot TRADING_MODE=LIVE outside the production settings module or without
# live broker credentials present. Pure function tests; no Django or
# external services required.
from __future__ import annotations

import pytest

from intraday.settings.trading_mode import (
    TradingMode,
    UnsafeLiveConfigurationError,
    resolve_trading_mode,
)


def test_defaults_to_research_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRADING_MODE", raising=False)
    mode = resolve_trading_mode(
        settings_module_is_production=False, live_broker_credentials_present=False
    )
    assert mode is TradingMode.RESEARCH


def test_paper_mode_allowed_outside_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    mode = resolve_trading_mode(
        settings_module_is_production=False, live_broker_credentials_present=False
    )
    assert mode is TradingMode.PAPER


def test_live_mode_rejected_outside_production_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRADING_MODE", "LIVE")
    with pytest.raises(UnsafeLiveConfigurationError):
        resolve_trading_mode(settings_module_is_production=False, live_broker_credentials_present=True)


def test_live_mode_rejected_without_broker_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRADING_MODE", "LIVE")
    with pytest.raises(UnsafeLiveConfigurationError):
        resolve_trading_mode(settings_module_is_production=True, live_broker_credentials_present=False)


def test_live_mode_allowed_only_with_both_conditions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRADING_MODE", "LIVE")
    mode = resolve_trading_mode(
        settings_module_is_production=True, live_broker_credentials_present=True
    )
    assert mode is TradingMode.LIVE


def test_unrecognized_trading_mode_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRADING_MODE", "NOT_A_MODE")
    with pytest.raises(UnsafeLiveConfigurationError):
        resolve_trading_mode(
            settings_module_is_production=False, live_broker_credentials_present=False
        )
