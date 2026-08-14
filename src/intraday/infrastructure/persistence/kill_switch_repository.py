# File: src/intraday/infrastructure/persistence/kill_switch_repository.py
#
# Checkpoint 34 Part 11: Django ORM implementation of
# `application.repositories.kill_switch.KillSwitchRepository`. Singleton
# (`get_or_create(pk=1)`, matching every other singleton state model in
# this project). Every state change is audited via the existing
# append-only `AuditLogEntry` (Checkpoint 12) - engage AND reset both
# write a new audit row; neither ever deletes or overwrites history.
from __future__ import annotations

import datetime as dt

from django.db import transaction

from intraday.domain.risk.contracts import TradingHaltState, TradingHaltStatus
from intraday.infrastructure.persistence.models import AuditLogEntry, KillSwitchState


class DjangoKillSwitchRepository:
    """Django ORM implementation of `KillSwitchRepository`."""

    def _singleton(self) -> KillSwitchState:
        row, _created = KillSwitchState.objects.get_or_create(pk=1)
        return row

    def get(self) -> TradingHaltState:
        row = self._singleton()
        if row.enabled:
            return TradingHaltState(
                status=TradingHaltStatus.HALTED,
                reason=row.reason or "Kill switch engaged.",
                changed_at=row.changed_at,
            )
        return TradingHaltState(
            status=TradingHaltStatus.ACTIVE,
            reason=None,
            changed_at=row.changed_at,
        )

    @transaction.atomic
    def engage(
        self, *, reason: str, actor: str, actor_user_id: int, request_id: str
    ) -> TradingHaltState:
        now = dt.datetime.now(tz=dt.UTC)
        row = self._singleton()
        row.enabled = True
        row.reason = reason
        row.actor_username = actor
        row.changed_at = now
        row.save()
        AuditLogEntry.objects.create(
            occurred_at=now,
            actor_username=actor,
            actor_user_id=actor_user_id,
            action="kill_switch.engaged",
            resource_type="kill_switch",
            resource_id="global",
            version_identifier=str(row.pk),
            previous_version=None,
            outcome="engaged",
            request_id=request_id,
        )
        return self.get()

    @transaction.atomic
    def reset(self, *, actor: str, actor_user_id: int, request_id: str) -> TradingHaltState:
        now = dt.datetime.now(tz=dt.UTC)
        row = self._singleton()
        row.enabled = False
        row.actor_username = actor
        row.changed_at = now
        row.save()
        AuditLogEntry.objects.create(
            occurred_at=now,
            actor_username=actor,
            actor_user_id=actor_user_id,
            action="kill_switch.reset",
            resource_type="kill_switch",
            resource_id="global",
            version_identifier=str(row.pk),
            previous_version=None,
            outcome="reset",
            request_id=request_id,
        )
        return self.get()
