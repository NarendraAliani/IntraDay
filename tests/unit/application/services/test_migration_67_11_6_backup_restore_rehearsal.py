# File: tests/unit/application/services/test_migration_67_11_6_backup_restore_rehearsal.py
#
# Checkpoint 67.11.6 Part 10 -- backup RESTORE rehearsal, disposable
# PostgreSQL ONLY (the pytest-django per-session `test_<POSTGRES_DB>`
# database, created and torn down by the test runner -- never the real
# dev/"production" database this checkpoint applied migration 0041 to).
#
# Loads the immutable canary backup produced by Part 8/9
# (artifacts/canary_backup_67_11_6.json) and restores every row into an
# ISOLATED table (a throwaway HistoricalBar-shaped table created here,
# never `persistence_historicalbar` itself) inside the disposable test
# database, then verifies exact field-by-field preservation against the
# backup file. This never writes to production and never overwrites any
# existing row anywhere.
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from tests.postgres_utils import requires_postgres

BACKUP_PATH = Path(r"D:\IntraDay\artifacts\canary_backup_67_11_6.json")


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_canary_backup_restores_with_exact_field_preservation_in_disposable_db() -> None:
    from django.db import connection

    assert BACKUP_PATH.exists(), "canary backup export must exist before rehearsing restore"
    backup = json.loads(BACKUP_PATH.read_text(encoding="utf-8"))
    rows = backup["rows"]
    assert len(rows) == backup["row_count"] > 0

    with connection.cursor() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS canary_restore_rehearsal_67_11_6 (
                id BIGINT PRIMARY KEY,
                instrument_id VARCHAR(100),
                exchange VARCHAR(20),
                symbol VARCHAR(40),
                timeframe VARCHAR(8),
                bar_timestamp TIMESTAMPTZ,
                open_price NUMERIC(18,4),
                high_price NUMERIC(18,4),
                low_price NUMERIC(18,4),
                close_price NUMERIC(18,4),
                volume NUMERIC(18,4),
                source VARCHAR(40),
                provenance VARCHAR(40),
                source_timestamp_semantics VARCHAR(20),
                canonicalization_state VARCHAR(40)
            )
            """
        )
        for r in rows:
            c.execute(
                """
                INSERT INTO canary_restore_rehearsal_67_11_6
                (id, instrument_id, exchange, symbol, timeframe, bar_timestamp,
                 open_price, high_price, low_price, close_price, volume, source,
                 provenance, source_timestamp_semantics, canonicalization_state)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                [
                    r["id"], r["instrument_id"], r["exchange"], r["symbol"], r["timeframe"],
                    r["bar_timestamp"], r["open_price"], r["high_price"], r["low_price"],
                    r["close_price"], r["volume"], r["source"], r["provenance"],
                    r["source_timestamp_semantics"], r["canonicalization_state"],
                ],
            )

        c.execute(
            "SELECT id, instrument_id, exchange, symbol, timeframe, bar_timestamp, "
            "open_price, high_price, low_price, close_price, volume, source, "
            "provenance, source_timestamp_semantics, canonicalization_state "
            "FROM canary_restore_rehearsal_67_11_6 ORDER BY id"
        )
        restored = c.fetchall()

    assert len(restored) == len(rows)
    for restored_row, backup_row in zip(restored, rows, strict=True):
        assert restored_row[0] == backup_row["id"]
        assert restored_row[1] == backup_row["instrument_id"]
        assert restored_row[2] == backup_row["exchange"]
        assert restored_row[3] == backup_row["symbol"]
        assert restored_row[4] == backup_row["timeframe"]
        assert restored_row[5].isoformat() == backup_row["bar_timestamp"]
        assert Decimal(restored_row[6]) == Decimal(backup_row["open_price"])
        assert Decimal(restored_row[7]) == Decimal(backup_row["high_price"])
        assert Decimal(restored_row[8]) == Decimal(backup_row["low_price"])
        assert Decimal(restored_row[9]) == Decimal(backup_row["close_price"])
        assert Decimal(restored_row[10]) == Decimal(backup_row["volume"])
        assert restored_row[11] == backup_row["source"]
        assert restored_row[12] == backup_row["provenance"]
        assert restored_row[13] == backup_row["source_timestamp_semantics"]
        assert restored_row[14] == backup_row["canonicalization_state"]
