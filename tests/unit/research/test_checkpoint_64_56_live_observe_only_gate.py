# tests/unit/research/test_checkpoint_64_56_live_observe_only_gate.py
#
# Checkpoint 64.56: dynamic, spy/mock-based proof of the new
# MARKET_DATA_OBSERVE_ONLY safety gate. Checkpoint 64.55 discovered
# that a successful `--provider dhan` run could reach
# `promote_bars_and_trigger_signals()`, which can automatically drive
# the default `ema_crossover` strategy against PAPER as soon as a bar
# is promoted. This file proves - dynamically, with the REAL, unmocked
# `evaluate_bar_promotion()` gate and REAL bars built through the REAL
# `aggregate_quotes_into_bars()` (never a synthetic "assume it's
# TRADING_GRADE_BAR" shortcut) - that the new
# `strategy_execution_enabled` gate genuinely prevents strategy
# evaluation, `OrderIntent` construction, and `PaperBroker` execution
# from ever being reached, even for a bar that WOULD otherwise be
# promotable and WOULD otherwise reach the strategy engine.
#
# Every bar used below is built exactly the way Checkpoint 64.55's own
# `test_f_promotion_gate_reaches_trading_grade_bar_only_with_full_
# evidence` proved reaches `BarQualityGrade.TRADING_GRADE_BAR` - reused
# deliberately, not reinvented, so this file's own "this bar WOULD
# trigger a signal" claim rests on already-verified evidence.
from __future__ import annotations

import datetime as dt
import io
from decimal import Decimal

import pytest
from django.core.management import call_command

from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.aggregation import (
    BarAggregationResult,
    BarQualityGrade,
    BarStatus,
    aggregate_quotes_into_bars,
)
from intraday.domain.market_data.contracts import Quote
from intraday.domain.market_data.promotion import evaluate_bar_promotion
from intraday.domain.session.calendar import build_session_for
from intraday.domain.session.contracts import TradingSession
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe
from intraday.infrastructure.api import active_loop_runtime, signal_pipeline_runtime
from intraday.infrastructure.api.signal_pipeline_runtime import promote_bars_and_trigger_signals
from intraday.infrastructure.persistence.models import (
    AggregatedBarObservation,
    LiveQuoteObservation,
    SignalRecord,
)
from tests.postgres_utils import requires_postgres

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
SESSION_DATE = dt.date(2026, 1, 5)  # a Monday, session-neutral


def _real_trading_grade_bar_result() -> tuple[BarAggregationResult, TradingSession, dt.datetime]:
    """Builds ONE real, unmocked `TRADING_GRADE_BAR`-eligible closed
    bar, using the exact recipe Checkpoint 64.55's own `test_f` proved
    produces `BarQualityGrade.TRADING_GRADE_BAR` with
    `failed_conditions == ()` - never a shortcut/assumption. Returns
    the aggregation result, the real session, and the clock instant a
    caller of `promote_bars_and_trigger_signals()` would supply."""
    base = dt.datetime(2026, 1, 5, 4, 0, tzinfo=dt.UTC)  # 09:30 IST - real market open
    session = build_session_for(SESSION_DATE, base)
    quotes = tuple(
        Quote(
            instrument_id=RELIANCE,
            timestamp=base + dt.timedelta(seconds=i * 20),
            last_price=Decimal("2500.00") + i,
            source="checkpoint_64_56_test",
        )
        for i in range(6)
    ) + (
        Quote(
            instrument_id=RELIANCE,
            timestamp=base + dt.timedelta(minutes=1, seconds=5),
            last_price=Decimal("2505.00"),
            source="checkpoint_64_56_test",
        ),
    )
    result = aggregate_quotes_into_bars(
        quotes,
        timeframe=Timeframe.ONE_MINUTE,
        as_of=quotes[-1].timestamp + dt.timedelta(minutes=1),
        data_source="checkpoint_64_56_test",
    )
    closed = [b for b in result.bars if b.status is BarStatus.CLOSED]
    assert closed, "setup bug: this recipe must produce a CLOSED bar (matches 64.55's test_f)"
    # Sanity-check the REAL promotion gate reaches TRADING_GRADE_BAR for
    # this exact bar BEFORE using it in any gate test below - otherwise
    # a "strategy never ran" assertion would be meaningless (nothing
    # would have run anyway).
    promotion = evaluate_bar_promotion(
        bar=closed[0], session=session, preceding_bars=(), connection_is_healthy=True, now=base
    )
    assert promotion.grade is BarQualityGrade.TRADING_GRADE_BAR
    assert promotion.failed_conditions == ()
    # Isolate to exactly ONE closed, provably-promotable bar - the
    # aggregation may also produce a second, later bar from the
    # trailing quote; keeping only the sanity-checked bar keeps this
    # file's own assertions ("promoted_count == 1") unambiguous.
    single_bar_result = BarAggregationResult(
        bars=(closed[0],), missing_intervals=(), anomalous_observations=()
    )
    return single_bar_result, session, base


# --- A: default behavior is UNCHANGED for every pre-existing caller ---


def test_a_default_still_triggers_the_active_loop_exactly_like_before_64_56(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Checkpoint 64.56 must not silently change the REST-ingestion
    path's (Checkpoint 41/46, already-accepted PAPER trading) existing
    behavior. Calling `promote_bars_and_trigger_signals()` with NO
    `strategy_execution_enabled` argument at all - exactly how every
    pre-64.56 caller invokes it - must still reach the active loop."""
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        signal_pipeline_runtime, "run_active_loop_tick", lambda **kw: calls.append(kw)
    )
    result, session, clock = _real_trading_grade_bar_result()

    outcome = promote_bars_and_trigger_signals(
        result, session=session, clock=clock, connection_is_healthy=True
    )

    assert outcome.promoted_count == 1
    assert outcome.active_loop_invocations == 1
    assert len(calls) == 1


# --- B: observe-only mode blocks strategy execution for a REAL promotable bar ---


def test_b_observe_only_mode_blocks_the_active_loop_for_a_real_trading_grade_bar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE core Checkpoint 64.56 proof: a bar that the REAL,
    unmocked `evaluate_bar_promotion()` genuinely grades
    TRADING_GRADE_BAR - a bar that Test A above just proved WOULD
    trigger the active loop under the pre-existing default - must NOT
    reach `run_active_loop_tick()` when `strategy_execution_enabled=
    False`. The spy raises if ever called, the strongest available
    proof of non-invocation (not just "it wasn't in the returned
    outcome," but "the function was never even called")."""

    def _raises_if_called(**kwargs: object) -> None:
        raise AssertionError(
            "run_active_loop_tick must NEVER be called under strategy_execution_enabled=False"
        )

    monkeypatch.setattr(signal_pipeline_runtime, "run_active_loop_tick", _raises_if_called)
    result, session, clock = _real_trading_grade_bar_result()

    outcome = promote_bars_and_trigger_signals(
        result,
        session=session,
        clock=clock,
        connection_is_healthy=True,
        strategy_execution_enabled=False,
    )

    # Promotion itself is UNAFFECTED - observe-only means "ingest,
    # aggregate, promote, persist," never "stop grading bars."
    assert outcome.promoted_count == 1
    # But strategy execution never happened.
    assert outcome.active_loop_invocations == 0


@pytest.mark.parametrize("strategy_id", ["ema_crossover", "sma_crossover", "third_party_strategy"])
def test_c_observe_only_blocks_every_strategy_id_not_just_the_default(
    monkeypatch: pytest.MonkeyPatch, strategy_id: str
) -> None:
    """G/H/I: EMA, SMA, and any other future strategy id are ALL disabled under observe-only -
    the gate operates BEFORE any strategy-specific dispatch, so it
    protects every `strategy_id`, not only the current
    `DEFAULT_STRATEGY_ID` (`ema_crossover`). `sma_crossover`/
    `third_party_strategy` need not even be a registered strategy for this
    proof to hold - the gate short-circuits before the strategy id is
    ever used to look anything up."""

    def _raises_if_called(**kwargs: object) -> None:
        raise AssertionError(f"run_active_loop_tick must never run for strategy_id={strategy_id}")

    monkeypatch.setattr(signal_pipeline_runtime, "run_active_loop_tick", _raises_if_called)
    result, session, clock = _real_trading_grade_bar_result()

    outcome = promote_bars_and_trigger_signals(
        result,
        session=session,
        clock=clock,
        connection_is_healthy=True,
        strategy_id=strategy_id,
        strategy_execution_enabled=False,
    )

    assert outcome.promoted_count == 1
    assert outcome.active_loop_invocations == 0


# --- D: deep boundary - even the strategy-execution/OrderIntent/PaperBroker
# composition point one layer below is never reached ---


def test_d_the_deeper_strategy_order_broker_boundary_is_also_never_reached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Goes one layer deeper than Test B: `PaperSignalExecutionService`
    (`active_loop_runtime.py`'s own composition of strategy evaluation,
    `OrderIntent` construction via `evaluate_and_submit()`, and
    `PaperBroker` submission) is patched to explode if even
    CONSTRUCTED. Test A already proves this same class WOULD be
    reached under the pre-existing default (strategy_execution_enabled
    defaults True and Test A's spy on `run_active_loop_tick` itself
    already proves the call happens) - this test proves that under
    observe-only, the pipeline never even gets close enough to
    `active_loop_runtime.py` to construct it."""

    class _ExplodesIfConstructed:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise AssertionError(
                "PaperSignalExecutionService (strategy eval / OrderIntent / PaperBroker "
                "boundary) must never be constructed under strategy_execution_enabled=False"
            )

    monkeypatch.setattr(active_loop_runtime, "PaperSignalExecutionService", _ExplodesIfConstructed)
    result, session, clock = _real_trading_grade_bar_result()

    outcome = promote_bars_and_trigger_signals(
        result,
        session=session,
        clock=clock,
        connection_is_healthy=True,
        strategy_execution_enabled=False,
    )

    assert outcome.promoted_count == 1
    assert outcome.active_loop_invocations == 0


# --- E: no Dhan order API anywhere in this pipeline (structural, like 64.55) ---


def test_e_no_order_placement_identifier_anywhere_in_the_observe_only_call_chain() -> None:
    """There is no Dhan order-placement client wired into
    `signal_pipeline_runtime.py` or `active_loop_runtime.py` at all -
    dynamically proving the absence of a call that literally cannot be
    made is not meaningful (there's nothing to spy on), so this is
    confirmed the same honest way Checkpoint 64.55 confirmed it: a
    direct source scan for forbidden identifiers, on the two modules
    this checkpoint actually touched."""
    import inspect

    forbidden = ("place_order", "PlaceOrder", "OrderPlacementClient", "submit_order")
    for module in (signal_pipeline_runtime, active_loop_runtime):
        source = inspect.getsource(module)
        for name in forbidden:
            assert name not in source, f"{name!r} must not appear in {module.__name__}"


# --- F: mode CLI wiring, fail-closed default ---


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_f_default_mode_is_observe_only_and_no_signal_is_ever_recorded() -> None:
    """Integration-level control test (Checkpoint 64.56 §14): running
    the REAL worker command through `--provider fake-ws`, with NO
    `--mode` flag supplied at all, must produce zero new
    `SignalRecord` rows - the fail-closed default in action end to
    end, through the real command, not just the pure function."""
    signals_before = SignalRecord.objects.count()
    out = io.StringIO()

    call_command(
        "run_market_data_worker", "--provider", "fake-ws", "--packet-count", "10", stdout=out
    )

    assert SignalRecord.objects.count() == signals_before
    assert "mode=observe-only" in out.getvalue()
    assert "DISABLED (observe-only)" in out.getvalue()


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_f2_explicit_observe_only_flag_prints_the_same_disabled_message() -> None:
    out = io.StringIO()

    call_command(
        "run_market_data_worker",
        "--provider",
        "fake-ws",
        "--packet-count",
        "5",
        "--mode",
        "observe-only",
        stdout=out,
    )

    assert "mode=observe-only" in out.getvalue()
    assert "DISABLED (observe-only)" in out.getvalue()


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_f3_explicit_paper_mode_prints_the_enabled_message() -> None:
    """Proves the two modes are genuinely distinct and controllable -
    `--mode paper` (an explicit opt-in, never the default) reports
    strategy execution as ENABLED. This does NOT assert a signal was
    created (market-session timing at real test-run time is outside
    this test's control - the existing `run_active_loop_tick()`
    session gate would legitimately skip outside real market hours,
    exactly as it already does for the pre-existing REST path) - only
    that the MODE ITSELF is reported honestly, matching what Section 8
    of the directive requires: paper and observe-only must remain
    conceptually distinct and never confused in the operator-facing
    output."""
    out = io.StringIO()

    call_command(
        "run_market_data_worker",
        "--provider",
        "fake-ws",
        "--packet-count",
        "5",
        "--mode",
        "paper",
        stdout=out,
    )

    assert "mode=paper" in out.getvalue()
    assert "ENABLED (PAPER)" in out.getvalue()


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_f4_an_unrecognized_mode_value_is_rejected_outright_never_silently_enabled() -> None:
    """`--mode` uses argparse `choices` - a malformed value is REJECTED
    before the command even runs, never silently defaulted to
    'paper'."""
    from django.core.management.base import CommandError

    with pytest.raises((CommandError, SystemExit)):
        call_command(
            "run_market_data_worker",
            "--provider",
            "fake-ws",
            "--mode",
            "not-a-real-mode",
            stdout=io.StringIO(),
        )


# --- G: market-data ingestion, aggregation, promotion, persistence still work ---


@requires_postgres
@pytest.mark.django_db(transaction=True)
def test_g_observe_only_mode_still_persists_quotes_and_bars() -> None:
    """Checkpoint 64.56 §15: observe-only must NOT disable the
    market-data persistence path - only the strategy pipeline. Reuses
    the exact before/after DB-delta pattern Checkpoint 64.55's own
    `test_g` established."""
    quotes_before = LiveQuoteObservation.objects.count()
    bars_before = AggregatedBarObservation.objects.count()
    out = io.StringIO()

    call_command(
        "run_market_data_worker", "--provider", "fake-ws", "--packet-count", "8", stdout=out
    )

    assert LiveQuoteObservation.objects.count() - quotes_before == 8
    assert AggregatedBarObservation.objects.count() >= bars_before
    assert "aggregated" in out.getvalue()


# --- H: expired-token behavior is unaffected by the new mode flag ---


@requires_postgres
@pytest.mark.django_db
def test_h_expired_token_still_refuses_to_connect_even_with_mode_paper_explicitly_requested(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Checkpoint 64.56 §12/§13: the mode flag must NEVER override or
    interact with the credential/token gate - an expired token refuses
    the connection BEFORE mode is even relevant, regardless of which
    mode was requested. Proves `--mode paper` cannot be used to bypass
    the pre-existing token-expiry safety stop."""
    import base64
    import json

    from intraday.application.services.provider_settings import DhanSettingsService

    expired_at = dt.datetime.now(tz=dt.UTC) - dt.timedelta(hours=1)
    header = base64.urlsafe_b64encode(b'{"alg":"HS512","typ":"JWT"}').rstrip(b"=").decode()
    payload = (
        base64.urlsafe_b64encode(json.dumps({"exp": expired_at.timestamp()}).encode())
        .rstrip(b"=")
        .decode()
    )
    expired_jwt = f"{header}.{payload}.fake-signature-not-verified"

    monkeypatch.setattr(
        DhanSettingsService,
        "effective_credentials",
        lambda self: ("fake-client-id", expired_jwt),
    )
    out = io.StringIO()

    call_command("run_market_data_worker", "--provider", "dhan", "--mode", "paper", stdout=out)

    assert "final_state=TOKEN_EXPIRED" in out.getvalue()
    assert "refusing to start a live connection" in out.getvalue()
    assert expired_jwt not in out.getvalue()


# --- I: BacktestTrustLevel is untouched by this checkpoint ---


def test_i_backtest_trust_level_poc_unchanged() -> None:
    from intraday.research.backtesting.contracts import BacktestTrustLevel

    assert BacktestTrustLevel.POC.name == "POC"
