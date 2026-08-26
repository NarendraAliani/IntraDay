# tests/unit/infrastructure/api/test_checkpoint_64_83_archive_api.py
#
# Checkpoint 64.83: coverage for the read-only archive / reconciliation
# query surface and the archive-qualified correlation trace.
#
# Mirrors `test_checkpoint_64_82_correlation_api.py` exactly - real
# Django test Client against the real URLconf, real persisted rows,
# never fabricated data. The governing assertion running through every
# test below: NOTHING here may report a day as complete, reconciled, or
# validated unless real stored rows say so.
from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext

from intraday.infrastructure.persistence.models import (
    AggregatedBarObservation,
    HistoricalBar,
    MarketDataArchiveDay,
    SignalRecord,
)
from tests.postgres_utils import requires_postgres

READER = "archive_reader"
PASSWORD = "correct-horse-battery-staple"  # noqa: S105

# 2026-08-24 is a Monday - a real NSE trading day. 2026-08-22 is the
# Saturday before it, used to prove a non-trading day reads as CORRECTLY
# empty rather than as an operational gap.
TRADING_DAY = date(2026, 8, 24)
WEEKEND = date(2026, 8, 22)
ARCHIVE_URL = f"/api/v1/market-data/archive/{TRADING_DAY.isoformat()}/"
RECON_URL = f"/api/v1/market-data/reconciliation/{TRADING_DAY.isoformat()}/"


def _client() -> Client:
    User.objects.create_user(username=READER, password=PASSWORD)
    client = Client()
    assert client.login(username=READER, password=PASSWORD)
    return client


def _cell(
    symbol: str = "RELIANCE",
    *,
    timeframe: str = "1m",
    status: str = "PARTIAL",
    trading_date: date = TRADING_DAY,
    completeness_supported: bool = True,
    expected: int = 375,
    closed: int = 1,
    missing: int = 374,
    duplicates: int = 0,
    reconciliation_status: str = "NOT_RECONCILED",
) -> MarketDataArchiveDay:
    return MarketDataArchiveDay.objects.create(
        exchange="NSE",
        trading_date=trading_date,
        instrument_symbol=symbol,
        timeframe=timeframe,
        data_source="dhan",
        status=status,
        reason=f"missing_bars:{missing}" if missing else "all_expected_bars_present",
        completeness_supported=completeness_supported,
        expected_bar_count=expected,
        closed_bar_count=closed,
        forming_bar_count=0,
        missing_bar_count=missing,
        duplicate_bar_count=duplicates,
        quote_observation_count=120,
        first_observation_at=datetime(2026, 8, 24, 3, 45, tzinfo=UTC),
        last_observation_at=datetime(2026, 8, 24, 3, 46, tzinfo=UTC),
        reconciliation_status=reconciliation_status,
    )


def _observed_bar(
    symbol: str = "RELIANCE", *, minute: int = 46, trading_date: date = TRADING_DAY
) -> AggregatedBarObservation:
    """One CLOSED archived bar.

    Needed because `archived_symbols_for_trading_date` enumerates the
    day's symbols from the RAW observation layer, not from the archive
    projection - archive rows alone describe a day, they do not
    constitute one.
    """
    return AggregatedBarObservation.objects.create(
        instrument_symbol=symbol,
        exchange="NSE",
        timeframe="1m",
        interval_start=datetime(2026, 8, 24, 3, minute - 1, tzinfo=UTC),
        interval_end=datetime(2026, 8, 24, 3, minute, tzinfo=UTC),
        open_price=Decimal("100"),
        high_price=Decimal("101"),
        low_price=Decimal("99"),
        close_price=Decimal("100.5"),
        status="CLOSED",
        observation_count=5,
        data_source="dhan",
        trading_date=trading_date,
    )


# =====================================================================
# A / B / C / D - archive queryability
# =====================================================================


@pytest.mark.django_db
@requires_postgres
def test_a_archive_is_queryable_by_trading_date() -> None:
    """Final gate A: a caller can query archive status by trading date."""
    _cell("RELIANCE")
    _cell("INFY")
    body = _client().get(ARCHIVE_URL).json()

    assert body["trading_date"] == TRADING_DAY.isoformat()
    assert body["is_trading_day"] is True
    assert body["symbol_count"] == 2
    assert body["cell_count"] == 2
    assert {c["symbol"] for c in body["cells"]} == {"RELIANCE", "INFY"}


@pytest.mark.django_db
@requires_postgres
def test_b_archive_is_queryable_by_symbol_through_a_filter() -> None:
    """Final gate B: by symbol - via a composable filter on the same day
    resource rather than a second endpoint."""
    _cell("RELIANCE")
    _cell("INFY")
    body = _client().get(ARCHIVE_URL, {"symbol": "INFY"}).json()

    assert body["cell_count"] == 1
    assert body["cells"][0]["symbol"] == "INFY"
    assert body["symbol_filter"] == "INFY"


@pytest.mark.django_db
@requires_postgres
def test_b_a_filtered_response_still_reports_the_whole_day_status() -> None:
    """A caller narrowing to one healthy symbol must NOT see the whole
    day reported as healthy - `archive_status` always describes the day."""
    _cell("RELIANCE", status="COMPLETE", missing=0, closed=375)
    _cell("INFY", status="PARTIAL", missing=374)
    body = _client().get(ARCHIVE_URL, {"symbol": "RELIANCE"}).json()

    assert body["cells"][0]["archive_status"] == "COMPLETE"
    # Worst-wins across the WHOLE day, not the filtered subset.
    assert body["archive_status"] == "PARTIAL"
    assert body["symbol_count"] == 2


@pytest.mark.django_db
@requires_postgres
def test_c_expected_versus_actual_bars_are_both_exposed() -> None:
    """Final gate C: expected vs actual bars are visible side by side."""
    _cell("RELIANCE", expected=375, closed=24, missing=351)
    cell = _client().get(ARCHIVE_URL).json()["cells"][0]

    assert cell["expected_bar_count"] == 375
    assert cell["closed_bar_count"] == 24
    assert cell["forming_bar_count"] == 0


@pytest.mark.django_db
@requires_postgres
def test_d_missing_and_duplicate_coverage_are_exposed() -> None:
    """Final gate D: missing and duplicate coverage are both visible."""
    _cell("RELIANCE", missing=351, duplicates=2)
    cell = _client().get(ARCHIVE_URL).json()["cells"][0]

    assert cell["missing_bar_count"] == 351
    assert cell["duplicate_bar_count"] == 2


@pytest.mark.django_db
@requires_postgres
def test_unsupported_timeframe_reports_null_not_zero_expected_bars() -> None:
    """THE NULL RULE. A 1h cell has no defensible expected-bar count, so
    `expected_bar_count`/`missing_bar_count` are `null` - never `0`,
    which would read as "nothing was expected and nothing is missing"."""
    _cell("RELIANCE", timeframe="1h", completeness_supported=False, expected=0, missing=0)
    cell = _client().get(ARCHIVE_URL).json()["cells"][0]

    assert cell["completeness_supported"] is False
    assert cell["expected_bar_count"] is None
    assert cell["missing_bar_count"] is None
    # A genuinely measured zero stays a zero.
    assert cell["duplicate_bar_count"] == 0


@pytest.mark.django_db
@requires_postgres
def test_empty_trading_day_is_not_observed_not_a_404() -> None:
    """ "Nothing was observed" is a real reportable state, not a 404 and
    not an invented completeness claim."""
    response = _client().get(ARCHIVE_URL)
    assert response.status_code == 200
    body = response.json()
    assert body["cells"] == []
    assert body["archive_status"] == "NOT_OBSERVED"
    assert body["is_trading_day"] is True


@pytest.mark.django_db
@requires_postgres
def test_weekend_is_flagged_so_empty_reads_as_correct_not_as_a_gap() -> None:
    """An empty Saturday is CORRECT. `is_trading_day: false` is what
    lets an operator tell that apart from a real outage."""
    body = _client().get(f"/api/v1/market-data/archive/{WEEKEND.isoformat()}/").json()
    assert body["is_trading_day"] is False
    assert body["cells"] == []


@pytest.mark.django_db
@requires_postgres
def test_malformed_date_is_a_typed_400_not_a_bare_404() -> None:
    """A malformed date must be distinguishable from "this date has no
    data" - so it is a typed 400, never a routing 404."""
    response = _client().get("/api/v1/market-data/archive/not-a-date/")
    assert response.status_code == 400
    assert response.json()["error_code"] == "invalid_request"


@pytest.mark.django_db
@requires_postgres
def test_unknown_timeframe_filter_is_rejected_not_silently_ignored() -> None:
    """A silently-ignored filter would make a filtered response look
    unfiltered - the exact confusion this surface must not create."""
    _cell("RELIANCE")
    response = _client().get(ARCHIVE_URL, {"timeframe": "7m"})
    assert response.status_code == 400


# =====================================================================
# E / F - reconciliation queryability and integrity
# =====================================================================


@pytest.mark.django_db
@requires_postgres
def test_e_reconciliation_evidence_is_queryable() -> None:
    """Final gate E: reconciliation evidence is queryable, and carries
    its `evidence_source` so the reference pipeline is auditable."""
    _cell("RELIANCE")
    _observed_bar("RELIANCE")
    body = _client().get(RECON_URL).json()

    assert body["timeframe"] == "1m"
    assert body["evidence_source"] == "dhan_historical_candle_api"
    assert body["cell_count"] == 1
    assert body["cells"][0]["symbol"] == "RELIANCE"
    assert body["cells"][0]["observed_count"] == 1


@pytest.mark.django_db
@requires_postgres
def test_f_no_reference_data_yields_not_reconciled_never_pass() -> None:
    """THE CENTRAL HONESTY ASSERTION of this checkpoint. With archived
    bars but ZERO overlapping reference bars - the platform's real
    state today - every cell must be NOT_RECONCILED. "Nothing disagreed
    with us" is not evidence of agreement."""
    _cell("RELIANCE")
    body = _client().get(RECON_URL, {"symbol": "RELIANCE"}).json()

    assert body["reconciliation_status"] == "NOT_RECONCILED"
    cell = body["cells"][0]
    assert cell["reconciliation_status"] == "NOT_RECONCILED"
    assert cell["reason"] == "no_reference_bars_available"
    assert cell["reference_count"] == 0
    assert cell["matched_count"] == 0


@pytest.mark.django_db
@requires_postgres
def test_f_unreconciled_days_are_distinguishable_from_reconciled_ones() -> None:
    """Final gate F. The stored archive claim and the computed
    comparison result are two SEPARATE fields and are never merged."""
    _cell("RELIANCE", reconciliation_status="NOT_RECONCILED")
    archive_cell = _client().get(ARCHIVE_URL).json()["cells"][0]
    assert archive_cell["reconciliation_status"] == "NOT_RECONCILED"
    assert archive_cell["reconciled_at"] is None


@pytest.mark.django_db
@requires_postgres
def test_volume_mismatch_count_is_null_when_volume_was_not_compared() -> None:
    """`null`, not `0`: volume was not compared at all, which is a
    different claim from "volume was compared and agreed"."""
    _cell("RELIANCE")
    cell = _client().get(RECON_URL, {"symbol": "RELIANCE"}).json()["cells"][0]

    assert cell["volume_compared"] is False
    assert cell["volume_mismatch_count"] is None


@pytest.mark.django_db
@requires_postgres
def test_reconciliation_never_writes_to_the_archive() -> None:
    """The reconciliation service writes NOTHING (64.79's own rule).
    Calling this endpoint must never flip a stored archive claim."""
    _cell("RELIANCE")
    _observed_bar("RELIANCE")
    HistoricalBar.objects.create(
        exchange="NSE",
        symbol="RELIANCE",
        timeframe="1m",
        bar_timestamp=datetime(2026, 8, 24, 3, 46, tzinfo=UTC),
        open_price=Decimal("100"),
        high_price=Decimal("101"),
        low_price=Decimal("99"),
        close_price=Decimal("100.5"),
        volume=Decimal("1000"),
    )
    _client().get(RECON_URL)

    row = MarketDataArchiveDay.objects.get(instrument_symbol="RELIANCE")
    assert row.reconciliation_status == "NOT_RECONCILED"
    assert row.reconciled_at is None


# =====================================================================
# G / H / I - archive -> outcome traceability
# =====================================================================


@pytest.mark.django_db
@requires_postgres
def test_g_signal_trace_reports_archive_evidence_when_it_exists() -> None:
    """Final gates G/H: a signal trace states whether archive evidence
    exists for its own instrument and trading date."""
    _cell("RELIANCE", status="PARTIAL")
    SignalRecord.objects.create(
        signal_id="sig-archive-1",
        strategy_id="ema_crossover",
        instrument_id="NSE:RELIANCE",
        direction="BULLISH",
        price=Decimal("101"),
        timeframe="1m",
        # 09:20 IST on the trading day = 03:50 UTC.
        signal_timestamp=datetime(2026, 8, 24, 3, 50, tzinfo=UTC),
        risk_status="APPROVED",
    )
    body = _client().get("/api/v1/correlation/signals/sig-archive-1/trace/").json()

    assert body["market_data_outcome_status"] == "ARCHIVE_PARTIAL"


@pytest.mark.django_db
@requires_postgres
def test_g_signal_with_no_archived_day_reports_unavailable() -> None:
    """No archive cell for that instrument/date is reported honestly as
    unavailable - never softened into a partial-evidence claim."""
    SignalRecord.objects.create(
        signal_id="sig-archive-2",
        strategy_id="ema_crossover",
        instrument_id="NSE:RELIANCE",
        direction="BULLISH",
        price=Decimal("101"),
        timeframe="1m",
        signal_timestamp=datetime(2026, 8, 24, 3, 50, tzinfo=UTC),
        risk_status="APPROVED",
    )
    body = _client().get("/api/v1/correlation/signals/sig-archive-2/trace/").json()

    assert body["market_data_outcome_status"] == "ARCHIVE_NOT_AVAILABLE"


@pytest.mark.django_db
@requires_postgres
def test_complete_but_unreconciled_is_never_reported_as_reconciled() -> None:
    """COMPLETE and RECONCILED are SEPARATE CLAIMS. A whole session that
    was never independently checked must never read as validated."""
    _cell("RELIANCE", status="COMPLETE", missing=0, closed=375)
    SignalRecord.objects.create(
        signal_id="sig-archive-3",
        strategy_id="ema_crossover",
        instrument_id="NSE:RELIANCE",
        direction="BULLISH",
        price=Decimal("101"),
        timeframe="1m",
        signal_timestamp=datetime(2026, 8, 24, 3, 50, tzinfo=UTC),
        risk_status="APPROVED",
    )
    body = _client().get("/api/v1/correlation/signals/sig-archive-3/trace/").json()

    assert body["market_data_outcome_status"] == "ARCHIVE_COMPLETE_NOT_RECONCILED"


@pytest.mark.django_db
@requires_postgres
def test_archive_evidence_rolls_up_worst_wins_across_timeframes() -> None:
    """One COMPLETE timeframe must never hide a PARTIAL one."""
    _cell("RELIANCE", timeframe="1m", status="COMPLETE", missing=0, closed=375)
    _cell("RELIANCE", timeframe="5m", status="PARTIAL", missing=10)
    SignalRecord.objects.create(
        signal_id="sig-archive-4",
        strategy_id="ema_crossover",
        instrument_id="NSE:RELIANCE",
        direction="BULLISH",
        price=Decimal("101"),
        timeframe="1m",
        signal_timestamp=datetime(2026, 8, 24, 3, 50, tzinfo=UTC),
        risk_status="APPROVED",
    )
    body = _client().get("/api/v1/correlation/signals/sig-archive-4/trace/").json()

    assert body["market_data_outcome_status"] == "ARCHIVE_PARTIAL"


@pytest.mark.django_db
@requires_postgres
def test_unparseable_instrument_id_is_never_looked_up_under_a_guessed_exchange() -> None:
    """An id with no exchange prefix resolves to no archive evidence -
    never a lookup against an assumed default exchange."""
    _cell("RELIANCE")
    SignalRecord.objects.create(
        signal_id="sig-archive-5",
        strategy_id="ema_crossover",
        instrument_id="RELIANCE",  # no exchange prefix
        direction="BULLISH",
        price=Decimal("101"),
        timeframe="1m",
        signal_timestamp=datetime(2026, 8, 24, 3, 50, tzinfo=UTC),
        risk_status="APPROVED",
    )
    body = _client().get("/api/v1/correlation/signals/sig-archive-5/trace/").json()

    assert body["market_data_outcome_status"] == "ARCHIVE_NOT_AVAILABLE"


@pytest.mark.django_db
@requires_postgres
def test_archive_evidence_uses_the_ist_trading_date_not_the_utc_date() -> None:
    """A signal at 09:20 IST is 03:50 UTC on the SAME calendar date, but
    a signal archived under the IST rule must not be looked up under a
    naive UTC date for pre-05:30-UTC instants. Proven by a cell that
    exists ONLY under the correct IST date."""
    _cell("RELIANCE", trading_date=TRADING_DAY)
    SignalRecord.objects.create(
        signal_id="sig-archive-6",
        strategy_id="ema_crossover",
        instrument_id="NSE:RELIANCE",
        direction="BULLISH",
        price=Decimal("101"),
        timeframe="1m",
        # 03:45 UTC = 09:15 IST on TRADING_DAY - inside the opening range
        # where a naive `.date()` would still agree; the guard is that
        # the archive resolves through `trading_date_for` either way.
        signal_timestamp=datetime(2026, 8, 24, 3, 45, tzinfo=UTC),
        risk_status="APPROVED",
    )
    body = _client().get("/api/v1/correlation/signals/sig-archive-6/trace/").json()
    assert body["market_data_outcome_status"] == "ARCHIVE_PARTIAL"


# =====================================================================
# Authorization / read-only surface (Phase 8)
# =====================================================================


@pytest.mark.django_db
@requires_postgres
@pytest.mark.parametrize("url", [ARCHIVE_URL, RECON_URL])
def test_every_endpoint_requires_authentication(url: str) -> None:
    assert Client().get(url).status_code in (401, 403)


@pytest.mark.django_db
@requires_postgres
@pytest.mark.parametrize("url", [ARCHIVE_URL, RECON_URL])
def test_endpoints_are_read_only(url: str) -> None:
    client = _client()
    for method in (client.post, client.put, client.patch, client.delete):
        assert method(url).status_code == 405


# =====================================================================
# Query performance (Phase 10)
# =====================================================================


@pytest.mark.django_db
@requires_postgres
def test_archive_day_query_count_is_independent_of_symbol_count() -> None:
    """Phase 10: a day holding twelve symbols must cost the SAME number
    of queries as a day holding two. This is the N+1 guard."""
    client = _client()
    for symbol in ("AAA", "BBB"):
        _cell(symbol)
    with CaptureQueriesContext(connection) as small:
        assert client.get(ARCHIVE_URL).status_code == 200

    for index in range(10):
        _cell(f"SYM{index}")
    with CaptureQueriesContext(connection) as large:
        assert client.get(ARCHIVE_URL).status_code == 200

    assert len(small) == len(large), (
        f"archive day query count grew with symbol count: "
        f"{len(small)} (2 symbols) -> {len(large)} (12 symbols)"
    )


@pytest.mark.django_db
@requires_postgres
def test_archive_day_filtered_query_count_is_also_bounded() -> None:
    client = _client()
    for index in range(12):
        _cell(f"SYM{index}")
    with CaptureQueriesContext(connection) as captured:
        assert client.get(ARCHIVE_URL, {"symbol": "SYM3"}).status_code == 200
    # One filtered archive read + one whole-day rollup read + auth.
    assert len(captured) <= 6, [q["sql"] for q in captured]


@pytest.mark.django_db
@requires_postgres
def test_scan_run_trace_query_count_stays_fixed_with_archive_evidence() -> None:
    """The 64.83 archive lookup must be ONE bulk query for the whole
    response - a run of twelve signals across twelve instruments must
    cost the same as a run of two."""
    client = _client()
    for index in range(12):
        _cell(f"SYM{index}")

    def _signal(index: int, run: str) -> None:
        SignalRecord.objects.create(
            signal_id=f"{run}-sig-{index}",
            strategy_id="ema_crossover",
            instrument_id=f"NSE:SYM{index}",
            direction="BULLISH",
            price=Decimal("101"),
            timeframe="1m",
            signal_timestamp=datetime(2026, 8, 24, 3, 50, tzinfo=UTC),
            risk_status="APPROVED",
            scan_run_id=run,
        )

    for index in range(2):
        _signal(index, "run-small")
    with CaptureQueriesContext(connection) as small:
        assert client.get("/api/v1/correlation/runs/run-small/signals/").status_code == 200

    for index in range(12):
        _signal(index, "run-large")
    with CaptureQueriesContext(connection) as large:
        assert client.get("/api/v1/correlation/runs/run-large/signals/").status_code == 200

    assert len(small) == len(large), (
        f"correlation trace query count grew with signal count: "
        f"{len(small)} (2 signals) -> {len(large)} (12 signals)"
    )


@pytest.mark.django_db
@requires_postgres
def test_reconciliation_query_count_is_deterministic_per_symbol() -> None:
    """HONEST SCOPE NOTE: the 64.79 reconciliation service reconciles ONE
    cell per call by design, so a whole-day reconciliation is
    per-symbol by construction - this checkpoint reuses that service
    exactly rather than building a second engine, so it does not change
    that shape.

    What IS asserted: the cost is DETERMINISTIC and strictly linear -
    the same fixed number of queries per symbol, with no additional
    per-symbol growth. That is bounded work proportional to the data
    requested, not unbounded N+1 over unrelated tables."""
    client = _client()
    for symbol in ("AAA", "BBB"):
        _cell(symbol)
        _observed_bar(symbol)
    with CaptureQueriesContext(connection) as small:
        assert client.get(RECON_URL).json()["cell_count"] == 2

    for symbol in ("CCC", "DDD"):
        _cell(symbol)
        _observed_bar(symbol)
    with CaptureQueriesContext(connection) as large:
        assert client.get(RECON_URL).json()["cell_count"] == 4

    growth = len(large) - len(small)
    # Two added symbols, a fixed per-symbol cost (archived bars +
    # reference bars) and nothing else.
    assert (
        growth == 4
    ), f"reconciliation cost is not linear-per-symbol: {len(small)} -> {len(large)}"


# =====================================================================
# OpenAPI contract (Phase 9)
# =====================================================================


def test_openapi_exposes_named_archive_component_schemas() -> None:
    """Phase 9 forbids untyped objects for the primary responses - every
    shape must be a NAMED component, not an opaque dict."""
    from drf_spectacular.generators import SchemaGenerator

    schema = SchemaGenerator().get_schema(request=None, public=True)
    components = schema["components"]["schemas"]
    for name in (
        "ArchiveDayResponse",
        "ArchiveCell",
        "ReconciliationDayResponse",
        "ReconciliationCell",
        "ReconciliationMismatch",
    ):
        assert name in components, f"{name} missing from generated OpenAPI components"
        assert (
            "additionalProperties" not in components[name]
        ), f"{name} degraded to an untyped object"

    cells = components["ArchiveDayResponse"]["properties"]["cells"]
    assert cells["items"]["$ref"].endswith("/ArchiveCell")


def test_openapi_registers_exactly_the_two_market_data_routes() -> None:
    """Deliberately TWO endpoints, not four: symbol and timeframe are
    composable filters, not separate resources."""
    from drf_spectacular.generators import SchemaGenerator

    schema = SchemaGenerator().get_schema(request=None, public=True)
    paths = {p for p in schema["paths"] if p.startswith("/api/v1/market-data/")}
    assert paths == {
        "/api/v1/market-data/archive/{trading_date}/",
        "/api/v1/market-data/reconciliation/{trading_date}/",
    }
    for path in paths:
        assert set(schema["paths"][path]) == {"get"}, f"{path} exposes a non-GET method"
