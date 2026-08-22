# File: src/intraday/domain/trade/net_pnl.py
#
# Checkpoint 64.37 — ADDITIVE REALIZED NET P&L CONTRACT. 64.36 mechanically
# proved that Backtest's `SimulatedTrade.net_pnl` (cost-inclusive) and
# Paper Trading's `Position.realized_pnl`/`Trade.realized_pnl`
# (cost-exclusive, by deliberate, pre-existing convention — see
# `domain/position/contracts.py` and `domain/trade/contracts.py`'s own
# Checkpoint 5 docstrings) feed the SAME `RiskEvaluationContext.
# current_daily_realized_pnl` field with two different financial
# meanings, and that this can flip `evaluate_order_risk()`'s decision for
# economically identical trades.
#
# THIS MODULE DOES NOT REDEFINE `realized_pnl`/`net_pnl` ANYWHERE. It adds
# exactly one new, explicit, deterministic, Decimal-based, dependency-free
# pure function: the smallest possible domain-level contract that lets
# BOTH Backtest and Paper Trading compute the SAME semantic quantity —
# "realized P&L after attributable transaction costs" — without either
# engine's existing fields changing formula or meaning.
#
# Deliberately NOT a class, NOT a "Service"/"Engine"/"Ledger" — a single
# pure function, mirroring this project's existing small domain-utility
# modules (`domain/order/idempotency.py`, `domain/order/state_machine.py`)
# rather than inventing new accounting-architecture vocabulary the
# checkpoint directive explicitly forbids introducing
# (AccountingEngine/AccountingLedger/NetPnlService/PnlManager).
#
# SEMANTICS (documented here, the single source of truth both producers
# below reference):
#   - `gross_price_pnl` (a.k.a. "gross P&L"): the raw price-movement P&L
#     of a closed trade/round-trip, on the SLIPPAGE-ADJUSTED fill price
#     (slippage is already folded into the fill price by both engines —
#     64.36 test_e/test_f — so it must NOT be counted again here).
#     Backtest: `SimulatedTrade.gross_pnl`. Paper Trading:
#     `Trade.realized_pnl` / the per-fill `realized` delta computed in
#     `PaperBroker._apply_to_position` — this IS the gross figure, by
#     PaperBroker's own existing, unchanged convention.
#   - `transaction_cost`: the REAL, itemized round-trip trading cost
#     (brokerage/STT/exchange charges/SEBI charges/GST/stamp duty),
#     produced by the SAME verified cost model
#     (`research.backtesting.cost_model.
#     verified_nse_cash_equity_intraday_cost_model()`) on both engines.
#     Does NOT include slippage (slippage is a fill-price adjustment, not
#     a cost line item — 64.36's own finding, preserved here).
#   - `realized_net_pnl` = `gross_price_pnl - transaction_cost`. This is
#     the ONE explicit, additive, cost-inclusive realized-P&L figure this
#     checkpoint introduces. It is NOT `Position.realized_pnl` (which
#     stays cost-exclusive/gross, unchanged) and NOT a replacement for
#     `SimulatedTrade.net_pnl` (which already equals this quantity for
#     Backtest, by construction — see
#     `research/backtesting/risk_gate_adapter.py`'s own header docstring).
#   - Costs are counted EXACTLY ONCE: this function performs one
#     subtraction. Callers must pass the trade's own attributable
#     transaction cost, never a value that has already been subtracted
#     from `gross_price_pnl` a second time.
from __future__ import annotations

from decimal import Decimal

__all__ = ["compute_realized_net_pnl"]


def compute_realized_net_pnl(gross_price_pnl: Decimal, transaction_cost: Decimal) -> Decimal:
    """`realized_net_pnl = gross_price_pnl - transaction_cost`.

    `gross_price_pnl` is the slippage-adjusted, cost-EXCLUSIVE realized
    P&L of one closed trade/round-trip leg (Backtest's `gross_pnl`, or
    Paper Trading's per-fill `realized`/`Trade.realized_pnl`).
    `transaction_cost` is the REAL, non-negative round-trip (or
    trade-attributable) transaction cost from the verified cost model.
    Pure, deterministic, no I/O, no mutation, no P&L field redefined.
    """
    if transaction_cost < 0:
        raise ValueError("transaction_cost must not be negative")
    return gross_price_pnl - transaction_cost
