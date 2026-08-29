# File: src/intraday/infrastructure/market_data_providers/synthetic_historical.py
#
# Checkpoint 63.x Phase 5: the "HISTORICAL API" step of the DB-first
# pipeline.
#
# HONEST DISCLOSURE (read before reusing this anywhere else): this
# codebase has NO real Dhan historical-candle integration. The prior
# checkpoint's own deep audit confirmed it explicitly — grepping
# `infrastructure/brokers/dhan/` and `infrastructure/market_data_providers/
# dhan/` for "historical" returns nothing; only LIVE quote/WebSocket
# ingestion exists there. Building a genuine Dhan historical-candle REST
# adapter is real, separate broker-integration work (auth, rate limits,
# response-shape mapping, live credentials) that this checkpoint's PoC
# scope does not include.
#
# What this class IS: a deterministic, seeded, plausible-OHLCV generator
# that satisfies the exact same `HistoricalBarProvider` Protocol a real
# Dhan adapter eventually would — so the DB-first coverage/fetch/persist/
# scan PIPELINE around it (coverage detection, gap-filling, upsert,
# provenance tracking, partial-failure handling, the DB-only-after-
# preparation guarantee) can be built and PROVEN correct now, honestly,
# without waiting on real broker historical-API access. Swapping this
# for a real Dhan adapter later is a single-class substitution — nothing
# above this Protocol boundary (coverage service, preparation service,
# orchestrator, API, frontend) needs to change.
#
# `is_available` is the deliberate failure-injection switch Phase 6/23's
# acceptance tests need ("API = unavailable") — a real adapter's
# equivalent failure mode would be a network/HTTP exception; this is the
# fixture-adapter equivalent, mirroring `FixtureHistoricalMarketDataRepository`'s
# own "deterministic, injectable" precedent.
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from intraday.domain.market_data.contracts import Bar
from intraday.domain.market_data.provenance import PROVENANCE_SYNTHETIC_TEST
from intraday.domain.market_data.quality import expected_bar_timestamps
from intraday.domain.session.calendar import build_session_for, is_trading_day
from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe


class HistoricalBarProviderUnavailableError(RuntimeError):
    """Raised when the historical data provider cannot serve a request —
    the ONLY signal `HistoricalDataPreparationService` treats as "this
    instrument's fetch failed," never a silently-empty bar tuple."""


def _seed(instrument_id: InstrumentId, timeframe: Timeframe, ts: datetime) -> int:
    """A bar's synthetic price is a pure function of its own identity —
    deterministic and reproducible (re-fetching the same bar always
    produces the same OHLCV), never randomly regenerated on every call,
    so re-running an already-fetched range is safe and idempotent."""
    digest = hashlib.sha256(
        f"{instrument_id}|{timeframe.value}|{ts.isoformat()}".encode()
    ).hexdigest()
    return int(digest[:8], 16)


def _synthetic_bar(instrument_id: InstrumentId, timeframe: Timeframe, ts: datetime) -> Bar:
    seed = _seed(instrument_id, timeframe, ts)
    base = Decimal(100 + (seed % 900))  # 100.00 - 999.xx, plausible NSE cash-equity range
    wobble = Decimal(seed % 200) / Decimal(100)  # 0.00 - 1.99
    open_price = base
    close_price = base + wobble - Decimal("1.00")
    high_price = max(open_price, close_price) + Decimal(seed % 50) / Decimal(100)
    low_price = min(open_price, close_price) - Decimal(seed % 50) / Decimal(100)
    volume = Decimal(1000 + (seed % 50000))
    return Bar(
        instrument_id=instrument_id,
        timeframe=timeframe,
        timestamp=ts,
        open=open_price.quantize(Decimal("0.01")),
        high=high_price.quantize(Decimal("0.01")),
        low=low_price.quantize(Decimal("0.01")),
        close=close_price.quantize(Decimal("0.01")),
        volume=volume,
    )


@dataclass
class SyntheticHistoricalBarProvider:
    """Satisfies the `HistoricalBarProvider` Protocol
    (`application.services.historical_data_preparation`). See module
    docstring above for the honest scope disclosure — NOT a real broker
    integration."""

    is_available: bool = True
    fetch_call_count: int = field(default=0, init=False)
    provenance: str = field(default=PROVENANCE_SYNTHETIC_TEST, init=False)
    """Checkpoint 65.12: this provider is ALWAYS `SYNTHETIC_TEST` — see
    module docstring above. `HistoricalDataPreparationService` reads
    this attribute to stamp `HistoricalBar.provenance` per-provider
    (fixing 65.01's root-cause bug #1: every provider used to write the
    same provenance label regardless of which one actually ran)."""

    def fetch(
        self,
        instrument_id: InstrumentId,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
    ) -> tuple[Bar, ...]:
        self.fetch_call_count += 1
        if not self.is_available:
            raise HistoricalBarProviderUnavailableError(
                f"synthetic historical provider unavailable for {instrument_id} {timeframe.value}"
            )
        bars: list[Bar] = []
        current_date: date = start.date()
        end_date: date = end.date()
        while current_date <= end_date:
            if is_trading_day(current_date):
                session = build_session_for(current_date, end)
                for ts in expected_bar_timestamps(session, timeframe):
                    if start <= ts <= end:
                        bars.append(_synthetic_bar(instrument_id, timeframe, ts))
            current_date += timedelta(days=1)
        return tuple(bars)


__all__ = ["SyntheticHistoricalBarProvider", "HistoricalBarProviderUnavailableError"]
