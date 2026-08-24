# File: tests/unit/research/test_checkpoint_64_48_gainz_adapter_design.py
#
# Checkpoint 64.48: GAINZ STRATEGY ADAPTER DESIGN.
#
# HONESTY NOTICE (do not remove): no Gainz reference implementation file
# exists anywhere in this repository as of this checkpoint (independently
# re-verified this session via `grep -ril "gainz" src/ tests/ docs/` and a
# full-tree grep -- the only hits are this test file, the architecture doc,
# and taskReport.md, all of which THIS checkpoint or its predecessors
# wrote). This file therefore does NOT read, port, or execute any Gainz
# mathematics. Every "Gainz Concept" name below is taken verbatim from the
# checkpoint directive's OWN descriptive prose (SignalConfig fields,
# feature list, profile names, TP1/TP2/TP3, confidence, position sizing,
# disable_repeating_signals, require_confirmed_bar) -- not from source code
# that was read. This is a design/mapping proof against the REAL, existing
# `trading_engine.strategy_execution` contracts (imported below and
# exercised for real), not a port of Gainz.
#
# This checkpoint MUST NOT create a GainzStrategy class, MUST NOT touch
# Risk/OrderIntent/Execution/Fill/Position/Accounting/Dhan/PaperBroker, and
# MUST NOT modify StrategySignal/TradePlan. Tests below verify the MAPPING
# DECISIONS documented in taskReport.md and the architecture doc, using the
# real existing contracts -- they do not implement Gainz.
from __future__ import annotations

import ast
from pathlib import Path

from intraday.signal_intelligence.feature_engine.field_registry import list_fields
from intraday.trading_engine.strategy_execution.contracts import StrategySignal, TradePlan
from intraday.trading_engine.strategy_execution.registry import build_default_registry

REPO_ROOT = Path(__file__).resolve().parents[3]
STRATEGIES_DIR = REPO_ROOT / "src/intraday/trading_engine/strategy_execution/strategies"


# ---------------------------------------------------------------------------
# A. Gainz field mapping table exists and is well-formed.
# ---------------------------------------------------------------------------
#
# Columns: (gainz_concept, current_gainz_type, canonical_destination, required, owner, reason)
# "owner" is one of: STRATEGY, TRADE_PLAN, RISK, EXECUTION, DIAGNOSTIC.
# This table is DERIVED FROM THE DIRECTIVE'S OWN PROSE, not from a read
# Gainz source file (see HONESTY NOTICE above).
GAINZ_FIELD_MAPPING: tuple[tuple[str, str, str, bool, str, str], ...] = (
    (
        "direction",
        "internal enum/str (BUY/SELL/long/short)",
        "StrategySignal.direction (StrategyDirection)",
        True,
        "STRATEGY",
        "Directional call is exactly what StrategySignal.direction already represents; no new "
        "field needed.",
    ),
    (
        "signal timestamp",
        "datetime",
        "StrategySignal.timestamp",
        True,
        "STRATEGY",
        "Existing field, already UTC-validated by StrategySignal.__post_init__.",
    ),
    (
        "instrument",
        "symbol/ticker str",
        "StrategySignal.instrument_id",
        True,
        "STRATEGY",
        "Existing InstrumentId field, no new representation required.",
    ),
    (
        "timeframe",
        "str/enum",
        "StrategySignal.timeframe",
        True,
        "STRATEGY",
        "Existing Timeframe field.",
    ),
    (
        "score",
        "numeric (setup scoring)",
        "StrategySignal.evidence (FeatureValue) or diagnostic metadata",
        False,
        "DIAGNOSTIC",
        "A derived scalar explaining WHY the signal fired -- exactly what evidence already carries "
        "for other strategies; not required by any downstream consumer today.",
    ),
    (
        "confidence / setup quality",
        "numeric (0-1 or 0-100, explicitly NOT win probability)",
        "diagnostic metadata / evidence -- NOT a new probability_of_profit field",
        False,
        "DIAGNOSTIC",
        "Directive Part 5 explicitly forbids introducing probability_of_profit or implying "
        "confidence==win-probability; no existing strategy has a confidence field and none is "
        "proven universal yet.",
    ),
    (
        "regime",
        "str/enum (e.g. trending/ranging)",
        "diagnostic metadata / evidence",
        False,
        "DIAGNOSTIC",
        "Descriptive context for why a signal fired, not a value any downstream consumer (Risk, "
        "Execution) acts on today.",
    ),
    (
        "reasons/evidence",
        "list[str] or list[dict]",
        "StrategySignal.evidence (tuple[FeatureValue, ...])",
        False,
        "STRATEGY",
        "evidence already exists precisely to carry the FeatureValues that justified a signal; "
        "textual reasons are a diagnostic elaboration of the same evidence, not a new contract.",
    ),
    (
        "entry price (candidate)",
        "Decimal/float",
        "TradePlan.entry_price",
        False,
        "TRADE_PLAN",
        "TradePlan already exists as the sole owner of entry/stop/target values (Checkpoint 64.7); "
        "ATR breakout strategy already populates this field via build_trade_plan().",
    ),
    (
        "stop_loss",
        "Decimal/float",
        "TradePlan.stop_loss",
        False,
        "TRADE_PLAN",
        "Direct reuse; independently-nullable, matching Gainz's own partial-plan possibility.",
    ),
    (
        "TP1",
        "Decimal/float",
        "TradePlan.target_1",
        False,
        "TRADE_PLAN",
        "Direct reuse.",
    ),
    (
        "TP2",
        "Decimal/float",
        "TradePlan.target_2",
        False,
        "TRADE_PLAN",
        "Direct reuse.",
    ),
    (
        "TP3",
        "Decimal/float",
        "TradePlan.target_3",
        False,
        "TRADE_PLAN",
        "Direct reuse.",
    ),
    (
        "position_size",
        "int/float (Gainz-proposed)",
        "NOT a canonical destination on StrategySignal/TradePlan -- advisory only, informs a "
        "future Risk Engine input, never OrderIntent quantity directly",
        False,
        "RISK",
        "Directive Part 8: Gainz's proposed sizing must flow through Risk Engine before "
        "becoming an actual order quantity; no strategy-authored quantity may bypass Risk. "
        "Not implemented this checkpoint -- Risk Engine is untouched.",
    ),
    (
        "risk_per_trade",
        "numeric (% or currency)",
        "future Risk Engine input (not a Strategy/TradePlan field)",
        False,
        "RISK",
        "Capital/risk-limit constraints belong to Risk, matching the directive's Part 4 "
        "hypothesis; a strategy may only PROPOSE, never enforce, a risk budget.",
    ),
    (
        "profile (alpha/trend/breakout/mean_reversion/hybrid/scalp)",
        "str enum selecting an internal rule variant",
        "StrategyConfigurationValues.values['profile'] (ENUM parameter) OR a distinct registered "
        "strategy_id per profile -- see docs architecture section for the full reasoning",
        False,
        "STRATEGY",
        "A profile changes WHICH internal rule Gainz applies, not what kind of output it is -- "
        "matches the existing ENUM ParameterType/configuration convention rather than requiring a "
        "new concept.",
    ),
    (
        "consensus_signal()",
        "function combining multiple profiles",
        "future strategy-composition layer (NOT inside StrategyRegistry, NOT a global feature)",
        False,
        "STRATEGY",
        "Directive Part 10: consensus must not be hard-coded into the global StrategyRegistry; the "
        "safest ownership is a future composition layer above individual strategies, undecided in "
        "detail this checkpoint.",
    ),
    (
        "disable_repeating_signals",
        "bool config flag",
        "Gainz-specific strategy/configuration behavior for now "
        "(StrategyConfigurationValues.values)",
        False,
        "STRATEGY",
        "Directive Part 13: keep this Gainz-specific rather than build a global dedup system in "
        "64.48; no existing strategy has repeat suppression today so it is not proven universal.",
    ),
    (
        "require_confirmed_bar",
        "bool config flag",
        "StrategyConfigurationValues.values['require_confirmed_bar'] (proposed future "
        "BOOLEAN-typed ParameterDefinition) -- enforcement at the coordinator/bar-feed boundary",
        False,
        "STRATEGY",
        "The reference configuration names this flag but (per the directive itself) it 'may not "
        "currently be enforced' -- this checkpoint does NOT claim it is implemented anywhere.",
    ),
    (
        "indicator values (EMA, RSI, ATR, ADX, +DI/-DI, rel-vol, MACD-hist, breakout, body ratio, "
        "delta)",
        "internal numeric series",
        "StrategySignal.evidence (FeatureValue) for the subset already in the canonical field "
        "registry (EMA, ATR); everything else is future work, not fabricated",
        False,
        "STRATEGY",
        "See Gainz Feature Mapping below -- only EMA/ATR (and raw OHLCV) already exist in "
        "field_registry.list_fields(); RSI/ADX/+DI-/-DI/relative-volume/MACD-histogram/breakout/"
        "body-ratio/delta do not exist and are NOT implemented this checkpoint.",
    ),
    (
        "final order quantity / actual fill / slippage / transaction cost",
        "n/a in Gainz reference (execution-time only)",
        "OrderIntent / Fill (existing, untouched)",
        True,
        "EXECUTION",
        "Pure execution-time facts; Gainz (a strategy) never computes or claims these.",
    ),
)


def test_a_gainz_field_mapping_exists_and_is_well_formed() -> None:
    assert len(GAINZ_FIELD_MAPPING) >= 15
    valid_owners = {"STRATEGY", "TRADE_PLAN", "RISK", "EXECUTION", "DIAGNOSTIC"}
    seen_concepts: set[str] = set()
    for concept, current_type, destination, required, owner, reason in GAINZ_FIELD_MAPPING:
        assert concept and concept not in seen_concepts, f"duplicate/blank concept: {concept!r}"
        seen_concepts.add(concept)
        assert current_type, f"{concept}: missing current-type description"
        assert destination, f"{concept}: missing canonical destination"
        assert isinstance(required, bool)
        assert owner in valid_owners, f"{concept}: invalid owner {owner!r}"
        assert reason, f"{concept}: missing reason"


# ---------------------------------------------------------------------------
# B. Gainz outputs are classified into Strategy / TradePlan / Risk /
#    Execution / Diagnostics -- every classification bucket is actually used.
# ---------------------------------------------------------------------------
def test_b_gainz_outputs_classified_into_all_expected_buckets() -> None:
    owners_used = {row[4] for row in GAINZ_FIELD_MAPPING}
    assert owners_used == {"STRATEGY", "TRADE_PLAN", "RISK", "EXECUTION", "DIAGNOSTIC"}

    # position_size and risk_per_trade must NOT be classified as STRATEGY or
    # TRADE_PLAN outputs -- directive Part 8/4 requires Risk ownership.
    by_concept = {row[0]: row for row in GAINZ_FIELD_MAPPING}
    assert by_concept["position_size"][4] == "RISK"
    assert by_concept["risk_per_trade"][4] == "RISK"
    # Entry/stop/targets must land on TradePlan, reusing the existing type.
    for concept in ("entry price (candidate)", "stop_loss", "TP1", "TP2", "TP3"):
        assert by_concept[concept][4] == "TRADE_PLAN"
        assert "TradePlan" in by_concept[concept][2]


# ---------------------------------------------------------------------------
# C. Existing StrategySignal is sufficient -- no new field required.
# ---------------------------------------------------------------------------
def test_c_strategysignal_unmodified_and_sufficient_for_gainz_mapping() -> None:
    existing_fields = set(StrategySignal.__dataclass_fields__.keys())
    assert existing_fields == {
        "strategy_id",
        "specification_version",
        "code_version",
        "configuration_version",
        "instrument_id",
        "timeframe",
        "timestamp",
        "direction",
        "price",
        "evidence",
    }
    # Every Gainz concept whose destination mentions StrategySignal must map
    # onto one of these existing fields (evidence, direction, timestamp,
    # instrument_id, timeframe) -- never a fabricated new attribute name.
    for concept, _current, destination, _required, _owner, _reason in GAINZ_FIELD_MAPPING:
        if "StrategySignal" in destination and "NOT a canonical destination" not in destination:
            assert any(f in destination for f in existing_fields), (
                f"{concept}: destination {destination!r} does not name an existing StrategySignal "
                "field -- would require a contract change, which this checkpoint has not proven "
                "necessary"
            )
    # No probability_of_profit field was introduced.
    assert "probability_of_profit" not in existing_fields
    assert "confidence" not in existing_fields
    assert "probability" not in existing_fields


# ---------------------------------------------------------------------------
# D. Existing TradePlan destination is identified where applicable.
# ---------------------------------------------------------------------------
def test_d_tradeplan_reused_for_entry_stop_targets() -> None:
    tradeplan_fields = set(TradePlan.__dataclass_fields__.keys())
    assert {"entry_price", "stop_loss", "target_1", "target_2", "target_3"} <= tradeplan_fields
    # No GainzTradePlan subtype/duplicate exists in the strategies directory.
    for path in STRATEGIES_DIR.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "GainzTradePlan" not in source
        assert "class GainzSignal" not in source
        assert "class GainzOutput" not in source


# ---------------------------------------------------------------------------
# E. Gainz feature mapping against the REAL canonical field registry.
#
# UPDATED at Checkpoint 64.49: this table originally recorded 64.48's
# snapshot (only EMA/ATR reusable, 8 features missing). 64.49 has since
# built RSI/ADX/+DI/-DI/Relative Volume/MACD Histogram/Candle Body Ratio
# as canonical PLATFORM features (standard TA conventions, explicitly
# NOT verified against a Gainz reference - see
# `test_checkpoint_64_49_gainz_feature_registry.py` and
# `field_registry.py`'s module docstring). Breakout and Delta remain
# genuinely deferred (ambiguous semantics, no Gainz source to
# disambiguate) - unchanged from 64.48. This table is kept updated
# in-place, rather than left stale, because it asserts a fact about the
# REAL registry that 64.49 legitimately changed.
# ---------------------------------------------------------------------------
GAINZ_FEATURE_MAPPING: tuple[tuple[str, bool, bool], ...] = (
    # (gainz_feature, exists_in_canonical_registry, reusable_without_new_code)
    ("EMA", True, True),
    ("ATR", True, True),
    ("RSI", True, True),
    ("ADX", True, True),
    ("+DI/-DI", True, True),
    ("relative volume", True, True),
    ("MACD-like histogram", True, True),
    ("breakout", False, False),
    ("candle body ratio", True, True),
    ("delta", False, False),
)


def test_e_feature_registry_reuse_opportunities_identified() -> None:
    real_field_ids = {f.field_id for f in list_fields()}
    # Updated at Checkpoint 64.49: the registry now has 15 fields (8
    # original + rsi/adx/plus_di/minus_di/relative_volume/macd_hist/
    # candle_body_ratio) - see field_registry.py's own Checkpoint 64.49
    # section and test_checkpoint_64_49_gainz_feature_registry.py.
    assert real_field_ids == {
        "open",
        "high",
        "low",
        "close",
        "volume",
        "sma",
        "ema",
        "atr",
        "rsi",
        "adx",
        "plus_di",
        "minus_di",
        "relative_volume",
        "macd_hist",
        "candle_body_ratio",
    }

    # "+DI/-DI" is one directive-prose concept mapping onto TWO real
    # field_ids (plus_di, minus_di) - handled explicitly rather than by
    # a naive lowercase-substring match.
    special_cases = {"+DI/-DI": {"plus_di", "minus_di"}}

    for feature, claimed_exists, claimed_reusable in GAINZ_FEATURE_MAPPING:
        if feature in special_cases:
            actually_exists = special_cases[feature].issubset(real_field_ids)
        else:
            actually_exists = feature.lower().replace(" ", "_").replace(
                "-like_histogram", "_hist"
            ) in real_field_ids or feature.upper() in {fid.upper() for fid in real_field_ids}
        assert actually_exists == claimed_exists, (
            f"{feature}: mapping claims exists={claimed_exists} but real registry says "
            f"{actually_exists}"
        )
        if claimed_exists:
            assert claimed_reusable, f"{feature}: exists but not marked reusable"
        else:
            assert not claimed_reusable, f"{feature}: cannot be reusable if it does not exist yet"

    reusable = {f for f, exists, _r in GAINZ_FEATURE_MAPPING if exists}
    missing = {f for f, exists, _r in GAINZ_FEATURE_MAPPING if not exists}
    assert reusable == {
        "EMA",
        "ATR",
        "RSI",
        "ADX",
        "+DI/-DI",
        "relative volume",
        "MACD-like histogram",
        "candle body ratio",
    }
    assert missing == {"breakout", "delta"}


# ---------------------------------------------------------------------------
# F. Gainz profile ownership is defined (configuration value, not a
#    separate strategy_id per profile, and not hard-coded).
# ---------------------------------------------------------------------------
def test_f_profile_ownership_is_configuration_not_separate_strategies() -> None:
    by_concept = {row[0]: row for row in GAINZ_FIELD_MAPPING}
    profile_row = by_concept["profile (alpha/trend/breakout/mean_reversion/hybrid/scalp)"]
    assert profile_row[4] == "STRATEGY"
    assert "StrategyConfigurationValues" in profile_row[2] or "strategy_id" in profile_row[2]


# ---------------------------------------------------------------------------
# G. Consensus ownership is defined and NOT baked into the global registry.
# ---------------------------------------------------------------------------
def test_g_consensus_ownership_not_in_global_registry() -> None:
    by_concept = {row[0]: row for row in GAINZ_FIELD_MAPPING}
    consensus_row = by_concept["consensus_signal()"]
    assert "StrategyRegistry" not in consensus_row[2] or "NOT" in consensus_row[2]
    registry_source = (STRATEGIES_DIR.parent / "registry.py").read_text(encoding="utf-8")
    assert "consensus" not in registry_source.lower()
    assert "gainz" not in registry_source.lower()


# ---------------------------------------------------------------------------
# H. Confidence is explicitly NOT treated as probability.
# ---------------------------------------------------------------------------
def test_h_confidence_not_treated_as_probability() -> None:
    by_concept = {row[0]: row for row in GAINZ_FIELD_MAPPING}
    confidence_row = by_concept["confidence / setup quality"]
    assert "NOT" in confidence_row[2] or "not" in confidence_row[5].lower()
    assert "probability_of_profit" in confidence_row[2]  # named only as what it must NOT become


# ---------------------------------------------------------------------------
# I. Position size is NOT treated as final Risk-approved order quantity.
# ---------------------------------------------------------------------------
def test_i_position_size_not_final_quantity() -> None:
    by_concept = {row[0]: row for row in GAINZ_FIELD_MAPPING}
    sizing_row = by_concept["position_size"]
    assert sizing_row[4] == "RISK"
    assert "advisory" in sizing_row[2].lower() or "never" in sizing_row[2].lower()


# ---------------------------------------------------------------------------
# J. Gainz remains completely unintegrated: no GainzStrategy class exists,
#    no strategy named/id'd "gainz" is registered, no Gainz module exists.
# ---------------------------------------------------------------------------
def test_j_gainz_remains_unintegrated() -> None:
    """As of 64.48, no strategy module referenced Gainz at all - actual
    GainzAlgo V2 remains unintegrated, unchanged today.

    Checkpoint 64.50 legitimately adds exactly ONE honestly-labeled
    research/compatibility strategy, `gainz_compatible_research.py`
    (class `GainzCompatibleResearchStrategy`) - explicitly NOT
    `GainzStrategy`, NOT verified GainzAlgo V2 mathematics (see that
    module's own header). This test is updated (not deleted) to allow
    exactly that one file/class while still failing on `gainz.py`, a
    class literally named `GainzStrategy`, or default-registry inclusion
    - none of which exist."""
    assert not (STRATEGIES_DIR / "gainz.py").exists()
    allowed_gainz_module = "gainz_compatible_research.py"
    allowed_gainz_class = "GainzCompatibleResearchStrategy"
    for path in STRATEGIES_DIR.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        if "gainz" in source.lower():
            assert path.name == allowed_gainz_module, f"{path} unexpectedly references Gainz"
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and "gainz" in node.name.lower():
                assert (
                    node.name == allowed_gainz_class
                ), f"{path}: unexpected Gainz-named class {node.name!r}"

    registry = build_default_registry()
    ids = {s.strategy_id for s in registry.list()}
    assert ids == {"ema_crossover", "sma_trend_filter", "atr_volatility_breakout"}
    for sid in ids:
        assert "gainz" not in sid.lower()


# ---------------------------------------------------------------------------
# K. Honesty guard: no file in the repo actually contains a Gainz reference
#    implementation (re-verified structurally, not just narratively).
# ---------------------------------------------------------------------------
def test_k_no_gainz_reference_file_exists_in_repo() -> None:
    hits: list[Path] = []
    for base in (REPO_ROOT / "src", REPO_ROOT / "tests", REPO_ROOT / "docs"):
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.is_file() and path.suffix in (".py", ".md") and "__pycache__" not in path.parts:
                try:
                    text = path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                if "gainz" in text.lower():
                    hits.append(path)

    # Every hit must be THIS checkpoint's own artifacts (or a prior
    # checkpoint's report/doc discussing Gainz's ABSENCE) -- never an actual
    # reference implementation module.
    allowed_names = {
        "test_checkpoint_64_48_gainz_adapter_design.py",
        "test_checkpoint_64_47_strategy_registry.py",
        "test_checkpoint_64_49_gainz_feature_registry.py",
        "taskReport.md",
        "CANONICAL_TRADE_LIFECYCLE_AND_PNL_ARCHITECTURE.md",
        # Checkpoint 64.49's own new canonical-feature modules mention
        # "Gainz" only to honestly disclaim "not verified against a
        # Gainz reference (none exists)" - see each module's own header.
        "field_registry.py",
        "definitions.py",
        "rsi.py",
        "directional_movement.py",
        "relative_volume.py",
        "macd_histogram.py",
        "candle_body_ratio.py",
        # Checkpoint 64.50: the honestly-labeled research/compatibility
        # strategy that CONSUMES those canonical features - explicitly
        # NOT a Gainz reference implementation (see its own header) - and
        # its dedicated test file.
        "gainz_compatible_research.py",
        "test_checkpoint_64_50_strategy_integration.py",
        "strategy_execution.py",
        # Checkpoint 64.68: this checkpoint's own paper-trading MVP test
        # files, which reference Gainz ONLY to prove its continued
        # absence (no `GainzPaperEngine` class exists; the paper-session
        # API REFUSES `gainz_compatible_research` because it is not in
        # the default registry). No Gainz math or module is added.
        "test_checkpoint_64_68_replay_paper_session.py",
        "test_checkpoint_64_68_paper_session_api.py",
        # Checkpoint 64.51: this checkpoint's own new registry-regression
        # test file discusses the same (already-allowed)
        # `gainz_compatible_research.py`/`GainzCompatibleResearchStrategy`
        # artifact - no new Gainz-named module was added.
        "test_checkpoint_64_51_registry_regression.py",
        # Checkpoint 64.52: this checkpoint's own new database-first
        # backtest integration test file - discusses the same
        # already-allowed `gainz_compatible_research.py` artifact, no
        # new Gainz-named module was added.
        "test_checkpoint_64_52_database_first_backtest.py",
    }
    for path in hits:
        assert path.name in allowed_names, (
            f"Unexpected Gainz reference found at {path} -- if this is a real Gainz implementation "
            "file, this test (and the whole checkpoint's honesty premise) must be revisited before "
            "any GainzStrategy adapter is built."
        )
