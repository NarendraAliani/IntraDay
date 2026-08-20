# File: src/intraday/infrastructure/persistence/scanner_configuration_repository.py
#
# Checkpoint 64.4: Django ORM implementation of
# `ScannerConfigurationRepository`. `save()` bumps
# `configuration_version` and writes a durable `AuditLogEntry` in the
# SAME `transaction.atomic()` block, mirroring
# `DjangoRiskConfigurationRepository.activate()`'s own established
# "state change + audit append happen together, or neither does"
# pattern (Checkpoint 12) - never a separate, un-audited write path.
from __future__ import annotations

import datetime as dt

from django.db import transaction

from intraday.application.repositories.scanner_configuration import ScannerConfigurationRecord
from intraday.infrastructure.persistence.models import AuditLogEntry, ScannerConfiguration

_ACTION = "scanner_configuration.update"
_RESOURCE_TYPE = "scanner_configuration"


def _to_record(row: ScannerConfiguration) -> ScannerConfigurationRecord:
    return ScannerConfigurationRecord(
        provider=row.provider,
        enabled=row.enabled,
        timeframe=row.timeframe,
        universe_mode=row.universe_mode,
        selected_instrument_ids=tuple(row.selected_instrument_ids),
        selected_watchlist_name=row.selected_watchlist_name,
        selected_strategy_ids=tuple(row.selected_strategy_ids),
        configuration_version=row.configuration_version,
        requested_by=row.requested_by,
        requested_at=row.requested_at,
        session_started_at=row.session_started_at,
        session_stopped_at=row.session_stopped_at,
    )


def describe_changes(old: ScannerConfiguration, new_values: dict[str, object]) -> str:
    """A short, human-readable "what changed" summary - Checkpoint
    64.4's own explicit "Changed: timeframe 1m -> 5m" example - computed
    generically rather than hand-listing every field at every call
    site. Exposed for the API view to log (structlog, not the audit
    row itself - `AuditLogEntry.request_id` is a UUID-shaped
    correlation field, not free text; cramming a change description
    into it would be exactly the kind of field-repurposing this
    project's own conventions avoid)."""
    changes = []
    for field_name, new_value in new_values.items():
        old_value = getattr(old, field_name)
        if old_value != new_value:
            changes.append(f"{field_name}: {old_value!r} -> {new_value!r}")
    return "; ".join(changes) if changes else "no field changed"


class DjangoScannerConfigurationRepository:
    def get(self, provider: str) -> ScannerConfigurationRecord:
        row, _created = ScannerConfiguration.objects.get_or_create(provider=provider)
        return _to_record(row)

    def save(
        self,
        provider: str,
        *,
        enabled: bool,
        timeframe: str,
        universe_mode: str,
        selected_instrument_ids: list[str],
        selected_watchlist_name: str,
        selected_strategy_ids: list[str],
        requested_by: str,
        requested_by_user_id: int,
        request_id: str,
        action: str = _ACTION,
        session_transition: str | None = None,
    ) -> ScannerConfigurationRecord:
        """Checkpoint 64.14 §10: `action` defaults to the ORIGINAL
        Checkpoint 64.4 label (`"scanner_configuration.update"`) - every
        pre-existing caller (`scanner_configuration_views.py`,
        `scanner_lifecycle_simulation.py`) is unaffected, verified by
        reading both call sites before this change (neither passes
        `action`). Only `live_paper_session.py`'s explicit start/stop
        calls pass a distinguishing label - the smallest architecturally
        correct extension, never a second audit table.

        Checkpoint 64.17 §10: `session_transition` defaults to `None`
        (every pre-existing caller is unaffected, verified the same
        way) - only `live_paper_session.py` passes `"START"`/`"STOP"`."""
        new_values = {
            "enabled": enabled,
            "timeframe": timeframe,
            "universe_mode": universe_mode,
            "selected_instrument_ids": selected_instrument_ids,
            "selected_watchlist_name": selected_watchlist_name,
            "selected_strategy_ids": selected_strategy_ids,
        }
        with transaction.atomic():
            row, _created = ScannerConfiguration.objects.select_for_update().get_or_create(
                provider=provider
            )
            previous_version = str(row.configuration_version)

            for field_name, value in new_values.items():
                setattr(row, field_name, value)
            row.configuration_version += 1
            row.requested_by = requested_by
            if session_transition == "START":
                row.session_started_at = dt.datetime.now(tz=dt.UTC)
                row.session_stopped_at = None
            elif session_transition == "STOP":
                row.session_stopped_at = dt.datetime.now(tz=dt.UTC)
            row.save()

            AuditLogEntry.objects.create(
                occurred_at=dt.datetime.now(tz=dt.UTC),
                actor_username=requested_by,
                actor_user_id=requested_by_user_id,
                action=action,
                resource_type=_RESOURCE_TYPE,
                resource_id=provider,
                version_identifier=str(row.configuration_version),
                previous_version=previous_version,
                outcome="updated",
                request_id=request_id,
            )
        return _to_record(row)


__all__ = ["DjangoScannerConfigurationRepository"]
