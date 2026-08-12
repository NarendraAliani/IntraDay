# tests/unit/application/services/test_risk_service.py
#
# Unit tests for RiskConfigurationService (Checkpoint 8 §6) using an
# in-memory FAKE repository — no Django, no database, no network. This is
# the concrete proof that application services are testable in isolation
# from any concrete persistence technology, per Checkpoint 8's explicit
# dependency-injection requirement.
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from intraday.application.config_schema.records import RiskConfigurationRecord
from intraday.application.services.errors import (
    InvalidActivationRequestError,
    ResourceNotFoundError,
)
from intraday.application.services.risk import RiskConfigurationService
from intraday.domain.risk.contracts import RiskLimits
from intraday.domain.shared_kernel.contracts import Version

NOW = datetime(2026, 1, 1, 9, 20, tzinfo=UTC)


class FakeRiskConfigurationRepository:
    """In-memory stand-in implementing the same shape as
    `RiskConfigurationRepository` (a `Protocol`, so no explicit
    inheritance is required — structural typing is the point)."""

    def __init__(self) -> None:
        self._versions: dict[tuple[str, str], RiskConfigurationRecord] = {}
        self._active: dict[str, str] = {}

    def save(self, record: RiskConfigurationRecord) -> None:
        self._versions[(record.risk_configuration_id, record.version.value)] = record

    def get_version(
        self, risk_configuration_id: str, version: str
    ) -> RiskConfigurationRecord | None:
        return self._versions.get((risk_configuration_id, version))

    def get_active(self, risk_configuration_id: str) -> RiskConfigurationRecord | None:
        version = self._active.get(risk_configuration_id)
        if version is None:
            return None
        return self.get_version(risk_configuration_id, version)

    def list_versions(self, risk_configuration_id: str) -> tuple[RiskConfigurationRecord, ...]:
        return tuple(
            record
            for (config_id, _), record in self._versions.items()
            if config_id == risk_configuration_id
        )

    def activate(self, risk_configuration_id: str, version: str) -> None:
        if (risk_configuration_id, version) not in self._versions:
            raise ValueError(f"cannot activate unknown version {version!r}")
        self._active[risk_configuration_id] = version


def _record(version: str) -> RiskConfigurationRecord:
    return RiskConfigurationRecord(
        risk_configuration_id="default",
        version=Version(value=version),
        limits=RiskLimits(
            max_intraday_loss=Decimal("10000.00"),
            max_position_size=Decimal("50000.00"),
            max_per_trade_risk=Decimal("2000.00"),
        ),
        created_at=NOW,
    )


def test_get_version_returns_saved_record() -> None:
    repo = FakeRiskConfigurationRepository()
    repo.save(_record("v1"))
    service = RiskConfigurationService(repository=repo)
    assert service.get_version("default", "v1").version.value == "v1"


def test_get_version_raises_not_found_for_missing_version() -> None:
    service = RiskConfigurationService(repository=FakeRiskConfigurationRepository())
    with pytest.raises(ResourceNotFoundError):
        service.get_version("default", "nonexistent")


def test_get_active_raises_not_found_when_nothing_activated() -> None:
    repo = FakeRiskConfigurationRepository()
    repo.save(_record("v1"))
    service = RiskConfigurationService(repository=repo)
    with pytest.raises(ResourceNotFoundError):
        service.get_active("default")


def test_activate_then_get_active_returns_activated_version() -> None:
    repo = FakeRiskConfigurationRepository()
    repo.save(_record("v1"))
    repo.save(_record("v2"))
    service = RiskConfigurationService(repository=repo)

    activated = service.activate("default", "v2")

    assert activated.version.value == "v2"
    assert service.get_active("default").version.value == "v2"


def test_activate_unknown_version_raises_invalid_activation_request() -> None:
    service = RiskConfigurationService(repository=FakeRiskConfigurationRepository())
    with pytest.raises(InvalidActivationRequestError):
        service.activate("default", "nonexistent")


def test_activate_is_idempotent() -> None:
    repo = FakeRiskConfigurationRepository()
    repo.save(_record("v1"))
    service = RiskConfigurationService(repository=repo)

    first = service.activate("default", "v1")
    second = service.activate("default", "v1")

    assert first == second


def test_list_versions_returns_all_saved_versions() -> None:
    repo = FakeRiskConfigurationRepository()
    repo.save(_record("v1"))
    repo.save(_record("v2"))
    service = RiskConfigurationService(repository=repo)

    versions = {record.version.value for record in service.list_versions("default")}

    assert versions == {"v1", "v2"}
