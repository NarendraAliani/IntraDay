# File: src/intraday/application/services/migration_advisory_lock.py
#
# Checkpoint 67.7 Part 2 — a PostgreSQL advisory-lock helper keyed
# deterministically from `(instrument_id, timeframe)`, transaction
# scoped, meant to serialize the migration runner against
# `DjangoHistoricalBarRepository.bulk_upsert` (the live ingestion
# writer identified in Part 1's inventory) for the SAME
# instrument/timeframe.
#
# THIS CHECKPOINT'S DRY-RUN RUNNER NEVER CALLS `pg_advisory_xact_lock`
# FOR REAL — see `migration_dry_run.py`'s own docstring for why:
# acquiring a real Postgres advisory lock requires a live DB
# connection and a transaction, and this checkpoint's dry-run path is
# deliberately built to run with NO write-capable connection at all
# (Part 5's fail-closed safety guard). `historical_migration_lock_key`
# below is a PURE function (no DB call) so it can be tested and so the
# dry-run runner can report "this is the lock key a real commit run
# WOULD acquire" without needing a database transaction to prove it.
#
# PART 2's ORIGINAL 67.7 FINDING (now CLOSED by Checkpoint 67.8 Part 1):
# the live ingestion writer, `DjangoHistoricalBarRepository.bulk_upsert()`
# (`infrastructure/persistence/historical_bar_repository.py`), used to
# go straight to `HistoricalBar.objects.bulk_create(...,
# update_conflicts=True)` with no locking of any kind beyond Postgres's
# own row-level `ON CONFLICT` semantics — a real, named bypass of this
# lock. As of 67.8, `bulk_upsert()` groups its incoming bars by
# `(instrument_id, timeframe)` and wraps EACH group's `bulk_create`
# call in `acquire_historical_bar_migration_lock(instrument_id,
# timeframe)` below — the exact same function, same key derivation,
# used here unmodified. This closes the gap narrowly: no new lock
# scheme, no application-thread mutex, no change to upsert semantics or
# conflict-resolution fields, only the addition of the lock acquisition
# around the existing write. See `historical_bar_repository.py`'s
# module docstring for the exact mechanism and
# `tests/unit/infrastructure/persistence/test_historical_bar_repository.py`
# / the 67.8 concurrency test for proof that a concurrent migration
# commit and a concurrent `bulk_upsert()` for the SAME instrument/
# timeframe now serialize, while DIFFERENT instrument/timeframe pairs
# still do not block each other.
from __future__ import annotations

import zlib
from contextlib import contextmanager
from typing import Iterator

from django.db import connection, transaction

from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe

_LOCK_NAMESPACE = "intraday.historical_bar.migration"


def historical_migration_lock_key(instrument_id: InstrumentId, timeframe: Timeframe) -> int:
    """Deterministic PostgreSQL advisory-lock key (a signed 32-bit int,
    the single-argument `pg_advisory_xact_lock(key int)` form) derived
    ONLY from `(instrument_id, timeframe)` — the same two dimensions
    every `HistoricalBar` writer keys its upsert identity on (alongside
    `bar_timestamp`, which is deliberately EXCLUDED from the lock key:
    the lock must cover the whole instrument/timeframe stream, not one
    bar, so a migration touching bar N and an ingestion upsert touching
    bar M of the SAME instrument/timeframe still serialize against each
    other). Pure function — no DB call, safe to call from a read-only
    dry-run context and to unit test directly."""
    payload = f"{_LOCK_NAMESPACE}:{instrument_id}:{timeframe.value}".encode("utf-8")
    unsigned = zlib.crc32(payload)
    # pg_advisory_xact_lock(int) takes a signed 32-bit integer; crc32
    # returns unsigned 32-bit - fold into the signed range rather than
    # risk a driver-level overflow error.
    return unsigned - (1 << 32) if unsigned >= (1 << 31) else unsigned


@contextmanager
def acquire_historical_bar_migration_lock(
    instrument_id: InstrumentId, timeframe: Timeframe
) -> Iterator[int]:
    """Transaction-scoped: acquires `pg_advisory_xact_lock(key)` inside
    `transaction.atomic()`, which Postgres releases automatically at
    COMMIT or ROLLBACK — never held past the transaction boundary.

    NOT CALLED ANYWHERE by this checkpoint's dry-run runner (see module
    docstring) — provided so a FUTURE real (write-capable) migration
    commit path has a ready-made, tested lock primitive, and so this
    checkpoint's tests can prove the key is deterministic and that two
    different (instrument, timeframe) pairs never collide by
    construction-testable properties, without requiring this dry-run
    checkpoint to open a write transaction against `HistoricalBar`."""
    key = historical_migration_lock_key(instrument_id, timeframe)
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [key])
        yield key


__all__ = [
    "historical_migration_lock_key",
    "acquire_historical_bar_migration_lock",
]
