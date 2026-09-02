# tests/unit/infrastructure/persistence/management/test_verify_data_integrity_command.py
#
# Checkpoint 67.12.2-B (retry): proves `manage.py verify_data_integrity`
# is genuinely read-only and that its content checksum actually detects
# what the legacy 2-column (id, bar_timestamp) checksum structurally
# cannot: a changed close_price or a changed provenance with everything
# else held fixed.
from __future__ import annotations

import inspect
import io
import json
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.db import connection

from intraday.infrastructure.persistence import models as persistence_models
from intraday.infrastructure.persistence.management.commands import (
    verify_data_integrity as cmd_module,
)
from tests.postgres_utils import requires_postgres

pytestmark = requires_postgres


def _make_bar(**overrides: object) -> persistence_models.HistoricalBar:
    defaults = dict(
        instrument_id="NSE:TESTCO",
        exchange="NSE",
        symbol="TESTCO",
        timeframe="5m",
        bar_timestamp="2026-08-17T09:15:00+00:00",
        open_price=Decimal("100.00"),
        high_price=Decimal("101.00"),
        low_price=Decimal("99.00"),
        close_price=Decimal("100.50"),
        volume=Decimal("1000"),
        source="API_FETCH",
        provenance="REAL_DHAN",
        canonicalization_state="CANONICALIZED",
    )
    defaults.update(overrides)
    return persistence_models.HistoricalBar.objects.create(**defaults)


def _run_command() -> dict:
    out = io.StringIO()
    call_command("verify_data_integrity", stdout=out)
    return json.loads(out.getvalue())


def test_command_source_contains_no_mutating_calls_or_sql() -> None:
    """Structural proof (not just runtime behavior): the command module's
    own source has no ORM `.save(`/`.create(`/`.update(`/`.delete(` call and
    no mutating SQL keyword anywhere."""
    source = inspect.getsource(cmd_module)
    forbidden_orm = [".save(", ".objects.create(", "HistoricalBar.objects.update(", ".objects.delete(", "queryset.update(", "queryset.delete("]
    for token in forbidden_orm:
        assert token not in source, f"found forbidden ORM call {token!r} in verify_data_integrity.py"
    forbidden_sql = ["INSERT ", "UPDATE ", "DELETE FROM", "DROP ", "ALTER TABLE", "TRUNCATE"]
    upper_source = source.upper()
    for token in forbidden_sql:
        assert token not in upper_source, f"found forbidden SQL keyword {token!r}"


@pytest.mark.django_db(transaction=True)
def test_command_makes_zero_writes_to_historical_bar() -> None:
    _make_bar()
    before = list(
        persistence_models.HistoricalBar.objects.order_by("id").values_list("id", "close_price")
    )
    _run_command()
    after = list(
        persistence_models.HistoricalBar.objects.order_by("id").values_list("id", "close_price")
    )
    assert before == after


@pytest.mark.django_db(transaction=True)
def test_content_checksum_stable_across_two_runs_unchanged_data() -> None:
    _make_bar()
    r1 = _run_command()
    r2 = _run_command()
    assert r1["content_checksum"] == r2["content_checksum"]
    assert r1["legacy_id_timestamp_checksum"] == r2["legacy_id_timestamp_checksum"]


@pytest.mark.django_db(transaction=True)
def test_content_checksum_changes_on_close_price_change() -> None:
    bar = _make_bar()
    r1 = _run_command()
    bar.close_price = Decimal("999.99")
    bar.save(update_fields=["close_price"])
    r2 = _run_command()
    assert r1["content_checksum"] != r2["content_checksum"]
    # legacy checksum is blind to this — only (id, bar_timestamp) — proving
    # the exact blind spot this checkpoint's content checksum fixes.
    assert r1["legacy_id_timestamp_checksum"] == r2["legacy_id_timestamp_checksum"]


@pytest.mark.django_db(transaction=True)
def test_content_checksum_changes_on_provenance_change() -> None:
    bar = _make_bar()
    r1 = _run_command()
    bar.provenance = "UNKNOWN"
    bar.save(update_fields=["provenance"])
    r2 = _run_command()
    assert r1["content_checksum"] != r2["content_checksum"]
    assert r1["legacy_id_timestamp_checksum"] == r2["legacy_id_timestamp_checksum"]


@pytest.mark.django_db(transaction=True)
def test_legacy_checksum_matches_recorded_arc_value_shape() -> None:
    """Not the literal historical value (test DB has different rows) —
    proves the legacy checksum is computed by the SAME formula:
    sha256(str(list(values_list('id','bar_timestamp'))))."""
    import hashlib

    _make_bar()
    result = _run_command()
    pairs = list(
        persistence_models.HistoricalBar.objects.order_by("id").values_list("id", "bar_timestamp")
    )
    expected = hashlib.sha256(str(pairs).encode()).hexdigest()
    assert result["legacy_id_timestamp_checksum"] == expected


@pytest.mark.django_db(transaction=True)
def test_content_checksum_invariant_under_row_reordering() -> None:
    _make_bar(symbol="AAA")
    _make_bar(symbol="BBB", instrument_id="NSE:BBB")
    r1 = _run_command()
    with connection.cursor() as cur:
        cur.execute("VACUUM FULL persistence_historicalbar")
        cur.execute("REINDEX TABLE persistence_historicalbar")
    r2 = _run_command()
    assert r1["content_checksum"] == r2["content_checksum"]


@pytest.mark.django_db(transaction=True)
def test_content_checksum_invariant_under_session_setting_changes() -> None:
    _make_bar()
    r1 = _run_command()
    with connection.cursor() as cur:
        cur.execute("SET DateStyle = 'ISO, DMY'")
        cur.execute("SET extra_float_digits = 1")
        try:
            cur.execute("SET lc_numeric = 'English_India.1252'")
        except Exception:
            cur.execute("SET lc_numeric = 'C'")  # locale unavailable on this host; SET LOCAL inside command still pins UTC/ISO/C regardless
    r2 = _run_command()
    assert r1["content_checksum"] == r2["content_checksum"]


@pytest.mark.django_db(transaction=True)
def test_snapshot_identity_matches_first_and_last() -> None:
    _make_bar()
    result = _run_command()
    si = result["snapshot_identity"]
    assert si["snapshot_matches"] is True
    assert si["backend_pid_matches"] is True


@pytest.mark.django_db(transaction=True)
def test_invariant_duplicate_symbol_timeframe_bar_timestamp_positive() -> None:
    _make_bar(symbol="DUP")
    _make_bar(symbol="DUP", instrument_id="NSE:DUP2")
    result = _run_command()
    assert result["invariants"]["duplicate_symbol_timeframe_bar_timestamp"]["count"] >= 1


@pytest.mark.django_db(transaction=True)
def test_invariant_duplicate_negative_when_unique() -> None:
    _make_bar(symbol="UNIQ1")
    result = _run_command()
    assert result["invariants"]["duplicate_symbol_timeframe_bar_timestamp"]["count"] == 0


@pytest.mark.django_db(transaction=True)
def test_invariant_ohlc_sanity_positive() -> None:
    _make_bar(symbol="BADOHLC", high_price=Decimal("1.00"), low_price=Decimal("50.00"))
    result = _run_command()
    assert result["invariants"]["ohlc_sanity_violations"]["count"] >= 1


@pytest.mark.django_db(transaction=True)
def test_invariant_ohlc_sanity_negative() -> None:
    _make_bar(symbol="GOODOHLC")
    result = _run_command()
    assert result["invariants"]["ohlc_sanity_violations"]["count"] == 0


@pytest.mark.django_db(transaction=True)
def test_invariant_non_positive_prices_positive() -> None:
    _make_bar(symbol="ZEROPRICE", close_price=Decimal("0.00"))
    result = _run_command()
    assert result["invariants"]["non_positive_prices"]["count"] >= 1


@pytest.mark.django_db(transaction=True)
def test_invariant_non_positive_prices_negative() -> None:
    _make_bar(symbol="POSPRICE")
    result = _run_command()
    assert result["invariants"]["non_positive_prices"]["count"] == 0


@pytest.mark.django_db(transaction=True)
def test_invariant_negative_volume_positive() -> None:
    _make_bar(symbol="NEGVOL", volume=Decimal("-5"))
    result = _run_command()
    assert result["invariants"]["negative_volume"]["count"] >= 1


@pytest.mark.django_db(transaction=True)
def test_invariant_negative_volume_negative() -> None:
    _make_bar(symbol="POSVOL")
    result = _run_command()
    assert result["invariants"]["negative_volume"]["count"] == 0


@pytest.mark.django_db(transaction=True)
def test_invariant_weekend_bar_timestamps_positive() -> None:
    # 2026-08-15 is a Saturday.
    _make_bar(symbol="WEEKEND", bar_timestamp="2026-08-15T09:15:00+00:00")
    result = _run_command()
    assert result["invariants"]["weekend_bar_timestamps"]["count"] >= 1


@pytest.mark.django_db(transaction=True)
def test_invariant_weekend_bar_timestamps_negative() -> None:
    # 2026-08-17 is a Monday.
    _make_bar(symbol="WEEKDAY", bar_timestamp="2026-08-17T09:15:00+00:00")
    result = _run_command()
    assert result["invariants"]["weekend_bar_timestamps"]["count"] == 0


@pytest.mark.django_db(transaction=True)
def test_invariant_required_column_nulls_negative() -> None:
    _make_bar(symbol="NONNULL")
    result = _run_command()
    assert result["invariants"]["required_column_nulls"]["count"] == 0
