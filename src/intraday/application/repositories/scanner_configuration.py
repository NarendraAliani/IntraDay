# File: src/intraday/application/repositories/scanner_configuration.py
#
# Checkpoint 64.4: the live scanner's DESIRED-state Protocol - see
# `ScannerConfiguration`'s own model docstring for the desired/
# effective split. Mirrors this project's existing "singleton row per
# provider" repository shape (`ProviderConnectionStatusRepository`,
# `WorkerRuntimeStatusRepository`).
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ScannerConfigurationRecord:
    provider: str
    enabled: bool
    timeframe: str
    universe_mode: str
    selected_instrument_ids: tuple[str, ...]
    selected_watchlist_name: str
    selected_strategy_ids: tuple[str, ...]
    configuration_version: int
    requested_by: str
    requested_at: datetime | None


class ScannerConfigurationRepository(Protocol):
    def get(self, provider: str) -> ScannerConfigurationRecord: ...

    def save(
        self,
        provider: str,
        *,
        enabled: bool,
        timeframe: str,
        universe_mode: str,
        selected_instrument_ids: list[str],
        selected_watchlist_name: str,
        selected_strategy_ids: list[str],
        requested_by: str,
        requested_by_user_id: int,
        request_id: str,
    ) -> ScannerConfigurationRecord:
        """Persists a NEW desired configuration - always bumps
        `configuration_version` (the caller never sets it directly),
        matching this project's established "version bump on every real
        change" convention."""
        ...


__all__ = ["ScannerConfigurationRecord", "ScannerConfigurationRepository"]
