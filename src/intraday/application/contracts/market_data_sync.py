# File: src/intraday/application/contracts/market_data_sync.py
#
# DRF serializers for the manual historical-market-data-sync resource
# (the Settings page's "fetch real data from Dhan into the database"
# trigger) - mirrors `application/contracts/backtesting.py`'s own
# request/created/progress serializer shapes for the analogous
# `BacktestRun` resource.
from __future__ import annotations

from rest_framework import serializers


class MarketDataSyncRunRequestSerializer(serializers.Serializer[None]):
    instrument_ids = serializers.ListField(child=serializers.CharField(), min_length=1)
    timeframe = serializers.CharField()
    start_date = serializers.DateField()
    end_date = serializers.DateField()


class MarketDataSyncRunCreatedSerializer(serializers.Serializer[None]):
    run_id = serializers.CharField()


class MarketDataSyncRunProgressSerializer(serializers.Serializer[None]):
    run_id = serializers.CharField()
    status = serializers.CharField()
    progress_percent = serializers.FloatField()
    current_instrument = serializers.CharField()
    message = serializers.CharField()
    total_instruments = serializers.IntegerField()
    completed_instruments = serializers.IntegerField()
    bars_fetched = serializers.IntegerField()
    bars_persisted = serializers.IntegerField()
    cache_hits = serializers.IntegerField()
    api_requests = serializers.IntegerField()
    failed_instruments = serializers.JSONField()
    created_at = serializers.DateTimeField()
    started_at = serializers.DateTimeField(allow_null=True)
    completed_at = serializers.DateTimeField(allow_null=True)


__all__ = [
    "MarketDataSyncRunRequestSerializer",
    "MarketDataSyncRunCreatedSerializer",
    "MarketDataSyncRunProgressSerializer",
]
