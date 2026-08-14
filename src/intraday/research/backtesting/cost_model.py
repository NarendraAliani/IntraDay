# File: src/intraday/research/backtesting/cost_model.py
#
# Checkpoint 28 Part 10/11 / Checkpoint 29: a provider-neutral cost-model
# abstraction. The engine (single-instrument and portfolio) never
# inlines a brokerage/STT/GST/stamp-duty/slippage formula directly - it
# calls a `CostModel`. Two implementations exist:
#
#   - `FlatPercentageCostModel` (Checkpoint 27/28, UNCHANGED numerically)
#     - a MODEL ASSUMPTION, not a verified schedule.
#   - `IndianCashEquityIntradayCostModel` (Checkpoint 29) - a VERIFIED
#     Indian NSE cash-equity intraday statutory/exchange cost schedule,
#     with brokerage kept as a separate, explicitly configurable
#     component (Part 11: represent Indian cash-equity economics, not
#     one broker's economics).
#
# Neither implementation imports Dhan, any broker SDK, or any HTTP
# client - `research.backtesting` remains exactly as provider-neutral as
# before (Part 11).
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol

from intraday.research.backtesting import StrategyDirection

# Checkpoint 29 Part 7: the ONE place rounding policy is defined. Every
# emitted cost component and the total are rounded to 2 decimal places
# (rupee.paisa) using ROUND_HALF_UP - the conventional Indian brokerage-
# contract-note rounding convention. Internal intermediate sums (e.g.
# GST computed from unrounded brokerage+exchange+SEBI) use full Decimal
# precision before this final rounding is applied, so rounding error
# never compounds across components.
COST_DECIMAL_PLACES = Decimal("0.01")


def _round_rupees(value: Decimal) -> Decimal:
    return value.quantize(COST_DECIMAL_PLACES, rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class CostBreakdown:
    """Checkpoint 29 Part 5: an auditable line-item breakdown - never
    only gross/net. Every field is >= 0 by construction (enforced in
    `__post_init__`); "which side" semantics (STT/stamp duty apply to
    only one leg of a trade) are the calling model's responsibility, not
    this dataclass's - it simply holds whatever was actually charged for
    one leg (or a summed whole trade, when combined via `combine()`)."""

    brokerage: Decimal = Decimal("0")
    stt: Decimal = Decimal("0")
    exchange_transaction_charges: Decimal = Decimal("0")
    sebi_charges: Decimal = Decimal("0")
    gst: Decimal = Decimal("0")
    stamp_duty: Decimal = Decimal("0")
    other_statutory_charges: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        for name in (
            "brokerage",
            "stt",
            "exchange_transaction_charges",
            "sebi_charges",
            "gst",
            "stamp_duty",
            "other_statutory_charges",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"CostBreakdown.{name} must not be negative")

    @property
    def total(self) -> Decimal:
        """Total regulatory + broker cost - deliberately EXCLUDES
        slippage (Part 8: slippage is priced into the fill price itself,
        never summed into this total, to avoid double-counting it both
        as a price adjustment and as a cost line item)."""
        return (
            self.brokerage
            + self.stt
            + self.exchange_transaction_charges
            + self.sebi_charges
            + self.gst
            + self.stamp_duty
            + self.other_statutory_charges
        )

    def combine(self, other: CostBreakdown) -> CostBreakdown:
        """Sums two leg-level breakdowns (e.g. entry + exit) into one
        whole-trade breakdown - each statutory charge is applied exactly
        once per leg it is actually due on (Part 14: "statutory charges
        are applied exactly once"; the calling model decides per-leg
        applicability, this just adds two already-computed breakdowns)."""
        return CostBreakdown(
            brokerage=self.brokerage + other.brokerage,
            stt=self.stt + other.stt,
            exchange_transaction_charges=self.exchange_transaction_charges
            + other.exchange_transaction_charges,
            sebi_charges=self.sebi_charges + other.sebi_charges,
            gst=self.gst + other.gst,
            stamp_duty=self.stamp_duty + other.stamp_duty,
            other_statutory_charges=self.other_statutory_charges + other.other_statutory_charges,
        )


ZERO_BREAKDOWN = CostBreakdown()


class CostModel(Protocol):
    """What every cost model must answer, regardless of how it computes
    the answer internally. `name`/`version`/`effective_from` (Part 9)
    identify WHICH schedule produced a result - included in the
    deterministic backtest identity (Checkpoint 27's own
    `_deterministic_backtest_id`) so two backtests differing only in
    cost model never collide."""

    @property
    def name(self) -> str: ...

    @property
    def version(self) -> str: ...

    @property
    def effective_from(self) -> date: ...

    def cost_breakdown(self, *, is_buy: bool, notional: Decimal) -> CostBreakdown:
        """The full, itemized cost for ONE leg (one fill) of `notional`
        value. `is_buy=True` for a buy-side fill (a long entry or a
        short exit), `is_buy=False` for a sell-side fill (a long exit or
        a short entry) - side-specific charges (STT, stamp duty) are
        NEVER assumed symmetric (Part 6)."""
        ...

    def slippage_adjusted_price(
        self, direction: StrategyDirection, price: Decimal, *, entering: bool
    ) -> Decimal:
        """Returns the actually-filled price after slippage - always
        moved AGAINST the trader (a long entry/short exit pays more, a
        short entry/long exit receives less). Kept structurally SEPARATE
        from `cost_breakdown()` (Part 8) - slippage is a price-level
        effect, never a statutory/broker cost line item."""
        ...


@dataclass(frozen=True, slots=True)
class FlatPercentageCostModel:
    """MODEL ASSUMPTION (Checkpoint 27/28, UNCHANGED numerically in
    Checkpoint 29): brokerage is a flat percentage of notional; every
    statutory charge is 0. Slippage is a flat percentage price
    adjustment. Kept exactly as before so every Checkpoint 27/28 test
    and result remains byte-for-byte reproducible (Part 12)."""

    brokerage_percent: Decimal
    slippage_percent: Decimal
    name: str = "FLAT_PERCENTAGE"
    version: str = "v1"
    effective_from: date = field(default_factory=lambda: date(2026, 1, 1))

    def cost_breakdown(self, *, is_buy: bool, notional: Decimal) -> CostBreakdown:
        del is_buy  # symmetric by design - matches Checkpoint 27/28 behavior exactly
        return CostBreakdown(brokerage=notional * (self.brokerage_percent / Decimal("100")))

    def slippage_adjusted_price(
        self, direction: StrategyDirection, price: Decimal, *, entering: bool
    ) -> Decimal:
        factor = self.slippage_percent / Decimal("100")
        is_buy = (direction == StrategyDirection.BULLISH) == entering
        return price * (1 + factor) if is_buy else price * (1 - factor)


@dataclass(frozen=True, slots=True)
class BrokeragePolicy:
    """Checkpoint 29 Part 11: brokerage is explicitly NOT part of the
    verified statutory schedule - it is broker-specific and configurable.
    `percent_rate`/`flat_cap_per_order` together express the common
    Indian discount-broker structure ("X% of turnover or a flat cap per
    executed order, whichever is lower") WITHOUT asserting this is any
    specific broker's (including Dhan's) exact published rate - the
    default values below are a representative, clearly-labeled default,
    not a verified Dhan rate (Dhan's own current brokerage schedule was
    not part of this checkpoint's authoritative-source research)."""

    percent_rate: Decimal = Decimal("0.03")
    """Percent of notional, e.g. Decimal("0.03") = 0.03%."""
    flat_cap_per_order: Decimal | None = Decimal("20")
    """Maximum brokerage per executed order (leg) - `None` disables the
    cap (pure percentage brokerage)."""

    def charge_for(self, notional: Decimal) -> Decimal:
        percent_charge = notional * (self.percent_rate / Decimal("100"))
        if self.flat_cap_per_order is None:
            return percent_charge
        return min(percent_charge, self.flat_cap_per_order)


@dataclass(frozen=True, slots=True)
class IndianCashEquityIntradayCostModel:
    """Checkpoint 29: a VERIFIED NSE cash-equity INTRADAY cost schedule.
    See `docs/architecture/BACKTESTING_ARCHITECTURE.md`'s "Verified
    Indian Cost Schedule" section for the full authoritative-source
    table (name/legal basis/side/formula/source URL/verification date
    per charge) - this docstring states only the calculation itself.

    Per-leg charges (Part 3/6):
      - Brokerage: `brokerage_policy.charge_for(notional)` - BOTH sides.
      - STT (Securities Transaction Tax): `stt_rate` of notional - SELL
        side only (a long trade's exit leg, or a short trade's entry
        leg - never symmetric).
      - Exchange transaction charges (NSE): `exchange_rate` of notional
        - BOTH sides.
      - SEBI turnover fees: `sebi_rate` of notional - BOTH sides.
      - Stamp duty: `stamp_duty_rate` of notional - BUY side only (a
        long trade's entry leg, or a short trade's exit leg).
      - GST: `gst_rate` applied to (brokerage + exchange transaction
        charges + SEBI charges) ONLY - NEVER applied to STT or stamp
        duty (both are themselves taxes, not taxable services).

    Calculation order (Part 3, exact): brokerage -> exchange charges ->
    SEBI charges -> GST (on the sum of those three) -> STT (sell-side
    only, computed independently of GST) -> stamp duty (buy-side only,
    computed independently of GST). All charges computed on unrounded
    Decimal notional; the RETURNED breakdown's components are each
    rounded to 2 decimal places (Part 7) via `_round_rupees` before
    being returned - rounding happens once, at the boundary, never
    mid-calculation.
    """

    stt_rate: Decimal
    exchange_rate: Decimal
    sebi_rate: Decimal
    gst_rate: Decimal
    stamp_duty_rate: Decimal
    brokerage_policy: BrokeragePolicy = field(default_factory=BrokeragePolicy)
    slippage_percent: Decimal = Decimal("0")
    name: str = "INDIAN_CASH_EQUITY_INTRADAY"
    version: str = "v1"
    effective_from: date = field(default_factory=lambda: date(2026, 8, 14))

    def cost_breakdown(self, *, is_buy: bool, notional: Decimal) -> CostBreakdown:
        brokerage = self.brokerage_policy.charge_for(notional)
        exchange_charges = notional * (self.exchange_rate / Decimal("100"))
        sebi_charges = notional * (self.sebi_rate / Decimal("100"))
        gst = (brokerage + exchange_charges + sebi_charges) * (self.gst_rate / Decimal("100"))
        stt = notional * (self.stt_rate / Decimal("100")) if not is_buy else Decimal("0")
        stamp_duty = notional * (self.stamp_duty_rate / Decimal("100")) if is_buy else Decimal("0")

        return CostBreakdown(
            brokerage=_round_rupees(brokerage),
            stt=_round_rupees(stt),
            exchange_transaction_charges=_round_rupees(exchange_charges),
            sebi_charges=_round_rupees(sebi_charges),
            gst=_round_rupees(gst),
            stamp_duty=_round_rupees(stamp_duty),
            other_statutory_charges=Decimal("0"),
        )

    def slippage_adjusted_price(
        self, direction: StrategyDirection, price: Decimal, *, entering: bool
    ) -> Decimal:
        """Slippage remains a SEPARATE, explicit model (Part 8) - never
        silently folded into the verified statutory schedule above."""
        factor = self.slippage_percent / Decimal("100")
        is_buy = (direction == StrategyDirection.BULLISH) == entering
        return price * (1 + factor) if is_buy else price * (1 - factor)


def verified_nse_cash_equity_intraday_cost_model(
    *, brokerage_policy: BrokeragePolicy | None = None, slippage_percent: Decimal = Decimal("0")
) -> IndianCashEquityIntradayCostModel:
    """Constructs the verified model with the rates recorded in
    `docs/architecture/BACKTESTING_ARCHITECTURE.md`'s source table
    (Checkpoint 29 Part 2), verified 2026-08-14 against Zerodha's own
    official published charges page (an "official broker pricing
    documentation" source per Part 2's own accepted source list) - the
    statutory/exchange rates (STT, NSE transaction charge, SEBI turnover
    fee, GST treatment, stamp duty) are government/exchange/regulator-
    mandated and apply uniformly across brokers; only `brokerage_policy`
    is genuinely broker-specific and is kept independently configurable."""
    return IndianCashEquityIntradayCostModel(
        stt_rate=Decimal("0.025"),
        exchange_rate=Decimal("0.00307"),
        sebi_rate=Decimal("0.0001"),
        gst_rate=Decimal("18"),
        stamp_duty_rate=Decimal("0.003"),
        brokerage_policy=brokerage_policy or BrokeragePolicy(),
        slippage_percent=slippage_percent,
    )
