# File: src/intraday/application/contracts/watchlist_market_data.py
#
# CHECKPOINT-WATCHLIST-A, Phase A of WATCHLIST_REDESIGN_ROADMAP.md:
# wire-facing contracts for the read-only watchlist market-data
# endpoint. Mirrors `screening.py`'s own established "HONEST labeling,
# no field ever fabricated" shape rather than inventing a new one.
#
# `price`/`change_percent`/`volume`/`sparkline` are ALL nullable/empty
# on the wire when the underlying data isn't genuinely available -
# never a fabricated or silently-stale value (the roadmap's own
# explicit requirement, reusing the same discipline
# `ScreeningInstrumentResultSerializer`'s own `NOT_GATE_VERIFIED`
# status established).
from __future__ import annotations

from rest_framework import serializers


class WatchlistInstrumentMarketDataSerializer(serializers.Serializer[None]):
    instrument_id = serializers.CharField()

    # HONEST labeling of the daily-bar (change%/sparkline/historical
    # price) data specifically - independent of whether a LIVE quote
    # happens to be available for this same instrument.
    gate_status = serializers.ChoiceField(choices=["OK", "NOT_GATE_VERIFIED"])
    coverage_detail = serializers.CharField(required=False, allow_blank=True, default="")

    price = serializers.DecimalField(
        max_digits=14, decimal_places=4, allow_null=True, required=False
    )
    # "LIVE" when price came from a genuinely fresh `LiveQuoteObservation`
    # (only possible when a worker is running for this instrument);
    # "HISTORICAL" when it is the latest gate-verified daily close;
    # "" when neither is available - never fabricated.
    price_source = serializers.ChoiceField(
        choices=["LIVE", "HISTORICAL", ""], required=False, default=""
    )

    change_percent = serializers.DecimalField(
        max_digits=10, decimal_places=4, allow_null=True, required=False
    )
    """Always `(latest gate-verified daily close - prior gate-verified
    daily close) / prior close * 100` - "vs. previous close", per the
    roadmap's own explicit convention. `null` whenever `gate_status`
    is `NOT_GATE_VERIFIED` or there is no prior trading day in range."""

    volume = serializers.DecimalField(
        max_digits=18, decimal_places=4, allow_null=True, required=False
    )
    # Per the roadmap's own explicit "never silently conflate
    # session-to-date vs. full-day" instruction: which of the two
    # genuinely different measurements `volume` is.
    volume_basis = serializers.ChoiceField(
        choices=["SESSION_TO_DATE", "HISTORICAL_DAY", ""], required=False, default=""
    )

    sparkline = serializers.ListField(
        child=serializers.DecimalField(max_digits=14, decimal_places=4), required=False, default=list
    )
    """Last N gate-verified daily closes, chronological (oldest first).
    Empty when `gate_status` is `NOT_GATE_VERIFIED`. Historical closes
    only, even when the overall response `mode` is `LIVE` - the
    roadmap's own explicit scope limit (a live intraday chart is a
    separate, larger feature, not this one)."""

    as_of = serializers.CharField()
    """An ISO datetime (LIVE, from the quote's own `source_timestamp`)
    or a plain `"YYYY-MM-DD close"` label (HISTORICAL) - always a
    human-readable statement of what moment this row's price reflects,
    never left implicit."""

    is_stale = serializers.BooleanField(default=False)
    """Only meaningful when `price_source == "LIVE"` - reuses the same
    `is_stale` convention `QuoteResponseSerializer` already has."""


class WatchlistMarketDataResponseSerializer(serializers.Serializer[None]):
    watchlist_name = serializers.CharField()
    # Whole-response default, per the roadmap's own Part 1 item 4
    # reasoning: "LIVE" only when a worker is genuinely running
    # (a lightweight `WorkerRuntimeStatus` check) - "HISTORICAL"
    # is the always-available default with zero live infrastructure
    # running. An individual row can still fall back to HISTORICAL
    # pricing even when the envelope is "LIVE" (see `price_source`
    # above) - this field describes what was ATTEMPTED, not a promise
    # every row succeeded at it. A plain `CharField`, not `ChoiceField`
    # - matches `screening.py`'s own `mode` field convention exactly,
    # which avoids drf-spectacular's shared-enum-name collision a
    # second "mode" `ChoiceField` would otherwise trigger.
    mode = serializers.CharField()
    results = WatchlistInstrumentMarketDataSerializer(many=True)


__all__ = [
    "WatchlistInstrumentMarketDataSerializer",
    "WatchlistMarketDataResponseSerializer",
]
