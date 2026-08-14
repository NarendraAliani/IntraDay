# File: src/intraday/application/contracts/backtesting.py
#
# Wire-facing contracts for the Checkpoint 27 backtesting/watchlist/
# strategy-research-status API resources. Nested structures (trades,
# equity curve, metrics, configuration, data-quality disclosure) are
# represented as `JSONField` rather than fully-typed nested serializers
# - the single canonical shape is `research.backtesting.serialization.
# to_json_dict()`'s own dict shape; duplicating that shape field-by-field
# into a second serializer definition here would be exactly the kind of
# redundancy Part 27 forbids. `drf-spectacular` still generates a valid
# (if less granular) OpenAPI schema for `JSONField`.
from __future__ import annotations

from decimal import Decimal

from rest_framework import serializers


class BacktestRunRequestSerializer(serializers.Serializer[None]):
    instrument_id = serializers.CharField()
    timeframe = serializers.CharField()
    start = serializers.DateTimeField()
    end = serializers.DateTimeField()
    strategy_id = serializers.CharField()
    specification_version = serializers.CharField()
    code_version = serializers.CharField()
    configuration_version = serializers.CharField()
    strategy_values = serializers.JSONField()
    initial_capital = serializers.DecimalField(max_digits=18, decimal_places=4)
    position_sizing_mode = serializers.ChoiceField(choices=["FIXED_QUANTITY", "PERCENT_OF_EQUITY"])
    position_size_value = serializers.DecimalField(max_digits=18, decimal_places=6)
    brokerage_percent = serializers.DecimalField(
        max_digits=8, decimal_places=4, default=Decimal("0")
    )
    slippage_percent = serializers.DecimalField(
        max_digits=8, decimal_places=4, default=Decimal("0")
    )
    cost_model_name = serializers.ChoiceField(
        choices=["FLAT_PERCENTAGE", "INDIAN_CASH_EQUITY_INTRADAY"],
        default="FLAT_PERCENTAGE",
        help_text=(
            "FLAT_PERCENTAGE is a MODEL ASSUMPTION (brokerage_percent applied flat). "
            "INDIAN_CASH_EQUITY_INTRADAY is a VERIFIED NSE cash-equity intraday "
            "statutory/exchange cost schedule (STT/exchange charges/SEBI fees/GST/"
            "stamp duty) - see docs/architecture/BACKTESTING_ARCHITECTURE.md."
        ),
    )


class BacktestResultSerializer(serializers.Serializer[None]):
    backtest_id = serializers.CharField()
    generated_at = serializers.DateTimeField()
    configuration = serializers.JSONField()
    trades = serializers.JSONField()
    equity_curve = serializers.JSONField()
    mark_to_market_curve = serializers.JSONField()
    metrics = serializers.JSONField()
    data_quality = serializers.JSONField()
    validation = serializers.JSONField()
    trust_level = serializers.CharField()
    cost_model_identity = serializers.JSONField()


class WatchlistSaveRequestSerializer(serializers.Serializer[None]):
    name = serializers.CharField()
    instrument_ids = serializers.ListField(child=serializers.CharField())


class WatchlistResponseSerializer(serializers.Serializer[None]):
    name = serializers.CharField()
    instrument_ids = serializers.ListField(child=serializers.CharField())


class ResearchStatusResponseSerializer(serializers.Serializer[None]):
    strategy_id = serializers.CharField()
    status = serializers.CharField()


class ResearchStatusUpdateRequestSerializer(serializers.Serializer[None]):
    status = serializers.ChoiceField(choices=["RESEARCH_ACTIVE", "RESEARCH_PAUSED", "DISABLED"])
