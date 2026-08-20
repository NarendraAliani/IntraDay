# File: src/intraday/infrastructure/persistence/signal_evidence_repository.py
#
# Checkpoint 64.18: Django ORM implementation of `SignalEvidenceRepository`
# - mirrors `trade_plan_repository.py`'s own established shape exactly.
from __future__ import annotations

import datetime as dt

from intraday.application.repositories.signal_evidence import SignalEvidenceRecordView
from intraday.infrastructure.persistence.models import SignalEvidenceRecord
from intraday.trading_engine.strategy_execution.evidence import SignalEvidence


def _to_view(row: SignalEvidenceRecord) -> SignalEvidenceRecordView:
    return SignalEvidenceRecordView(
        signal_id=row.signal_id,
        strategy_id=row.strategy_id,
        schema_version=row.schema_version,
        fields=tuple((pair[0], pair[1]) for pair in row.fields),
        generated_at=row.generated_at,
    )


class DjangoSignalEvidenceRepository:
    def save(self, signal_id: str, evidence: SignalEvidence) -> SignalEvidenceRecordView:
        row, _created = SignalEvidenceRecord.objects.update_or_create(
            signal_id=signal_id,
            defaults={
                "strategy_id": evidence.strategy_id,
                "schema_version": evidence.schema_version,
                "fields": [[f.label, f.value] for f in evidence.fields],
                "generated_at": dt.datetime.now(tz=dt.UTC),
            },
        )
        return _to_view(row)

    def get_by_signal_id(self, signal_id: str) -> SignalEvidenceRecordView | None:
        row = SignalEvidenceRecord.objects.filter(signal_id=signal_id).first()
        return _to_view(row) if row is not None else None


__all__ = ["DjangoSignalEvidenceRepository"]
