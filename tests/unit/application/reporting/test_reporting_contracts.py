# tests/unit/application/reporting/test_reporting_contracts.py
#
# Checkpoint 32 Part 17: report metadata contract, catalogue, and the
# backtest/market-data-quality report mappers - including the explicit
# "never auto-promote" assertions Part 17 requires.
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from intraday.application.reporting.backtest_report import build_backtest_report_metadata
from intraday.application.reporting.contracts import (
    REPORT_CATALOGUE,
    ReportMetadata,
    ReportStatus,
    ReportType,
)
from intraday.application.reporting.market_data_quality_report import (
    ConditionStatus,
    build_market_data_quality_report,
)
from intraday.domain.market_data.aggregation import BarQualityGrade
from intraday.domain.market_data.contracts import Bar
from intraday.domain.shared_kernel.contracts import Timeframe
from intraday.research.backtesting import StrategyConfigurationValues, build_default_registry
from intraday.research.backtesting.contracts import (
    BacktestConfiguration,
    BacktestTrustLevel,
    DataQualityDisclosure,
    DataQualityLabel,
    PositionSizingMode,
)
from intraday.research.backtesting.cost_model import verified_nse_cash_equity_intraday_cost_model
from intraday.research.backtesting.engine import run_backtest
from intraday.signal_intelligence.feature_engine.definitions import (
    ExponentialMovingAverageDefinition,
)
from intraday.signal_intelligence.feature_engine.ema import compute_exponential_moving_average


def _compute(field_id, bars):
    _, _, raw = field_id.partition("_")
    return compute_exponential_moving_average(ExponentialMovingAverageDefinition(int(raw)), bars)


def _bars():
    base = datetime(2026, 1, 5, 3, 45, tzinfo=UTC)
    prices = [100, 100, 100, 100, 100, 100, 101, 103, 105, 107]
    bars = []
    for i, price in enumerate(prices):
        bars.append(
            Bar(
                instrument_id="NSE:VALIDATION01",
                timeframe=Timeframe.ONE_MINUTE,
                timestamp=base + __import__("datetime").timedelta(minutes=i + 1),
                open=Decimal(price - 1),
                high=Decimal(price + 1),
                low=Decimal(price - 2),
                close=Decimal(price),
                volume=Decimal("0"),
            )
        )
    return tuple(bars)


def _result():
    bars = _bars()
    registry = build_default_registry()
    config = BacktestConfiguration(
        instrument_id="NSE:VALIDATION01",
        timeframe=Timeframe.ONE_MINUTE,
        start=bars[0].timestamp,
        end=bars[-1].timestamp,
        strategy_id="ema_crossover",
        specification_version="v1",
        code_version="v1",
        configuration_version="v1",
        initial_capital=Decimal("100000"),
        position_sizing_mode=PositionSizingMode.FIXED_QUANTITY,
        position_size_value=Decimal("10"),
        brokerage_percent=Decimal("0"),
        slippage_percent=Decimal("0"),
    )
    strategy_config = StrategyConfigurationValues(
        "ema_crossover", "v1", "v1", "v1", {"fast_lookback": 2, "slow_lookback": 4}
    )
    dq = DataQualityDisclosure(
        data_source="fixture",
        data_quality=DataQualityLabel.FIXTURE_OR_HISTORICAL,
        bar_count=len(bars),
        missing_bar_note="none",
        transaction_cost_assumption="verified",
        slippage_assumption="none",
        survivorship_bias_note="n/a",
    )
    return run_backtest(
        bars,
        registry.get("ema_crossover"),
        strategy_config,
        config,
        _compute,
        data_quality=dq,
        generated_at=datetime.now(tz=UTC),
        cost_model=verified_nse_cash_equity_intraday_cost_model(),
    )


# --- ReportMetadata ------------------------------------------------------


def test_report_metadata_rejects_empty_report_id() -> None:
    with pytest.raises(ValueError, match="report_id"):
        ReportMetadata(
            report_id="",
            report_type=ReportType.BACKTEST_REPORT,
            title="x",
            generated_at=datetime.now(tz=UTC),
            generated_by="test",
            data_source="x",
            data_identity="x",
            strategy_identity=None,
            timeframe=None,
            instrument_universe=(),
            trust_level=None,
            quality_status=None,
            report_status=ReportStatus.AVAILABLE,
            version="1",
            period_start=None,
            period_end=None,
        )


def test_report_metadata_rejects_period_start_after_end() -> None:
    with pytest.raises(ValueError, match="period_start"):
        ReportMetadata(
            report_id="r1",
            report_type=ReportType.BACKTEST_REPORT,
            title="x",
            generated_at=datetime.now(tz=UTC),
            generated_by="test",
            data_source="x",
            data_identity="x",
            strategy_identity=None,
            timeframe=None,
            instrument_universe=(),
            trust_level=None,
            quality_status=None,
            report_status=ReportStatus.AVAILABLE,
            version="1",
            period_start=date(2026, 1, 10),
            period_end=date(2026, 1, 1),
        )


def test_report_metadata_requires_utc_generated_at() -> None:
    with pytest.raises(ValueError):
        ReportMetadata(
            report_id="r1",
            report_type=ReportType.BACKTEST_REPORT,
            title="x",
            generated_at=datetime(2026, 1, 1),  # naive
            generated_by="test",
            data_source="x",
            data_identity="x",
            strategy_identity=None,
            timeframe=None,
            instrument_universe=(),
            trust_level=None,
            quality_status=None,
            report_status=ReportStatus.AVAILABLE,
            version="1",
            period_start=None,
            period_end=None,
        )


# --- REPORT_CATALOGUE ------------------------------------------------------


def test_report_catalogue_has_exactly_twelve_entries() -> None:
    """Ten from Checkpoint 32, plus COMMUNICATION_DELIVERY_REPORT added
    Checkpoint 37 Part 8, plus DAILY_SESSION_REPORT added Checkpoint
    64.10 - both real, AVAILABLE reports backed by real ledgers, never
    placeholders."""
    assert len(REPORT_CATALOGUE) == 12


def test_report_catalogue_covers_every_report_type_exactly_once() -> None:
    types = [entry.report_type for entry in REPORT_CATALOGUE]
    assert set(types) == set(ReportType)
    assert len(types) == len(set(types))


def test_report_catalogue_never_claims_unimplemented_capability_is_available() -> None:
    """Risk/Production reports have no underlying data yet - their
    catalogue status must never be AVAILABLE."""
    for entry in REPORT_CATALOGUE:
        if entry.report_type in (ReportType.RISK_REPORT, ReportType.PRODUCTION_REPORT):
            assert entry.status is not ReportStatus.AVAILABLE


# --- Backtest report mapping ------------------------------------------------------


def test_backtest_report_metadata_copies_trust_level_verbatim() -> None:
    result = _result()
    metadata = build_backtest_report_metadata(result, generated_by="test")

    assert metadata.trust_level == result.trust_level
    assert metadata.trust_level == BacktestTrustLevel.POC


def test_backtest_report_metadata_cannot_become_research_ready_automatically() -> None:
    """Even a real, engine-computed, non-empty backtest result must not
    yield a RESEARCH_READY report - Part 17's explicit requirement."""
    result = _result()
    metadata = build_backtest_report_metadata(result, generated_by="test")

    assert metadata.trust_level is not BacktestTrustLevel.RESEARCH_READY


def test_backtest_report_metadata_report_id_matches_backtest_id() -> None:
    result = _result()
    metadata = build_backtest_report_metadata(result, generated_by="test")

    assert metadata.report_id == result.backtest_id


# --- Market-data quality report ------------------------------------------------------


def test_market_data_quality_report_stays_sample_bar_with_partial_conditions() -> None:
    report = build_market_data_quality_report(generated_by="test")

    assert report.conditions_passed < len(report.conditions)
    assert report.current_classification is BarQualityGrade.SAMPLE_BAR


def test_market_data_quality_report_condition_counts_are_consistent() -> None:
    report = build_market_data_quality_report(generated_by="test")

    total = report.conditions_passed + report.conditions_failed + report.conditions_blocked
    assert total == len(report.conditions)


def test_market_data_quality_report_blocked_conditions_are_not_satisfied() -> None:
    report = build_market_data_quality_report(generated_by="test")

    blocked = [c for c in report.conditions if c.status is ConditionStatus.BLOCKED]
    assert blocked  # at least one condition genuinely blocked (WebSocket ingestion)
    for condition in blocked:
        assert condition.status is not ConditionStatus.SATISFIED
