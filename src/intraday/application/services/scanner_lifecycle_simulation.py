# File: src/intraday/application/services/scanner_lifecycle_simulation.py
#
# Checkpoint 64.5 §19: the FIRST reusable, deterministic scanner
# lifecycle simulation harness - a genuine foundation, not the full
# "start to EOD with signals/risk/paper/notifications/reconnect"
# simulation the brief describes as the eventual target.
#
# Deliberately uses the SAME `ScannerConfigurationRepository` Protocol
# (and therefore the same `ScannerConfiguration` model) the real worker
# and API read/write - never a parallel, simulation-only configuration
# format. Every transition below is a real repository call producing a
# real, audited `ScannerConfiguration` row change; nothing here is
# faked or hand-computed.
#
# HONESTLY SCOPED (see taskReport.md "Full-Day Simulation Foundation"):
# this harness drives the DESIRED-configuration half of a trading day's
# lifecycle only (START / a mid-session configuration change / PAUSE /
# RESUME / STOP / an EOD stop). It does NOT yet simulate signal
# generation, risk decisions, paper execution, notification delivery,
# or a WebSocket disconnect/reconnect - those require a running
# strategy/risk/paper pipeline with synthetic bar injection, which is
# the next real increment, not built here. Building a "simulation" of
# those steps without a real pipeline behind them would mean fabricated
# results, which this project does not do.
from __future__ import annotations

import dataclasses
import uuid

from intraday.application.repositories.scanner_configuration import (
    ScannerConfigurationRecord,
    ScannerConfigurationRepository,
)


@dataclasses.dataclass(frozen=True, slots=True)
class SimulationStep:
    """One real, applied transition - `before`/`after` are the actual
    `ScannerConfigurationRecord` values read back from the repository,
    never synthesized."""

    name: str
    before: ScannerConfigurationRecord
    after: ScannerConfigurationRecord


class ScannerLifecycleSimulation:
    """Drives a `ScannerConfigurationRepository` through a deterministic
    sequence of real desired-configuration transitions, recording each
    step's genuine before/after state. Reusable by any future full-day
    simulation without inventing a second configuration model."""

    def __init__(
        self, repository: ScannerConfigurationRepository, *, provider: str = "dhan"
    ) -> None:
        self._repository = repository
        self._provider = provider
        self.steps: list[SimulationStep] = []

    def _apply(
        self,
        name: str,
        *,
        enabled: bool,
        timeframe: str,
        universe_mode: str,
        selected_instrument_ids: list[str],
        selected_watchlist_name: str,
        selected_strategy_ids: list[str],
    ) -> ScannerConfigurationRecord:
        before = self._repository.get(self._provider)
        after = self._repository.save(
            self._provider,
            enabled=enabled,
            timeframe=timeframe,
            universe_mode=universe_mode,
            selected_instrument_ids=selected_instrument_ids,
            selected_watchlist_name=selected_watchlist_name,
            selected_strategy_ids=selected_strategy_ids,
            requested_by="simulation",
            requested_by_user_id=0,
            request_id=str(uuid.uuid4()),
        )
        self.steps.append(SimulationStep(name=name, before=before, after=after))
        return after

    def start(self, *, timeframe: str, strategy_ids: list[str]) -> ScannerConfigurationRecord:
        return self._apply(
            "START",
            enabled=True,
            timeframe=timeframe,
            universe_mode="ALL_CONFIGURED",
            selected_instrument_ids=[],
            selected_watchlist_name="",
            selected_strategy_ids=strategy_ids,
        )

    def change_configuration(
        self, *, timeframe: str, strategy_ids: list[str]
    ) -> ScannerConfigurationRecord:
        current = self._repository.get(self._provider)
        return self._apply(
            "CONFIGURATION_CHANGE",
            enabled=current.enabled,
            timeframe=timeframe,
            universe_mode=current.universe_mode,
            selected_instrument_ids=list(current.selected_instrument_ids),
            selected_watchlist_name=current.selected_watchlist_name,
            selected_strategy_ids=strategy_ids,
        )

    def pause(self) -> ScannerConfigurationRecord:
        current = self._repository.get(self._provider)
        return self._apply(
            "PAUSE",
            enabled=False,
            timeframe=current.timeframe,
            universe_mode=current.universe_mode,
            selected_instrument_ids=list(current.selected_instrument_ids),
            selected_watchlist_name=current.selected_watchlist_name,
            selected_strategy_ids=list(current.selected_strategy_ids),
        )

    def resume(self) -> ScannerConfigurationRecord:
        current = self._repository.get(self._provider)
        return self._apply(
            "RESUME",
            enabled=True,
            timeframe=current.timeframe,
            universe_mode=current.universe_mode,
            selected_instrument_ids=list(current.selected_instrument_ids),
            selected_watchlist_name=current.selected_watchlist_name,
            selected_strategy_ids=list(current.selected_strategy_ids),
        )

    def end_of_day_stop(self) -> ScannerConfigurationRecord:
        current = self._repository.get(self._provider)
        return self._apply(
            "EOD_STOP",
            enabled=False,
            timeframe=current.timeframe,
            universe_mode=current.universe_mode,
            selected_instrument_ids=list(current.selected_instrument_ids),
            selected_watchlist_name=current.selected_watchlist_name,
            selected_strategy_ids=list(current.selected_strategy_ids),
        )


__all__ = ["ScannerLifecycleSimulation", "SimulationStep"]
