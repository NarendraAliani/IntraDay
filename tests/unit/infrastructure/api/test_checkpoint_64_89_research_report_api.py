# tests/unit/infrastructure/api/test_checkpoint_64_89_research_report_api.py
#
# Checkpoint 64.89: minimal API coverage for the read-only research
# report endpoint, mirroring the established `test_checkpoint_64_82_
# correlation_api.py` pattern - real Django test Client, real URLconf,
# real persisted rows.
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, TestCase

from intraday.infrastructure.persistence.models import SignalRecord

READER_USERNAME = "research_reader"  # noqa: S105
PASSWORD = "correct-horse-battery-staple"  # noqa: S105

BASE = datetime(2026, 2, 9, 4, 15, tzinfo=UTC)


def _client() -> Client:
    User.objects.create_user(username=READER_USERNAME, password=PASSWORD)
    client = Client()
    assert client.login(username=READER_USERNAME, password=PASSWORD)
    return client


class ResearchReportApiTests(TestCase):
    def test_requires_authentication(self) -> None:
        response = Client().get("/api/v1/correlation/research/report/")
        assert response.status_code in (401, 403)

    def test_zero_data_reports_none_percentages_and_empty_analyses(self) -> None:
        response = _client().get("/api/v1/correlation/research/report/")
        assert response.status_code == 200
        body = response.json()
        assert body["traceability_coverage"]["total_signals"] == 0
        assert body["traceability_coverage"]["evidence_coverage_pct"] is None
        assert body["feature_outcome"] == []
        assert body["feature_interaction"] == []
        assert body["symbol_robustness"] == []

    def test_reports_signal_count_from_real_records(self) -> None:
        SignalRecord.objects.create(
            signal_id="sig-1",
            strategy_id="ema_crossover",
            instrument_id="NSE:RELIANCE",
            direction="BULLISH",
            price=Decimal("101"),
            timeframe="1m",
            signal_timestamp=BASE,
            risk_status="APPROVED",
        )
        response = _client().get("/api/v1/correlation/research/report/")
        assert response.status_code == 200
        body = response.json()
        assert body["traceability_coverage"]["total_signals"] == 1
        assert body["min_sample_size"] == 20
