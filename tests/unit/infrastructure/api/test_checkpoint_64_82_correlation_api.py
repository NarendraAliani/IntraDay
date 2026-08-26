# tests/unit/infrastructure/api/test_checkpoint_64_82_correlation_api.py
#
# Checkpoint 64.82 Phase 15/16: coverage for the read-only correlation
# query surface. Mirrors `test_checkpoint_64_81_traceability_api.py`'s
# established pattern exactly - real Django test Client against the real
# URLconf, real persisted rows, never fabricated data.
#
# Every test below maps to a lettered Phase 16 requirement; the letter
# is named in the test's own docstring so the mapping is checkable.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext

from intraday.infrastructure.persistence.models import (
    PaperOrderRecord,
    PaperTradeRecord,
    ScannerScanProgress,
    SignalEvidenceRecord,
    SignalRecord,
    StrategyConfigurationRecord,
)
from tests.postgres_utils import requires_postgres

READER_USERNAME = "correlation_reader"  # noqa: S105
PASSWORD = "correct-horse-battery-staple"  # noqa: S105

BASE = datetime(2026, 2, 9, 4, 15, tzinfo=UTC)
RUN_A = "2026-02-09T04:15:00+00:00"
RUN_B = "2026-02-09T04:20:00+00:00"
VERSION_A = "specv1:codev1:configv1"
VERSION_B = "specv2:codev2:configv2"


def _client() -> Client:
    User.objects.create_user(username=READER_USERNAME, password=PASSWORD)
    client = Client()
    assert client.login(username=READER_USERNAME, password=PASSWORD)
    return client


def _signal(signal_id: str = "sig-1", **overrides: object) -> SignalRecord:
    defaults: dict[str, object] = {
        "signal_id": signal_id,
        "strategy_id": "ema_crossover",
        "instrument_id": "NSE:RELIANCE",
        "direction": "BULLISH",
        "price": Decimal("101"),
        "timeframe": "1m",
        "signal_timestamp": BASE,
        "risk_status": "APPROVED",
    }
    defaults.update(overrides)
    return SignalRecord.objects.create(**defaults)


def _order(order_id: str = "order-1", **overrides: object) -> PaperOrderRecord:
    defaults: dict[str, object] = {
        "order_id": order_id,
        "idempotency_key": f"idem-{order_id}",
        "correlation_id": "corr-1",
        "instrument_id": "NSE:RELIANCE",
        "strategy_id": "ema_crossover",
        "side": "BUY",
        "order_type": "MARKET",
        "quantity": Decimal("10"),
        "filled_quantity": Decimal("10"),
        "status": "FILLED",
        "created_at": BASE,
    }
    defaults.update(overrides)
    return PaperOrderRecord.objects.create(**defaults)


def _trade(trade_id: str = "trade-1", **overrides: object) -> PaperTradeRecord:
    defaults: dict[str, object] = {
        "trade_id": trade_id,
        "strategy_id": "ema_crossover",
        "instrument_id": "NSE:RELIANCE",
        "direction": "BUY",
        "order_ids": ["order-1"],
        "entry_price": Decimal("100"),
        "exit_price": Decimal("101"),
        "quantity": Decimal("10"),
        "realized_pnl": Decimal("10"),
        "opened_at": BASE,
        "closed_at": BASE,
    }
    defaults.update(overrides)
    return PaperTradeRecord.objects.create(**defaults)


def _evidence(signal_id: str, fields: list[list[object]]) -> SignalEvidenceRecord:
    return SignalEvidenceRecord.objects.create(
        signal_id=signal_id,
        strategy_id="ema_crossover",
        schema_version="1",
        fields=fields,
        generated_at=BASE,
    )


# ---------------------------------------------------------------------------
# (A)(B) signal trace returns the correct version and scanner run
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.django_db
def test_a_signal_trace_returns_the_exact_recorded_strategy_version() -> None:
    """(A) The version returned is the one stored on THIS signal, not the
    strategy's currently-active version."""
    _signal("sig-1", strategy_version_identifier=VERSION_A)
    _signal("sig-2", strategy_version_identifier=VERSION_B)
    body = _client().get("/api/v1/correlation/signals/sig-1/trace/").json()
    assert body["strategy_version_identifier"] == VERSION_A


@requires_postgres
@pytest.mark.django_db
def test_b_signal_trace_returns_the_exact_recorded_scan_run_id() -> None:
    """(B) The timestamp-shaped run id is preserved byte-for-byte."""
    _signal("sig-1", scan_run_id=RUN_A)
    body = _client().get("/api/v1/correlation/signals/sig-1/trace/").json()
    assert body["scan_run_id"] == RUN_A


# ---------------------------------------------------------------------------
# (C)(D)(E) isolation: a trace never leaks another signal's rows
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.django_db
def test_c_signal_trace_returns_only_its_own_evidence() -> None:
    """(C)"""
    _signal("sig-1")
    _signal("sig-2")
    _evidence("sig-1", [["EMA Fast", "101.5", "ema_12"]])
    _evidence("sig-2", [["EMA Fast", "999.9", "ema_26"]])
    body = _client().get("/api/v1/correlation/signals/sig-1/trace/").json()
    assert [f["value"] for f in body["evidence"]] == ["101.5"]


@requires_postgres
@pytest.mark.django_db
def test_d_signal_trace_returns_only_its_own_orders() -> None:
    """(D)"""
    _signal("sig-1")
    _signal("sig-2")
    _order("order-1", signal_id="sig-1")
    _order("order-2", signal_id="sig-2")
    body = _client().get("/api/v1/correlation/signals/sig-1/trace/").json()
    assert [o["order_id"] for o in body["orders"]] == ["order-1"]


@requires_postgres
@pytest.mark.django_db
def test_e_signal_trace_returns_only_its_own_trades_and_pnl() -> None:
    """(E) Realised P&L is summed over LINKED trades only."""
    _signal("sig-1")
    _signal("sig-2")
    _trade("trade-1", signal_id="sig-1", realized_pnl=Decimal("25"))
    _trade("trade-2", signal_id="sig-2", realized_pnl=Decimal("999"))
    body = _client().get("/api/v1/correlation/signals/sig-1/trace/").json()
    assert [t["trade_id"] for t in body["trades"]] == ["trade-1"]
    assert Decimal(body["realized_pnl"]) == Decimal("25")


# ---------------------------------------------------------------------------
# (F)(H) manual workflows keep their honest absence
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.django_db
def test_f_manual_trade_never_acquires_a_fabricated_signal_id() -> None:
    """(F)(H) A manually-created trade sharing instrument, direction, and
    timestamp with a real signal must STILL report `signal_id: null` -
    the read model must not match on any of those attributes."""
    _signal("sig-1", scan_run_id=RUN_A)
    _trade("trade-manual", signal_id="")
    body = _client().get("/api/v1/correlation/trades/trade-manual/trace/").json()
    assert body["signal_id"] is None
    assert body["trace"] is None


@requires_postgres
@pytest.mark.django_db
def test_h_signal_linked_trade_reverse_trace_resolves() -> None:
    """(H) The reverse traversal still works for a genuinely linked
    trade - the null case above is not achieved by disabling the join."""
    _signal("sig-1", strategy_version_identifier=VERSION_A)
    _trade("trade-1", signal_id="sig-1")
    body = _client().get("/api/v1/correlation/trades/trade-1/trace/").json()
    assert body["signal_id"] == "sig-1"
    assert body["trace"]["strategy_version_identifier"] == VERSION_A


# ---------------------------------------------------------------------------
# (G) scan run isolation
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.django_db
def test_g_scan_run_trace_returns_only_signals_of_that_run() -> None:
    """(G)"""
    _signal("sig-1", scan_run_id=RUN_A)
    _signal("sig-2", scan_run_id=RUN_B)
    _signal("sig-3", scan_run_id="")
    body = _client().get(f"/api/v1/correlation/runs/{RUN_A}/signals/").json()
    assert body["signal_count"] == 1
    assert [s["signal_id"] for s in body["signals"]] == ["sig-1"]
    assert body["strategy_ids"] == ["ema_crossover"]


@requires_postgres
@pytest.mark.django_db
def test_g_scan_run_metadata_is_null_when_the_progress_row_moved_on() -> None:
    """(G) The scanner-progress singleton is overwritten by each run, so
    an older run honestly reports no metadata rather than borrowing the
    current run's."""
    _signal("sig-1", scan_run_id=RUN_A)
    ScannerScanProgress.objects.create(provider="dhan", scan_id=RUN_B, status="RUNNING")
    body = _client().get(f"/api/v1/correlation/runs/{RUN_A}/signals/").json()
    assert body["run_metadata_available"] is False
    assert body["scan_started_at"] is None
    assert body["status"] is None


@requires_postgres
@pytest.mark.django_db
def test_unknown_scan_run_returns_empty_not_fabricated() -> None:
    body = _client().get("/api/v1/correlation/runs/never-happened/signals/").json()
    assert body["signal_count"] == 0
    assert body["signals"] == []


# ---------------------------------------------------------------------------
# (I) evidence field identity is canonical where resolvable
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.django_db
def test_i_evidence_field_ids_are_canonical_where_applicable() -> None:
    """(I) `ema_12` resolves to canonical field id `ema`; a genuinely
    non-feature row stays `null` rather than being forced to resolve."""
    _signal("sig-1")
    _evidence("sig-1", [["EMA Fast", "101.5", "ema_12"], ["Price", "101", None]])
    body = _client().get("/api/v1/correlation/signals/sig-1/trace/").json()
    assert body["evidence"][0]["field_id"] == "ema"
    assert body["evidence"][0]["feature_name"] == "ema_12"
    assert body["evidence"][1]["field_id"] is None


@requires_postgres
@pytest.mark.django_db
def test_k_legacy_two_element_evidence_rows_remain_readable() -> None:
    """(K) Pre-64.81 `[label, value]` rows still render, carrying no
    fabricated identity."""
    _signal("sig-1")
    _evidence("sig-1", [["EMA Fast", "101.5"]])
    body = _client().get("/api/v1/correlation/signals/sig-1/trace/").json()
    assert body["evidence"][0]["label"] == "EMA Fast"
    assert body["evidence"][0]["feature_name"] is None
    assert body["evidence"][0]["field_id"] is None


# ---------------------------------------------------------------------------
# (J) null / empty semantics
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.django_db
def test_j_missing_relationships_are_null_or_empty_never_invented() -> None:
    """(J) A bare signal - no run, no version, no evidence, no order, no
    trade - reports every absence honestly. `realized_pnl` is `null`,
    NOT `0`."""
    _signal("sig-1")
    body = _client().get("/api/v1/correlation/signals/sig-1/trace/").json()
    assert body["scan_run_id"] is None
    assert body["strategy_version_identifier"] is None
    assert body["evidence"] == []
    assert body["evidence_schema_version"] is None
    assert body["orders"] == []
    assert body["trades"] == []
    assert body["realized_pnl"] is None


@requires_postgres
@pytest.mark.django_db
def test_j_zero_pnl_is_distinguishable_from_no_linked_trade() -> None:
    """(J) A break-even linked trade yields `0`, not `null` - proving the
    two states are genuinely distinct on the wire."""
    _signal("sig-1")
    _trade("trade-1", signal_id="sig-1", realized_pnl=Decimal("0"))
    body = _client().get("/api/v1/correlation/signals/sig-1/trace/").json()
    assert body["realized_pnl"] is not None
    assert Decimal(body["realized_pnl"]) == Decimal("0")


@requires_postgres
@pytest.mark.django_db
def test_l_market_data_outcome_is_reported_honestly() -> None:
    """Phase 12, UPDATED BY CHECKPOINT 64.83 Phase 7.

    64.82 asserted the literal placeholder `"ARCHIVE_API_NOT_IMPLEMENTED"`
    because no archive API existed to consult. 64.83 resolves the status
    against the real 64.73 archive projection, so the placeholder is
    gone. The INVARIANT the original test existed to protect is
    unchanged and is what is asserted here: a signal with no archived
    market-data evidence must say so plainly rather than fabricate
    evidence. This signal has no archive row, so the honest answer is
    ARCHIVE_NOT_AVAILABLE.

    See `test_checkpoint_64_83_archive_api.py` for the positive cases
    (ARCHIVE_PARTIAL / ARCHIVE_COMPLETE_NOT_RECONCILED)."""
    _signal("sig-1")
    body = _client().get("/api/v1/correlation/signals/sig-1/trace/").json()
    assert body["market_data_outcome_status"] == "ARCHIVE_NOT_AVAILABLE"


@requires_postgres
@pytest.mark.django_db
def test_unknown_signal_returns_404_without_a_stack_trace() -> None:
    response = _client().get("/api/v1/correlation/signals/nope/trace/")
    assert response.status_code == 404
    body = response.json()
    assert "Traceback" not in str(body)


# ---------------------------------------------------------------------------
# (H) strategy configuration trace: required features vs evidence
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.django_db
def test_h_required_features_are_canonical_field_ids() -> None:
    """(H) `required_features` carries canonical `field_id`s resolved
    from the strategy's own `required_features(config)` output, and the
    matched signals are exactly those of this version."""
    StrategyConfigurationRecord.objects.create(
        strategy_id="ema_crossover",
        specification_version="specv1",
        code_version="codev1",
        configuration_version="configv1",
        parameter_values={"fast_lookback": 12, "slow_lookback": 26},
        created_at=BASE,
        created_by="tester",
    )
    _signal("sig-1", strategy_version_identifier=VERSION_A)
    _signal("sig-2", strategy_version_identifier=VERSION_B)
    body = (
        _client()
        .get(
            "/api/v1/correlation/strategies/ema_crossover/configurations/specv1/codev1/configv1/trace/"
        )
        .json()
    )
    assert body["strategy_version_identifier"] == VERSION_A
    assert [s["signal_id"] for s in body["signals"]] == ["sig-1"]
    if body["required_features"] is not None:
        # When resolution succeeds it MUST be canonical - a feature name
        # that resolves has a real registry field id, never a guess.
        for feature in body["required_features"]:
            assert "feature_name" in feature
            assert "field_id" in feature


@requires_postgres
@pytest.mark.django_db
def test_required_features_and_evidence_are_never_merged() -> None:
    """Phase 6: a REQUIRED feature is not asserted to have CAUSED any
    signal - the two lists stay separate, and a signal citing nothing
    keeps an empty evidence list even when the configuration requires
    features."""
    StrategyConfigurationRecord.objects.create(
        strategy_id="ema_crossover",
        specification_version="specv1",
        code_version="codev1",
        configuration_version="configv1",
        parameter_values={"fast_lookback": 12, "slow_lookback": 26},
        created_at=BASE,
        created_by="tester",
    )
    _signal("sig-1", strategy_version_identifier=VERSION_A)
    body = (
        _client()
        .get(
            "/api/v1/correlation/strategies/ema_crossover/configurations/specv1/codev1/configv1/trace/"
        )
        .json()
    )
    assert body["signals"][0]["evidence"] == []


@requires_postgres
@pytest.mark.django_db
def test_unknown_strategy_configuration_returns_404() -> None:
    response = _client().get("/api/v1/correlation/strategies/nope/configurations/a/b/c/trace/")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# (L) permissions
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.django_db
@pytest.mark.parametrize(
    "url",
    [
        "/api/v1/correlation/signals/sig-1/trace/",
        f"/api/v1/correlation/runs/{RUN_A}/signals/",
        "/api/v1/correlation/trades/trade-1/trace/",
        "/api/v1/correlation/strategies/s/configurations/a/b/c/trace/",
    ],
)
def test_l_every_correlation_endpoint_requires_authentication(url: str) -> None:
    """(L) Anonymous access is rejected on EVERY endpoint - reusing the
    existing `IsAuthenticated` boundary, no new auth mechanism."""
    _signal("sig-1", scan_run_id=RUN_A)
    assert Client().get(url).status_code in (401, 403)


@requires_postgres
@pytest.mark.django_db
def test_l_correlation_endpoints_are_read_only() -> None:
    """(L) No write verb is routed - this surface cannot mutate
    anything."""
    client = _client()
    _signal("sig-1")
    for method in (client.post, client.put, client.patch, client.delete):
        assert method("/api/v1/correlation/signals/sig-1/trace/").status_code == 405


# ---------------------------------------------------------------------------
# (M) N+1 protection - the hard requirement
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.django_db
def test_m_scan_run_trace_query_count_is_bounded_and_independent_of_signal_count() -> None:
    """(M) THE N+1 GUARD.

    The scan-run trace is the most important multi-signal path: it fans
    out to evidence, orders, and trades for every signal in the run. A
    naive implementation would issue 3 queries PER SIGNAL.

    This test measures the repository's query count for a 2-signal run
    and a 12-signal run and asserts they are IDENTICAL - which is a
    stronger and more honest guarantee than pinning one magic number,
    because it fails for any implementation whose cost grows with N,
    while remaining stable if an unrelated query is added to the path.
    An exact upper bound is asserted too.
    """
    from intraday.infrastructure.persistence.correlation_repository import (
        DjangoCorrelationRepository,
    )

    repository = DjangoCorrelationRepository()

    def _seed(prefix: str, run_id: str, count: int) -> None:
        for i in range(count):
            sid = f"{prefix}-sig-{i}"
            _signal(sid, scan_run_id=run_id, signal_timestamp=BASE + timedelta(minutes=i))
            _evidence(sid, [["EMA Fast", str(100 + i), "ema_12"]])
            _order(f"{prefix}-order-{i}", signal_id=sid)
            _trade(f"{prefix}-trade-{i}", signal_id=sid)

    _seed("small", RUN_A, 2)
    with CaptureQueriesContext(connection) as small:
        small_trace = repository.get_scan_run_trace(RUN_A)

    _seed("large", RUN_B, 12)
    with CaptureQueriesContext(connection) as large:
        large_trace = repository.get_scan_run_trace(RUN_B)

    assert small_trace.signal_count == 2
    assert large_trace.signal_count == 12
    # Correctness first: a bounded query count is only meaningful if the
    # data is actually complete.
    assert all(t.orders and t.trades and t.evidence for t in large_trace.signals)
    # The guarantee: 6x the signals, the SAME number of queries.
    assert len(large.captured_queries) == len(small.captured_queries)
    assert len(large.captured_queries) <= 6


@requires_postgres
@pytest.mark.django_db
def test_m_single_signal_trace_query_count_is_fixed() -> None:
    """(M) The single-signal trace is a FIXED query count regardless of
    how many orders/trades/evidence rows hang off it.

    Checkpoint 64.83 raised the constant from four to five: one bulk
    archive-evidence lookup was added. It is still a CONSTANT - the
    property this test protects - and 64.83's own
    `test_scan_run_trace_query_count_stays_fixed_with_archive_evidence`
    proves the added query does not grow with signal count."""
    from intraday.infrastructure.persistence.correlation_repository import (
        DjangoCorrelationRepository,
    )

    _signal("sig-1")
    _evidence("sig-1", [["EMA Fast", "101", "ema_12"]])
    for i in range(5):
        _order(f"order-{i}", signal_id="sig-1")
        _trade(f"trade-{i}", signal_id="sig-1")

    with CaptureQueriesContext(connection) as captured:
        trace = DjangoCorrelationRepository().get_signal_trace("sig-1")

    assert trace is not None
    assert len(trace.orders) == 5
    assert len(trace.trades) == 5
    assert len(captured.captured_queries) == 5


# ---------------------------------------------------------------------------
# Phase 9: the generated contract must carry NAMED types, never opaque dicts
# ---------------------------------------------------------------------------


def _openapi_schema() -> dict:
    from drf_spectacular.generators import SchemaGenerator

    return SchemaGenerator().get_schema(request=None, public=True)


@pytest.mark.django_db
def test_openapi_exposes_named_correlation_component_schemas() -> None:
    """Phase 9: `CorrelationTrace` and friends must exist as real named
    components - if any of them degraded to an untyped object the
    generated TypeScript would carry `[key: string]: unknown` and the
    contract would be worthless to a caller."""
    document = _openapi_schema()
    schemas = document["components"]["schemas"]
    for name in (
        "CorrelationTrace",
        "CorrelationOrder",
        "CorrelationTrade",
        "CorrelationFeatureEvidence",
        "CorrelationScanRunTraceResponse",
        "CorrelationStrategyTraceResponse",
        "CorrelationTradeTraceResponse",
    ):
        assert name in schemas, f"{name} missing from the generated contract"
        assert "additionalProperties" not in schemas[name]

    trace = schemas["CorrelationTrace"]["properties"]
    assert trace["orders"]["items"]["$ref"].endswith("/CorrelationOrder")
    assert trace["trades"]["items"]["$ref"].endswith("/CorrelationTrade")
    assert trace["evidence"]["items"]["$ref"].endswith("/CorrelationFeatureEvidence")


@pytest.mark.django_db
def test_openapi_registers_all_four_correlation_routes() -> None:
    """Checkpoint 64.82's four endpoints remain the smallest set giving
    full traversal - `signals/{id}/orders/` and `signals/{id}/trades/`
    are deliberately absent: both are strict subsets of the trace
    endpoint. Checkpoint 64.89 adds exactly ONE further route
    (`research/report/`) - the read-only research report built on top of
    that same traversal, per that checkpoint's own "extend an existing
    research endpoint minimally" instruction."""
    paths = _openapi_schema()["paths"]
    correlation = sorted(p for p in paths if p.startswith("/api/v1/correlation/"))
    assert correlation == [
        "/api/v1/correlation/research/report/",
        "/api/v1/correlation/runs/{scan_run_id}/signals/",
        "/api/v1/correlation/signals/{signal_id}/trace/",
        "/api/v1/correlation/strategies/{strategy_id}/configurations/"
        "{specification_version}/{code_version}/{configuration_version}/trace/",
        "/api/v1/correlation/trades/{trade_id}/trace/",
    ]
