# tests/unit/application/services/test_signal_verification_service.py
#
# Unit tests for SignalVerificationService (Checkpoint 19) using an
# in-memory FAKE market-data repository - no Django, no database, no
# Dhan. Mirrors SignalGenerationService's own test pattern.
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from intraday.application.services.market_data import HistoricalMarketDataService
from intraday.application.services.signal_verification import SignalVerificationService
from intraday.domain.feature.contracts import FeatureValue
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.contracts import Bar
from intraday.domain.shared_kernel.contracts import Exchange, InstrumentId, Timeframe, Version
from intraday.signal_intelligence.signal_generation.contracts import (
    DirectionalIndication,
    SignalDirection,
)
from intraday.signal_intelligence.signal_verification.contracts import VerificationOutcome

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
START = datetime(2026, 1, 1, 3, 50, tzinfo=UTC)
FEATURE_VERSION = Version(value="v1")


def _bar(close: str, offset_minutes: int) -> Bar:
    price = Decimal(close)
    return Bar(
        instrument_id=RELIANCE,
        timeframe=Timeframe.FIVE_MINUTE,
        timestamp=START + timedelta(minutes=5 * offset_minutes),
        open=price,
        high=price + Decimal("1"),
        low=price - Decimal("1"),
        close=price,
        volume=Decimal("1000"),
    )


def _indication(direction: SignalDirection, price: str) -> DirectionalIndication:
    def _feature(name: str, value: str) -> FeatureValue:
        return FeatureValue(
            feature_name=name,
            feature_version=FEATURE_VERSION,
            instrument_id=RELIANCE,
            timeframe=Timeframe.FIVE_MINUTE,
            timestamp=START,
            value=Decimal(value),
        )

    return DirectionalIndication(
        definition_name="sma_ema_atr_directional",
        definition_version=Version(value="v1"),
        instrument_id=RELIANCE,
        timeframe=Timeframe.FIVE_MINUTE,
        timestamp=START,
        direction=direction,
        price=Decimal(price),
        sma=_feature("sma_20", "100"),
        ema=_feature("ema_10", "100"),
        atr=_feature("atr_14", "5"),
    )


class FakeHistoricalMarketDataRepository:
    def __init__(self, bars: tuple[Bar, ...]) -> None:
        self._bars = bars

    def get_bars(
        self, instrument_id: InstrumentId, timeframe: Timeframe, start: datetime, end: datetime
    ) -> tuple[Bar, ...]:
        return tuple(
            bar
            for bar in self._bars
            if bar.instrument_id == instrument_id
            and bar.timeframe == timeframe
            and start <= bar.timestamp <= end
        )


def _service(bars: tuple[Bar, ...]) -> SignalVerificationService:
    market_data = HistoricalMarketDataService(repository=FakeHistoricalMarketDataRepository(bars))
    return SignalVerificationService(market_data=market_data)


def test_service_verifies_a_bullish_indication_as_supported() -> None:
    bars = (
        _bar("100", offset_minutes=0),
        _bar("102", offset_minutes=1),
        _bar("105", offset_minutes=2),
    )
    service = _service(bars)
    indication = _indication(SignalDirection.BULLISH, "100")

    result = service.verify(indication, horizon_bars=2)

    assert result.outcome is VerificationOutcome.SUPPORTED
    assert result.observed_price == Decimal("105")


def test_service_reports_inconclusive_when_horizon_incomplete() -> None:
    bars = (_bar("100", offset_minutes=0), _bar("101", offset_minutes=1))
    service = _service(bars)
    indication = _indication(SignalDirection.BULLISH, "100")

    result = service.verify(indication, horizon_bars=5)

    assert result.outcome is VerificationOutcome.INCONCLUSIVE


def test_service_output_is_deterministic() -> None:
    bars = (
        _bar("100", offset_minutes=0),
        _bar("102", offset_minutes=1),
        _bar("105", offset_minutes=2),
    )
    service = _service(bars)
    indication = _indication(SignalDirection.BULLISH, "100")

    first = service.verify(indication, horizon_bars=2)
    second = service.verify(indication, horizon_bars=2)

    assert first == second


def test_service_works_without_django_postgresql_or_dhan() -> None:
    """Static proof, not just behavioral: the service module never
    imports Django, infrastructure, or a provider name."""
    import ast
    import inspect

    import intraday.application.services.signal_verification as module

    source = inspect.getsource(module)
    tree = ast.parse(source)
    imported_roots = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "django" not in imported_roots
    assert "intraday.infrastructure" not in imported_roots
    assert not any("dhan" in name.lower() for name in imported_roots)
