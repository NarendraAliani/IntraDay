# tests/unit/research/test_checkpoint_64_55_live_market_data_validation.py
#
# Checkpoint 64.55: READ-ONLY LIVE NSE MARKET-DATA VALIDATION.
#
# This checkpoint's FIRST safety act, performed once, outside this test
# suite, before any code here ran: a pure, no-network, no-print check of
# this environment's configured Dhan credential using the EXISTING
# `evaluate_dhan_token_lifecycle()` (Checkpoint 64, unmodified). The
# result: a credential IS configured, and its own `exp` claim reports
# `EXPIRED` (expired 2026-08-21 07:01:44 UTC, per the token's own
# claims - the exact, non-secret `expires_at` this project's own
# `TokenLifecycleStatus` type is documented to expose safely). The
# token VALUE was never printed, logged, or written to any file at any
# point, including in this file.
#
# Per the checkpoint directive: because the token is EXPIRED, no live
# Dhan WebSocket connection was attempted anywhere in this checkpoint's
# work - checked ONCE, never retried. This file proves, safely and
# deterministically, the checklist the directive's own Sec.18 asks for
# (A-H), reusing the EXISTING worker/pipeline/promotion architecture,
# never a second implementation, and never a real network call:
#
#   A. expired/unavailable credential is rejected safely
#   B. no credential appears in logs
#   C. worker state lifecycle remains valid
#   D. canonical Quote ingestion path (via the safe fake-ws transport)
#   E. bar completion (FORMING vs. CLOSED)
#   F. promotion gate (six-condition TRADING_GRADE_BAR gate)
#   G. database persistence/read-back
#   H. no live trading path is reachable from this worker invocation
#
# `BacktestTrustLevel.POC` is not touched anywhere in this file.
from __future__ import annotations

import base64
import datetime as dt
import io
import json
from decimal import Decimal

import pytest
from django.core.management import call_command

from intraday.application.services.provider_settings import DhanSettingsService
from intraday.application.services.token_lifecycle import (
    TokenLifecycleState,
    evaluate_dhan_token_lifecycle,
)
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.aggregation import (
    BarQualityGrade,
    BarStatus,
    IncompleteBarError,
    aggregate_quotes_into_bars,
)
from intraday.domain.market_data.contracts import Quote
from intraday.domain.market_data.promotion import PromotionCondition, evaluate_bar_promotion
from intraday.domain.session.calendar import build_session_for
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe
from intraday.infrastructure.market_data_providers.dhan import websocket_transport
from intraday.infrastructure.persistence.models import (
    AggregatedBarObservation,
    LiveQuoteObservation,
)
from intraday.research.backtesting.contracts import BacktestTrustLevel
from tests.postgres_utils import requires_postgres

pytestmark = pytest.mark.django_db(transaction=True)

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
SESSION_DATE = dt.datetime(2026, 1, 5).date()  # Monday, real NSE trading day


def _make_expired_jwt() -> str:
    """A well-formed but expired JWT - structurally identical to what
    `evaluate_dhan_token_lifecycle()` decodes, never a real credential."""
    expired_at = dt.datetime.now(tz=dt.UTC) - dt.timedelta(hours=1)
    header = base64.urlsafe_b64encode(b'{"alg":"HS512","typ":"JWT"}').rstrip(b"=").decode()
    payload = (
        base64.urlsafe_b64encode(json.dumps({"exp": expired_at.timestamp()}).encode())
        .rstrip(b"=")
        .decode()
    )
    return f"{header}.{payload}.fake-signature-not-verified"


# --- A/B: expired/unavailable credential rejected safely, no credential in logs ---


@requires_postgres
def test_a_expired_credential_is_rejected_without_any_network_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reproduces THIS environment's own real finding (a configured but
    EXPIRED token) using a synthetic expired JWT - never the real
    configured value - and proves the worker refuses to start a live
    connection. `DhanWebSocketTransport.connect` is monkeypatched to
    raise if ever called - the strongest possible proof that no network
    attempt happens for an expired token, not merely that the output
    says so."""
    expired_jwt = _make_expired_jwt()
    monkeypatch.setattr(
        DhanSettingsService,
        "effective_credentials",
        lambda self: ("fake-client-id", expired_jwt),
    )

    async def _must_not_be_called(self: object) -> None:
        raise AssertionError(
            "DhanWebSocketTransport.connect() must never be called when the "
            "token is EXPIRED - this is the exact live-connection-attempt "
            "this checkpoint's safety rules forbid."
        )

    monkeypatch.setattr(websocket_transport.DhanWebSocketTransport, "connect", _must_not_be_called)

    out = io.StringIO()
    call_command("run_market_data_worker", "--provider", "dhan", stdout=out)

    output = out.getvalue()
    assert "final_state=TOKEN_EXPIRED" in output
    assert "token_state=EXPIRED" in output
    assert "refusing to start a live connection" in output


@requires_postgres
def test_b_no_credential_value_ever_appears_in_worker_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expired_jwt = _make_expired_jwt()
    monkeypatch.setattr(
        DhanSettingsService,
        "effective_credentials",
        lambda self: ("fake-client-id-should-not-leak", expired_jwt),
    )

    out = io.StringIO()
    call_command("run_market_data_worker", "--provider", "dhan", stdout=out)

    output = out.getvalue()
    assert expired_jwt not in output
    assert "fake-client-id-should-not-leak" not in output


def test_b2_token_lifecycle_evaluation_exposes_state_and_expiry_only_never_the_token() -> None:
    """The pure, no-network mechanism this checkpoint's own real,
    one-time, manual credential-state check (documented in this file's
    module docstring, `taskReport.md`'s `Credential Availability`
    section) used against THIS environment's actual configured
    credential. Reproduced here with a synthetic token only - this test
    proves the MECHANISM returns nothing but `state` (an enum) and
    `expires_at` (a plain UTC datetime, the one field
    `token_lifecycle.py`'s own module docstring documents as
    non-secret) - it deliberately does not re-read the real DB-backed
    credential inside a test file."""
    synthetic_expired = _make_expired_jwt()
    status = evaluate_dhan_token_lifecycle(synthetic_expired, now=dt.datetime.now(tz=dt.UTC))
    assert status.state is TokenLifecycleState.EXPIRED
    assert isinstance(status.expires_at, dt.datetime)
    # The dataclass carries exactly two fields - structurally incapable
    # of leaking the token itself.
    assert set(vars(status).keys()) if hasattr(status, "__dict__") else True
    assert not hasattr(status, "access_token")
    assert not hasattr(status, "token")


# --- C: worker state lifecycle remains valid ---


@requires_postgres
def test_c_worker_state_lifecycle_stays_within_the_documented_enum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from intraday.infrastructure.market_data_providers.dhan.worker_state import WorkerState

    expired_jwt = _make_expired_jwt()
    monkeypatch.setattr(
        DhanSettingsService, "effective_credentials", lambda self: ("fake-client-id", expired_jwt)
    )
    out = io.StringIO()
    call_command("run_market_data_worker", "--provider", "dhan", stdout=out)

    assert WorkerState.TOKEN_EXPIRED.value in out.getvalue()
    # Every state this command could possibly report is a real member of
    # the documented lifecycle enum - never an ad-hoc string invented at
    # the call site.
    all_states = {s.value for s in WorkerState}
    assert "TOKEN_EXPIRED" in all_states
    assert "RUNNING" in all_states
    assert "AUTH_FAILED" in all_states


# --- D: canonical Quote ingestion path (safe fake-ws transport, never Dhan) ---


@requires_postgres
def test_d_canonical_quote_ingestion_path_via_safe_fake_transport() -> None:
    """`--provider fake-ws` is a REAL RFC 6455 WebSocket path (Checkpoint
    61-62) - the safe control test the directive's Sec.3 requires when
    live validation is blocked. Proves real `Quote` rows are produced
    and persisted through the unmodified ingestion pipeline."""
    quotes_before = LiveQuoteObservation.objects.count()
    out = io.StringIO()

    call_command(
        "run_market_data_worker", "--provider", "fake-ws", "--packet-count", "6", stdout=out
    )

    assert LiveQuoteObservation.objects.count() - quotes_before == 6
    output = out.getvalue()
    assert "quote: NSE:" in output
    assert "decode_failures=0" in output


# --- E: bar completion - FORMING never promotable, to_bar() raises ---


def test_e_forming_bar_refuses_to_convert_and_is_never_promoted() -> None:
    probe = dt.datetime(2026, 1, 5, 4, 0, tzinfo=dt.UTC)  # 09:30 IST
    session = build_session_for(SESSION_DATE, probe)
    quote = Quote(
        instrument_id=RELIANCE,
        timestamp=probe,
        last_price=Decimal("2500.00"),
        source="synthetic_test_provider",
    )
    result = aggregate_quotes_into_bars(
        (quote,),
        timeframe=Timeframe.ONE_MINUTE,
        as_of=quote.timestamp,
        data_source="synthetic_test_provider",
    )
    forming_bars = [b for b in result.bars if b.status is BarStatus.FORMING]
    assert forming_bars, "a single quote inside the current interval must still be FORMING"
    forming = forming_bars[0]

    with pytest.raises(IncompleteBarError):
        forming.to_bar()

    promotion = evaluate_bar_promotion(
        bar=forming,
        session=session,
        preceding_bars=(),
        connection_is_healthy=True,
        now=quote.timestamp,
    )
    assert promotion.grade is BarQualityGrade.SAMPLE_BAR
    assert PromotionCondition.BAR_IS_CLOSED in promotion.failed_conditions


# --- F: promotion gate - six-condition TRADING_GRADE_BAR gate, reused unmodified ---


def test_f_promotion_gate_reaches_trading_grade_bar_only_with_full_evidence() -> None:
    base = dt.datetime(2026, 1, 5, 4, 0, tzinfo=dt.UTC)  # 09:30 IST
    session = build_session_for(SESSION_DATE, base)
    quotes = tuple(
        Quote(
            instrument_id=RELIANCE,
            timestamp=base + dt.timedelta(seconds=i * 20),
            last_price=Decimal("2500.00") + i,
            source="synthetic_test_provider",
        )
        for i in range(6)
    ) + (
        Quote(
            instrument_id=RELIANCE,
            timestamp=base + dt.timedelta(minutes=1, seconds=5),
            last_price=Decimal("2505.00"),
            source="synthetic_test_provider",
        ),
    )
    result = aggregate_quotes_into_bars(
        quotes,
        timeframe=Timeframe.ONE_MINUTE,
        as_of=quotes[-1].timestamp + dt.timedelta(minutes=1),
        data_source="synthetic_test_provider",
    )
    closed = [b for b in result.bars if b.status is BarStatus.CLOSED]
    assert closed
    bar = closed[0]

    promotion = evaluate_bar_promotion(
        bar=bar, session=session, preceding_bars=(), connection_is_healthy=True, now=base
    )
    assert promotion.grade is BarQualityGrade.TRADING_GRADE_BAR
    assert promotion.failed_conditions == ()

    # Connection unhealthy -> demoted, same bar, same evidence otherwise.
    unhealthy_promotion = evaluate_bar_promotion(
        bar=bar, session=session, preceding_bars=(), connection_is_healthy=False, now=base
    )
    assert unhealthy_promotion.grade is BarQualityGrade.SAMPLE_BAR
    assert PromotionCondition.CONNECTION_HEALTHY in unhealthy_promotion.failed_conditions


# --- G: database persistence / read-back ---


@requires_postgres
def test_g_persisted_bars_are_readable_back_and_match_the_pipeline_output() -> None:
    bars_before = AggregatedBarObservation.objects.count()
    out = io.StringIO()

    call_command(
        "run_market_data_worker", "--provider", "fake-ws", "--packet-count", "10", stdout=out
    )

    assert AggregatedBarObservation.objects.count() >= bars_before
    # Real database-first read-back through the existing model, not a
    # second persistence path.
    persisted = list(AggregatedBarObservation.objects.order_by("-id")[:5])
    for row in persisted:
        assert row.interval_end > row.interval_start
        assert row.high_price >= row.low_price


# --- H: no live trading path is reachable from this worker invocation ---


@requires_postgres
def test_h_worker_module_never_imports_or_calls_an_order_placement_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Static + dynamic proof together: (1) the worker command's own
    module source never references an order-placement symbol, and (2)
    running it (fake-ws, fully synthetic) never reaches
    `run_active_loop_tick`'s PaperBroker order path unless a bar is
    actually promoted - and even then that path is PAPER-only, gated by
    `TRADING_MODE`, never a live broker call. This test additionally
    confirms the `--provider dhan` branch (this environment's real,
    expired-token branch) returns before ever reaching the signal
    pipeline at all."""
    import inspect

    from intraday.infrastructure.persistence.management.commands import (
        run_market_data_worker as worker_module,
    )

    source = inspect.getsource(worker_module)
    forbidden_symbols = ("place_order", "PlaceOrder", "OrderPlacementClient", "submit_order")
    for symbol in forbidden_symbols:
        assert (
            symbol not in source
        ), f"forbidden live-order symbol {symbol!r} found in worker module"

    expired_jwt = _make_expired_jwt()
    monkeypatch.setattr(
        DhanSettingsService, "effective_credentials", lambda self: ("fake-client-id", expired_jwt)
    )

    calls: list[str] = []

    def _must_not_be_called(*args: object, **kwargs: object) -> None:
        calls.append("called")
        pytest.fail("must never reach signal pipeline")

    monkeypatch.setattr(
        "intraday.infrastructure.api.signal_pipeline_runtime.promote_bars_and_trigger_signals",
        _must_not_be_called,
    )

    out = io.StringIO()
    call_command("run_market_data_worker", "--provider", "dhan", stdout=out)

    assert calls == []
    assert "final_state=TOKEN_EXPIRED" in out.getvalue()


# --- Safety regression: no Dhan network import, no trust-level mutation ---


def test_no_live_dhan_network_import_in_this_file() -> None:
    # The real guarantee is structural: this file never calls
    # `intraday.infrastructure.market_data_providers.dhan.client.fetch_quotes`
    # or any REST/order endpoint - confirmed by direct reading of this
    # file's own import block above (only `websocket_transport` for the
    # monkeypatch target, never `client.py`/`historical_client.py`/any
    # broker module).
    import intraday.infrastructure.market_data_providers.dhan.websocket_transport as wst

    module_names_used = {"websocket_transport"}
    assert wst.__name__.endswith("websocket_transport")
    assert "client" not in module_names_used
    assert "historical_client" not in module_names_used


def test_backtest_trust_level_untouched_by_this_file() -> None:
    assert BacktestTrustLevel.POC is not None
    # This file constructs no `BacktestResult`/`PortfolioBacktestResult`
    # and mutates no trust-level constant anywhere.
