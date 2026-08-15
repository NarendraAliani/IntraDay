# File: src/intraday/communication/contracts/templates.py
#
# Checkpoint 37 Part 5: versioned, human-readable message templates.
# Every renderer is a pure function `SignalCommunicationContext -> str`
# — no I/O, no provider knowledge, no persistence. Only fields the
# `SignalCommunicationContext` actually carries are rendered; nothing
# is fabricated to fill a gap.
from __future__ import annotations

from collections.abc import Callable

from intraday.communication.contracts.signal_communication import (
    MessageTemplateId,
    SignalCommunicationContext,
)
from intraday.domain.shared_kernel.contracts import Side


def _fmt_price(value: object) -> str:
    return f"₹{value:,.2f}" if value is not None else "-"


def _fmt_time(ctx: SignalCommunicationContext) -> str:
    return ctx.signal_time.strftime("%H:%M:%S %Z") or ctx.signal_time.isoformat()


def _header(ctx: SignalCommunicationContext) -> str:
    return (
        f"Strategy: {ctx.strategy_id} (v{ctx.strategy_version})\n"
        f"Signal ID: {ctx.signal_id}\n"
        f"Stock: {ctx.symbol}\n"
        f"Exchange: {ctx.exchange}\n"
        f"Time: {_fmt_time(ctx)}\n"
        f"Timeframe: {ctx.timeframe}\n"
    )


def _render_validated_signal(ctx: SignalCommunicationContext) -> str:
    direction_word = "BUY" if ctx.direction is Side.BUY else "SELL"
    targets = "\n".join(f"Target {i + 1}: {_fmt_price(t)}" for i, t in enumerate(ctx.targets))
    confidence_line = (
        f"\nSignal Score: {ctx.confidence * 10:.1f}/10" if ctx.confidence is not None else ""
    )
    return (
        "\U0001f6a8 VALIDATED SIGNAL\n\n"
        f"{_header(ctx)}\n"
        f"Spot Price: {_fmt_price(ctx.spot_price)}\n\n"
        f"Signal: {direction_word}\n"
        f"Entry: {_fmt_price(ctx.entry_price)}\n\n"
        f"Stop Loss: {_fmt_price(ctx.stop_loss)}\n\n"
        f"{targets}\n\n"
        f"Trailing SL: {'Enabled' if ctx.trailing_stop_enabled else 'Disabled'}"
        f"{confidence_line}\n\n"
        f"Signal Status: {ctx.signal_status.value}\n"
        f"Execution Status: {ctx.execution_status.value}"
    )


def _render_execution_blocked(ctx: SignalCommunicationContext) -> str:
    return (
        "⚠️ VALIDATED SIGNAL / EXECUTION BLOCKED\n\n"
        f"{_header(ctx)}\n"
        f"Signal: {'BUY' if ctx.direction is Side.BUY else 'SELL'} "
        f"@ {_fmt_price(ctx.entry_price)}\n\n"
        f"Signal Status: {ctx.signal_status.value}\n"
        f"Execution Status: {ctx.execution_status.value}\n"
        f"Reason: {ctx.block_reason or 'Not specified'}"
    )


def _render_order_submitted(ctx: SignalCommunicationContext) -> str:
    return (
        "\U0001f4e4 ORDER SUBMITTED\n\n"
        f"{_header(ctx)}\n"
        f"Order ID: {ctx.order_id or '-'}\n"
        f"Entry: {_fmt_price(ctx.entry_price)}\n"
        f"Execution Status: {ctx.execution_status.value}"
    )


def _render_order_filled(ctx: SignalCommunicationContext) -> str:
    return (
        "✅ ORDER FILLED\n\n"
        f"{_header(ctx)}\n"
        f"Order ID: {ctx.order_id or '-'}\n"
        f"Fill Price: {_fmt_price(ctx.fill_price)}\n"
        f"Filled Quantity: {ctx.filled_quantity if ctx.filled_quantity is not None else '-'}\n"
        f"Execution Status: {ctx.execution_status.value}"
    )


def _render_partial_fill(ctx: SignalCommunicationContext) -> str:
    return (
        "\U0001f7e1 PARTIAL FILL\n\n"
        f"{_header(ctx)}\n"
        f"Order ID: {ctx.order_id or '-'}\n"
        f"Filled Quantity: {ctx.filled_quantity if ctx.filled_quantity is not None else '-'}\n"
        f"Fill Price: {_fmt_price(ctx.fill_price)}\n"
        f"Execution Status: {ctx.execution_status.value}"
    )


def _render_order_rejected(ctx: SignalCommunicationContext) -> str:
    return (
        "❌ ORDER REJECTED\n\n"
        f"{_header(ctx)}\n"
        f"Order ID: {ctx.order_id or '-'}\n"
        f"Reason: {ctx.rejection_reason or 'Not specified'}\n"
        f"Execution Status: {ctx.execution_status.value}"
    )


def _render_target_hit(index: int) -> Callable[[SignalCommunicationContext], str]:
    def _render(ctx: SignalCommunicationContext) -> str:
        return (
            f"\U0001f3af TARGET {index} HIT\n\n"
            f"{_header(ctx)}\n"
            f"Target {index}: {_fmt_price(ctx.target_hit_price)}\n"
            f"Execution Status: {ctx.execution_status.value}"
        )

    return _render


def _render_stop_loss_hit(ctx: SignalCommunicationContext) -> str:
    return (
        "\U0001f6d1 STOP LOSS HIT\n\n"
        f"{_header(ctx)}\n"
        f"Stop Loss: {_fmt_price(ctx.stop_loss)}\n"
        f"Realized P&L: {_fmt_price(ctx.realized_pnl) if ctx.realized_pnl is not None else '-'}\n"
        f"Execution Status: {ctx.execution_status.value}"
    )


def _render_trailing_stop_updated(ctx: SignalCommunicationContext) -> str:
    return (
        "\U0001f504 TRAILING STOP UPDATED\n\n"
        f"{_header(ctx)}\n"
        f"New Trailing SL: {_fmt_price(ctx.trailing_stop_price)}"
    )


def _render_position_closed(ctx: SignalCommunicationContext) -> str:
    return (
        "\U0001f512 POSITION CLOSED\n\n"
        f"{_header(ctx)}\n"
        f"Realized P&L: {_fmt_price(ctx.realized_pnl) if ctx.realized_pnl is not None else '-'}\n"
        f"Execution Status: {ctx.execution_status.value}"
    )


def _render_risk_limit_reached(ctx: SignalCommunicationContext) -> str:
    return (
        "⛔ RISK LIMIT REACHED\n\n"
        f"{_header(ctx)}\n"
        f"Reason: {ctx.block_reason or 'Not specified'}\n"
        f"Execution Status: {ctx.execution_status.value}"
    )


def _render_daily_trade_limit_reached(ctx: SignalCommunicationContext) -> str:
    return (
        "⛔ DAILY TRADE LIMIT REACHED\n\n"
        f"{_header(ctx)}\n"
        f"Reason: {ctx.block_reason or 'Not specified'}\n"
        f"Execution Status: {ctx.execution_status.value}"
    )


def _render_broker_disconnected(ctx: SignalCommunicationContext) -> str:
    return (
        "\U0001f50c BROKER DISCONNECTED\n\n"
        f"{_header(ctx)}\n"
        f"{ctx.extra_text or 'The configured broker connection is unavailable.'}"
    )


def _render_market_data_stale(ctx: SignalCommunicationContext) -> str:
    return (
        "⏳ MARKET DATA STALE\n\n"
        f"{_header(ctx)}\n"
        f"{ctx.extra_text or 'The market-data feed has not updated within the expected window.'}"
    )


def _render_kill_switch_alert(ctx: SignalCommunicationContext) -> str:
    return (
        "\U0001f6d1 SYSTEM / KILL SWITCH ALERT\n\n"
        f"{ctx.extra_text or 'The kill switch has been activated. '
                             'No new orders will be submitted.'}"
    )


def _render_end_of_day_summary(ctx: SignalCommunicationContext) -> str:
    return f"\U0001f4ca END-OF-DAY SUMMARY\n\n{ctx.extra_text or 'No summary data supplied.'}"


_RENDERERS: dict[MessageTemplateId, Callable[[SignalCommunicationContext], str]] = {
    MessageTemplateId.VALIDATED_SIGNAL: _render_validated_signal,
    MessageTemplateId.VALIDATED_SIGNAL_EXECUTION_BLOCKED: _render_execution_blocked,
    MessageTemplateId.ORDER_SUBMITTED: _render_order_submitted,
    MessageTemplateId.ORDER_FILLED: _render_order_filled,
    MessageTemplateId.PARTIAL_FILL: _render_partial_fill,
    MessageTemplateId.ORDER_REJECTED: _render_order_rejected,
    MessageTemplateId.TARGET_1_HIT: _render_target_hit(1),
    MessageTemplateId.TARGET_2_HIT: _render_target_hit(2),
    MessageTemplateId.TARGET_3_HIT: _render_target_hit(3),
    MessageTemplateId.STOP_LOSS_HIT: _render_stop_loss_hit,
    MessageTemplateId.TRAILING_STOP_UPDATED: _render_trailing_stop_updated,
    MessageTemplateId.POSITION_CLOSED: _render_position_closed,
    MessageTemplateId.RISK_LIMIT_REACHED: _render_risk_limit_reached,
    MessageTemplateId.DAILY_TRADE_LIMIT_REACHED: _render_daily_trade_limit_reached,
    MessageTemplateId.BROKER_DISCONNECTED: _render_broker_disconnected,
    MessageTemplateId.MARKET_DATA_STALE: _render_market_data_stale,
    MessageTemplateId.KILL_SWITCH_ALERT: _render_kill_switch_alert,
    MessageTemplateId.END_OF_DAY_SUMMARY: _render_end_of_day_summary,
}


def render_message(template_id: MessageTemplateId, context: SignalCommunicationContext) -> str:
    """The one call site every provider dispatch goes through - raises
    on an unknown template rather than silently sending a blank
    message."""
    renderer = _RENDERERS.get(template_id)
    if renderer is None:
        raise ValueError(f"No renderer registered for template {template_id}")
    return renderer(context)
