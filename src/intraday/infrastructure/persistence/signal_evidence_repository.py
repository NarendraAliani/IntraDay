# File: src/intraday/infrastructure/persistence/signal_evidence_repository.py
#
# Checkpoint 64.18: Django ORM implementation of `SignalEvidenceRepository`
# - mirrors `trade_plan_repository.py`'s own established shape exactly.
from __future__ import annotations

import datetime as dt

from intraday.application.repositories.signal_evidence import (
    SignalEvidenceFieldView,
    SignalEvidenceRecordView,
)
from intraday.infrastructure.persistence.models import SignalEvidenceRecord
from intraday.signal_intelligence.feature_engine.field_registry import resolve_feature_name
from intraday.trading_engine.strategy_execution.evidence import SignalEvidence


def evidence_field_to_view(entry: list[object]) -> SignalEvidenceFieldView:
    """Checkpoint 64.81: reads BOTH persisted shapes.

    - Legacy (pre-64.81) rows are 2-element `[label, value]` lists.
      They stay perfectly readable and simply carry no field identity -
      `feature_name`/`field_id` are `None`. A historical record is
      NEVER back-filled with a guessed identity: nothing in a stored
      label can prove which feature produced it.
    - New rows are 3-element `[label, value, feature_name]`, where the
      third element is `None` for a genuinely non-feature row.

    This is why no data migration accompanies this change: the
    `fields` column is a `JSONField` whose element LENGTH is what
    varies, and both lengths are handled here. `schema_version` is
    deliberately NOT bumped either - the stored shape is a strict
    superset and every existing reader keeps working, which is the
    exact condition `SIGNAL_EVIDENCE_SCHEMA_VERSION`'s own docstring
    sets for leaving it alone ("bumped only if the FIELD SHAPE itself
    changes in a way that would make an already-persisted record
    ambiguous to render" - it does not).
    """
    label = str(entry[0])
    value = str(entry[1])
    raw_name = entry[2] if len(entry) > 2 else None
    feature_name = str(raw_name) if isinstance(raw_name, str) and raw_name else None
    field_id = resolve_feature_name(feature_name).field_id if feature_name is not None else None
    return SignalEvidenceFieldView(
        label=label, value=value, feature_name=feature_name, field_id=field_id
    )


def _to_view(row: SignalEvidenceRecord) -> SignalEvidenceRecordView:
    return SignalEvidenceRecordView(
        signal_id=row.signal_id,
        strategy_id=row.strategy_id,
        schema_version=row.schema_version,
        fields=tuple(evidence_field_to_view(entry) for entry in row.fields),
        generated_at=row.generated_at,
    )


class DjangoSignalEvidenceRepository:
    def save(self, signal_id: str, evidence: SignalEvidence) -> SignalEvidenceRecordView:
        row, _created = SignalEvidenceRecord.objects.update_or_create(
            signal_id=signal_id,
            defaults={
                "strategy_id": evidence.strategy_id,
                "schema_version": evidence.schema_version,
                "fields": [[f.label, f.value, f.feature_name] for f in evidence.fields],
                "generated_at": dt.datetime.now(tz=dt.UTC),
            },
        )
        return _to_view(row)

    def get_by_signal_id(self, signal_id: str) -> SignalEvidenceRecordView | None:
        row = SignalEvidenceRecord.objects.filter(signal_id=signal_id).first()
        return _to_view(row) if row is not None else None


__all__ = ["DjangoSignalEvidenceRepository", "evidence_field_to_view"]
