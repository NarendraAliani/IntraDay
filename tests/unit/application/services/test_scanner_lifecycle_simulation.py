# tests/unit/application/services/test_scanner_lifecycle_simulation.py
#
# Checkpoint 64.5 §19: coverage for the first deterministic scanner
# lifecycle simulation foundation - proves every step is a REAL,
# applied `ScannerConfiguration` transition (via the same repository
# the API/worker use), not a simulated/fabricated state change.
from __future__ import annotations

import pytest

from intraday.application.services.scanner_lifecycle_simulation import (
    ScannerLifecycleSimulation,
)
from intraday.infrastructure.persistence.scanner_configuration_repository import (
    DjangoScannerConfigurationRepository,
)
from tests.postgres_utils import requires_postgres


@requires_postgres
@pytest.mark.django_db
def test_full_lifecycle_sequence_produces_real_consecutive_configuration_versions() -> None:
    repository = DjangoScannerConfigurationRepository()
    simulation = ScannerLifecycleSimulation(repository, provider="dhan")

    simulation.start(timeframe="1m", strategy_ids=["ema_crossover"])
    simulation.change_configuration(
        timeframe="5m", strategy_ids=["ema_crossover", "sma_trend_filter"]
    )
    simulation.pause()
    simulation.resume()
    simulation.end_of_day_stop()

    assert [step.name for step in simulation.steps] == [
        "START",
        "CONFIGURATION_CHANGE",
        "PAUSE",
        "RESUME",
        "EOD_STOP",
    ]
    # Each step's `after` genuinely came from the repository, and versions
    # are consecutive - proving no step was skipped or faked.
    versions = [step.after.configuration_version for step in simulation.steps]
    assert versions == sorted(versions)
    assert len(set(versions)) == len(versions)

    assert simulation.steps[0].after.enabled is True
    assert simulation.steps[1].after.timeframe == "5m"
    assert simulation.steps[1].after.selected_strategy_ids == ("ema_crossover", "sma_trend_filter")
    assert simulation.steps[2].after.enabled is False  # PAUSE
    assert simulation.steps[3].after.enabled is True  # RESUME
    assert simulation.steps[4].after.enabled is False  # EOD_STOP

    final = repository.get("dhan")
    assert final.configuration_version == versions[-1]
    assert final.enabled is False
