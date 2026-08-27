# tests/unit/infrastructure/api/test_checkpoint_64_94_notification_routing.py
#
# Checkpoint 64.94 Phase 13: THE deterministic end-to-end proof that
# EFFECTIVE scanner configuration -> selected_notification_channels ->
# canonical signal -> actual per-channel delivery, exercised through
# the REAL `run_active_loop_tick()` composition root (the same
# function `run_market_data_worker.py` calls), with the ONLY fake
# things being the Telegram/Discord `CommunicationProvider`s
# themselves (never a real network call, never Dhan). Proves
# `signal_id`/`scan_run_id`/`strategy_version_identifier` are all
# preserved on the persisted `SignalRecord` regardless of which
# channels were selected.
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from intraday.application.services.signal_communication import (
    NotificationRouter,
    SignalCommunicationService,
)
from intraday.communication.contracts.signal_communication import (
    CommunicationChannel,
    DeliveryStatus,
)
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.contracts import Bar
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe
from intraday.infrastructure.api import active_loop_runtime
from intraday.infrastructure.api.active_loop_runtime import run_active_loop_tick
from intraday.infrastructure.api.paper_trading_runtime import (
    get_paper_trading_service,
    reset_paper_broker_for_testing,
)
from intraday.infrastructure.persistence.communication_ledger_repository import (
    DjangoCommunicationLedgerRepository,
)
from intraday.infrastructure.persistence.models import CommunicationLedgerRecord, SignalRecord
from intraday.trading_engine.strategy_execution.contracts import StrategyConfigurationValues

pytestmark = pytest.mark.django_db

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
MARKET_OPEN_INSTANT = datetime(2026, 1, 5, 6, 0, tzinfo=UTC)  # 2026-01-05 is a Monday, OPEN


@dataclass
class FakeProvider:
    channel: CommunicationChannel
    provider_name: str
    destination_masked: str = "****fake"
    sent: list[str] = field(default_factory=list)

    def send(self, text: str) -> tuple[bool, str | None, str | None, str | None, bool]:
        self.sent.append(text)
        return True, "fake-msg-1", None, None, False


def _bars(prices: list[int], base: datetime) -> tuple[Bar, ...]:
    return tuple(
        Bar(
            instrument_id=RELIANCE,
            timeframe=Timeframe.ONE_MINUTE,
            timestamp=base + timedelta(minutes=i + 1),
            open=Decimal(price - 1),
            high=Decimal(price + 1),
            low=Decimal(price - 2),
            close=Decimal(price),
            volume=Decimal("0"),
        )
        for i, price in enumerate(prices)
    )


def _uptrend_bars(base: datetime) -> tuple[Bar, ...]:
    flat = [100] * 8
    up = [101 + i for i in range(10)]
    return _bars(flat + up, base)


def _config() -> StrategyConfigurationValues:
    return StrategyConfigurationValues(
        "ema_crossover", "v1", "v1", "v1", {"fast_lookback": 3, "slow_lookback": 6}
    )


@pytest.fixture(autouse=True)
def _reset_broker():  # type: ignore[no-untyped-def]
    reset_paper_broker_for_testing()
    yield
    reset_paper_broker_for_testing()


def _patch_fake_communication_service(
    monkeypatch: pytest.MonkeyPatch, telegram: FakeProvider, discord: FakeProvider
) -> None:
    """Replaces the REAL `get_signal_communication_service()` composition
    (which reads actual Telegram/Discord credentials) with one wired to
    deterministic in-memory fakes, while keeping the REAL
    `NotificationRouter`/`SignalCommunicationService`/durable ledger -
    only the outermost network-touching providers are faked, exactly
    Checkpoint 37's own established test discipline."""

    def _fake_factory(
        *, selected_channels: frozenset[CommunicationChannel] | None = None
    ) -> SignalCommunicationService:
        router = NotificationRouter(
            providers=(telegram, discord),
            ledger=DjangoCommunicationLedgerRepository(),
            selected_channels=selected_channels,
        )
        return SignalCommunicationService(router=router)

    monkeypatch.setattr(active_loop_runtime, "get_signal_communication_service", _fake_factory)


def _run_scan(
    monkeypatch: pytest.MonkeyPatch, *, selected_channel_ids: frozenset[str], scan_run_id: str
) -> tuple[FakeProvider, FakeProvider]:
    telegram = FakeProvider(CommunicationChannel.TELEGRAM, "telegram")
    discord = FakeProvider(CommunicationChannel.DISCORD, "discord")
    _patch_fake_communication_service(monkeypatch, telegram, discord)

    trading_service = get_paper_trading_service()
    bars = _uptrend_bars(MARKET_OPEN_INSTANT)
    trading_service.broker.record_price(RELIANCE, bars[-1].close, MARKET_OPEN_INSTANT)

    selected_channels = frozenset(
        CommunicationChannel(c.upper())
        for c in selected_channel_ids
        if c.upper() in CommunicationChannel.__members__
    )

    outcome = run_active_loop_tick(
        instrument_id=RELIANCE,
        strategy_id="ema_crossover",
        configuration=_config(),
        bars=bars,
        now=MARKET_OPEN_INSTANT,
        scan_run_id=scan_run_id,
        selected_notification_channels=selected_channels,
    )
    assert outcome.ran is True
    return telegram, discord


def test_telegram_only_configuration_end_to_end(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configuration: Universe=SELECTED_STOCKS(RELIANCE),
    Strategies=ema_crossover, Notifications=TELEGRAM ONLY."""
    telegram, discord = _run_scan(
        monkeypatch, selected_channel_ids=frozenset({"telegram"}), scan_run_id="scan-run-tg"
    )
    assert telegram.sent, "Telegram must have been attempted"
    assert not discord.sent, "Discord must NEVER be sent to when not selected"

    record = SignalRecord.objects.exclude(scan_run_id="").get(scan_run_id="scan-run-tg")
    assert record.instrument_id == str(RELIANCE)
    assert record.scan_run_id == "scan-run-tg"
    assert record.strategy_id == "ema_crossover"
    assert record.strategy_version_identifier  # preserved, non-empty

    ledger_rows = list(CommunicationLedgerRecord.objects.filter(signal_id=record.signal_id))
    tg_row = next(r for r in ledger_rows if r.channel == "TELEGRAM")
    dc_row = next(r for r in ledger_rows if r.channel == "DISCORD")
    assert tg_row.delivery_status == DeliveryStatus.SENT.value
    assert dc_row.delivery_status == DeliveryStatus.SKIPPED_NOT_SELECTED.value


def test_discord_only_configuration_end_to_end(monkeypatch: pytest.MonkeyPatch) -> None:
    telegram, discord = _run_scan(
        monkeypatch, selected_channel_ids=frozenset({"discord"}), scan_run_id="scan-run-dc"
    )
    assert discord.sent, "Discord must have been attempted"
    assert not telegram.sent, "Telegram must NEVER be sent to when not selected"

    record = SignalRecord.objects.get(scan_run_id="scan-run-dc")
    assert record.scan_run_id == "scan-run-dc"

    ledger_rows = list(CommunicationLedgerRecord.objects.filter(signal_id=record.signal_id))
    tg_row = next(r for r in ledger_rows if r.channel == "TELEGRAM")
    dc_row = next(r for r in ledger_rows if r.channel == "DISCORD")
    assert dc_row.delivery_status == DeliveryStatus.SENT.value
    assert tg_row.delivery_status == DeliveryStatus.SKIPPED_NOT_SELECTED.value


def test_telegram_and_discord_configuration_end_to_end(monkeypatch: pytest.MonkeyPatch) -> None:
    telegram, discord = _run_scan(
        monkeypatch,
        selected_channel_ids=frozenset({"telegram", "discord"}),
        scan_run_id="scan-run-both",
    )
    assert telegram.sent and discord.sent

    record = SignalRecord.objects.get(scan_run_id="scan-run-both")
    ledger_rows = list(CommunicationLedgerRecord.objects.filter(signal_id=record.signal_id))
    assert {r.channel: r.delivery_status for r in ledger_rows} == {
        "TELEGRAM": DeliveryStatus.SENT.value,
        "DISCORD": DeliveryStatus.SENT.value,
    }
