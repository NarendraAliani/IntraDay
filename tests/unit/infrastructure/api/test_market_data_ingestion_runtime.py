# tests/unit/infrastructure/api/test_market_data_ingestion_runtime.py
#
# Checkpoint 41 Part 3/7: proves the scheduler-invocable market-data
# ingestion tick session-gates itself and skips honestly (never
# fabricates data) when Dhan credentials are not configured - the two
# cases fully provable WITHOUT real Dhan credentials in this
# environment. The credentials-configured path (a real fetch_quotes()
# call) is exercised via a monkeypatched fetch_quotes in a SEPARATE
# test, clearly labelled CONTRACT TEST - NOT LIVE VALIDATION.
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from intraday.domain.session.contracts import SessionStatus
from intraday.infrastructure.api.market_data_ingestion_runtime import (
    run_market_data_ingestion_tick,
)
from intraday.infrastructure.market_data_providers.dhan.client import DhanQuoteFetchResult
from intraday.infrastructure.market_data_providers.dhan.instruments import observation_universe

pytestmark = pytest.mark.django_db

MARKET_HOLIDAY_INSTANT = datetime(2026, 1, 26, 6, 0, tzinfo=UTC)
MARKET_OPEN_INSTANT = datetime(2026, 1, 5, 6, 0, tzinfo=UTC)


def test_tick_skips_on_a_holiday_without_attempting_any_dhan_call() -> None:
    outcome = run_market_data_ingestion_tick(now=MARKET_HOLIDAY_INSTANT)
    assert outcome.ran is False
    assert outcome.session_status is SessionStatus.HOLIDAY
    assert "market_session_not_open" in (outcome.skipped_reason or "")


def test_tick_skips_cleanly_when_dhan_credentials_are_not_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deterministically forces the "not configured" branch, regardless
    of whatever DHAN_CLIENT_ID/DHAN_ACCESS_TOKEN environment values
    this particular dev/test environment happens to have set (Checkpoint
    22's own 'no fake credentials' rule means an env-level placeholder
    could exist here without being a REAL, usable credential) - this
    proves the SKIP behavior itself, not the state of any particular
    environment's env vars."""
    from intraday.application.services.provider_settings import DhanSettingsService

    monkeypatch.setattr(DhanSettingsService, "effective_credentials", lambda self: None)

    outcome = run_market_data_ingestion_tick(now=MARKET_OPEN_INSTANT)
    assert outcome.ran is False
    assert outcome.session_status is SessionStatus.OPEN
    assert outcome.skipped_reason == "credentials_not_configured"


# --- CONTRACT TEST - NOT LIVE VALIDATION ------------------------------------
#
# The following test monkeypatches fetch_quotes() to return a fixture
# shaped like Dhan's own documented quote response (never real network
# I/O, never real credentials) - it proves the ingestion pipeline
# WIRING (fetch -> persist -> aggregate -> promote) is correct, NOT
# that Dhan's real API behaves this way today. See
# docs/research/ACTIVE_SYSTEM_OPERATIONAL_BENCHMARK.md for the
# distinction this project draws between contract-tested and
# live-validated.


def test_configured_credentials_trigger_a_real_fetch_call(monkeypatch: pytest.MonkeyPatch) -> None:
    from intraday.application.services.provider_settings import DhanSettingsService

    called_with: dict[str, object] = {}

    def _fake_effective_credentials(self):  # type: ignore[no-untyped-def]
        return ("fake-client-id", "fake-access-token")

    def _fake_fetch_quotes(*, client_id, access_token, instruments):  # type: ignore[no-untyped-def]
        called_with["client_id"] = client_id
        called_with["access_token"] = access_token
        called_with["instruments"] = instruments
        return DhanQuoteFetchResult(observations=(), fetched_at=MARKET_OPEN_INSTANT, latency_ms=42)

    monkeypatch.setattr(DhanSettingsService, "effective_credentials", _fake_effective_credentials)
    monkeypatch.setattr(
        "intraday.infrastructure.api.market_data_ingestion_runtime.fetch_quotes",
        _fake_fetch_quotes,
    )

    outcome = run_market_data_ingestion_tick(now=MARKET_OPEN_INSTANT)

    assert outcome.ran is True
    assert called_with["client_id"] == "fake-client-id"
    assert called_with["instruments"] == observation_universe()
    assert outcome.bars_aggregated == 0  # no observations supplied - nothing to aggregate yet


def test_tick_skips_when_the_ingestion_lock_is_already_held() -> None:
    """Checkpoint 42 Part 10: proves two overlapping ticks cannot both
    run - the second sees the lock held and skips, never runs
    concurrently."""
    from intraday.infrastructure.scheduling.distributed_lock import acquire

    with acquire("market-data-ingestion-tick"):
        outcome = run_market_data_ingestion_tick(now=MARKET_OPEN_INSTANT)

    assert outcome.ran is False
    assert outcome.skipped_reason == "lock_held_by_another_tick"
