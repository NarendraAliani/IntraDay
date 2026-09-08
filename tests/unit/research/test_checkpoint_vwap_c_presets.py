# tests/unit/research/test_checkpoint_vwap_c_presets.py
#
# CHECKPOINT-VWAP-C: 3 config presets (tight/normal/wide deviation
# bands) for `vwap_mean_reversion`. Matches
# `test_checkpoint_gainz_c_presets.py`'s own rigor and structure: each
# preset's canonical values live in ONE shared module-level dict, used
# BOTH to persist a real `StrategyConfigurationRecord` row (via the
# real `StrategyConfigurationService.save_configuration()` path, never
# a raw ORM insert - proving real DB creation) AND to construct an
# in-memory `StrategyConfigurationValues` directly for the behavioral-
# divergence tests (no database dependency there, mirroring
# `test_checkpoint_gainz_c_presets.py`'s own `_config_from()` helper -
# these tests run against the SAME values a persisted row would hold,
# without depending on presets created by an earlier, separate
# process surviving into pytest's own ephemeral test database).
# `registry.py` untouched.
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from intraday.application.services.strategy_configuration import StrategyConfigurationService
from intraday.domain.feature.contracts import FeatureValue
from intraday.domain.market_data.contracts import Bar
from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe, Version
from intraday.infrastructure.persistence.models import StrategyConfigurationRecord
from intraday.infrastructure.persistence.repositories import DjangoStrategyConfigurationRepository
from intraday.trading_engine.strategy_execution.contracts import (
    StrategyConfigurationValues,
    StrategyDirection,
    coerce_configuration_values,
)
from intraday.trading_engine.strategy_execution.registry import StrategyRegistry
from intraday.trading_engine.strategy_execution.strategies.vwap_mean_reversion import (
    STRATEGY_ID,
    VwapMeanReversionStrategy,
)

IID = InstrumentId("NSE:VWAPCTEST")
TF = Timeframe.FIVE_MINUTE
TS = datetime(2026, 1, 5, 4, 0, tzinfo=UTC)
FV_VERSION = Version(value="v1")

TIGHT_VERSION = "vwap_tight"
NORMAL_VERSION = "vwap_normal"
WIDE_VERSION = "vwap_wide"


def tight_values() -> dict[str, object]:
    return {
        "vwap_deviation_atr_multiplier": "1.0",
        "stop_loss_atr_multiplier": "2.0",
        "atr_lookback": 14,
        "target_reversion_fraction": "1.0",
    }


def normal_values() -> dict[str, object]:
    return {
        "vwap_deviation_atr_multiplier": "1.5",
        "stop_loss_atr_multiplier": "2.5",
        "atr_lookback": 14,
        "target_reversion_fraction": "1.0",
    }


def wide_values() -> dict[str, object]:
    return {
        "vwap_deviation_atr_multiplier": "2.0",
        "stop_loss_atr_multiplier": "3.0",
        "atr_lookback": 14,
        "target_reversion_fraction": "1.0",
    }


def _bar(close: str) -> Bar:
    price = Decimal(close)
    return Bar(
        instrument_id=IID,
        timeframe=TF,
        timestamp=TS,
        open=price,
        high=price + Decimal("1"),
        low=price - Decimal("1"),
        close=price,
        volume=Decimal("1000"),
    )


def _feature(name: str, value: str) -> FeatureValue:
    return FeatureValue(
        feature_name=name,
        feature_version=FV_VERSION,
        instrument_id=IID,
        timeframe=TF,
        timestamp=TS,
        value=Decimal(value),
    )


def _local_registry() -> StrategyRegistry:
    registry = StrategyRegistry()
    registry.register(VwapMeanReversionStrategy())
    return registry


def _service() -> StrategyConfigurationService:
    return StrategyConfigurationService(
        repository=DjangoStrategyConfigurationRepository(), registry=_local_registry()
    )


def _config_from(values: dict[str, object], configuration_version: str) -> StrategyConfigurationValues:
    schema = VwapMeanReversionStrategy().parameter_schema()
    coerced = coerce_configuration_values(schema, values)
    return StrategyConfigurationValues(STRATEGY_ID, "v1", "v1", configuration_version, coerced)


def _direction_for(values: dict[str, object], name: str, price: str, vwap: str, atr: str) -> StrategyDirection:
    config = _config_from(values, name)
    feature_values = {"vwap": _feature("vwap", vwap), "atr_14": _feature("atr_14", atr)}
    signal = VwapMeanReversionStrategy().evaluate(_bar(price), feature_values, config)
    assert signal is not None
    return signal.direction


# ---------------------------------------------------------------------------
# 1. Creation, count, retrievability, distinctness - real DB rows.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_1_three_presets_created_retrievable_and_distinct() -> None:
    before = StrategyConfigurationRecord.objects.filter(strategy_id=STRATEGY_ID).count()
    assert before == 0

    service = _service()
    for configuration_version, values in (
        (TIGHT_VERSION, tight_values()),
        (NORMAL_VERSION, normal_values()),
        (WIDE_VERSION, wide_values()),
    ):
        snapshot = service.save_configuration(
            STRATEGY_ID, "v1", "v1", configuration_version, values, created_by="checkpoint-vwap-c",
        )
        assert snapshot.configuration_version == configuration_version

    after = StrategyConfigurationRecord.objects.filter(strategy_id=STRATEGY_ID).count()
    assert after == 3

    repo = DjangoStrategyConfigurationRepository()
    tight = repo.get(STRATEGY_ID, "v1", "v1", TIGHT_VERSION)
    normal = repo.get(STRATEGY_ID, "v1", "v1", NORMAL_VERSION)
    wide = repo.get(STRATEGY_ID, "v1", "v1", WIDE_VERSION)
    assert tight is not None and normal is not None and wide is not None

    assert tight.parameter_values["vwap_deviation_atr_multiplier"] == "1.0"
    assert normal.parameter_values["vwap_deviation_atr_multiplier"] == "1.5"
    assert wide.parameter_values["vwap_deviation_atr_multiplier"] == "2.0"
    assert tight.parameter_values != normal.parameter_values != wide.parameter_values

    # atr_lookback/target_reversion_fraction deliberately identical
    # across all 3 (feature/target-completeness parameters, not
    # deviation-band parameters).
    assert (
        tight.parameter_values["atr_lookback"]
        == normal.parameter_values["atr_lookback"]
        == wide.parameter_values["atr_lookback"]
        == 14
    )
    assert (
        tight.parameter_values["target_reversion_fraction"]
        == normal.parameter_values["target_reversion_fraction"]
        == wide.parameter_values["target_reversion_fraction"]
        == "1.0"
    )


@pytest.mark.django_db
def test_2_each_preset_persists_and_reloads_through_coerce_into_valid_values() -> None:
    """Confirms each preset's `parameter_values` (as persisted - JSON-safe
    strings for DECIMAL parameters) parses correctly through
    `coerce_configuration_values()` into a valid `StrategyConfigurationValues`,
    the same path production code uses."""
    service = _service()
    repo = DjangoStrategyConfigurationRepository()
    for configuration_version, values in (
        (TIGHT_VERSION, tight_values()),
        (NORMAL_VERSION, normal_values()),
        (WIDE_VERSION, wide_values()),
    ):
        service.save_configuration(
            STRATEGY_ID, "v1", "v1", configuration_version, values, created_by="checkpoint-vwap-c",
        )
        rec = repo.get(STRATEGY_ID, "v1", "v1", configuration_version)
        assert rec is not None
        config = _config_from(dict(rec.parameter_values), configuration_version)
        assert isinstance(config.values["vwap_deviation_atr_multiplier"], Decimal)
        assert isinstance(config.values["stop_loss_atr_multiplier"], Decimal)
        assert isinstance(config.values["atr_lookback"], int)
        assert config.values["target_reversion_fraction"] == Decimal("1.0")


def test_3_ascending_deviation_and_stop_bands_tight_lt_normal_lt_wide() -> None:
    n = {
        "tight": Decimal(tight_values()["vwap_deviation_atr_multiplier"]),
        "normal": Decimal(normal_values()["vwap_deviation_atr_multiplier"]),
        "wide": Decimal(wide_values()["vwap_deviation_atr_multiplier"]),
    }
    m = {
        "tight": Decimal(tight_values()["stop_loss_atr_multiplier"]),
        "normal": Decimal(normal_values()["stop_loss_atr_multiplier"]),
        "wide": Decimal(wide_values()["stop_loss_atr_multiplier"]),
    }
    assert n["tight"] < n["normal"] < n["wide"]
    assert m["tight"] < m["normal"] < m["wide"]


def test_4_m_greater_than_n_holds_for_every_preset_the_runtime_guard_checkpoint_vwap_b_built() -> None:
    """Directly verified, not assumed from the table alone: for each
    preset's own values, `build_trade_plan()` must NOT refuse (the
    M > N guard `CHECKPOINT-VWAP-B` added)."""
    strategy = VwapMeanReversionStrategy()
    for name, values in (
        (TIGHT_VERSION, tight_values()),
        (NORMAL_VERSION, normal_values()),
        (WIDE_VERSION, wide_values()),
    ):
        config = _config_from(values, name)
        feature_values = {"vwap": _feature("vwap", "1000"), "atr_14": _feature("atr_14", "10")}
        # Deviation far beyond any preset's own N (10x ATR) - guarantees
        # a genuine BULLISH signal for all 3, isolating this test to the
        # M > N guard alone, not the deviation threshold itself.
        signal = strategy.evaluate(_bar("900"), feature_values, config)
        assert signal is not None
        assert signal.direction is StrategyDirection.BULLISH
        plan = strategy.build_trade_plan(_bar("900"), feature_values, config, signal)
        assert plan is not None, f"{name}: M > N guard unexpectedly refused a valid plan"


# ---------------------------------------------------------------------------
# 2. Real behavioral divergence - the actual point of this checkpoint.
#    Same hand-computed feature values fed to all 3 presets; direction
#    diverges purely from each preset's own N, never from a different
#    entry price or a different evidence number.
# ---------------------------------------------------------------------------


def test_5_small_deviation_only_tight_signals_normal_and_wide_stay_neutral() -> None:
    # vwap=1000, atr=10, price=988 -> deviation = (988-1000)/10 = -1.2x ATR.
    # tight  (N=1.0, band=10): trigger below 990 -> 988 < 990 -> BULLISH.
    # normal (N=1.5, band=15): trigger below 985 -> 988 NOT < 985 -> NEUTRAL.
    # wide   (N=2.0, band=20): trigger below 980 -> 988 NOT < 980 -> NEUTRAL.
    assert _direction_for(tight_values(), TIGHT_VERSION, "988", "1000", "10") is StrategyDirection.BULLISH
    assert _direction_for(normal_values(), NORMAL_VERSION, "988", "1000", "10") is StrategyDirection.NEUTRAL
    assert _direction_for(wide_values(), WIDE_VERSION, "988", "1000", "10") is StrategyDirection.NEUTRAL


def test_6_medium_deviation_tight_and_normal_signal_wide_stays_neutral() -> None:
    # price=983 -> deviation = -1.7x ATR.
    # tight  (band=10, trigger<990): 983<990 -> BULLISH.
    # normal (band=15, trigger<985): 983<985 -> BULLISH.
    # wide   (band=20, trigger<980): 983 NOT <980 -> NEUTRAL.
    assert _direction_for(tight_values(), TIGHT_VERSION, "983", "1000", "10") is StrategyDirection.BULLISH
    assert _direction_for(normal_values(), NORMAL_VERSION, "983", "1000", "10") is StrategyDirection.BULLISH
    assert _direction_for(wide_values(), WIDE_VERSION, "983", "1000", "10") is StrategyDirection.NEUTRAL


def test_7_large_deviation_all_three_presets_agree_control_case() -> None:
    # price=975 -> deviation = -2.5x ATR, beyond even wide's N=2.0 band
    # (trigger<980) - a control case proving all 3 presets CAN produce
    # the identical signal when the deviation is large enough; the
    # divergence above is genuinely caused by each preset's own
    # threshold, not a broken/miswired preset.
    assert _direction_for(tight_values(), TIGHT_VERSION, "975", "1000", "10") is StrategyDirection.BULLISH
    assert _direction_for(normal_values(), NORMAL_VERSION, "975", "1000", "10") is StrategyDirection.BULLISH
    assert _direction_for(wide_values(), WIDE_VERSION, "975", "1000", "10") is StrategyDirection.BULLISH


def test_8_symmetric_divergence_holds_on_the_bearish_side_too() -> None:
    # Mirror of test_5 above the VWAP instead of below it - price=1012,
    # deviation = +1.2x ATR.
    assert _direction_for(tight_values(), TIGHT_VERSION, "1012", "1000", "10") is StrategyDirection.BEARISH
    assert _direction_for(normal_values(), NORMAL_VERSION, "1012", "1000", "10") is StrategyDirection.NEUTRAL
    assert _direction_for(wide_values(), WIDE_VERSION, "1012", "1000", "10") is StrategyDirection.NEUTRAL
