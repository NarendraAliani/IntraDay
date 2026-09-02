# File: tests/unit/infrastructure/persistence/test_checkpoint_67_9_audit_schema_constraints.py
#
# Checkpoint 67.9 Part 4 — proves the REAL DB-level uniqueness
# constraints on the new `MigrationRun`/`MigrationUnit`/`MigrationRow`
# tables (`uq_migration_unit_identity` on (migration_id, unit_id),
# `uq_migration_row_identity` on (migration_id, row_id), and
# `migration_id` UNIQUE on `MigrationRun`) actually fire at the
# database level — not merely the in-memory checks
# `migration_audit.py`'s dataclasses already had. Requires real
# PostgreSQL; every row created here lives ONLY in the disposable
# pytest test database (`django_db(transaction=True)`), never
# production.
from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from django.db import IntegrityError, transaction

from intraday.infrastructure.persistence.models import MigrationRow, MigrationRun, MigrationUnit
from tests.postgres_utils import requires_postgres


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_migration_run_id_is_unique() -> None:
    MigrationRun.objects.create(
        migration_id="mig-a",
        migration_version="v1",
        status="PLANNED",
        scope_fingerprint="a" * 64,
        started_at=datetime.now(UTC),
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            MigrationRun.objects.create(
                migration_id="mig-a",  # duplicate - "no two active migrations with the same id"
                migration_version="v2",
                status="PLANNED",
                scope_fingerprint="b" * 64,
                started_at=datetime.now(UTC),
            )


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_migration_unit_identity_uniqueness_is_migration_id_and_unit_id() -> None:
    kwargs = dict(
        migration_id="mig-b",
        unit_id="RELIANCE:5m:2026-01-05",
        instrument_id="NSE:RELIANCE",
        timeframe="5m",
        trading_date=date(2026, 1, 5),
        status="PENDING",
        old_row_count=1,
        new_row_count=1,
        old_scope_fingerprint="a" * 64,
    )
    MigrationUnit.objects.create(**kwargs)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            MigrationUnit.objects.create(**kwargs)  # exact duplicate (migration_id, unit_id)

    # a DIFFERENT migration_id with the SAME unit_id is legal (a unit
    # can be revisited by a later, distinct migration run).
    other = dict(kwargs)
    other["migration_id"] = "mig-b-2"
    MigrationUnit.objects.create(**other)  # must not raise


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_migration_row_identity_uniqueness_is_migration_id_and_row_id() -> None:
    kwargs = dict(
        migration_id="mig-c",
        row_id=42,
        old_timestamp=datetime(2026, 1, 5, 9, 15, tzinfo=UTC),
        new_timestamp=datetime(2026, 1, 5, 9, 20, tzinfo=UTC),
        source_semantics="OPEN",
        proof_scope="RELIANCE/5m/2026-01-05",
        status="COMMITTED",
    )
    MigrationRow.objects.create(**kwargs)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            MigrationRow.objects.create(**kwargs)

    other = dict(kwargs)
    other["migration_id"] = "mig-c-2"
    MigrationRow.objects.create(**other)  # different migration_id, same row_id - legal
