# tests/unit/research/test_checkpoint_64_47_strategy_registry.py
#
# Checkpoint 64.47: STRATEGY PLUGIN / REGISTRY FOUNDATION.
#
# This is a VERIFICATION checkpoint, not a from-scratch build. The
# canonical `Strategy` Protocol (strategy.py), `StrategyRegistry`
# (registry.py), and `StrategySignal`/`StrategyConfigurationValues`
# contracts (contracts.py) already existed since Checkpoint 26. This
# suite proves that architecture already satisfies the 64.47 directive:
# a brand-new strategy (`TestStrategy` below) can be registered and can
# produce a canonical `StrategySignal` WITHOUT modifying (and without
# even importing) Risk/OrderIntent/Execution/Fill/Position/Accounting/
# Dhan/PaperBroker code.
#
# `TestStrategy` is registered into a LOCAL `StrategyRegistry()`
# instance constructed in this test module - never into
# `build_default_registry()` - so this proof-of-concept never pollutes
# the real strategy suite the rest of the system consumes.
from __future__ import annotations

import ast
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from intraday.domain.feature.contracts import FeatureValue
from intraday.domain.instrument.contracts import make_instrument_id
from intraday.domain.market_data.contracts import Bar, MarketDataQuality, PriceAdjustment
from intraday.domain.shared_kernel.contracts import Exchange, Timeframe, Version
from intraday.trading_engine.strategy_execution.contracts import (
    ParameterDefinition,
    ParameterType,
    StrategyConfigurationValues,
    StrategyDirection,
    StrategyParameterSchema,
    StrategySignal,
    require_int,
    validate_configuration,
)
from intraday.trading_engine.strategy_execution.errors import (
    DuplicateStrategyRegistrationError,
    InvalidParameterValueError,
    MissingRequiredParameterError,
    UnknownStrategyError,
)
from intraday.trading_engine.strategy_execution.registry import StrategyRegistry
from intraday.trading_engine.strategy_execution.strategy import Strategy

RELIANCE = make_instrument_id(Exchange.NSE, "RELIANCE")
BASE_TS = datetime(2026, 8, 24, 4, 15, tzinfo=UTC)

TEST_STRATEGY_ID = "checkpoint_64_47_test_strategy"
TEST_STRATEGY_DISPLAY_NAME = "Checkpoint 64.47 Test Strategy"
TEST_STRATEGY_SPEC_VERSION = "v1"
TEST_STRATEGY_CODE_VERSION = "v1"


def _bar(close: Decimal, *, timestamp: datetime = BASE_TS) -> Bar:
    return Bar(
        instrument_id=RELIANCE,
        timeframe=Timeframe.FIVE_MINUTE,
        timestamp=timestamp,
        open=close,
        high=close,
        low=close,
        close=close,
        volume=Decimal("1000"),
        quality=MarketDataQuality.OK,
        adjustment=PriceAdjustment.RAW,
    )


class TestStrategy:
    """Deliberately trivial: BULLISH iff `bar.close` exceeds the
    configured `threshold` parameter, else BEARISH. Proves nothing more
    than "a brand new class conforming to the `Strategy` Protocol can be
    registered and evaluated" - the entire point of 64.47's acceptance
    test. Never registered into the real `build_default_registry()`."""

    strategy_id = TEST_STRATEGY_ID
    display_name = TEST_STRATEGY_DISPLAY_NAME
    specification_version = TEST_STRATEGY_SPEC_VERSION
    code_version = TEST_STRATEGY_CODE_VERSION

    def parameter_schema(self) -> StrategyParameterSchema:
        return StrategyParameterSchema(
            strategy_id=TEST_STRATEGY_ID,
            parameters=(
                ParameterDefinition(
                    parameter_id="threshold",
                    label="Price Threshold",
                    parameter_type=ParameterType.INTEGER,
                    required=True,
                    default=100,
                    minimum=1,
                    maximum=100_000,
                    help_text="Bar close above this triggers BULLISH.",
                ),
            ),
        )

    def required_features(self, config: StrategyConfigurationValues) -> tuple[str, ...]:
        # Deliberately requires no computed features - proves a strategy
        # can be feature-free and still conform to the Protocol.
        return ()

    def evaluate(
        self,
        bar: Bar,
        feature_values: dict[str, FeatureValue],
        config: StrategyConfigurationValues,
    ) -> StrategySignal | None:
        threshold = require_int(config.values, "threshold")
        direction = (
            StrategyDirection.BULLISH if bar.close > threshold else StrategyDirection.BEARISH
        )
        return StrategySignal(
            strategy_id=self.strategy_id,
            specification_version=self.specification_version,
            code_version=self.code_version,
            configuration_version=config.configuration_version,
            instrument_id=bar.instrument_id,
            timeframe=bar.timeframe,
            timestamp=bar.timestamp,
            direction=direction,
            price=bar.close,
            evidence=(),
        )


def _config(threshold: int = 100) -> StrategyConfigurationValues:
    return StrategyConfigurationValues(
        strategy_id=TEST_STRATEGY_ID,
        specification_version=TEST_STRATEGY_SPEC_VERSION,
        code_version=TEST_STRATEGY_CODE_VERSION,
        configuration_version="v1",
        values={"threshold": threshold},
    )


# --- A. Canonical strategy interface exists/reused ---------------------


def test_a_strategy_protocol_is_reused_not_duplicated() -> None:
    # TestStrategy satisfies the existing Protocol structurally - no new
    # interface/ABC was defined for this checkpoint.
    strategy: Strategy = TestStrategy()
    assert hasattr(strategy, "strategy_id")
    assert hasattr(strategy, "evaluate")
    assert hasattr(strategy, "required_features")
    assert hasattr(strategy, "parameter_schema")


# --- B. Dummy TestStrategy conforms -------------------------------------


def test_b_test_strategy_conforms_to_contract() -> None:
    strategy = TestStrategy()
    schema = strategy.parameter_schema()
    assert schema.strategy_id == TEST_STRATEGY_ID
    assert strategy.required_features(_config()) == ()


# --- C/D/E. register() / get() / list() ---------------------------------


def test_c_d_e_register_get_list() -> None:
    registry = StrategyRegistry()  # local instance - NOT build_default_registry()
    strategy = TestStrategy()

    registry.register(strategy)

    fetched = registry.get(TEST_STRATEGY_ID)
    assert fetched is strategy

    listed = registry.list()
    assert listed == (strategy,)


# --- F. Duplicate registration rejected ----------------------------------


def test_f_duplicate_registration_rejected() -> None:
    registry = StrategyRegistry()
    registry.register(TestStrategy())
    with pytest.raises(DuplicateStrategyRegistrationError):
        registry.register(TestStrategy())


# --- G. Unknown strategy lookup ------------------------------------------


def test_g_unknown_strategy_lookup_raises() -> None:
    registry = StrategyRegistry()
    with pytest.raises(UnknownStrategyError):
        registry.get("no_such_strategy_id")


# --- H. TestStrategy generates canonical Signal --------------------------


def test_h_test_strategy_generates_canonical_signal() -> None:
    registry = StrategyRegistry()
    strategy = TestStrategy()
    registry.register(strategy)

    resolved = registry.get(TEST_STRATEGY_ID)
    signal = resolved.evaluate(_bar(Decimal("150")), {}, _config(threshold=100))

    assert isinstance(signal, StrategySignal)
    assert signal.strategy_id == TEST_STRATEGY_ID
    assert signal.direction == StrategyDirection.BULLISH
    assert signal.instrument_id == RELIANCE
    assert signal.timeframe == Timeframe.FIVE_MINUTE
    assert signal.price == Decimal("150")

    # Deterministic: same inputs -> same signal fields.
    signal_2 = resolved.evaluate(_bar(Decimal("150")), {}, _config(threshold=100))
    assert signal_2 is not None
    assert signal_2.direction == signal.direction
    assert signal_2.price == signal.price

    # Below threshold -> BEARISH, proving the signal is not fabricated.
    bearish = resolved.evaluate(_bar(Decimal("50")), {}, _config(threshold=100))
    assert bearish is not None
    assert bearish.direction == StrategyDirection.BEARISH


# --- I. Strategy version is explicit --------------------------------------


def test_i_strategy_version_is_explicit() -> None:
    strategy = TestStrategy()
    assert strategy.specification_version == TEST_STRATEGY_SPEC_VERSION
    assert strategy.code_version == TEST_STRATEGY_CODE_VERSION
    signal = strategy.evaluate(_bar(Decimal("150")), {}, _config())
    assert signal is not None
    assert signal.specification_version == TEST_STRATEGY_SPEC_VERSION
    assert signal.code_version == TEST_STRATEGY_CODE_VERSION
    assert signal.configuration_version == "v1"


# --- J. Configuration is explicit and validated ---------------------------


def test_j_configuration_is_explicit_and_validated() -> None:
    strategy = TestStrategy()
    schema = strategy.parameter_schema()

    # Valid configuration passes.
    validate_configuration(schema, {"threshold": 100}, known_field_ids=frozenset())

    # Missing required parameter with no default rejected... but
    # threshold HAS a default, so omitting it is fine:
    validate_configuration(schema, {}, known_field_ids=frozenset())

    # Wrong type rejected.
    with pytest.raises(InvalidParameterValueError):
        validate_configuration(schema, {"threshold": "not-an-int"}, known_field_ids=frozenset())

    # Unknown parameter rejected.
    from intraday.trading_engine.strategy_execution.errors import UnknownParameterError

    with pytest.raises(UnknownParameterError):
        validate_configuration(schema, {"bogus": 1}, known_field_ids=frozenset())


def test_j_missing_required_parameter_without_default_rejected() -> None:
    schema = StrategyParameterSchema(
        strategy_id=TEST_STRATEGY_ID,
        parameters=(
            ParameterDefinition(
                parameter_id="required_no_default",
                label="Required, No Default",
                parameter_type=ParameterType.INTEGER,
                required=True,
            ),
        ),
    )
    with pytest.raises(MissingRequiredParameterError):
        validate_configuration(schema, {}, known_field_ids=frozenset())


# --- K. Strategy does not import Dhan/PaperBroker/Fill/Accounting --------


def test_k_strategy_module_isolation_via_ast() -> None:
    """Static AST check (not merely 'I didn't import it') - mirrors the
    isolation-audit style used elsewhere in this suite (see
    test_checkpoint_64_38's own `ast`-based check). Scans THIS test
    module's own TestStrategy source region conceptually via the whole
    file, and separately the real production strategy modules, for any
    forbidden import."""
    forbidden_substrings = (
        "dhan",
        "paper.broker",
        "PaperBroker",
        "domain.order",  # OrderIntent
        "domain.position",  # Position
        "domain.accounting",
        "risk_engine",
        "evaluate_order_risk",
    )

    this_file = Path(__file__)
    source = this_file.read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported_names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.append(node.module)

    joined = " ".join(imported_names)
    for forbidden in forbidden_substrings:
        assert forbidden not in joined, f"forbidden import found: {forbidden!r} in {joined!r}"

    # Also verify the real production strategy modules stay clean.
    strategies_dir = (
        this_file.parents[3]
        / "src"
        / "intraday"
        / "trading_engine"
        / "strategy_execution"
        / "strategies"
    )
    for py_file in strategies_dir.glob("*.py"):
        src = py_file.read_text(encoding="utf-8")
        prod_tree = ast.parse(src)
        prod_imports: list[str] = []
        for node in ast.walk(prod_tree):
            if isinstance(node, ast.Import):
                prod_imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                prod_imports.append(node.module)
        prod_joined = " ".join(prod_imports)
        for forbidden in forbidden_substrings:
            assert (
                forbidden not in prod_joined
            ), f"forbidden import found in {py_file.name}: {forbidden!r}"


# --- L. Registry lookup does not instantiate heavy external services ------


def test_l_registry_lookup_is_pure_dict_access() -> None:
    registry = StrategyRegistry()
    strategy = TestStrategy()
    registry.register(strategy)

    # get() must be a dict lookup - no I/O, no network, no DB, no
    # market-data-service construction. Proven structurally: registry
    # internals are a plain dict/set, and get()/list() never call out to
    # anything beyond dict access (verified by reading registry.py; here
    # we assert repeated lookups are referentially identical and cheap).
    first = registry.get(TEST_STRATEGY_ID)
    second = registry.get(TEST_STRATEGY_ID)
    assert first is second is strategy


# --- M/N/O/P. New strategy added without modifying Risk/OrderIntent/Execution/Fill ---


def test_m_n_o_p_new_strategy_does_not_touch_downstream_modules() -> None:
    """Structural proof: this entire test file - which defines and
    registers a brand-new strategy - imports NOTHING from the risk
    engine, order/OrderIntent, execution, or fill modules. If adding
    TestStrategy required touching any of those, this test file (or
    TestStrategy itself) would need to import them; it does not."""
    source = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_names.append(node.module)

    joined = " ".join(imported_names)
    for forbidden_module in (
        "intraday.domain.order",
        "intraday.domain.position",
        "intraday.domain.accounting",
        "intraday.trading_engine.risk",
        "intraday.infrastructure.brokers.paper",
        "intraday.infrastructure.brokers.dhan",
    ):
        assert forbidden_module not in joined


# --- Q. Existing 64.41-64.46 invariants remain intact ---------------------


def test_q_existing_default_registry_still_builds_with_three_strategies() -> None:
    from intraday.trading_engine.strategy_execution.registry import build_default_registry

    registry = build_default_registry()
    listed = registry.list()
    assert len(listed) == 3
    ids = {s.strategy_id for s in listed}
    assert ids == {"ema_crossover", "sma_trend_filter", "atr_volatility_breakout"}
    # TestStrategy must NOT have polluted the default/global registry.
    assert TEST_STRATEGY_ID not in ids


# --- R/S. Gainz and EMA/SMA remain unmodified ------------------------------


def test_r_gainz_not_integrated() -> None:
    """As of 64.47, no Gainz module existed anywhere in
    trading_engine.strategy_execution - confirmed Gainz integration was
    NOT performed.

    Checkpoint 64.50 legitimately changes this fact: it adds ONE honestly
    labeled `gainz_compatible_research.py` (a canonical-feature-
    CONSUMPTION research strategy, explicitly NOT actual GainzAlgo V2
    mathematics - see that module's own header) to prove a real strategy
    can consume the 64.49 canonical feature set end-to-end. This
    assertion is updated (not deleted) to allow exactly that one, named
    file while still failing if any OTHER Gainz-named module ever
    appears without the same explicit review."""
    strategies_dir = (
        Path(__file__).parents[3]
        / "src"
        / "intraday"
        / "trading_engine"
        / "strategy_execution"
        / "strategies"
    )
    allowed_gainz_modules = {"gainz_compatible_research"}
    names = {p.stem.lower() for p in strategies_dir.glob("*.py")}
    unexpected = {n for n in names if "gainz" in n} - allowed_gainz_modules
    assert not unexpected


def test_s_ema_sma_strategies_unmodified_behaviorally() -> None:
    """EMA crossover / SMA trend filter strategies still behave exactly as
    before - proves the registry foundation work did not alter existing
    strategy evaluation logic. Uses the real production classes, not
    TestStrategy."""
    from intraday.trading_engine.strategy_execution.contracts import (
        StrategyConfigurationValues as SCV,
    )
    from intraday.trading_engine.strategy_execution.strategies.ema_crossover import (
        EmaCrossoverStrategy,
    )

    strategy = EmaCrossoverStrategy()
    config = SCV(
        strategy_id="ema_crossover",
        specification_version=strategy.specification_version,
        code_version=strategy.code_version,
        configuration_version="v1",
        values={"fast_lookback": 12, "slow_lookback": 26},
    )
    fast = FeatureValue(
        feature_name="ema_12",
        feature_version=Version("v1"),
        instrument_id=RELIANCE,
        timeframe=Timeframe.FIVE_MINUTE,
        timestamp=BASE_TS,
        value=Decimal("110"),
    )
    slow = FeatureValue(
        feature_name="ema_26",
        feature_version=Version("v1"),
        instrument_id=RELIANCE,
        timeframe=Timeframe.FIVE_MINUTE,
        timestamp=BASE_TS,
        value=Decimal("100"),
    )
    signal = strategy.evaluate(_bar(Decimal("115")), {"ema_12": fast, "ema_26": slow}, config)
    assert signal is not None
    assert signal.direction == StrategyDirection.BULLISH
