# tests/unit/infrastructure/persistence/test_scanner_configuration_repository.py
#
# Checkpoint 64.4: real-Postgres coverage for the scanner's DESIRED-
# state repository - version bumping, and the audit trail written in
# the SAME transaction as the state change (mirrors
# `DjangoRiskConfigurationRepository.activate()`'s own established
# pattern, Checkpoint 12).
from __future__ import annotations

import pytest

from intraday.infrastructure.persistence.models import AuditLogEntry
from intraday.infrastructure.persistence.scanner_configuration_repository import (
    DjangoScannerConfigurationRepository,
)
from tests.postgres_utils import requires_postgres


@requires_postgres
@pytest.mark.django_db
def test_get_returns_sensible_defaults_before_any_save() -> None:
    record = DjangoScannerConfigurationRepository().get("dhan")

    assert record.enabled is False
    assert record.timeframe == "1m"
    assert record.universe_mode == "ALL_CONFIGURED"
    assert record.configuration_version == 1
    assert record.selected_strategy_ids == ()


@requires_postgres
@pytest.mark.django_db
def test_save_bumps_the_configuration_version() -> None:
    repository = DjangoScannerConfigurationRepository()
    before = repository.get("dhan")

    after = repository.save(
        "dhan",
        enabled=True,
        timeframe="5m",
        universe_mode="ALL_CONFIGURED",
        selected_instrument_ids=[],
        selected_watchlist_name="",
        selected_strategy_ids=["ema_crossover"],
        requested_by="operator",
        requested_by_user_id=1,
        request_id="11111111-1111-1111-1111-111111111111",
    )

    assert after.configuration_version == before.configuration_version + 1
    assert after.enabled is True
    assert after.timeframe == "5m"
    assert after.selected_strategy_ids == ("ema_crossover",)


@requires_postgres
@pytest.mark.django_db
def test_save_writes_a_durable_audit_record_in_the_same_operation() -> None:
    repository = DjangoScannerConfigurationRepository()

    audit_count_before = AuditLogEntry.objects.filter(resource_type="scanner_configuration").count()
    repository.save(
        "dhan",
        enabled=True,
        timeframe="15m",
        universe_mode="SELECTED",
        selected_instrument_ids=["NSE:RELIANCE"],
        selected_watchlist_name="",
        selected_strategy_ids=["ema_crossover", "sma_trend_filter"],
        requested_by="operator",
        requested_by_user_id=7,
        request_id="22222222-2222-2222-2222-222222222222",
    )

    entries = AuditLogEntry.objects.filter(resource_type="scanner_configuration").order_by("-id")
    assert entries.count() == audit_count_before + 1
    entry = entries.first()
    assert entry is not None
    assert entry.actor_username == "operator"
    assert entry.actor_user_id == 7
    assert entry.action == "scanner_configuration.update"
    assert entry.resource_id == "dhan"
    assert entry.outcome == "updated"
    assert entry.request_id == "22222222-2222-2222-2222-222222222222"


@requires_postgres
@pytest.mark.django_db
def test_repeated_saves_each_bump_the_version_and_record_the_previous_one() -> None:
    repository = DjangoScannerConfigurationRepository()

    first = repository.save(
        "dhan",
        enabled=True,
        timeframe="1m",
        universe_mode="ALL_CONFIGURED",
        selected_instrument_ids=[],
        selected_watchlist_name="",
        selected_strategy_ids=["ema_crossover"],
        requested_by="operator",
        requested_by_user_id=1,
        request_id="33333333-3333-3333-3333-333333333333",
    )
    second = repository.save(
        "dhan",
        enabled=True,
        timeframe="5m",
        universe_mode="ALL_CONFIGURED",
        selected_instrument_ids=[],
        selected_watchlist_name="",
        selected_strategy_ids=["ema_crossover"],
        requested_by="operator",
        requested_by_user_id=1,
        request_id="44444444-4444-4444-4444-444444444444",
    )

    assert second.configuration_version == first.configuration_version + 1
    audit_entries = AuditLogEntry.objects.filter(
        resource_type="scanner_configuration", resource_id="dhan"
    ).order_by("id")
    versions = [e.version_identifier for e in audit_entries]
    previous = [e.previous_version for e in audit_entries]
    assert versions[-1] == str(second.configuration_version)
    assert previous[-1] == str(first.configuration_version)
