# File: src/intraday/infrastructure/persistence/signal_repository.py
#
# Checkpoint 62.x: Django ORM implementation of
# `application.services.paper_signal_execution.SignalRecorder`, plus a
# read side (`list_signals`) for the new signals API view. The FIRST
# persistence for `domain.signal.contracts.Signal` in this project -
# a fresh audit this checkpoint found the domain contract existed with
# no repository and no API anywhere, which would have forced an
# "active signal monitor" UI to either fabricate rows or go unbuilt.
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from intraday.domain.shared_kernel.contracts import InstrumentId, SignalId
from intraday.infrastructure.persistence.models import SignalRecord


@dataclass(frozen=True, slots=True)
class SignalListPage:
    items: tuple[SignalRecord, ...]
    total_count: int
    page: int
    page_size: int


class DjangoSignalRepository:
    """Django ORM implementation. `record_signal()` satisfies
    `PaperSignalExecutionService`'s `SignalRecorder` Protocol
    structurally - never imported by that application-layer module
    directly (`.importlinter` contract 6)."""

    def record_signal(
        self,
        *,
        signal_id: SignalId,
        strategy_id: str,
        instrument_id: InstrumentId,
        direction: str,
        price: Decimal,
        timeframe: str,
        signal_timestamp: dt.datetime,
        risk_status: str,
        risk_reason: str,
        order_status: str,
    ) -> None:
        # `signal_id` is deterministic (same strategy+config+instrument
        # +timeframe+bar-timestamp always derives the same ID,
        # `derive_signal_id()` in `paper_signal_execution.py`) - a
        # duplicate `record_signal()` call for the identical signal
        # (e.g. a scheduler retry) must never create a second row.
        SignalRecord.objects.update_or_create(
            signal_id=str(signal_id),
            defaults={
                "strategy_id": strategy_id,
                "instrument_id": str(instrument_id),
                "direction": direction,
                "price": price,
                "timeframe": timeframe,
                "signal_timestamp": signal_timestamp,
                "risk_status": risk_status,
                "risk_reason": risk_reason,
                "order_status": order_status,
            },
        )

    def list_signals(
        self,
        *,
        page: int = 1,
        page_size: int = 25,
        strategy_id: str | None = None,
        instrument_id: str | None = None,
    ) -> SignalListPage:
        """Read-only, server-side paginated - no existing endpoint in
        this project paginated before this checkpoint (a fresh audit
        confirmed this), so this establishes the pattern rather than
        copying one."""
        queryset = SignalRecord.objects.all()
        if strategy_id:
            queryset = queryset.filter(strategy_id=strategy_id)
        if instrument_id:
            queryset = queryset.filter(instrument_id=instrument_id)

        total_count = queryset.count()
        page = max(page, 1)
        page_size = max(min(page_size, 200), 1)
        start = (page - 1) * page_size
        items = tuple(queryset[start : start + page_size])
        return SignalListPage(items=items, total_count=total_count, page=page, page_size=page_size)
