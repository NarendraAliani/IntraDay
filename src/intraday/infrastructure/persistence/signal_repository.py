# File: src/intraday/infrastructure/persistence/signal_repository.py
#
# Checkpoint 62.x: Django ORM implementation of
# `application.services.paper_signal_execution.SignalRecorder`, plus a
# read side (`list_signals`) for the signals API view. The FIRST
# persistence for `domain.signal.contracts.Signal` in this project -
# a fresh audit this checkpoint found the domain contract existed with
# no repository and no API anywhere, which would have forced an
# "active signal monitor" UI to either fabricate rows or go unbuilt.
#
# Checkpoint 64.9: `list_signals()` now enriches each signal with its
# real TradePlan (Checkpoint 64.7) and per-channel communication status
# (Checkpoint 37's Communication Engine) via two bulk queries against
# the SAME already-persisted tables - never a third, competing
# "signal operations" table. `TradePlanEnrichment`/`ChannelStatus` are
# read-side view objects only, not new domain concepts.
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from intraday.domain.shared_kernel.contracts import InstrumentId, SignalId
from intraday.infrastructure.persistence.models import (
    CommunicationLedgerRecord,
    SignalRecord,
    TradePlanRecord,
)

_SORT_FIELDS = {
    "newest": "-signal_timestamp",
    "oldest": "signal_timestamp",
    "strategy": "strategy_id",
    "stock": "instrument_id",
    "risk_status": "risk_status",
}


@dataclass(frozen=True, slots=True)
class TradePlanEnrichment:
    entry_price: Decimal | None
    stop_loss: Decimal | None
    target_1: Decimal | None
    target_2: Decimal | None
    target_3: Decimal | None
    trailing_stop_loss: Decimal | None
    calculation_method: str


@dataclass(frozen=True, slots=True)
class ChannelStatus:
    """The MOST RECENT `CommunicationLedgerRecord` for one (signal,
    channel) pair - "current status," not a full attempt history (the
    signal detail view queries the full history separately when
    needed)."""

    status: str
    attempted_at: dt.datetime | None
    delivered_at: dt.datetime | None
    retry_count: int
    error_message: str


@dataclass(frozen=True, slots=True)
class EnrichedSignal:
    record: SignalRecord
    trade_plan: TradePlanEnrichment | None
    telegram: ChannelStatus | None
    discord: ChannelStatus | None


@dataclass(frozen=True, slots=True)
class SignalListPage:
    items: tuple[EnrichedSignal, ...]
    total_count: int
    page: int
    page_size: int


def _latest_ledger_rows(signal_ids: list[str]) -> dict[tuple[str, str], CommunicationLedgerRecord]:
    """One (signal_id, channel) -> its most recent ledger row (by
    `created_at`), across ALL configured channels for these signals -
    a signal may have retried, so this is deliberately "latest," never
    "first" or "any."""
    rows = CommunicationLedgerRecord.objects.filter(signal_id__in=signal_ids).order_by(
        "signal_id", "channel", "-created_at"
    )
    latest: dict[tuple[str, str], CommunicationLedgerRecord] = {}
    for row in rows:
        key = (row.signal_id, row.channel)
        if (
            key not in latest
        ):  # first seen per (signal_id, channel) is the latest, given the order_by
            latest[key] = row
    return latest


def _to_channel_status(row: CommunicationLedgerRecord | None) -> ChannelStatus | None:
    if row is None:
        return None
    return ChannelStatus(
        status=row.delivery_status,
        attempted_at=row.attempted_at,
        delivered_at=row.attempted_at if row.delivery_status == "SENT" else None,
        retry_count=row.retry_count,
        error_message=row.error_message,
    )


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
        timeframe: str | None = None,
        direction: str | None = None,
        risk_status: str | None = None,
        order_status: str | None = None,
        date_from: dt.datetime | None = None,
        date_to: dt.datetime | None = None,
        telegram_status: str | None = None,
        discord_status: str | None = None,
        sort: str = "newest",
    ) -> SignalListPage:
        """Read-only, server-side paginated - filters map directly to
        real query parameters, never a client-side-only filter over an
        already-fetched array (the Active Signal Monitor UI's controls
        bind to every one of these). `telegram_status`/`discord_status`
        filter on the MOST RECENT ledger row per channel (see
        `_latest_ledger_rows`) - applied in Python after the base
        queryset is evaluated, since "most recent per channel" is not a
        single-table condition; acceptable at this project's current
        data volumes (never used for an unbounded historical query -
        every caller of this repository already page-limits)."""
        queryset = SignalRecord.objects.all()
        if strategy_id:
            queryset = queryset.filter(strategy_id=strategy_id)
        if instrument_id:
            queryset = queryset.filter(instrument_id=instrument_id)
        if timeframe:
            queryset = queryset.filter(timeframe=timeframe)
        if direction:
            queryset = queryset.filter(direction=direction)
        if risk_status:
            queryset = queryset.filter(risk_status=risk_status)
        if order_status:
            queryset = queryset.filter(order_status=order_status)
        if date_from:
            queryset = queryset.filter(signal_timestamp__gte=date_from)
        if date_to:
            queryset = queryset.filter(signal_timestamp__lte=date_to)
        queryset = queryset.order_by(_SORT_FIELDS.get(sort, _SORT_FIELDS["newest"]))

        if telegram_status or discord_status:
            candidate_ids = list(queryset.values_list("signal_id", flat=True))
            latest = _latest_ledger_rows(candidate_ids)
            keep: set[str] = set()
            for signal_id in candidate_ids:
                telegram_row = latest.get((signal_id, "TELEGRAM"))
                discord_row = latest.get((signal_id, "DISCORD"))
                if telegram_status and (
                    telegram_row is None or telegram_row.delivery_status != telegram_status
                ):
                    continue
                if discord_status and (
                    discord_row is None or discord_row.delivery_status != discord_status
                ):
                    continue
                keep.add(signal_id)
            queryset = queryset.filter(signal_id__in=keep)

        total_count = queryset.count()
        page = max(page, 1)
        page_size = max(min(page_size, 200), 1)
        start = (page - 1) * page_size
        records = list(queryset[start : start + page_size])

        signal_ids = [r.signal_id for r in records]
        plans = {p.signal_id: p for p in TradePlanRecord.objects.filter(signal_id__in=signal_ids)}
        ledger = _latest_ledger_rows(signal_ids)

        items = tuple(
            EnrichedSignal(
                record=record,
                trade_plan=(
                    TradePlanEnrichment(
                        entry_price=plans[record.signal_id].entry_price,
                        stop_loss=plans[record.signal_id].stop_loss,
                        target_1=plans[record.signal_id].target_1,
                        target_2=plans[record.signal_id].target_2,
                        target_3=plans[record.signal_id].target_3,
                        trailing_stop_loss=plans[record.signal_id].trailing_stop_loss,
                        calculation_method=plans[record.signal_id].calculation_method,
                    )
                    if record.signal_id in plans
                    else None
                ),
                telegram=_to_channel_status(ledger.get((record.signal_id, "TELEGRAM"))),
                discord=_to_channel_status(ledger.get((record.signal_id, "DISCORD"))),
            )
            for record in records
        )
        return SignalListPage(items=items, total_count=total_count, page=page, page_size=page_size)

    def get_signal_communication_history(
        self, signal_id: str
    ) -> tuple[CommunicationLedgerRecord, ...]:
        """Every attempt (not just the latest) for ONE signal - used by
        the signal detail screen's full communication trace, never by
        the list view (which only needs "current status")."""
        return tuple(
            CommunicationLedgerRecord.objects.filter(signal_id=signal_id).order_by(
                "channel", "-created_at"
            )
        )


__all__ = [
    "ChannelStatus",
    "DjangoSignalRepository",
    "EnrichedSignal",
    "SignalListPage",
    "TradePlanEnrichment",
]
