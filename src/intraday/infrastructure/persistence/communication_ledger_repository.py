# File: src/intraday/infrastructure/persistence/communication_ledger_repository.py
#
# Checkpoint 37 Part 7: the Django ORM implementation of
# `application.services.signal_communication.CommunicationLedger`.
from __future__ import annotations

from intraday.communication.contracts.signal_communication import (
    CommunicationChannel,
    DeliveryAttempt,
)
from intraday.infrastructure.persistence.models import CommunicationLedgerRecord


class DjangoCommunicationLedgerRepository:
    def record_attempt(self, attempt: DeliveryAttempt) -> None:
        CommunicationLedgerRecord.objects.update_or_create(
            communication_id=attempt.communication_id,
            defaults={
                "signal_id": str(attempt.signal_id),
                "event_id": attempt.event_id,
                "channel": attempt.channel.value,
                "provider": attempt.provider,
                "destination_masked": attempt.destination_masked,
                "template_id": attempt.template_id.value,
                "template_version": attempt.template_version,
                "created_at": attempt.created_at,
                "attempted_at": attempt.attempted_at,
                "delivery_status": attempt.delivery_status.value,
                "provider_message_id": attempt.provider_message_id or "",
                "error_code": attempt.error_code or "",
                "error_message": attempt.error_message or "",
                "retry_count": attempt.retry_count,
                "correlation_id": attempt.correlation_id,
            },
        )

    def already_sent(self, *, signal_id: str, event_id: str, channel: CommunicationChannel) -> bool:
        """A prior SENT (or already-attempted, non-skipped) row for the
        exact same (signal, event, channel) means this is a re-
        evaluation of the SAME lifecycle fact, not a new one - skip it.
        A DIFFERENT `event_id` for the same signal (e.g. VALIDATED_SIGNAL
        then ORDER_FILLED) is a legitimate lifecycle update and is
        never deduplicated by this check."""
        return CommunicationLedgerRecord.objects.filter(
            signal_id=signal_id,
            event_id=event_id,
            channel=channel.value,
            delivery_status__in=["SENT", "FAILED"],
        ).exists()
