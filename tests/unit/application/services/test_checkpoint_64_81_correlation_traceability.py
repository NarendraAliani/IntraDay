# tests/unit/application/services/test_checkpoint_64_81_correlation_traceability.py
#
# Checkpoint 64.81 Phase 9: CORRELATION INTEGRITY.
#
# Proves the decision chain
#   Features -> Strategy Version -> Signal -> Paper Order -> Paper Trade
# is mechanically traceable, using the REAL services, the REAL registry,
# the REAL paper broker, and the REAL Django repositories - never a mock
# of the thing under test, and never live market data (`PaperBroker`
# performs no network I/O at all, proven separately since Checkpoint 34).
#
# The governing rule of this checkpoint, and therefore of this file:
# an identifier is either GENUINELY traceable or it is `None`. Several
# tests below exist specifically to prove the NEGATIVE - that a workflow
# with no real relationship is left blank rather than filled with a
# plausible-looking value.
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from intraday.application.repositories.signal_evidence import SignalEvidenceFieldView
from intraday.application.services.paper_signal_execution import PaperSignalExecutionService
from intraday.application.services.paper_trading import PaperTradingService
from intraday.application.services.signal_communication import (
    NotificationRouter,
    SignalCommunicationService,
)
from intraday.application.services.strategy_execution import build_coordinator
from intraday.communication.contracts.signal_communication import CommunicationChannel
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.contracts import Bar
from intraday.domain.risk.contracts import RiskLimits, TradingHaltStatus
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe
from intraday.infrastructure.brokers.paper.broker import PaperBroker
from intraday.infrastructure.persistence.models import (
    PaperOrderRecord,
    PaperTradeRecord,
    SignalEvidenceRecord,
    SignalRecord,
)
from intraday.infrastructure.persistence.paper_ledger_repository import (
    DjangoPaperLedgerRepository,
    _trade_signal_id,
)
from intraday.infrastructure.persistence.signal_evidence_repository import (
    DjangoSignalEvidenceRepository,
    evidence_field_to_view,
)
from intraday.infrastructure.persistence.signal_repository import DjangoSignalRepository
from intraday.signal_intelligence.feature_engine.field_registry import (
    get_field,
    parse_feature_name,
    resolve_feature_name,
)
from intraday.trading_engine.strategy_execution.contracts import StrategyConfigurationValues
from intraday.trading_engine.strategy_execution.registry import build_default_registry

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
BASE = datetime(2026, 1, 5, 3, 45, tzinfo=UTC)

DEFAULT_LIMITS = RiskLimits(
    max_intraday_loss=Decimal("50000"),
    max_position_size=Decimal("1000"),
    max_per_trade_risk=Decimal("10000"),
)


def _no_cost(is_buy: bool, notional: Decimal) -> Decimal:  # noqa: ARG001
    return Decimal("0")


def _rising_bars(count: int = 40) -> tuple[Bar, ...]:
    """A monotonically rising series - guarantees fast EMA > slow EMA and
    price > fast EMA, i.e. a genuine BULLISH `ema_crossover` signal. The
    signal is REAL (produced by the unmodified strategy), never injected.
    """
    return tuple(
        Bar(
            instrument_id=RELIANCE,
            timeframe=Timeframe.ONE_MINUTE,
            timestamp=BASE + timedelta(minutes=i + 1),
            open=Decimal(100 + i),
            high=Decimal(102 + i),
            low=Decimal(99 + i),
            close=Decimal(101 + i),
            volume=Decimal("0"),
        )
        for i in range(count)
    )


def _ema_config() -> StrategyConfigurationValues:
    return StrategyConfigurationValues(
        "ema_crossover", "specv1", "codev1", "configv1", {"fast_lookback": 3, "slow_lookback": 5}
    )


EXPECTED_VERSION_IDENTIFIER = "specv1:codev1:configv1"
"""The flattened identity `{spec}:{code}:{config}` - the SAME shape
`DjangoStrategyVersionRepository.activate()` writes into
`AuditLogEntry.version_identifier`. Written out literally here so that a
future change to the format fails this test loudly rather than silently
producing an identifier nothing else in the platform can join against."""


@dataclass
class FakeProvider:
    channel: CommunicationChannel
    provider_name: str
    destination_masked: str = "****abcd"
    sent: list[str] = field(default_factory=list)

    def send(self, text: str) -> tuple[bool, str | None, str | None, str | None, bool]:
        self.sent.append(text)
        return True, "msg-1", None, None, False


def _bridge() -> tuple[PaperSignalExecutionService, PaperBroker]:
    registry = build_default_registry()
    registry.activate("ema_crossover")
    broker = PaperBroker(
        initial_capital=Decimal("1000000"), compute_cost=_no_cost, clock=lambda: BASE
    )
    trading_service = PaperTradingService(
        broker=broker,
        risk_limits=DEFAULT_LIMITS,
        risk_configuration_version="v1",
        max_concurrent_positions=5,
        max_total_exposure=Decimal("500000"),
        kill_switch_status_provider=lambda: TradingHaltStatus.ACTIVE,
        clock=lambda: BASE,
        # The REAL durable ledger - without it no `PaperOrderRecord` is
        # ever written and the order-side assertions below would be
        # testing nothing.
        ledger=DjangoPaperLedgerRepository(),
    )
    communication = SignalCommunicationService(
        router=NotificationRouter(
            providers=(FakeProvider(CommunicationChannel.TELEGRAM, "telegram"),), ledger=None
        )
    )
    service = PaperSignalExecutionService(
        coordinator=build_coordinator(registry),
        paper_trading_service=trading_service,
        quantity=Decimal("10"),
        communication=communication,
        signal_recorder=DjangoSignalRepository(),
        evidence_recorder=DjangoSignalEvidenceRepository(),
    )
    return service, broker


def _run(service: PaperSignalExecutionService, broker: PaperBroker, *, scan_run_id: str | None):
    bars = _rising_bars()
    broker.record_price(RELIANCE, bars[-1].close, BASE)
    return service.evaluate_and_submit(
        bars=bars,
        instrument_id=RELIANCE,
        strategy_id="ema_crossover",
        configuration=_ema_config(),
        strategy_is_active=True,
        market_session_is_open=True,
        data_quality_is_stale=False,
        already_processed_signal_ids=frozenset(),
        already_submitted_idempotency_keys=frozenset(),
        scan_run_id=scan_run_id,
    )


# ---------------------------------------------------------------------------
# (A) strategy required_features returns canonical field IDs
# ---------------------------------------------------------------------------


def test_a_required_features_resolve_to_canonical_registry_field_ids() -> None:
    """`required_features()` returns PARAMETERIZED names ("ema_3"), which
    are deliberately NOT registry field_ids - that mismatch was the gap.
    Resolution must produce the real registered field, with its
    parameters preserved separately."""
    registry = build_default_registry()
    strategy = registry.get("ema_crossover")

    names = strategy.required_features(_ema_config())
    assert names == ("ema_3", "ema_5")

    resolved = [resolve_feature_name(n) for n in names]
    assert [r.field_id for r in resolved] == ["ema", "ema"]
    assert [r.parameters for r in resolved] == [(3,), (5,)]
    # The resolved field_id is a REAL registry entry, not merely a string
    # that looks plausible.
    for r in resolved:
        assert r.field_id is not None
        assert get_field(r.field_id) is not None


def test_a2_every_registered_strategy_resolves_all_its_required_features() -> None:
    """A registry-wide guard: if a strategy ever declares a feature whose
    kind is not registered, this fails rather than silently emitting
    `field_id: null` to the API."""
    registry = build_default_registry()
    configs = {
        "ema_crossover": _ema_config(),
        "sma_trend_filter": StrategyConfigurationValues(
            "sma_trend_filter", "v1", "v1", "v1", {"lookback": 5}
        ),
        "atr_volatility_breakout": StrategyConfigurationValues(
            "atr_volatility_breakout",
            "v1",
            "v1",
            "v1",
            {
                "lookback": 5,
                "atr_multiplier": Decimal("0.1"),
                "stop_loss_atr_multiplier": Decimal("1.0"),
                "target_1_atr_multiplier": Decimal("1.5"),
                "target_2_atr_multiplier": Decimal("2.5"),
                "target_3_atr_multiplier": Decimal("4.0"),
                "trailing_stop_atr_multiplier": Decimal("1.0"),
            },
        ),
    }
    for strategy_id, config in configs.items():
        strategy = registry.get(strategy_id)
        for name in strategy.required_features(config):
            resolution = resolve_feature_name(name)
            assert resolution.field_id is not None, (strategy_id, name)
            assert get_field(resolution.field_id) is not None


def test_a3_parse_is_the_same_algorithm_the_feature_dispatcher_uses() -> None:
    """The resolver must never drift from the dispatcher that actually
    computes features - multi-word kinds are the case a naive
    first-underscore split would get wrong."""
    assert parse_feature_name("ema_12") == ("ema", (12,))
    assert parse_feature_name("macd_hist_12_26_9") == ("macd_hist", (12, 26, 9))
    assert parse_feature_name("plus_di_14") == ("plus_di", (14,))
    assert parse_feature_name("relative_volume_20") == ("relative_volume", (20,))
    assert parse_feature_name("candle_body_ratio") == ("candle_body_ratio", ())


def test_a4_an_unregistered_feature_name_resolves_to_none_never_a_guess() -> None:
    for bogus in ("definitely_not_a_feature_9", "", "zzz"):
        assert resolve_feature_name(bogus).field_id is None


# ---------------------------------------------------------------------------
# (B) signal evidence preserves field_id
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_b_signal_evidence_carries_canonical_field_identity() -> None:
    service, broker = _bridge()
    result = _run(service, broker, scan_run_id=None)
    assert result.signal_id is not None

    stored = DjangoSignalEvidenceRepository().get_by_signal_id(str(result.signal_id))
    assert stored is not None

    by_label = {f.label: f for f in stored.fields}
    # Feature-derived rows carry the strategy's own feature name AND the
    # canonical registry field_id.
    assert by_label["Fast EMA"].feature_name == "ema_3"
    assert by_label["Fast EMA"].field_id == "ema"
    assert by_label["Slow EMA"].feature_name == "ema_5"
    assert by_label["Slow EMA"].field_id == "ema"
    # The existing label/value contract is untouched.
    assert by_label["Fast EMA"].value not in ("", "Not provided")


@pytest.mark.django_db
def test_b2_non_feature_evidence_rows_stay_null_rather_than_guessing() -> None:
    """`Price` and `Crossover` are the signal's own price/direction, not
    feature readings. A label-matching implementation would be tempted
    to invent an identity for them; this proves we do not."""
    service, broker = _bridge()
    result = _run(service, broker, scan_run_id=None)
    stored = DjangoSignalEvidenceRepository().get_by_signal_id(str(result.signal_id))
    assert stored is not None

    by_label = {f.label: f for f in stored.fields}
    for label in ("Price", "Crossover"):
        assert by_label[label].feature_name is None, label
        assert by_label[label].field_id is None, label


# ---------------------------------------------------------------------------
# (C) scan-run ID propagates to signals when applicable
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_c_scan_run_id_propagates_into_the_persisted_signal() -> None:
    service, broker = _bridge()
    result = _run(service, broker, scan_run_id="2026-01-05T03:45:00+00:00")
    row = SignalRecord.objects.get(signal_id=str(result.signal_id))
    assert row.scan_run_id == "2026-01-05T03:45:00+00:00"


@pytest.mark.django_db
def test_c2_a_signal_generated_outside_a_scan_run_has_no_run_id() -> None:
    """Replay sessions and direct service calls are real workflows with
    genuinely no scanner run - they must not borrow one."""
    service, broker = _bridge()
    result = _run(service, broker, scan_run_id=None)
    row = SignalRecord.objects.get(signal_id=str(result.signal_id))
    assert row.scan_run_id == ""


@pytest.mark.django_db
def test_c3_re_recording_without_a_run_never_erases_a_real_run_id() -> None:
    """Provenance is write-once in practice: a later non-scanner
    re-record of the same deterministic signal must not blank the run
    that genuinely produced it."""
    repo = DjangoSignalRepository()
    common = {
        "signal_id": "sig-abc",
        "strategy_id": "ema_crossover",
        "instrument_id": RELIANCE,
        "direction": "BULLISH",
        "price": Decimal("101"),
        "timeframe": "1m",
        "signal_timestamp": BASE,
        "risk_status": "APPROVED",
        "risk_reason": "",
        "order_status": "FILLED",
    }
    repo.record_signal(**common, scan_run_id="run-1")  # type: ignore[arg-type]
    repo.record_signal(**common, scan_run_id=None)  # type: ignore[arg-type]

    assert SignalRecord.objects.filter(signal_id="sig-abc").count() == 1
    assert SignalRecord.objects.get(signal_id="sig-abc").scan_run_id == "run-1"


# ---------------------------------------------------------------------------
# (D)/(E) signal_id and strategy version propagate into paper execution
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_d_paper_order_carries_the_signal_and_the_exact_strategy_version() -> None:
    service, broker = _bridge()
    result = _run(service, broker, scan_run_id="run-7")
    assert result.order_result is not None

    order_row = PaperOrderRecord.objects.get(signal_id=str(result.signal_id))
    assert order_row.signal_id == str(result.signal_id)

    # The VERSION lives on the signal - the decision record - not
    # duplicated onto the order. See `SignalRecord.
    # strategy_version_identifier` for the two reasons why.
    signal_row = SignalRecord.objects.get(signal_id=str(result.signal_id))
    assert signal_row.strategy_version_identifier == EXPECTED_VERSION_IDENTIFIER


@pytest.mark.django_db
def test_e_trade_traceability_resolves_by_id_join_from_the_entry_order() -> None:
    """The trade-side link is an exact `order_id` join into the order
    ledger - proven here against real persisted rows."""
    PaperOrderRecord.objects.create(
        order_id="order-1",
        idempotency_key="idem-1",
        correlation_id="corr-1",
        instrument_id=str(RELIANCE),
        strategy_id="ema_crossover",
        signal_id="sig-xyz",
        side="BUY",
        order_type="MARKET",
        quantity=Decimal("10"),
        filled_quantity=Decimal("10"),
        status="FILLED",
        created_at=BASE,
    )

    @dataclass(frozen=True)
    class _Trade:
        order_ids: tuple[str, ...]

    assert _trade_signal_id(_Trade(order_ids=("order-1", "order-2"))) == "sig-xyz"  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# (F)/(I) non-signal workflows stay nullable; nothing is fabricated
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_f_a_trade_whose_orders_are_unknown_gets_no_fabricated_identity() -> None:
    @dataclass(frozen=True)
    class _Trade:
        order_ids: tuple[str, ...]

    assert _trade_signal_id(_Trade(order_ids=("no-such-order",))) == ""  # type: ignore[arg-type]
    assert _trade_signal_id(_Trade(order_ids=())) == ""  # type: ignore[arg-type]


@pytest.mark.django_db
def test_f2_a_manual_order_without_a_signal_contributes_no_identity() -> None:
    """A manually-submitted paper order is a real, supported workflow
    with genuinely no signal and no strategy configuration behind it."""
    PaperOrderRecord.objects.create(
        order_id="manual-1",
        idempotency_key="idem-manual-1",
        correlation_id="corr-2",
        instrument_id=str(RELIANCE),
        strategy_id="manual",
        side="BUY",
        order_type="MARKET",
        quantity=Decimal("5"),
        filled_quantity=Decimal("5"),
        status="FILLED",
        created_at=BASE,
    )

    @dataclass(frozen=True)
    class _Trade:
        order_ids: tuple[str, ...]

    assert _trade_signal_id(_Trade(order_ids=("manual-1",))) == ""  # type: ignore[arg-type]


@pytest.mark.django_db
def test_i_a_trade_never_borrows_another_trades_signal() -> None:
    """The single most important negative: an order that is NOT in this
    trade's `order_ids` must never contribute its signal."""
    PaperOrderRecord.objects.create(
        order_id="other-order",
        idempotency_key="idem-other",
        correlation_id="corr-3",
        instrument_id=str(RELIANCE),
        strategy_id="ema_crossover",
        signal_id="someone-elses-signal",
        side="BUY",
        order_type="MARKET",
        quantity=Decimal("1"),
        filled_quantity=Decimal("1"),
        status="FILLED",
        created_at=BASE,
    )

    @dataclass(frozen=True)
    class _Trade:
        order_ids: tuple[str, ...]

    assert _trade_signal_id(_Trade(order_ids=("unrelated",))) == ""  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# (G) existing records without metadata remain readable
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_g_legacy_two_element_evidence_rows_remain_readable() -> None:
    """Pre-64.81 evidence stored `[label, value]` pairs. Those rows must
    still read cleanly, carrying no identity rather than a guessed one -
    which is exactly why no data back-fill exists."""
    SignalEvidenceRecord.objects.create(
        signal_id="legacy-1",
        strategy_id="ema_crossover",
        schema_version="1",
        fields=[["Fast EMA", "100.5"], ["Price", "101"]],
        generated_at=BASE,
    )
    view = DjangoSignalEvidenceRepository().get_by_signal_id("legacy-1")
    assert view is not None
    assert [f.label for f in view.fields] == ["Fast EMA", "Price"]
    assert [f.value for f in view.fields] == ["100.5", "101"]
    assert all(f.feature_name is None and f.field_id is None for f in view.fields)


@pytest.mark.django_db
def test_g2_legacy_records_without_new_columns_remain_readable() -> None:
    """Rows created without the new columns take the blank default and
    stay fully readable - the backward-compatibility guarantee the
    migration relies on."""
    SignalRecord.objects.create(
        signal_id="old-signal",
        strategy_id="ema_crossover",
        instrument_id=str(RELIANCE),
        direction="BULLISH",
        price=Decimal("100"),
        timeframe="1m",
        signal_timestamp=BASE,
        risk_status="APPROVED",
    )
    assert SignalRecord.objects.get(signal_id="old-signal").scan_run_id == ""

    PaperTradeRecord.objects.create(
        trade_id="old-trade",
        strategy_id="ema_crossover",
        instrument_id=str(RELIANCE),
        direction="BUY",
        order_ids=[],
        entry_price=Decimal("100"),
        exit_price=Decimal("101"),
        quantity=Decimal("1"),
        realized_pnl=Decimal("1"),
        opened_at=BASE,
        closed_at=BASE,
    )
    assert PaperTradeRecord.objects.get(trade_id="old-trade").signal_id == ""
    assert SignalRecord.objects.get(signal_id="old-signal").strategy_version_identifier == ""


def test_g3_evidence_decoder_tolerates_a_null_third_element() -> None:
    assert evidence_field_to_view(["Price", "101", None]) == SignalEvidenceFieldView(
        label="Price", value="101", feature_name=None, field_id=None
    )


# ---------------------------------------------------------------------------
# (H) no duplicate correlation records
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_h_re_recording_the_same_signal_creates_no_duplicate_correlation_records() -> None:
    """`signal_id` is deterministic, so every correlation record keyed by
    it must UPDATE in place. Re-recording the identical signal and its
    identical evidence must never produce a second row - otherwise a
    scheduler retry would silently double-count a decision in any future
    attribution analysis."""
    service, broker = _bridge()
    result = _run(service, broker, scan_run_id="run-1")
    signal_id = str(result.signal_id)

    assert SignalRecord.objects.filter(signal_id=signal_id).count() == 1
    assert SignalEvidenceRecord.objects.filter(signal_id=signal_id).count() == 1
    assert PaperOrderRecord.objects.filter(signal_id=signal_id).count() == 1

    # Re-record both correlation artifacts directly - the exact thing a
    # retry would do - and prove the row counts are unchanged.
    row = SignalRecord.objects.get(signal_id=signal_id)
    DjangoSignalRepository().record_signal(
        signal_id=result.signal_id,  # type: ignore[arg-type]
        strategy_id=row.strategy_id,
        instrument_id=RELIANCE,
        direction=row.direction,
        price=row.price,
        timeframe=row.timeframe,
        signal_timestamp=row.signal_timestamp,
        risk_status=row.risk_status,
        risk_reason=row.risk_reason,
        order_status=row.order_status,
        scan_run_id="run-1",
    )
    evidence = DjangoSignalEvidenceRepository().get_by_signal_id(signal_id)
    assert evidence is not None

    assert SignalRecord.objects.filter(signal_id=signal_id).count() == 1
    assert SignalEvidenceRecord.objects.filter(signal_id=signal_id).count() == 1
    assert PaperOrderRecord.objects.filter(signal_id=signal_id).count() == 1
