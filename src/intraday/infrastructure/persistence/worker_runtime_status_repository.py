# File: src/intraday/infrastructure/persistence/worker_runtime_status_repository.py
#
# Checkpoint 64.3: Django ORM implementation of
# `WorkerRuntimeStatusRepository` - mirrors
# `DjangoProviderConnectionStatusRepository`'s own established
# get_or_create-and-update pattern exactly.
from __future__ import annotations

from datetime import datetime

from intraday.application.repositories.worker_runtime_status import (
    WorkerRuntimeStatusRecord,
    WorkerStopRequest,
)
from intraday.infrastructure.persistence.models import WorkerRuntimeStatus


class DjangoWorkerRuntimeStatusRepository:
    def get(self, provider: str) -> WorkerRuntimeStatusRecord | None:
        row = WorkerRuntimeStatus.objects.filter(provider=provider).first()
        if row is None:
            return None
        return WorkerRuntimeStatusRecord(
            provider=row.provider,
            worker_state=row.worker_state,
            token_state=row.token_state,
            watchdog_state=row.watchdog_state,
            last_packet_at=row.last_packet_at,
            last_bar_at=row.last_bar_at,
            reconnect_count=row.reconnect_count,
            consecutive_failures=row.consecutive_failures,
            subscribed_instrument_count=row.subscribed_instrument_count,
            last_error_safe=row.last_error_safe,
            updated_at=row.updated_at,
            effective_configuration_version=row.effective_configuration_version,
            effective_timeframe=row.effective_timeframe,
            effective_strategy_ids=tuple(row.effective_strategy_ids),
            effective_universe_requested_count=row.effective_universe_requested_count,
            effective_universe_subscribed_count=row.effective_universe_subscribed_count,
        )

    def save(
        self,
        provider: str,
        *,
        worker_state: str,
        token_state: str,
        watchdog_state: str,
        last_packet_at: datetime | None,
        last_bar_at: datetime | None,
        reconnect_count: int,
        consecutive_failures: int,
        subscribed_instrument_count: int,
        last_error_safe: str,
    ) -> None:
        WorkerRuntimeStatus.objects.update_or_create(
            provider=provider,
            defaults={
                "worker_state": worker_state,
                "token_state": token_state,
                "watchdog_state": watchdog_state,
                "last_packet_at": last_packet_at,
                "last_bar_at": last_bar_at,
                "reconnect_count": reconnect_count,
                "consecutive_failures": consecutive_failures,
                "subscribed_instrument_count": subscribed_instrument_count,
                "last_error_safe": last_error_safe,
            },
        )

    # Checkpoint 64.73: process-independent stop request. Deliberately
    # `update_or_create` on the SAME provider row the worker already
    # owns - no second table, no PID file, no control endpoint.
    def request_stop(
        self, provider: str, *, requested_at: datetime, requested_by: str, reason_safe: str
    ) -> None:
        WorkerRuntimeStatus.objects.update_or_create(
            provider=provider,
            defaults={
                "stop_requested_at": requested_at,
                "stop_requested_by": requested_by,
                "stop_reason_safe": reason_safe,
            },
        )

    def get_stop_request(self, provider: str) -> WorkerStopRequest | None:
        row = WorkerRuntimeStatus.objects.filter(provider=provider).first()
        if row is None or row.stop_requested_at is None:
            return None
        return WorkerStopRequest(
            provider=row.provider,
            requested_at=row.stop_requested_at,
            requested_by=row.stop_requested_by,
            reason_safe=row.stop_reason_safe,
        )

    def clear_stop_request(self, provider: str) -> None:
        WorkerRuntimeStatus.objects.filter(provider=provider).update(
            stop_requested_at=None, stop_requested_by="", stop_reason_safe=""
        )

    def save_effective_scanner_state(
        self,
        provider: str,
        *,
        effective_configuration_version: int,
        effective_timeframe: str,
        effective_strategy_ids: list[str],
        effective_universe_requested_count: int,
        effective_universe_subscribed_count: int,
    ) -> None:
        WorkerRuntimeStatus.objects.update_or_create(
            provider=provider,
            defaults={
                "effective_configuration_version": effective_configuration_version,
                "effective_timeframe": effective_timeframe,
                "effective_strategy_ids": effective_strategy_ids,
                "effective_universe_requested_count": effective_universe_requested_count,
                "effective_universe_subscribed_count": effective_universe_subscribed_count,
            },
        )


__all__ = ["DjangoWorkerRuntimeStatusRepository"]
