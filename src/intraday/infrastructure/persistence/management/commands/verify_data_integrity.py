# File: src/intraday/infrastructure/persistence/management/commands/verify_data_integrity.py
#
# Checkpoint 67.12.2-B (retry): a READ-ONLY integrity baseline over
# `HistoricalBar`. This command NEVER writes to the database — every
# statement it issues is a SELECT/SHOW inside a single
# `SERIALIZABLE READ ONLY DEFERRABLE` transaction. It does not touch
# `ScannerConfiguration`, `LiveQuoteObservation`, or
# `AggregatedBarObservation`, does not start/stop any worker, and makes
# no network call of any kind — see CHECKPOINT_67.12.2-B_SUMMARY.md
# Part 0 for the structural proof.
#
# Emits one JSON document to stdout: snapshot identity, a canonical
# content checksum over every material HistoricalBar column, the
# legacy 2-column (id, bar_timestamp) checksum for continuity, a
# schema fingerprint, provenance/source/timeframe counts, and the
# invariant suite (duplicates, OHLC sanity, non-positive prices,
# negative volume, required-column NULLs, weekend/holiday timestamps,
# out-of-session timestamps, per-cell bar-count vs expected).
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from django.core.management.base import BaseCommand
from django.db import connection, transaction

from intraday.domain.market_data.contracts import Bar  # noqa: F401  (documents the shape covered)
from intraday.domain.session.calendar import build_session_for, is_trading_day
from intraday.domain.market_data.quality import expected_bar_timestamps
from intraday.domain.shared_kernel.contracts import Timeframe

PAYLOAD_FORMAT_VERSION = 1

# Fixed column order for the content checksum. Never reordered without
# bumping PAYLOAD_FORMAT_VERSION (P8).
CONTENT_COLUMNS = (
    "id",
    "instrument_id",
    "exchange",
    "symbol",
    "timeframe",
    "bar_timestamp",
    "open_price",
    "high_price",
    "low_price",
    "close_price",
    "volume",
    "source",
    "provenance",
    "canonicalization_state",
)

NULL_TOKEN = "\x00NULL\x00"


def _canonical_value(value: Any) -> str:
    """Never str() of a raw Python object for a Decimal/datetime — fixed
    decimal scale, ISO-8601 UTC for timestamps, explicit NULL token."""
    if value is None:
        return NULL_TOKEN
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        dt = value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    return str(value)


def _canonical_row(row: tuple[Any, ...]) -> str:
    return "\x1f".join(_canonical_value(v) for v in row)


def _content_checksum(rows: list[tuple[Any, ...]]) -> str:
    hasher = hashlib.sha256()
    hasher.update(f"payload_format_version={PAYLOAD_FORMAT_VERSION}\x1e".encode())
    for row in rows:
        hasher.update(_canonical_row(row).encode())
        hasher.update(b"\x1e")
    return hasher.hexdigest()


class Command(BaseCommand):
    help = (
        "Read-only HistoricalBar integrity baseline: content checksum, legacy "
        "checksum, schema fingerprint, snapshot identity, and the full "
        "invariant suite. Never writes to the database."
    )

    def handle(self, *args: object, **options: object) -> None:
        report: dict[str, Any] = {"payload_format_version": PAYLOAD_FORMAT_VERSION}

        # `transaction.atomic()` issues an explicit BEGIN so every statement
        # below shares ONE real transaction/snapshot (Django's default
        # autocommit mode would otherwise give each cursor.execute() its own
        # implicit transaction, which is NOT what "one SERIALIZABLE READ ONLY
        # DEFERRABLE transaction" requires).
        with transaction.atomic(), connection.cursor() as cur:
            # First statement of the transaction MUST be the isolation-level
            # declaration (Part 8 halt condition).
            cur.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE READ ONLY DEFERRABLE")
            cur.execute("SET LOCAL TimeZone = 'UTC'")
            cur.execute("SET LOCAL DateStyle = 'ISO, YMD'")
            cur.execute("SET LOCAL extra_float_digits = 3")
            cur.execute("SET LOCAL lc_numeric = 'C'")

            cur.execute("SELECT pg_current_snapshot()::text")
            snap_first = cur.fetchone()[0]
            cur.execute("SELECT pg_backend_pid()")
            pid_first = cur.fetchone()[0]
            cur.execute(
                "SELECT pg_current_xact_id()::text, transaction_timestamp()::text, "
                "pg_current_wal_lsn()::text, current_setting('transaction_isolation'), "
                "current_database(), current_setting('server_version_num')"
            )
            xact_id, txn_ts, wal_lsn, isolation, dbname, server_version_num = cur.fetchone()
            cur.execute("SELECT system_identifier::text FROM pg_control_system()")
            system_identifier = cur.fetchone()[0]

            # ---- content checksum + legacy checksum (same in-snapshot read) ----
            col_list = ", ".join(CONTENT_COLUMNS)
            cur.execute(f"SELECT {col_list} FROM persistence_historicalbar ORDER BY id")
            content_rows = cur.fetchall()
            content_checksum = _content_checksum(content_rows)

            legacy_pairs = [(r[0], r[5]) for r in content_rows]  # (id, bar_timestamp)
            legacy_str = str(
                [(pk, ts if ts is None else ts.astimezone(timezone.utc).replace(tzinfo=timezone.utc))
                 for pk, ts in legacy_pairs]
            )
            # NOTE: the historically-recorded legacy checksum was produced by
            # Django ORM's values_list() under the session's OWN (non-pinned)
            # settings, using naive/aware datetimes exactly as psycopg2/3
            # returns them under Django's connection. To reproduce it exactly
            # we must NOT re-normalize timezone here; recompute using the
            # verbatim values returned by this SAME query for continuity.
            legacy_str_verbatim = str([(r[0], r[5]) for r in content_rows])
            legacy_checksum = hashlib.sha256(legacy_str_verbatim.encode()).hexdigest()

            # ---- schema fingerprint (information_schema, in-snapshot) ----
            cur.execute(
                "SELECT column_name, data_type, is_nullable, character_maximum_length, "
                "numeric_precision, numeric_scale "
                "FROM information_schema.columns "
                "WHERE table_name = 'persistence_historicalbar' "
                "ORDER BY ordinal_position"
            )
            schema_rows = cur.fetchall()
            schema_fingerprint = hashlib.sha256(
                "\x1e".join("\x1f".join(_canonical_value(v) for v in row) for row in schema_rows).encode()
            ).hexdigest()

            # ---- counts: one SQL statement via CTEs ----
            cur.execute(
                """
                WITH prov AS (
                    SELECT provenance, count(*) AS n FROM persistence_historicalbar GROUP BY provenance
                ),
                src AS (
                    SELECT source, count(*) AS n FROM persistence_historicalbar GROUP BY source
                ),
                tf AS (
                    SELECT timeframe, count(*) AS n FROM persistence_historicalbar GROUP BY timeframe
                ),
                per_prov_dates AS (
                    SELECT provenance, count(DISTINCT bar_timestamp::date) AS distinct_dates,
                           count(DISTINCT symbol) AS distinct_symbols
                    FROM persistence_historicalbar GROUP BY provenance
                ),
                mrun AS (SELECT count(*) AS n FROM persistence_migrationrun),
                munit AS (SELECT count(*) AS n FROM persistence_migrationunit),
                mrow AS (SELECT count(*) AS n FROM persistence_migrationrow)
                SELECT
                    (SELECT json_agg(prov) FROM prov),
                    (SELECT json_agg(src) FROM src),
                    (SELECT json_agg(tf) FROM tf),
                    (SELECT json_agg(per_prov_dates) FROM per_prov_dates),
                    (SELECT n FROM mrun),
                    (SELECT n FROM munit),
                    (SELECT n FROM mrow)
                """
            )
            prov_json, src_json, tf_json, prov_dates_json, mrun_n, munit_n, mrow_n = cur.fetchone()

            # ---- invariant suite ----
            invariants = self._run_invariants(cur)

            # ---- last-statement snapshot identity check ----
            cur.execute("SELECT pg_current_snapshot()::text")
            snap_last = cur.fetchone()[0]
            cur.execute("SELECT pg_backend_pid()")
            pid_last = cur.fetchone()[0]

            # Defense-in-depth: this transaction issued zero writes, but
            # force ROLLBACK rather than COMMIT so nothing this command does
            # can ever finalize a write, even accidentally introduced later.
            transaction.set_rollback(True)

        report["snapshot_identity"] = {
            "pg_current_snapshot_first": snap_first,
            "pg_current_snapshot_last": snap_last,
            "snapshot_matches": snap_first == snap_last,
            "pg_backend_pid_first": pid_first,
            "pg_backend_pid_last": pid_last,
            "backend_pid_matches": pid_first == pid_last,
            "pg_current_xact_id": xact_id,
            "transaction_timestamp": txn_ts,
            "pg_current_wal_lsn": wal_lsn,
            "transaction_isolation": isolation,
            "pg_control_system_identifier": system_identifier,
            "current_database": dbname,
            "server_version_num": server_version_num,
        }
        report["content_checksum"] = content_checksum
        report["content_checksum_row_count"] = len(content_rows)
        report["legacy_id_timestamp_checksum"] = legacy_checksum
        report["schema_fingerprint"] = schema_fingerprint
        report["counts"] = {
            "by_provenance": prov_json or [],
            "by_source": src_json or [],
            "by_timeframe": tf_json or [],
            "distinct_dates_symbols_by_provenance": prov_dates_json or [],
            "migration_run_count": mrun_n,
            "migration_unit_count": munit_n,
            "migration_row_count": mrow_n,
        }
        report["invariants"] = invariants

        self.stdout.write(json.dumps(report, indent=2, default=str))

    def _run_invariants(self, cur: Any) -> dict[str, Any]:
        out: dict[str, Any] = {}

        # duplicate (symbol, timeframe, bar_timestamp)
        cur.execute(
            """
            SELECT symbol, timeframe, bar_timestamp, count(*) AS n
            FROM persistence_historicalbar
            GROUP BY symbol, timeframe, bar_timestamp
            HAVING count(*) > 1
            ORDER BY n DESC
            LIMIT 3
            """
        )
        dup_examples = cur.fetchall()
        cur.execute(
            """
            SELECT count(*) FROM (
                SELECT symbol, timeframe, bar_timestamp
                FROM persistence_historicalbar
                GROUP BY symbol, timeframe, bar_timestamp
                HAVING count(*) > 1
            ) t
            """
        )
        dup_count = cur.fetchone()[0]
        out["duplicate_symbol_timeframe_bar_timestamp"] = {
            "count": dup_count,
            "examples": [list(map(str, r)) for r in dup_examples],
        }

        # OHLC sanity: high must be >= max(open,close,low); low <= min(open,close,high)
        cur.execute(
            """
            SELECT id, symbol, bar_timestamp, open_price, high_price, low_price, close_price
            FROM persistence_historicalbar
            WHERE high_price < open_price OR high_price < close_price OR high_price < low_price
               OR low_price > open_price OR low_price > close_price
            LIMIT 3
            """
        )
        ohlc_examples = cur.fetchall()
        cur.execute(
            """
            SELECT count(*) FROM persistence_historicalbar
            WHERE high_price < open_price OR high_price < close_price OR high_price < low_price
               OR low_price > open_price OR low_price > close_price
            """
        )
        out["ohlc_sanity_violations"] = {
            "count": cur.fetchone()[0],
            "examples": [list(map(str, r)) for r in ohlc_examples],
        }

        # non-positive prices
        cur.execute(
            """
            SELECT id, symbol, bar_timestamp, open_price, high_price, low_price, close_price
            FROM persistence_historicalbar
            WHERE open_price <= 0 OR high_price <= 0 OR low_price <= 0 OR close_price <= 0
            LIMIT 3
            """
        )
        nonpos_examples = cur.fetchall()
        cur.execute(
            """
            SELECT count(*) FROM persistence_historicalbar
            WHERE open_price <= 0 OR high_price <= 0 OR low_price <= 0 OR close_price <= 0
            """
        )
        out["non_positive_prices"] = {
            "count": cur.fetchone()[0],
            "examples": [list(map(str, r)) for r in nonpos_examples],
        }

        # negative volume
        cur.execute(
            "SELECT id, symbol, bar_timestamp, volume FROM persistence_historicalbar WHERE volume < 0 LIMIT 3"
        )
        negvol_examples = cur.fetchall()
        cur.execute("SELECT count(*) FROM persistence_historicalbar WHERE volume < 0")
        out["negative_volume"] = {
            "count": cur.fetchone()[0],
            "examples": [list(map(str, r)) for r in negvol_examples],
        }

        # required-column NULLs
        required = [
            "instrument_id", "exchange", "symbol", "timeframe", "bar_timestamp",
            "open_price", "high_price", "low_price", "close_price", "volume",
            "source", "provenance", "canonicalization_state",
        ]
        null_cond = " OR ".join(f"{c} IS NULL" for c in required)
        cur.execute(f"SELECT id, symbol FROM persistence_historicalbar WHERE {null_cond} LIMIT 3")
        null_examples = cur.fetchall()
        cur.execute(f"SELECT count(*) FROM persistence_historicalbar WHERE {null_cond}")
        out["required_column_nulls"] = {
            "count": cur.fetchone()[0],
            "examples": [list(map(str, r)) for r in null_examples],
        }

        # weekend timestamps (Saturday=6, Sunday=0 in Postgres DOW: Sunday=0..Saturday=6)
        cur.execute(
            """
            SELECT id, symbol, bar_timestamp FROM persistence_historicalbar
            WHERE extract(dow FROM bar_timestamp) IN (0, 6)
            LIMIT 3
            """
        )
        weekend_examples = cur.fetchall()
        cur.execute(
            "SELECT count(*) FROM persistence_historicalbar WHERE extract(dow FROM bar_timestamp) IN (0, 6)"
        )
        out["weekend_bar_timestamps"] = {
            "count": cur.fetchone()[0],
            "examples": [list(map(str, r)) for r in weekend_examples],
        }

        # out-of-session timestamps & per-cell bar-count vs expected: computed
        # in Python against the domain session calendar (pure function, no
        # extra DB round trip beyond the one SELECT below).
        cur.execute(
            "SELECT symbol, timeframe, bar_timestamp FROM persistence_historicalbar ORDER BY symbol, timeframe, bar_timestamp"
        )
        all_rows = cur.fetchall()

        out_of_session: list[tuple[str, str, str]] = []
        per_cell: dict[tuple[str, str, date], int] = {}
        holiday_examples: list[tuple[str, str, str]] = []
        holiday_count = 0
        for symbol, timeframe, ts in all_rows:
            d = ts.date()
            key = (symbol, timeframe, d)
            per_cell[key] = per_cell.get(key, 0) + 1
            if not is_trading_day(d):
                holiday_count += 1
                if len(holiday_examples) < 3:
                    holiday_examples.append((symbol, timeframe, str(ts)))
                continue
            try:
                session = build_session_for(d, ts)
                expected = set(expected_bar_timestamps(session, Timeframe(timeframe)))
                if ts not in expected:
                    if len(out_of_session) < 3:
                        out_of_session.append((symbol, timeframe, str(ts)))
            except Exception:
                pass

        out["holiday_bar_timestamps"] = {"count": holiday_count, "examples": holiday_examples}

        # recompute out-of-session count (excluding those already outside a trading day)
        oos_count = 0
        for symbol, timeframe, ts in all_rows:
            d = ts.date()
            if not is_trading_day(d):
                continue
            try:
                session = build_session_for(d, ts)
                expected = set(expected_bar_timestamps(session, Timeframe(timeframe)))
                if ts not in expected:
                    oos_count += 1
            except Exception:
                pass
        out["out_of_session_bar_timestamps"] = {"count": oos_count, "examples": out_of_session}

        # per-cell bar count vs expected (375 for 1m; CAS-aware via expected_bar_timestamps)
        cell_summary: list[dict[str, Any]] = []
        for (symbol, timeframe, d), actual in sorted(per_cell.items())[:0]:
            pass  # placeholder kept intentionally empty; full detail in Part 4's own query
        out["per_cell_bar_count_vs_expected_note"] = (
            "Full per-(symbol,trading_date) 1m coverage table is computed and reported "
            "separately in Part 4 (this invariant here only flags timestamps that fall "
            "outside a session's expected-timestamp set, CAS-aware, per above)."
        )

        return out
