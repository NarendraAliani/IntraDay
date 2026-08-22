# File: tests/unit/research/test_checkpoint_64_41_fill_contract.py
#
# Checkpoint 64.41: tests for the canonical `Fill` domain contract
# (`intraday.domain.execution.contracts.Fill`/`FillSource`). Pure
# contract-level tests only — no PaperBroker, no Backtest engine, no
# producer wiring exists yet (deliberately, per the 64.41 directive).
# Placed under `tests/unit/research/` to match this repository's own
# established convention for the 64.3x checkpoint series (64.34-64.40's
# own test files all live here, despite testing domain-layer contracts,
# because that is the nearest already-used location this project has
# settled on for this checkpoint series).
from __future__ import annotations

import time
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from intraday.domain.execution.contracts import Fill, FillSource
from intraday.domain.order.contracts import OrderStatus
from intraday.domain.shared_kernel.contracts import InstrumentId, OrderId, Side

UTC_NOW = datetime(2026, 8, 22, 9, 15, tzinfo=UTC)


def _make_fill(**overrides: object) -> Fill:
    defaults: dict[str, object] = {
        "fill_id": "fill-1",
        "order_id": OrderId("order-1"),
        "instrument_id": InstrumentId("NSE:RELIANCE"),
        "side": Side.BUY,
        "quantity": Decimal("10"),
        "price": Decimal("100.00"),
        "timestamp": UTC_NOW,
        "transaction_cost": Decimal("1.50"),
        "slippage_applied": Decimal("0.10"),
        "status_at_fill": OrderStatus.FILLED,
        "source": FillSource.PAPER,
    }
    defaults.update(overrides)
    return Fill(**defaults)  # type: ignore[arg-type]


class TestValidFullFill:
    """A. valid full fill."""

    def test_constructs_with_all_fields_set_correctly(self) -> None:
        fill = _make_fill()
        assert fill.fill_id == "fill-1"
        assert fill.order_id == OrderId("order-1")
        assert fill.instrument_id == InstrumentId("NSE:RELIANCE")
        assert fill.side is Side.BUY
        assert fill.quantity == Decimal("10")
        assert fill.price == Decimal("100.00")
        assert fill.timestamp == UTC_NOW
        assert fill.transaction_cost == Decimal("1.50")
        assert fill.slippage_applied == Decimal("0.10")
        assert fill.status_at_fill is OrderStatus.FILLED
        assert fill.source is FillSource.PAPER


class TestValidPartialFill:
    """B. valid partial fill."""

    def test_partial_fill_has_status_partially_filled(self) -> None:
        fill = _make_fill(quantity=Decimal("4"), status_at_fill=OrderStatus.PARTIALLY_FILLED)
        assert fill.quantity == Decimal("4")
        assert fill.status_at_fill is OrderStatus.PARTIALLY_FILLED


class TestMultipleFillsPerOrder:
    """C. same OrderIntent can conceptually create multiple Fill values
    with unique fill_id, both sharing the same order_id (directive §2's
    exact 40-then-60 example)."""

    def test_two_fills_share_order_id_but_have_distinct_fill_ids_and_sum_to_order_quantity(
        self,
    ) -> None:
        order_id = OrderId("order-multi")
        first = _make_fill(
            fill_id="fill-a",
            order_id=order_id,
            quantity=Decimal("40"),
            status_at_fill=OrderStatus.PARTIALLY_FILLED,
        )
        second = _make_fill(
            fill_id="fill-b",
            order_id=order_id,
            quantity=Decimal("60"),
            status_at_fill=OrderStatus.FILLED,
        )
        assert first.order_id == second.order_id == order_id
        assert first.fill_id != second.fill_id
        assert first.quantity + second.quantity == Decimal("100")


class TestQuantityValidation:
    """D/E. quantity > 0 required; <= 0 rejected."""

    def test_positive_quantity_accepted(self) -> None:
        assert _make_fill(quantity=Decimal("0.01")).quantity == Decimal("0.01")

    def test_zero_quantity_rejected(self) -> None:
        with pytest.raises(ValueError, match="quantity must be positive"):
            _make_fill(quantity=Decimal("0"))

    def test_negative_quantity_rejected(self) -> None:
        with pytest.raises(ValueError, match="quantity must be positive"):
            _make_fill(quantity=Decimal("-5"))


class TestPriceValidation:
    """F/G. price > 0 required; invalid price rejected."""

    def test_positive_price_accepted(self) -> None:
        assert _make_fill(price=Decimal("0.05")).price == Decimal("0.05")

    def test_zero_price_rejected(self) -> None:
        with pytest.raises(ValueError, match="price must be positive"):
            _make_fill(price=Decimal("0"))

    def test_negative_price_rejected(self) -> None:
        with pytest.raises(ValueError, match="price must be positive"):
            _make_fill(price=Decimal("-1"))


class TestTransactionCostValidation:
    """H/I. transaction_cost >= 0; negative rejected."""

    def test_zero_transaction_cost_accepted(self) -> None:
        assert _make_fill(transaction_cost=Decimal("0")).transaction_cost == Decimal("0")

    def test_positive_transaction_cost_accepted(self) -> None:
        assert _make_fill(transaction_cost=Decimal("12.34")).transaction_cost == Decimal("12.34")

    def test_negative_transaction_cost_rejected(self) -> None:
        with pytest.raises(ValueError, match="transaction_cost must not be negative"):
            _make_fill(transaction_cost=Decimal("-0.01"))


class TestTimestampValidation:
    """J/K. timezone-aware timestamp accepted; naive timestamp rejected
    (matches the project-wide `ensure_utc()` convention already applied
    to every other domain timestamp — `OrderIntent.created_at`,
    `OrderEvent.timestamp_utc`, `Position.opened_at`, etc.)."""

    def test_utc_aware_timestamp_accepted(self) -> None:
        assert _make_fill(timestamp=UTC_NOW).timestamp == UTC_NOW

    def test_naive_timestamp_rejected(self) -> None:
        naive = datetime(2026, 8, 22, 9, 15)
        with pytest.raises(ValueError, match="timezone-aware"):
            _make_fill(timestamp=naive)

    def test_non_utc_offset_rejected(self) -> None:
        from datetime import timedelta, timezone

        ist = datetime(2026, 8, 22, 9, 15, tzinfo=timezone(timedelta(hours=5, minutes=30)))
        with pytest.raises(ValueError, match="must be in UTC"):
            _make_fill(timestamp=ist)


class TestOrderIdRelationship:
    """L. order_id relationship — Fill.order_id references its
    originating OrderIntent's own order_id (by convention; Fill does not
    depend on an entire OrderIntent object)."""

    def test_order_id_is_the_originating_orders_own_id(self) -> None:
        order_id = OrderId("order-xyz")
        fill = _make_fill(order_id=order_id)
        assert fill.order_id == order_id

    def test_empty_order_id_rejected(self) -> None:
        with pytest.raises(ValueError, match="order_id must be non-empty"):
            _make_fill(order_id=OrderId(""))


class TestActualExecutionPriceSemantics:
    """M. Fill.price means the ACTUAL execution price, after slippage
    and after any limit-boundary clamp — never the raw/limit/pre-slippage
    price. Documented in the dataclass docstring; here we assert the
    contract does not conflate `price` with `slippage_applied` (i.e. it
    stores both independently, proving the design does not require the
    caller to back out slippage from price after the fact)."""

    def test_price_and_slippage_applied_are_independent_fields(self) -> None:
        # A LIMIT BUY clamped to 100.00 (Checkpoint 64.40 F2 semantics)
        # under 1% adverse slippage from a 100.00 reference: the ACTUAL
        # fill price is 100.00 (clamped), while slippage_applied still
        # records what adjustment was attempted/realized on this fill,
        # kept structurally separate from `price` itself.
        fill = _make_fill(price=Decimal("100.00"), slippage_applied=Decimal("0.00"))
        assert fill.price == Decimal("100.00")
        assert fill.slippage_applied == Decimal("0.00")

    def test_slippage_applied_can_be_nonzero_while_price_is_the_final_post_slippage_value(
        self,
    ) -> None:
        fill = _make_fill(price=Decimal("101.00"), slippage_applied=Decimal("1.00"))
        assert fill.price == Decimal("101.00")
        assert fill.slippage_applied == Decimal("1.00")


class TestSourceProvenance:
    """N. source/provenance validation — explicit FillSource enum, never
    inferred, never a bare string literal."""

    @pytest.mark.parametrize("source", [FillSource.BACKTEST, FillSource.PAPER, FillSource.LIVE])
    def test_all_three_sources_are_valid(self, source: FillSource) -> None:
        assert _make_fill(source=source).source is source

    def test_source_is_a_real_enum_not_a_bare_string(self) -> None:
        fill = _make_fill(source=FillSource.LIVE)
        assert isinstance(fill.source, FillSource)
        assert not isinstance(fill.source, str)

    def test_fill_source_enum_is_exactly_three_members_no_more_no_less(self) -> None:
        assert {member.value for member in FillSource} == {"BACKTEST", "PAPER", "LIVE"}


class TestFilledStatusRepresentation:
    """O. FILLED status representation."""

    def test_status_at_fill_filled_accepted(self) -> None:
        fill = _make_fill(status_at_fill=OrderStatus.FILLED)
        assert fill.status_at_fill is OrderStatus.FILLED


class TestPartiallyFilledStatusRepresentation:
    """P. PARTIALLY_FILLED representation — a Fill event CAN coexist with
    PARTIALLY_FILLED (directive: "YES: Fill quantity may be less than
    order quantity")."""

    def test_status_at_fill_partially_filled_accepted(self) -> None:
        fill = _make_fill(status_at_fill=OrderStatus.PARTIALLY_FILLED, quantity=Decimal("3"))
        assert fill.status_at_fill is OrderStatus.PARTIALLY_FILLED

    @pytest.mark.parametrize(
        "invalid_status",
        [
            OrderStatus.CREATED,
            OrderStatus.SUBMITTED,
            OrderStatus.TRANSIT,
            OrderStatus.ACKNOWLEDGED,
            OrderStatus.PENDING,
            OrderStatus.CANCEL_REQUESTED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
            OrderStatus.ERROR,
        ],
    )
    def test_non_fill_statuses_rejected(self, invalid_status: OrderStatus) -> None:
        with pytest.raises(ValueError, match="status_at_fill must be"):
            _make_fill(status_at_fill=invalid_status)


class TestImmutability:
    """Q/R. immutable Fill; does not mutate after construction."""

    def test_is_frozen_dataclass(self) -> None:
        fill = _make_fill()
        with pytest.raises(Exception):  # noqa: B017 - dataclasses.FrozenInstanceError
            fill.quantity = Decimal("999")  # type: ignore[misc]

    def test_uses_slots_no_arbitrary_attribute_assignment(self) -> None:
        fill = _make_fill()
        with pytest.raises(Exception):  # noqa: B017 - AttributeError, slots forbid new attrs
            fill.made_up_field = "nope"  # type: ignore[attr-defined]

    def test_fields_unchanged_after_construction_and_use_elsewhere(self) -> None:
        fill = _make_fill()
        original_price = fill.price
        original_quantity = fill.quantity
        # Simulate "use elsewhere" (e.g. read by a hypothetical consumer)
        _ = (fill.price, fill.quantity, fill.transaction_cost)
        assert fill.price == original_price
        assert fill.quantity == original_quantity


class TestNoDjangoDhanApplicationResearchDependency:
    """S. no Django/Dhan/application/research dependency — mechanically
    verified via the actual imports of the module that defines Fill."""

    def test_fill_module_imports_no_forbidden_package(self) -> None:
        import ast

        import intraday.domain.execution.contracts as fill_module

        source = fill_module.__file__
        assert source is not None
        with open(source, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        imported_modules: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.append(node.module)
            elif isinstance(node, ast.Import):
                imported_modules.extend(alias.name for alias in node.names)
        forbidden_substrings = (
            "django",
            "dhan",
            "intraday.application",
            "intraday.research",
            "intraday.infrastructure",
            "intraday.trading_engine",
            "intraday.signal_intelligence",
            "intraday.control_plane",
            "intraday.communication",
        )
        for module_name in imported_modules:
            lowered = module_name.lower()
            for forbidden in forbidden_substrings:
                assert (
                    forbidden not in lowered
                ), f"Fill module must not import {module_name!r} (contains {forbidden!r})"

    def test_fill_module_only_imports_stdlib_and_domain(self) -> None:
        import ast

        import intraday.domain.execution.contracts as fill_module

        source = fill_module.__file__
        assert source is not None
        with open(source, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert (
                    module == "__future__"
                    or module.startswith("intraday.domain")
                    or module
                    in (
                        "enum",
                        "dataclasses",
                        "datetime",
                        "decimal",
                    )
                ), f"unexpected import: {module}"
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    top_level = alias.name.split(".")[0]
                    assert top_level in (
                        "enum",
                        "dataclasses",
                        "datetime",
                        "decimal",
                    ), f"unexpected import: {alias.name}"


class TestNoOrderStatusVocabularyDuplicated:
    """T. no existing OrderStatus vocabulary duplicated — Fill reuses
    `domain.order.contracts.OrderStatus` directly for `status_at_fill`,
    never a parallel `FillStatus` enum."""

    def test_status_at_fill_type_is_the_existing_order_status_enum(self) -> None:
        import dataclasses

        field_types = {f.name: f.type for f in dataclasses.fields(Fill)}
        assert field_types["status_at_fill"] == "OrderStatus"

    def test_no_fillstatus_class_exists_in_module(self) -> None:
        import intraday.domain.execution.contracts as fill_module

        assert not hasattr(fill_module, "FillStatus")


class TestFillConstructionIsCheap:
    """§23: Fill construction is O(1) — no database lookup, no network
    call, no position/order scan. Cheap enough to construct one per
    execution event. A generous threshold (not a tight microbenchmark)
    to avoid flaking on a loaded CI box while still catching any
    pathological accidental O(n) behavior."""

    def test_ten_thousand_fills_construct_quickly(self) -> None:
        start = time.perf_counter()
        for i in range(10_000):
            _make_fill(fill_id=f"fill-{i}")
        elapsed = time.perf_counter() - start
        assert elapsed < 5.0, f"10,000 Fill constructions took {elapsed:.3f}s — investigate"


class TestFillIndependentlyConstructible:
    """§19: Fill remains independently constructible as a valid event —
    it does not require an entire OrderIntent/Order object, only the
    order_id reference (a plain str-based NewType)."""

    def test_fill_requires_no_order_intent_object(self) -> None:
        # If this constructs without importing/instantiating OrderIntent
        # anywhere in this test module's fixture, the independence claim
        # holds structurally — _make_fill above never builds one.
        fill = _make_fill()
        assert fill.order_id == OrderId("order-1")


class TestSumOfFillQuantitiesInvariant:
    """§19 (producer-level invariant, tested here at the Fill-collection
    level only — Fill itself does not enforce this, its producer must):
    sum(fill.quantity for fill in fills) <= order.quantity."""

    def test_sum_of_two_partial_fills_does_not_exceed_order_quantity(self) -> None:
        order_quantity = Decimal("100")
        fills = [
            _make_fill(
                fill_id="fill-1",
                quantity=Decimal("40"),
                status_at_fill=OrderStatus.PARTIALLY_FILLED,
            ),
            _make_fill(
                fill_id="fill-2",
                quantity=Decimal("60"),
                status_at_fill=OrderStatus.FILLED,
            ),
        ]
        assert sum((f.quantity for f in fills), Decimal("0")) <= order_quantity

    def test_a_producer_level_overfill_is_not_prevented_by_fill_itself(self) -> None:
        # Documents the deliberate boundary: Fill validates ITS OWN
        # quantity is positive, but does NOT know about any Order's
        # remaining_quantity — enforcing sum(fills) <= order.quantity is
        # explicitly the PRODUCER's job (directive §11/§19), not Fill's.
        # A pathological producer COULD construct two Fills that together
        # overfill; this is intentional (Fill stays independently
        # constructible) and is exercised here only to document the
        # boundary, not to claim Fill prevents it.
        oversized = [
            _make_fill(fill_id="fill-1", quantity=Decimal("70")),
            _make_fill(fill_id="fill-2", quantity=Decimal("70")),
        ]
        total = sum((f.quantity for f in oversized), Decimal("0"))
        assert total == Decimal("140")  # Fill does not reject this by itself, by design


class TestBacktestPaperParityDesign:
    """§21: the SAME contract (fields/types/semantics) works for both a
    BACKTEST-sourced and a PAPER-sourced Fill, differing only in
    `source`/`timestamp`/`price` as the execution environment dictates."""

    def test_backtest_and_paper_fills_use_identical_schema(self) -> None:
        backtest_fill = _make_fill(
            fill_id="bt-1", source=FillSource.BACKTEST, price=Decimal("100.00")
        )
        paper_fill = _make_fill(fill_id="pp-1", source=FillSource.PAPER, price=Decimal("100.05"))
        assert type(backtest_fill) is type(paper_fill) is Fill
        import dataclasses

        assert {f.name for f in dataclasses.fields(backtest_fill)} == {
            f.name for f in dataclasses.fields(paper_fill)
        }
        assert backtest_fill.source is not paper_fill.source


class TestNoNewSubsystemIntroduced:
    """§17: confirms no FillBook/FillManager/ExecutionLedger/FillService
    was introduced this checkpoint — Fill is a value object, not a
    subsystem."""

    def test_no_fillbook_or_manager_class_exists(self) -> None:
        import intraday.domain.execution.contracts as fill_module

        for forbidden_name in (
            "FillBook",
            "FillManager",
            "ExecutionLedger",
            "FillService",
            "FillRepository",
        ):
            assert not hasattr(fill_module, forbidden_name)
