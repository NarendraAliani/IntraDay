# tests/unit/infrastructure/api/test_strategy_api.py
#
# Endpoint tests for the strategy-version API resource (Checkpoint 8).
# Mirrors test_risk_api.py's coverage at lighter depth.
from __future__ import annotations

import pytest
from django.test import Client

from intraday.domain.shared_kernel.contracts import Timeframe, Version
from intraday.domain.strategy.contracts import StrategyMaturityState, StrategyVersion
from intraday.infrastructure.persistence.repositories import DjangoStrategyVersionRepository
from tests.postgres_utils import requires_postgres

IDENTITY_PATH = "/api/v1/config/strategy/example-strategy/spec-v1/code-v1/cfg-v1/"


def _seed() -> None:
    DjangoStrategyVersionRepository().save(
        StrategyVersion(
            strategy_id="example-strategy",
            specification_version=Version(value="spec-v1"),
            code_version=Version(value="code-v1"),
            configuration_version=Version(value="cfg-v1"),
            universe_version=Version(value="v1"),
            timeframe=Timeframe.FIVE_MINUTE,
            maturity_state=StrategyMaturityState.IDEA,
        )
    )


@requires_postgres
@pytest.mark.django_db
def test_get_version_by_three_part_identity() -> None:
    _seed()
    client = Client()

    response = client.get(IDENTITY_PATH)

    assert response.status_code == 200
    body = response.json()
    assert body["strategy_id"] == "example-strategy"
    assert body["maturity_state"] == "IDEA"
    assert body["timeframe"] == "5m"


@requires_postgres
@pytest.mark.django_db
def test_unknown_strategy_version_returns_404() -> None:
    client = Client()
    response = client.get("/api/v1/config/strategy/does-not-exist/a/b/c/")
    assert response.status_code == 404
    assert response.json()["error_code"] == "not_found"


@requires_postgres
@pytest.mark.django_db
def test_activate_then_active_endpoint_reflects_it() -> None:
    _seed()
    client = Client()

    activate_response = client.post(IDENTITY_PATH + "activate/")
    assert activate_response.status_code == 200

    active_response = client.get("/api/v1/config/strategy/example-strategy/active/")
    assert active_response.status_code == 200
    assert active_response.json()["specification_version"] == "spec-v1"
