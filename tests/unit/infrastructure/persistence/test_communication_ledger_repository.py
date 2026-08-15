# tests/unit/infrastructure/persistence/test_communication_ledger_repository.py
#
# Checkpoint 37 Part 7: proves the durable communication ledger
# actually persists and answers "was this signal communicated?" and
# correctly implements the idempotency check.
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from intraday.communication.contracts.signal_communication import (
    CommunicationChannel,
    DeliveryAttempt,
    DeliveryStatus,
    MessageTemplateId,
)
from intraday.infrastructure.persistence.communication_ledger_repository import (
    DjangoCommunicationLedgerRepository,
)
from intraday.infrastructure.persistence.models import CommunicationLedgerRecord

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 1, 5, 5, 0, tzinfo=UTC)


def _attempt(**overrides: object) -> DeliveryAttempt:
    defaults: dict[str, object] = dict(  # noqa: C408
        communication_id=str(uuid.uuid4()),
        signal_id="sig-1",
        event_id="event-1",
        channel=CommunicationChannel.TELEGRAM,
        provider="telegram",
        destination_masked="****abcd",
        template_id=MessageTemplateId.VALIDATED_SIGNAL,
        template_version="v1",
        created_at=NOW,
        attempted_at=NOW,
        delivery_status=DeliveryStatus.SENT,
        provider_message_id="msg-1",
        error_code=None,
        error_message=None,
        retry_count=0,
        correlation_id="corr-1",
    )
    defaults.update(overrides)
    return DeliveryAttempt(**defaults)  # type: ignore[arg-type]


def test_record_attempt_persists_a_row() -> None:
    repo = DjangoCommunicationLedgerRepository()
    attempt = _attempt()
    repo.record_attempt(attempt)

    row = CommunicationLedgerRecord.objects.get(communication_id=attempt.communication_id)
    assert row.signal_id == "sig-1"
    assert row.delivery_status == "SENT"
    assert row.provider_message_id == "msg-1"


def test_no_secret_field_exists_on_the_ledger_model() -> None:
    field_names = {f.name for f in CommunicationLedgerRecord._meta.get_fields()}
    assert "bot_token" not in field_names
    assert "webhook_url" not in field_names
    assert "destination_masked" in field_names
    assert "destination" not in field_names  # never the raw, unmasked destination


def test_already_sent_true_after_a_sent_attempt_same_signal_event_channel() -> None:
    repo = DjangoCommunicationLedgerRepository()
    repo.record_attempt(_attempt())

    assert repo.already_sent(
        signal_id="sig-1", event_id="event-1", channel=CommunicationChannel.TELEGRAM
    )


def test_already_sent_false_for_a_different_event_id() -> None:
    repo = DjangoCommunicationLedgerRepository()
    repo.record_attempt(_attempt())

    assert not repo.already_sent(
        signal_id="sig-1", event_id="event-2", channel=CommunicationChannel.TELEGRAM
    )


def test_already_sent_false_for_a_different_channel() -> None:
    repo = DjangoCommunicationLedgerRepository()
    repo.record_attempt(_attempt())

    assert not repo.already_sent(
        signal_id="sig-1", event_id="event-1", channel=CommunicationChannel.DISCORD
    )


def test_already_sent_false_when_only_skipped_attempts_recorded() -> None:
    """A SKIPPED_NOT_CONFIGURED attempt never actually reached a
    provider - it must not count as "already sent" and block a later,
    genuine attempt."""
    repo = DjangoCommunicationLedgerRepository()
    repo.record_attempt(
        _attempt(delivery_status=DeliveryStatus.SKIPPED_NOT_CONFIGURED, attempted_at=None)
    )

    assert not repo.already_sent(
        signal_id="sig-1", event_id="event-1", channel=CommunicationChannel.TELEGRAM
    )
