# tests/unit/infrastructure/api/test_active_loop_celery_task.py
#
# Checkpoint 40 Part 4: proves the REAL Celery task (not just the
# underlying function) round-trips plain, JSON-serializable arguments
# correctly - called synchronously via `.run()` (no broker needed for
# a unit test, matching this project's existing Celery-smoke-task
# testing pattern), never asserting anything about a live worker
# process actually being started.
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from intraday.infrastructure.api.paper_trading_runtime import reset_paper_broker_for_testing
from intraday.infrastructure.api.tasks import active_loop_tick
from intraday.infrastructure.persistence.models import PaperOrderRecord

pytestmark = pytest.mark.django_db

MARKET_HOLIDAY_INSTANT = datetime(2026, 1, 26, 6, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _reset_broker():  # type: ignore[no-untyped-def]
    reset_paper_broker_for_testing()
    yield
    reset_paper_broker_for_testing()


def _bar_payload(price: int, minutes_offset: int, base: datetime) -> dict[str, str]:
    ts = base + timedelta(minutes=minutes_offset)
    return {
        "timeframe": "1m",
        "timestamp": ts.isoformat(),
        "open": str(price - 1),
        "high": str(price + 1),
        "low": str(price - 2),
        "close": str(price),
        "volume": "0",
    }


def test_task_skips_cleanly_on_a_holiday_with_plain_json_arguments() -> None:
    prices = [100] * 8 + [101 + i for i in range(10)]
    bar_payloads = [
        _bar_payload(price, i + 1, MARKET_HOLIDAY_INSTANT) for i, price in enumerate(prices)
    ]

    result = active_loop_tick.run(
        exchange="NSE",
        symbol="RELIANCE",
        strategy_id="ema_crossover",
        configuration_version="v1",
        bar_payloads=bar_payloads,
        now_override=MARKET_HOLIDAY_INSTANT.isoformat(),
    )

    assert result.startswith("skipped:market_session_not_open")
    assert not PaperOrderRecord.objects.exists()
