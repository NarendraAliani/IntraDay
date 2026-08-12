# tests/unit/infrastructure/persistence/test_models.py
#
# Model-level tests (Checkpoint 7 §22): PostgreSQL-specific constraints,
# uniqueness, Decimal precision, and timestamp behavior. All gated by
# requires_postgres — see tests/postgres_utils.py.
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from django.db import IntegrityError

from intraday.infrastructure.persistence.models import (
    ActiveRiskConfiguration,
    RiskConfigurationVersion,
    UniverseVersion,
)
from tests.postgres_utils import requires_postgres

NOW = datetime(2026, 1, 1, 9, 20, tzinfo=UTC)


@requires_postgres
@pytest.mark.django_db
def test_risk_configuration_version_persists_decimal_precision() -> None:
    row = RiskConfigurationVersion.objects.create(
        risk_configuration_id="default",
        version="v1",
        max_intraday_loss=Decimal("10000.00"),
        max_position_size=Decimal("50000.00"),
        max_per_trade_risk=Decimal("2000.00"),
        created_at=NOW,
    )
    row.refresh_from_db()
    assert row.max_intraday_loss == Decimal("10000.00")
    assert row.created_at == NOW


@requires_postgres
@pytest.mark.django_db
def test_risk_configuration_version_enforces_unique_id_and_version() -> None:
    kwargs = {
        "risk_configuration_id": "default",
        "version": "v1",
        "max_intraday_loss": Decimal("10000.00"),
        "max_position_size": Decimal("50000.00"),
        "max_per_trade_risk": Decimal("2000.00"),
        "created_at": NOW,
    }
    RiskConfigurationVersion.objects.create(**kwargs)
    with pytest.raises(IntegrityError):
        RiskConfigurationVersion.objects.create(**kwargs)


@requires_postgres
@pytest.mark.django_db
def test_risk_configuration_version_rejects_non_positive_limit_at_db_level() -> None:
    """Database-level backstop (Checkpoint 7 §11) — the CHECK constraint,
    not domain re-implementation."""
    with pytest.raises(IntegrityError):
        RiskConfigurationVersion.objects.create(
            risk_configuration_id="default",
            version="v-bad",
            max_intraday_loss=Decimal("0"),
            max_position_size=Decimal("50000.00"),
            max_per_trade_risk=Decimal("2000.00"),
            created_at=NOW,
        )


@requires_postgres
@pytest.mark.django_db
def test_active_risk_configuration_enforces_one_pointer_per_id() -> None:
    ActiveRiskConfiguration.objects.create(risk_configuration_id="default", active_version="v1")
    with pytest.raises(IntegrityError):
        ActiveRiskConfiguration.objects.create(risk_configuration_id="default", active_version="v2")


@requires_postgres
@pytest.mark.django_db
def test_universe_version_stores_members_as_jsonb() -> None:
    row = UniverseVersion.objects.create(
        universe_id="example",
        version="v1",
        exchange="NSE",
        members=[{"instrument_id": "NSE:RELIANCE", "status": "INCLUDED"}],
        created_at=NOW,
    )
    row.refresh_from_db()
    assert row.members == [{"instrument_id": "NSE:RELIANCE", "status": "INCLUDED"}]
