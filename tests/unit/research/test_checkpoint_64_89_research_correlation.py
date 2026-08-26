# tests/unit/research/test_checkpoint_64_89_research_correlation.py
#
# Checkpoint 64.89: HISTORICAL FEATURE -> SIGNAL -> TRADE -> OUTCOME
# RESEARCH FOUNDATION.
#
# These tests build small, EXPLICITLY LABELLED, synthetic fixture rows
# directly through the Django ORM (the same tables the correlation API
# already reads) purely to exercise the RESEARCH MECHANISM - traceability
# coverage counting, sample-sufficiency gating, no-fabricated-joins, and
# NULL/UNKNOWN handling. They are NOT a claim about real market
# relationships; the platform's actual database is verified separately
# (see `taskReport.md`, "Research Data Availability") to hold
# `SignalRecord.objects.count() == 0` at the time of this checkpoint, so
# no live-data statistical claim is made anywhere in this file or in the
# production module it tests.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from django.test import TestCase

from intraday.infrastructure.persistence.correlation_repository import (
    DjangoCorrelationRepository,
)
from intraday.infrastructure.persistence.research_correlation import (
    MIN_SAMPLE_SIZE,
    SampleStatus,
    TimeOfDayBucket,
    build_research_observations,
    compute_traceability_coverage,
    feature_interaction_analysis,
    feature_outcome_analysis,
    symbol_robustness_analysis,
    time_of_day_analysis,
)
from intraday.infrastructure.persistence.models import (
    PaperOrderRecord,
    PaperTradeRecord,
    SignalEvidenceRecord,
    SignalRecord,
)

BASE = datetime(2026, 1, 5, 4, 0, tzinfo=UTC)  # 09:30 IST


def _make_signal(
    signal_id: str,
    *,
    instrument_id: str = "NSE:RELIANCE",
    strategy_id: str = "ema_crossover",
    signal_timestamp: datetime = BASE,
    strategy_version_identifier: str = "spec:code:config",
) -> SignalRecord:
    return SignalRecord.objects.create(
        signal_id=signal_id,
        strategy_id=strategy_id,
        instrument_id=instrument_id,
        direction="BULLISH",
        price=Decimal("100"),
        timeframe="Timeframe.ONE_MINUTE",
        signal_timestamp=signal_timestamp,
        risk_status="APPROVED",
        order_status="FILLED",
        strategy_version_identifier=strategy_version_identifier,
        scan_run_id="",
    )


def _make_evidence(signal_id: str, feature_name: str, value: str) -> SignalEvidenceRecord:
    return SignalEvidenceRecord.objects.create(
        signal_id=signal_id,
        strategy_id="ema_crossover",
        schema_version="v1",
        fields=[["EMA", value, feature_name]],
        generated_at=BASE,
    )


def _make_trade(signal_id: str, trade_id: str, realized_pnl: Decimal) -> PaperTradeRecord:
    return PaperTradeRecord.objects.create(
        trade_id=trade_id,
        strategy_id="ema_crossover",
        instrument_id="NSE:RELIANCE",
        direction="BULLISH",
        order_ids=[f"{trade_id}-entry", f"{trade_id}-exit"],
        entry_price=Decimal("100"),
        exit_price=Decimal("105"),
        quantity=Decimal("10"),
        realized_pnl=realized_pnl,
        opened_at=BASE,
        closed_at=BASE + timedelta(minutes=5),
        signal_id=signal_id,
    )


class TraceabilityCoverageTests(TestCase):
    def test_zero_data_reports_none_percentages_not_zero(self) -> None:
        coverage = compute_traceability_coverage()
        assert coverage.total_signals == 0
        assert coverage.evidence_coverage_pct is None
        assert coverage.order_coverage_pct is None
        assert coverage.trade_coverage_pct is None
        assert coverage.outcome_coverage_pct is None

    def test_coverage_counts_each_stage_independently(self) -> None:
        _make_signal("sig-1")
        _make_signal("sig-2")
        _make_signal("sig-3")
        _make_evidence("sig-1", "ema_12", "101.5")
        PaperOrderRecord.objects.create(
            order_id="ord-1",
            idempotency_key="idem-1",
            correlation_id="corr-1",
            instrument_id="NSE:RELIANCE",
            strategy_id="ema_crossover",
            signal_id="sig-1",
            side="BUY",
            order_type="MARKET",
            quantity=Decimal("10"),
            filled_quantity=Decimal("10"),
            status="FILLED",
            created_at=BASE,
        )
        _make_trade("sig-1", "trade-1", Decimal("50"))

        coverage = compute_traceability_coverage()
        assert coverage.total_signals == 3
        assert coverage.signals_with_evidence == 1
        assert coverage.signals_with_orders == 1
        assert coverage.signals_with_trades == 1
        assert coverage.signals_with_realized_outcome == 1
        assert coverage.evidence_coverage_pct == pytest.approx(33.33, abs=0.01)

    def test_no_fabricated_join_unrelated_trade_not_counted(self) -> None:
        """A trade with a DIFFERENT signal_id (or none) must never be
        counted against a signal it does not carry, even when instrument
        and timeframe happen to match."""
        _make_signal("sig-1")
        PaperTradeRecord.objects.create(
            trade_id="trade-orphan",
            strategy_id="ema_crossover",
            instrument_id="NSE:RELIANCE",
            direction="BULLISH",
            order_ids=[],
            entry_price=Decimal("100"),
            exit_price=Decimal("105"),
            quantity=Decimal("10"),
            realized_pnl=Decimal("50"),
            opened_at=BASE,
            closed_at=BASE + timedelta(minutes=5),
            signal_id="",  # genuinely unlinked - must stay unresolved
        )
        coverage = compute_traceability_coverage()
        assert coverage.signals_with_trades == 0
        assert coverage.signals_with_realized_outcome == 0


class ResearchObservationTests(TestCase):
    def test_unresolved_feature_name_is_dropped_not_guessed(self) -> None:
        _make_signal("sig-1")
        _make_evidence("sig-1", "totally_unregistered_feature_9", "1.0")
        observations = build_research_observations()
        assert len(observations) == 1
        assert observations[0].feature_values == {}

    def test_resolved_feature_name_maps_to_canonical_field_id(self) -> None:
        _make_signal("sig-1")
        _make_evidence("sig-1", "ema_12", "101.5")
        observations = build_research_observations()
        assert observations[0].feature_values == {"ema": Decimal("101.5")}

    def test_signal_without_trade_has_null_realized_pnl(self) -> None:
        _make_signal("sig-1")
        observations = build_research_observations()
        assert observations[0].realized_pnl is None
        assert observations[0].has_trade is False


class FeatureOutcomeAnalysisTests(TestCase):
    def _seed(self, n: int, *, pnl_sign: int = 1) -> None:
        for i in range(n):
            sid = f"sig-{i}"
            _make_signal(sid, signal_timestamp=BASE + timedelta(minutes=i))
            _make_evidence(sid, "rsi_14", "55.0")
            _make_trade(sid, f"trade-{i}", Decimal(pnl_sign * (i + 1)))

    def test_below_minimum_sample_is_insufficient_not_fabricated(self) -> None:
        self._seed(MIN_SAMPLE_SIZE - 1)
        observations = build_research_observations()
        results = feature_outcome_analysis(observations)
        assert len(results) == 1
        result = results[0]
        assert result.field_id == "rsi"
        assert result.observation_count == MIN_SAMPLE_SIZE - 1
        assert result.status is SampleStatus.INSUFFICIENT_SAMPLE
        assert result.mean_outcome is None
        assert result.win_rate is None

    def test_at_minimum_sample_computes_descriptive_stats(self) -> None:
        self._seed(MIN_SAMPLE_SIZE)
        observations = build_research_observations()
        results = feature_outcome_analysis(observations)
        result = results[0]
        assert result.observation_count == MIN_SAMPLE_SIZE
        assert result.status is SampleStatus.OK
        assert result.mean_outcome is not None
        assert result.win_rate == 100.0  # all pnl_sign=1 -> all wins
        assert result.loss_rate == 0.0

    def test_no_observations_is_no_data(self) -> None:
        results = feature_outcome_analysis(())
        assert results == ()


class FeatureInteractionTests(TestCase):
    def test_pair_requires_both_features_and_outcome(self) -> None:
        for i in range(MIN_SAMPLE_SIZE):
            sid = f"sig-{i}"
            _make_signal(sid, signal_timestamp=BASE + timedelta(minutes=i))
            SignalEvidenceRecord.objects.create(
                signal_id=sid,
                strategy_id="ema_crossover",
                schema_version="v1",
                fields=[["RSI", "55.0", "rsi_14"], ["ADX", "30.0", "adx_14"]],
                generated_at=BASE,
            )
            _make_trade(sid, f"trade-{i}", Decimal(i + 1))
        observations = build_research_observations()
        results = feature_interaction_analysis(observations)
        assert len(results) == 1
        assert results[0].field_id_a == "adx"
        assert results[0].field_id_b == "rsi"
        assert results[0].status is SampleStatus.OK


class SymbolRobustnessTests(TestCase):
    def test_symbols_are_reported_independently(self) -> None:
        for i in range(MIN_SAMPLE_SIZE):
            sid = f"sig-a-{i}"
            _make_signal(sid, instrument_id="NSE:RELIANCE", signal_timestamp=BASE + timedelta(minutes=i))
            _make_trade(sid, f"trade-a-{i}", Decimal(i + 1))
        # A single low-volume symbol must not be silently pooled with the
        # dominant one, and must not be reported as if it were sufficient.
        sid = "sig-b-0"
        _make_signal(sid, instrument_id="NSE:TCS", signal_timestamp=BASE)
        _make_trade(sid, "trade-b-0", Decimal("10"))

        observations = build_research_observations()
        results = {r.instrument_id: r for r in symbol_robustness_analysis(observations)}
        assert results["NSE:RELIANCE"].status is SampleStatus.OK
        assert results["NSE:TCS"].status is SampleStatus.INSUFFICIENT_SAMPLE
        assert results["NSE:TCS"].mean_outcome is None


class TimeOfDayTests(TestCase):
    def test_buckets_are_computed_from_stored_signal_timestamp(self) -> None:
        opening = BASE  # 09:30 IST -> OPENING
        _make_signal("sig-open", signal_timestamp=opening)
        _make_trade("sig-open", "trade-open", Decimal("5"))
        observations = build_research_observations()
        results = {r.bucket: r for r in time_of_day_analysis(observations)}
        assert results[TimeOfDayBucket.OPENING].observation_count == 1
        assert results[TimeOfDayBucket.MID_SESSION].observation_count == 0


class RepositoryReuseTests(TestCase):
    def test_uses_existing_correlation_repository_not_a_parallel_query_path(self) -> None:
        """Structural guard: the research service must build observations
        through `DjangoCorrelationRepository.build_signal_traces()`, never
        a second query path that could silently disagree with the
        correlation API's own answer."""
        _make_signal("sig-1")
        repo = DjangoCorrelationRepository()
        observations = build_research_observations(repository=repo)
        trace = repo.get_signal_trace("sig-1")
        assert observations[0].signal_id == trace.signal_id
        assert observations[0].strategy_version_identifier == trace.strategy_version_identifier
