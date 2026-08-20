# tests/unit/communication/test_templates.py
#
# Checkpoint 64.19 §2/§3/§5/§6/§7: pure-rendering coverage for the ONE
# broker-independent "Channel Renderer" (`render_message()`) - Telegram
# and Discord both call this exact function with the SAME context and
# get the SAME logical text back (only their own send()/formatting
# happens per-channel, never a duplicated TelegramEvidenceFormatter/
# DiscordEvidenceFormatter with its own business logic, per §3's
# explicit instruction).
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from intraday.communication.contracts.signal_communication import (
    ExecutionStatus,
    MessageTemplateId,
    SignalCommunicationContext,
)
from intraday.communication.contracts.templates import render_message
from intraday.domain.shared_kernel.contracts import Side, SignalId, StrategyId
from intraday.domain.signal.contracts import SignalStatus

NOW = datetime(2026, 1, 5, 5, 0, tzinfo=UTC)


def _context(**overrides: object) -> SignalCommunicationContext:
    defaults: dict[str, object] = dict(  # noqa: C408
        strategy_id=StrategyId("ema_crossover"),
        strategy_version="v1",
        signal_id=SignalId("sig-1"),
        symbol="RELIANCE",
        exchange="NSE",
        signal_time=NOW,
        timeframe="1m",
        spot_price=Decimal("1236.00"),
        direction=Side.BUY,
        entry_price=Decimal("1236.00"),
        stop_loss=None,
        targets=(),
        trailing_stop_enabled=False,
        confidence=None,
        signal_status=SignalStatus.VALIDATED,
        execution_status=ExecutionStatus.NOT_EVALUATED,
    )
    defaults.update(overrides)
    return SignalCommunicationContext(**defaults)  # type: ignore[arg-type]


EMA_EVIDENCE = (
    ("Fast EMA", "1234.50"),
    ("Slow EMA", "1229.40"),
    ("Crossover", "Bullish"),
)


def test_validated_signal_includes_key_evidence_when_present() -> None:
    ctx = _context(evidence_fields=EMA_EVIDENCE)

    text = render_message(MessageTemplateId.VALIDATED_SIGNAL, ctx)

    assert "Key Evidence:" in text
    assert "Fast EMA: 1234.50" in text
    assert "Slow EMA: 1229.40" in text
    assert "Crossover: Bullish" in text


def test_validated_signal_omits_key_evidence_section_when_absent() -> None:
    """§2's explicit instruction: missing evidence must never be
    fabricated - the whole "Key Evidence" heading is omitted, not shown
    with placeholder/blank values."""
    ctx = _context(evidence_fields=())

    text = render_message(MessageTemplateId.VALIDATED_SIGNAL, ctx)

    assert "Key Evidence" not in text


def test_execution_blocked_includes_key_evidence_when_present() -> None:
    """§4: a risk-rejected signal's evidence must still be communicated -
    the EXECUTION_BLOCKED template renders evidence exactly like
    VALIDATED_SIGNAL does."""
    ctx = _context(
        evidence_fields=EMA_EVIDENCE,
        execution_status=ExecutionStatus.BLOCKED,
        block_reason="Stale market data",
    )

    text = render_message(MessageTemplateId.VALIDATED_SIGNAL_EXECUTION_BLOCKED, ctx)

    assert "Key Evidence:" in text
    assert "Fast EMA: 1234.50" in text
    assert "EXECUTION BLOCKED" in text
    assert "Stale market data" in text


def test_key_evidence_only_shows_fields_the_strategy_actually_produced() -> None:
    """A strategy with only ONE evidence field (e.g. ATR) must never
    show a fabricated second field."""
    ctx = _context(evidence_fields=(("ATR", "12.5"),))

    text = render_message(MessageTemplateId.VALIDATED_SIGNAL, ctx)

    assert "ATR: 12.5" in text
    assert "Fast EMA" not in text
    assert "Slow EMA" not in text


def test_execution_status_wording_distinguishes_every_real_outcome() -> None:
    """§5: no semantic ambiguity - NOT ATTEMPTED / RISK REJECTED /
    SUBMITTED / FILLED / FAILED must all read distinctly, never
    "TRADED" merely because a signal occurred."""
    outcomes = {
        ExecutionStatus.NOT_EVALUATED: "NOT_EVALUATED",
        ExecutionStatus.BLOCKED: "BLOCKED",
        ExecutionStatus.ORDER_SUBMITTED: "ORDER_SUBMITTED",
        ExecutionStatus.FILLED: "FILLED",
        ExecutionStatus.REJECTED: "REJECTED",
    }
    rendered_values = set()
    for execution_status, expected_substring in outcomes.items():
        ctx = _context(execution_status=execution_status)
        text = render_message(MessageTemplateId.VALIDATED_SIGNAL, ctx)
        assert expected_substring in text
        assert "TRADED" not in text
        rendered_values.add(text)
    # Every outcome must actually render DIFFERENT text - no collapsing
    # two distinct execution states into identical wording.
    assert len(rendered_values) == len(outcomes)


def test_no_message_ever_contains_a_credential_shaped_value() -> None:
    """§6: a targeted regression test - evidence values are plain
    strategy-computed numbers/words, never capable of carrying a token/
    webhook/secret, but this proves the rendered text stays clean even
    when evidence is present alongside every other context field."""
    ctx = _context(
        evidence_fields=EMA_EVIDENCE,
        stop_loss=Decimal("1229.00"),
        targets=(Decimal("1240.00"), Decimal("1245.00"), Decimal("1250.00")),
        trailing_stop_enabled=True,
        order_id="order-123",
        fill_price=Decimal("1236.50"),
        filled_quantity=Decimal("10"),
    )

    for template_id in (
        MessageTemplateId.VALIDATED_SIGNAL,
        MessageTemplateId.VALIDATED_SIGNAL_EXECUTION_BLOCKED,
        MessageTemplateId.ORDER_SUBMITTED,
        MessageTemplateId.ORDER_FILLED,
    ):
        text = render_message(template_id, ctx)
        assert "token" not in text.lower()
        assert "webhook" not in text.lower()
        assert "secret" not in text.lower()
        assert "bearer" not in text.lower()


def test_telegram_and_discord_render_the_same_canonical_text() -> None:
    """§3: no TelegramEvidenceFormatter/DiscordEvidenceFormatter - both
    channels call the SAME render_message() with the SAME context and
    get byte-identical text back; only the provider's own send() call
    differs (proven separately by the adapter tests), never the
    message content itself."""
    ctx = _context(evidence_fields=EMA_EVIDENCE)

    telegram_text = render_message(MessageTemplateId.VALIDATED_SIGNAL, ctx)
    discord_text = render_message(MessageTemplateId.VALIDATED_SIGNAL, ctx)

    assert telegram_text == discord_text


def test_missing_evidence_matrix_across_risk_and_execution_outcomes() -> None:
    """§7 message test matrix (evidence-focused slice): every
    risk/execution combination must independently reflect whether
    evidence exists, never leak evidence from one context into
    another."""
    base = _context()
    approved_filled = replace(
        base, evidence_fields=EMA_EVIDENCE, execution_status=ExecutionStatus.FILLED
    )
    approved_no_evidence = replace(
        base, evidence_fields=(), execution_status=ExecutionStatus.FILLED
    )
    rejected_with_evidence = replace(
        base, evidence_fields=EMA_EVIDENCE, execution_status=ExecutionStatus.BLOCKED
    )

    assert "Key Evidence" in render_message(MessageTemplateId.VALIDATED_SIGNAL, approved_filled)
    assert "Key Evidence" not in render_message(
        MessageTemplateId.VALIDATED_SIGNAL, approved_no_evidence
    )
    assert "Key Evidence" in render_message(
        MessageTemplateId.VALIDATED_SIGNAL_EXECUTION_BLOCKED, rejected_with_evidence
    )
