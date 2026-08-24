# File: src/intraday/infrastructure/persistence/paper_session_repository.py
#
# Checkpoint 64.68 §18: the Django implementation of
# `application.repositories.paper_session.PaperSessionRepository`.
# Mirrors `scanner_configuration_repository.py`'s own shape exactly -
# a thin ORM <-> frozen-dataclass translator with no business logic.
from __future__ import annotations

from decimal import Decimal

from intraday.application.repositories.paper_session import PaperSessionRecord
from intraday.infrastructure.persistence.models import PaperTradingSessionRecord


class DjangoPaperSessionRepository:
    """Structurally implements `PaperSessionRepository`."""

    def get(self, session_id: str) -> PaperSessionRecord | None:
        row = PaperTradingSessionRecord.objects.filter(session_id=session_id).first()
        return None if row is None else _to_record(row)

    def save(self, record: PaperSessionRecord) -> PaperSessionRecord:
        row, _created = PaperTradingSessionRecord.objects.update_or_create(
            session_id=record.session_id,
            defaults={
                "status": record.status,
                "strategy_id": record.strategy_id,
                "timeframe": record.timeframe,
                "instrument_ids": list(record.instrument_ids),
                "starting_capital": record.starting_capital,
                "quantity": record.quantity,
                "replay_date": record.replay_date,
                "replay_cursor": record.replay_cursor,
                "replay_total_steps": record.replay_total_steps,
                "playback_speed": record.playback_speed,
                "last_error": record.last_error,
            },
        )
        row.refresh_from_db()
        return _to_record(row)

    def list_all(self) -> tuple[PaperSessionRecord, ...]:
        return tuple(
            _to_record(row) for row in PaperTradingSessionRecord.objects.order_by("-updated_at")
        )


def _to_record(row: PaperTradingSessionRecord) -> PaperSessionRecord:
    return PaperSessionRecord(
        session_id=row.session_id,
        status=row.status,
        strategy_id=row.strategy_id,
        timeframe=row.timeframe,
        instrument_ids=tuple(str(i) for i in row.instrument_ids),
        starting_capital=Decimal(str(row.starting_capital)),
        quantity=Decimal(str(row.quantity)),
        replay_date=row.replay_date,
        replay_cursor=row.replay_cursor,
        replay_total_steps=row.replay_total_steps,
        playback_speed=row.playback_speed,
        created_at=row.created_at,
        updated_at=row.updated_at,
        last_error=row.last_error,
    )


__all__ = ["DjangoPaperSessionRepository"]
