from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Gainz-style Signal Engine
# ---------------------------------------------------------------------------
# Important:
# This is a "research & rebuild" implementation inspired by the PUBLICLY
# VISIBLE GainzAlgo V2 Alpha logic (stable candle + engulfing + RSI regime +
# price-delta filter + ATR-based TP/SL + repeat suppression).
# It is NOT the proprietary GainzAlgo implementation.
#
# Expected OHLCV columns:
#   open, high, low, close, volume
#
# The function works on a DataFrame and returns one row per candle with:
# signal, confidence, score, entry, SL, TP1/TP2/TP3, R:R, position size,
# regime, and human-readable reasons.
# ---------------------------------------------------------------------------


@dataclass
class SignalConfig:
    # Core indicators
    rsi_period: int = 14
    atr_period: int = 14
    ema_fast: int = 9
    ema_slow: int = 21
    ema_trend: int = 50
    volume_period: int = 20
    adx_period: int = 14

    # Public Alpha-like defaults
    candle_stability: float = 0.70
    rsi_threshold: float = 80.0
    candle_delta_length: int = 10

    # Risk
    atr_sl_mult: float = 1.0
    rr1: float = 1.0
    rr2: float = 2.0
    rr3: float = 3.0
    min_rr: float = 1.5

    # Confidence / filtering
    min_confidence: float = 65.0
    min_score: float = 55.0
    min_relative_volume: float = 0.80
    max_atr_pct: float = 8.0

    # Signal hygiene
    disable_repeating_signals: bool = True
    require_confirmed_bar: bool = True

    # Position sizing
    risk_per_trade: float = 0.01
    max_position_value_pct: float = 0.25


def _validate_ohlcv(df: pd.DataFrame) -> None:
    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing OHLCV columns: {sorted(missing)}")


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))

    out = out.where(avg_loss != 0, 100.0)
    out = out.where(~((avg_gain == 0) & (avg_loss == 0)), 50.0)
    return out


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def _adx(df: pd.DataFrame, period: int = 14) -> Tuple[pd.Series, pd.Series, pd.Series]:
    high = df["high"]
    low = df["low"]
    close = df["close"]

    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
        index=df.index,
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
        index=df.index,
    )

    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    atr = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    return adx, plus_di, minus_di


def _prepare_features(df: pd.DataFrame, cfg: SignalConfig) -> pd.DataFrame:
    x = df.copy()

    x["ema_fast"] = x["close"].ewm(span=cfg.ema_fast, adjust=False).mean()
    x["ema_slow"] = x["close"].ewm(span=cfg.ema_slow, adjust=False).mean()
    x["ema_trend"] = x["close"].ewm(span=cfg.ema_trend, adjust=False).mean()

    x["rsi"] = _rsi(x["close"], cfg.rsi_period)
    x["atr"] = _atr(x, cfg.atr_period)
    x["atr_pct"] = 100 * x["atr"] / x["close"]

    x["volume_ma"] = x["volume"].rolling(cfg.volume_period).mean()
    x["rel_volume"] = x["volume"] / x["volume_ma"].replace(0, np.nan)

    x["adx"], x["plus_di"], x["minus_di"] = _adx(x, cfg.adx_period)

    x["body"] = (x["close"] - x["open"]).abs()
    x["range"] = (x["high"] - x["low"]).replace(0, np.nan)
    x["body_ratio"] = x["body"] / x["range"]

    # Public Alpha-like candle logic
    x["stable_candle"] = x["body_ratio"] >= cfg.candle_stability

    x["bullish_engulfing"] = (
        (x["close"].shift(1) < x["open"].shift(1))
        & (x["close"] > x["open"])
        & (x["close"] > x["open"].shift(1))
        & (x["open"] <= x["close"].shift(1))
    )

    x["bearish_engulfing"] = (
        (x["close"].shift(1) > x["open"].shift(1))
        & (x["close"] < x["open"])
        & (x["close"] < x["open"].shift(1))
        & (x["open"] >= x["close"].shift(1))
    )

    x["price_down_delta"] = x["close"] < x["close"].shift(cfg.candle_delta_length)
    x["price_up_delta"] = x["close"] > x["close"].shift(cfg.candle_delta_length)

    # Trend
    x["trend_bull"] = (
        (x["close"] > x["ema_trend"])
        & (x["ema_fast"] > x["ema_slow"])
        & (x["ema_slow"] > x["ema_trend"])
    )
    x["trend_bear"] = (
        (x["close"] < x["ema_trend"])
        & (x["ema_fast"] < x["ema_slow"])
        & (x["ema_slow"] < x["ema_trend"])
    )

    # Momentum
    x["momentum_bull"] = (x["rsi"] > 50) & (x["rsi"] > x["rsi"].shift(1))
    x["momentum_bear"] = (x["rsi"] < 50) & (x["rsi"] < x["rsi"].shift(1))

    # Breakout structure
    prior_high = x["high"].shift(1).rolling(20).max()
    prior_low = x["low"].shift(1).rolling(20).min()
    x["breakout_bull"] = x["close"] > prior_high
    x["breakout_bear"] = x["close"] < prior_low

    # MACD-like momentum
    macd = x["ema_fast"] - x["ema_slow"]
    macd_signal = macd.ewm(span=9, adjust=False).mean()
    x["macd"] = macd
    x["macd_signal"] = macd_signal
    x["macd_hist"] = macd - macd_signal
    x["macd_bull"] = x["macd_hist"] > 0
    x["macd_bear"] = x["macd_hist"] < 0

    # Directional strength
    x["adx_bull"] = (x["adx"] >= 20) & (x["plus_di"] > x["minus_di"])
    x["adx_bear"] = (x["adx"] >= 20) & (x["minus_di"] > x["plus_di"])

    return x


def _score_row(row: pd.Series, profile: str, cfg: SignalConfig) -> Tuple[float, float, str, List[str], List[str]]:
    """
    Returns:
        bull_score, bear_score, regime, bull_reasons, bear_reasons
    """
    bull = 0.0
    bear = 0.0
    br: List[str] = []
    sr: List[str] = []

    # -----------------------------
    # 1) Gainz-style Alpha pattern
    # -----------------------------
    if row["bullish_engulfing"]:
        bull += 25
        br.append("bullish_engulfing")
    if row["bearish_engulfing"]:
        bear += 25
        sr.append("bearish_engulfing")

    if row["stable_candle"]:
        bull += 8
        bear += 8
        br.append("stable_candle")
        sr.append("stable_candle")

    # The public Alpha logic uses RSI < 80 for bullish and RSI > 20 for bearish.
    # We retain that asymmetric "not extremely exhausted" gate.
    if pd.notna(row["rsi"]) and row["rsi"] < cfg.rsi_threshold:
        bull += 8
        br.append("rsi_below_alpha_threshold")

    if pd.notna(row["rsi"]) and row["rsi"] > 100 - cfg.rsi_threshold:
        bear += 8
        sr.append("rsi_above_alpha_threshold")

    if row["price_down_delta"]:
        bull += 8
        br.append("price_below_delta_reference")

    if row["price_up_delta"]:
        bear += 8
        sr.append("price_above_delta_reference")

    # -----------------------------
    # 2) Trend confirmation
    # -----------------------------
    if row["trend_bull"]:
        bull += 15
        br.append("ema_trend_bull")
    if row["trend_bear"]:
        bear += 15
        sr.append("ema_trend_bear")

    # -----------------------------
    # 3) Momentum confirmation
    # -----------------------------
    if row["momentum_bull"]:
        bull += 8
        br.append("rsi_momentum_bull")
    if row["momentum_bear"]:
        bear += 8
        sr.append("rsi_momentum_bear")

    if row["macd_bull"]:
        bull += 7
        br.append("macd_positive")
    if row["macd_bear"]:
        bear += 7
        sr.append("macd_negative")

    # -----------------------------
    # 4) Volume confirmation
    # -----------------------------
    if pd.notna(row["rel_volume"]):
        if row["rel_volume"] >= 1.20:
            if row["close"] > row["open"]:
                bull += 10
                br.append("volume_expansion")
            elif row["close"] < row["open"]:
                bear += 10
                sr.append("volume_expansion")
        elif row["rel_volume"] >= cfg.min_relative_volume:
            if row["close"] > row["open"]:
                bull += 4
                br.append("volume_acceptable")
            elif row["close"] < row["open"]:
                bear += 4
                sr.append("volume_acceptable")

    # -----------------------------
    # 5) Structure / breakout
    # -----------------------------
    if row["breakout_bull"]:
        bull += 12
        br.append("20_bar_breakout")
    if row["breakout_bear"]:
        bear += 12
        sr.append("20_bar_breakdown")

    # -----------------------------
    # 6) Directional strength
    # -----------------------------
    if row["adx_bull"]:
        bull += 7
        br.append("adx_direction_bull")
    if row["adx_bear"]:
        bear += 7
        sr.append("adx_direction_bear")

    # -----------------------------
    # Profile-specific adjustments
    # -----------------------------
    profile = profile.lower()

    if profile == "alpha":
        # Favor price-action reversal/continuation patterns.
        pass

    elif profile == "trend":
        # Trend profile penalizes counter-trend Alpha patterns.
        if row["trend_bull"]:
            bull += 8
        if row["trend_bear"]:
            bear += 8
        if row["rsi"] < 40:
            bull -= 5
        if row["rsi"] > 60:
            bear -= 5

    elif profile == "breakout":
        if row["breakout_bull"] and row["rel_volume"] >= 1.20:
            bull += 12
        if row["breakout_bear"] and row["rel_volume"] >= 1.20:
            bear += 12

    elif profile == "mean_reversion":
        # Oversold/overbought reversal, but only when candle structure confirms.
        if row["rsi"] < 35 and row["bullish_engulfing"]:
            bull += 15
            br.append("oversold_reversal")
        if row["rsi"] > 65 and row["bearish_engulfing"]:
            bear += 15
            sr.append("overbought_reversal")

    elif profile == "hybrid":
        # Hybrid deliberately requires several independent dimensions.
        if row["trend_bull"] and row["momentum_bull"] and row["rel_volume"] >= 1.0:
            bull += 10
        if row["trend_bear"] and row["momentum_bear"] and row["rel_volume"] >= 1.0:
            bear += 10

    elif profile == "scalp":
        # Faster confirmation; avoid weak-volatility entries.
        if row["atr_pct"] >= 0.35:
            if row["close"] > row["open"]:
                bull += 5
            else:
                bear += 5

    # Volatility penalty: don't blindly trade huge candles.
    if pd.notna(row["atr_pct"]) and row["atr_pct"] > cfg.max_atr_pct:
        bull -= 12
        bear -= 12

    regime = "RANGE"
    if row["adx"] >= 25:
        if row["trend_bull"]:
            regime = "BULL_TREND"
        elif row["trend_bear"]:
            regime = "BEAR_TREND"
        else:
            regime = "TRENDING"
    elif row["adx"] < 18:
        regime = "LOW_TREND"

    return max(0.0, bull), max(0.0, bear), regime, br, sr


def _confidence(
    bull: float,
    bear: float,
    row: pd.Series,
    cfg: SignalConfig,
) -> Tuple[str, float, float]:
    """
    Confidence is NOT a probability of profit.
    It is a normalized setup-quality score.
    """
    total = bull + bear

    if total <= 0:
        return "HOLD", 0.0, 0.0

    if bull > bear:
        side = "BUY"
        dominant = bull
        opposing = bear
    elif bear > bull:
        side = "SELL"
        dominant = bear
        opposing = bull
    else:
        return "HOLD", 0.0, 0.0

    # Directional separation.
    separation = 100 * (dominant - opposing) / max(dominant + opposing, 1e-9)

    # Setup quality cap based on independent confirmation dimensions.
    independent = 0
    if row["stable_candle"]:
        independent += 1
    if row["rel_volume"] >= 1.0:
        independent += 1
    if row["adx"] >= 20:
        independent += 1
    if row["atr_pct"] <= cfg.max_atr_pct:
        independent += 1
    if side == "BUY":
        independent += int(row["trend_bull"])
        independent += int(row["momentum_bull"])
    else:
        independent += int(row["trend_bear"])
        independent += int(row["momentum_bear"])

    # 0..100 quality score.
    quality = min(100.0, dominant * 0.85 + separation * 0.35 + independent * 3.0)

    # A practical "confidence" score.
    confidence = float(np.clip(quality, 0.0, 100.0))

    return side, confidence, dominant


def _risk_levels(
    side: str,
    entry: float,
    atr: float,
    cfg: SignalConfig,
) -> Tuple[float, float, float, float]:
    if not np.isfinite(atr) or atr <= 0:
        return np.nan, np.nan, np.nan, np.nan

    risk = atr * cfg.atr_sl_mult

    if side == "BUY":
        sl = entry - risk
        tp1 = entry + risk * cfg.rr1
        tp2 = entry + risk * cfg.rr2
        tp3 = entry + risk * cfg.rr3
    else:
        sl = entry + risk
        tp1 = entry - risk * cfg.rr1
        tp2 = entry - risk * cfg.rr2
        tp3 = entry - risk * cfg.rr3

    return sl, tp1, tp2, tp3


def generate_gainz_signals(
    df: pd.DataFrame,
    profile: str = "hybrid",
    config: Optional[SignalConfig] = None,
    capital: Optional[float] = None,
) -> pd.DataFrame:
    """
    Generate multi-profile Gainz-style signals.

    Parameters
    ----------
    df:
        OHLCV DataFrame. Index may be datetime.
    profile:
        "alpha", "trend", "breakout", "mean_reversion",
        "hybrid", or "scalp".
    config:
        SignalConfig object.
    capital:
        Optional account capital for risk-based position sizing.

    Returns
    -------
    DataFrame
        Original OHLCV plus indicators and signal metadata.

    Notes
    -----
    The signal is evaluated using the CLOSED candle. For live trading, call
    this after the bar has closed or explicitly pass only completed candles.
    """

    cfg = config or SignalConfig()
    _validate_ohlcv(df)

    profile = profile.lower()
    allowed = {"alpha", "trend", "breakout", "mean_reversion", "hybrid", "scalp"}
    if profile not in allowed:
        raise ValueError(f"profile must be one of {sorted(allowed)}")

    x = _prepare_features(df, cfg)

    signals: List[str] = []
    confidences: List[float] = []
    scores: List[float] = []
    regimes: List[str] = []
    reasons: List[str] = []
    entries: List[float] = []
    sls: List[float] = []
    tp1s: List[float] = []
    tp2s: List[float] = []
    tp3s: List[float] = []
    rr_values: List[float] = []
    position_sizes: List[float] = []

    last_signal = "HOLD"

    for _, row in x.iterrows():
        bull, bear, regime, br, sr = _score_row(row, profile, cfg)
        side, confidence, dominant = _confidence(bull, bear, row, cfg)

        # Hard filters
        valid_data = pd.notna(row["atr"]) and pd.notna(row["rsi"]) and pd.notna(row["adx"])
        if not valid_data:
            side = "HOLD"
            confidence = 0.0

        if pd.notna(row["atr_pct"]) and row["atr_pct"] > cfg.max_atr_pct:
            side = "HOLD"
            confidence = min(confidence, 45.0)

        if confidence < cfg.min_confidence or dominant < cfg.min_score:
            side = "HOLD"

        # Repeat suppression
        if cfg.disable_repeating_signals and side in {"BUY", "SELL"} and side == last_signal:
            side = "HOLD"
            confidence = 0.0

        if side == "BUY":
            why = br
            entry = float(row["close"])
            sl, tp1, tp2, tp3 = _risk_levels(side, entry, float(row["atr"]), cfg)
            rr = cfg.rr2
            last_signal = side
        elif side == "SELL":
            why = sr
            entry = float(row["close"])
            sl, tp1, tp2, tp3 = _risk_levels(side, entry, float(row["atr"]), cfg)
            rr = cfg.rr2
            last_signal = side
        else:
            why = []
            entry = np.nan
            sl = tp1 = tp2 = tp3 = np.nan
            rr = np.nan

        # Risk-based quantity.
        qty = np.nan
        if capital is not None and side in {"BUY", "SELL"} and np.isfinite(sl):
            risk_amount = capital * cfg.risk_per_trade
            per_share_risk = abs(entry - sl)

            if per_share_risk > 0:
                qty_by_risk = risk_amount / per_share_risk
                qty_by_value = (capital * cfg.max_position_value_pct) / entry
                qty = max(0.0, min(qty_by_risk, qty_by_value))

        signals.append(side)
        confidences.append(round(float(confidence), 2))
        scores.append(round(float(dominant), 2))
        regimes.append(regime)
        reasons.append(",".join(why))
        entries.append(entry)
        sls.append(sl)
        tp1s.append(tp1)
        tp2s.append(tp2)
        tp3s.append(tp3)
        rr_values.append(rr)
        position_sizes.append(qty)

    x["signal"] = signals
    x["confidence"] = confidences
    x["signal_score"] = scores
    x["regime"] = regimes
    x["signal_reasons"] = reasons
    x["entry"] = entries
    x["stop_loss"] = sls
    x["take_profit_1"] = tp1s
    x["take_profit_2"] = tp2s
    x["take_profit_3"] = tp3s
    x["risk_reward"] = rr_values
    x["position_size"] = position_sizes
    x["profile"] = profile

    return x


def generate_all_profiles(
    df: pd.DataFrame,
    config: Optional[SignalConfig] = None,
    capital: Optional[float] = None,
) -> Dict[str, pd.DataFrame]:
    """Run every strategy profile on the same OHLCV dataset."""
    profiles = [
        "alpha",
        "trend",
        "breakout",
        "mean_reversion",
        "hybrid",
        "scalp",
    ]
    return {
        p: generate_gainz_signals(df, profile=p, config=config, capital=capital)
        for p in profiles
    }


def consensus_signal(
    df: pd.DataFrame,
    config: Optional[SignalConfig] = None,
    capital: Optional[float] = None,
    min_votes: int = 3,
) -> pd.DataFrame:
    """
    Run all profiles and create a consensus signal.

    Consensus is intentionally stricter than any single profile.
    """
    results = generate_all_profiles(df, config=config, capital=capital)

    out = df.copy()
    profile_names = list(results.keys())

    for p in profile_names:
        out[f"{p}_signal"] = results[p]["signal"].values
        out[f"{p}_confidence"] = results[p]["confidence"].values

    final_signal = []
    final_conf = []
    final_reason = []

    for i in range(len(out)):
        buys = [
            results[p].iloc[i]["confidence"]
            for p in profile_names
            if results[p].iloc[i]["signal"] == "BUY"
        ]
        sells = [
            results[p].iloc[i]["confidence"]
            for p in profile_names
            if results[p].iloc[i]["signal"] == "SELL"
        ]

        if len(buys) >= min_votes and len(buys) > len(sells):
            final_signal.append("BUY")
            final_conf.append(round(float(np.mean(buys)), 2))
            final_reason.append(f"{len(buys)}/{len(profile_names)} profiles BUY")
        elif len(sells) >= min_votes and len(sells) > len(buys):
            final_signal.append("SELL")
            final_conf.append(round(float(np.mean(sells)), 2))
            final_reason.append(f"{len(sells)}/{len(profile_names)} profiles SELL")
        else:
            final_signal.append("HOLD")
            final_conf.append(0.0)
            final_reason.append("No consensus")

    out["consensus_signal"] = final_signal
    out["consensus_confidence"] = final_conf
    out["consensus_reason"] = final_reason

    # Attach risk levels using the hybrid profile as the execution layer.
    hybrid = results["hybrid"]
    out["entry"] = hybrid["entry"].values
    out["stop_loss"] = hybrid["stop_loss"].values
    out["take_profit_1"] = hybrid["take_profit_1"].values
    out["take_profit_2"] = hybrid["take_profit_2"].values
    out["take_profit_3"] = hybrid["take_profit_3"].values
    out["position_size"] = hybrid["position_size"].values

    return out


# ---------------------------------------------------------------------------
# Example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # CSV should contain:
    # datetime,open,high,low,close,volume
    data = pd.read_csv("ohlcv.csv")

    if "datetime" in data.columns:
        data["datetime"] = pd.to_datetime(data["datetime"])
        data = data.set_index("datetime")

    cfg = SignalConfig(
        candle_stability=0.70,
        rsi_threshold=80,
        candle_delta_length=10,
        atr_sl_mult=1.0,
        min_confidence=65,
        min_score=55,
        risk_per_trade=0.01,
    )

    # Single strategy:
    hybrid = generate_gainz_signals(
        data,
        profile="hybrid",
        config=cfg,
        capital=1_000_000,
    )

    print(
        hybrid.loc[
            hybrid["signal"] != "HOLD",
            [
                "close",
                "signal",
                "confidence",
                "regime",
                "entry",
                "stop_loss",
                "take_profit_1",
                "take_profit_2",
                "take_profit_3",
                "position_size",
                "signal_reasons",
            ],
        ].tail(20)
    )

    # Multi-strategy consensus:
    consensus = consensus_signal(
        data,
        config=cfg,
        capital=1_000_000,
        min_votes=3,
    )

    print(
        consensus.loc[
            consensus["consensus_signal"] != "HOLD",
            [
                "close",
                "consensus_signal",
                "consensus_confidence",
                "consensus_reason",
                "entry",
                "stop_loss",
                "take_profit_1",
                "take_profit_2",
                "take_profit_3",
                "position_size",
            ],
        ].tail(20)
    )
