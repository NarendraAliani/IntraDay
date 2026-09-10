# File: src/intraday/application/services/backtest_pdf_report.py
#
# CHECKPOINT-BACKTEST-PDF-A: renders an already-completed backtest
# result (the EXACT `to_json_dict()` shape `GET /backtesting/results/
# <backtest_id>/` already serves - no second, parallel representation
# invented) into a multi-page PDF. NO new backtest computation happens
# anywhere in this module - every number here is either copied
# verbatim from `result["metrics"]`/`result["validation"]`/
# `result["data_quality"]` or a pure arithmetic ROLLUP over the SAME
# already-computed trade list the frontend's own `BacktestResultsPanel`
# already sums client-side (`totalGrossPnl`/`totalCosts` in
# `BacktestingWorkbenchPage.tsx`) - never a re-run of the strategy
# engine, never a re-scan of bars.
#
# HONEST SCOPE, decided in Part 1 recon and reused here verbatim:
#   - No sector-wise breakdown - confirmed directly (this checkpoint's
#     own recon) that this project has no sector/fundamental data
#     source anywhere. "Results by Instrument" (per-instrument, not
#     per-sector) is the honest substitute already shown on-screen for
#     a multi-instrument run - Page 4 here mirrors it exactly.
#   - Page 3's Ratio Analysis is `profit_factor`/`sharpe_ratio_trade_level`/
#     `sortino_ratio_trade_level` ONLY - all three are already fully
#     computed fields on `result["metrics"]` (see
#     `research/backtesting/serialization.py::to_json_dict()`), zero
#     derivation needed. A Calmar ratio was considered and deliberately
#     EXCLUDED: it requires an ANNUALIZED return, and this project has
#     no established, honest trading-day-annualization convention for
#     an intraday-only backtest window - inventing one here risks
#     presenting a number that LOOKS precisely computed but rests on
#     an unstated, arbitrary assumption. Named explicitly rather than
#     silently omitted - see CHECKPOINT_BACKTEST-PDF-A_SUMMARY.md.
#
# CHARTS: real vector line charts (reportlab's own
# `graphics.charts.lineplots.LinePlot`), built from the SAME
# `mark_to_market_curve` the frontend's `EquityCurveChart`/
# `DrawdownChart` already render - not a second, invented data series.
from __future__ import annotations

import io
from decimal import Decimal, InvalidOperation

from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

_PAGE_SIZE = A4
_MARGIN = 1.8 * cm
_FOOTER_HEIGHT = 2.6 * cm

_styles = getSampleStyleSheet()
_TITLE = ParagraphStyle("ReportTitle", parent=_styles["Title"], fontSize=16)
_H2 = ParagraphStyle("ReportH2", parent=_styles["Heading2"], spaceBefore=10, spaceAfter=4)
_BODY = _styles["BodyText"]
_SMALL = ParagraphStyle("Small", parent=_styles["BodyText"], fontSize=8, leading=10)
_WARN = ParagraphStyle(
    "Warn", parent=_styles["BodyText"], fontSize=8, leading=10, textColor=colors.HexColor("#8a4b00")
)


def _money(value: object) -> str:
    """Same "never fabricate, never crash on an honestly-missing value"
    discipline the frontend's own `formatMoney()` follows - a `None`
    or unparsable value renders as an explicit em dash, never a fake
    zero."""
    if value is None:
        return "—"
    try:
        return f"Rs. {Decimal(str(value)):,.2f}"
    except (InvalidOperation, ValueError):
        return "—"


def _percent(value: object) -> str:
    if value is None:
        return "—"
    try:
        return f"{Decimal(str(value)):.2f}%"
    except (InvalidOperation, ValueError):
        return "—"


def _ratio(value: object) -> str:
    if value is None:
        return "—"
    try:
        return f"{Decimal(str(value)):.2f}"
    except (InvalidOperation, ValueError):
        return "—"


def _footer_lines(result: dict[str, object]) -> list[str]:
    """The EXACT disclaimer language `BacktestResultsPanel` already
    shows on-screen (`BacktestingWorkbenchPage.tsx`'s own "Data Quality
    & Assumptions" block and its "RESULT, not a promise" callout) -
    reused verbatim, never dropped for a "cleaner" report."""
    data_quality = result.get("data_quality", {}) or {}
    trust_level = result.get("trust_level", "POC")
    lines = [
        f"RESULT, not a promise. Backtest results are historical simulations and are not "
        f"guarantees of future performance. Trust level: {trust_level}.",
        f"Data quality: {data_quality.get('data_quality', '—')} "
        f"(bar count: {data_quality.get('bar_count', '—')}).",
    ]
    if data_quality.get("data_quality") == "SAMPLE_BAR":
        lines.append("NOT SUITABLE FOR TRADING-GRADE PERFORMANCE CLAIMS.")
    assumption = data_quality.get("transaction_cost_assumption")
    if assumption:
        lines.append(f"ASSUMPTION: {assumption}")
    slippage = data_quality.get("slippage_assumption")
    if slippage:
        lines.append(f"ASSUMPTION: {slippage}")
    survivorship = data_quality.get("survivorship_bias_note")
    if survivorship:
        lines.append(f"LIMITATION: {survivorship}")
    cost_identity = result.get("cost_model_identity", {}) or {}
    verified = "VERIFIED COST MODEL" if cost_identity.get("is_verified") else "MODEL ASSUMPTION"
    lines.append(
        f"{verified}: {cost_identity.get('name', '—')} v{cost_identity.get('version', '—')} "
        f"(effective from {cost_identity.get('effective_from', '—')})."
    )
    return lines


def _kpi_table(rows: list[tuple[str, str]], *, columns: int = 3) -> Table:
    """A simple KPI grid, mirroring the visual intent of the frontend's
    own `.backtest-results__kpi`/`.dashboard__grid` card pattern
    (label above value) in the one layout PDF table cells can actually
    express - a grid of label/value pairs, `columns` wide."""
    cells: list[list[Paragraph]] = []
    row: list[Paragraph] = []
    label_style = ParagraphStyle("KpiLabel", parent=_SMALL, textColor=colors.HexColor("#5b6572"))
    value_style = ParagraphStyle("KpiValue", parent=_BODY, fontSize=12, leading=14)
    for label, value in rows:
        row.append(Paragraph(f"{label}<br/><b>{value}</b>", value_style))
        if len(row) == columns:
            cells.append(row)
            row = []
    if row:
        while len(row) < columns:
            row.append(Paragraph("", _SMALL))
        cells.append(row)
    table = Table(cells, colWidths=[(_PAGE_SIZE[0] - 2 * _MARGIN) / columns] * columns)
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d7dbe0")),
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f7f8fa")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def _curve_chart(
    title: str, values: list[float], *, width: float, height: float, color: colors.Color
) -> Drawing:
    """A real vector line chart from `mark_to_market_curve` - the SAME
    series `EquityCurveChart`/`DrawdownChart` (`common/components/
    EquityChart.tsx`) already render on-screen, not an invented one.
    X-axis is bar sequence (the curve's own already-chronological
    order) - the underlying real timestamps are shown in the per-trade
    ledger on Page 2 instead of being re-derived as chart tick labels
    here."""
    drawing = Drawing(width, height)
    drawing.add(String(0, height - 10, title, fontSize=9, fillColor=colors.HexColor("#1c2530")))
    if len(values) < 2:
        drawing.add(
            String(4, height / 2, "No data", fontSize=8, fillColor=colors.HexColor("#5b6572"))
        )
        return drawing
    plot = LinePlot()
    plot.x = 4
    plot.y = 4
    plot.width = width - 12
    plot.height = height - 22
    plot.data = [list(enumerate(values))]
    plot.lines[0].strokeColor = color
    plot.lines[0].strokeWidth = 1.2
    y_min, y_max = min(values), max(values)
    if y_min == y_max:
        y_min -= 1
        y_max += 1
    plot.yValueAxis.valueMin = y_min
    plot.yValueAxis.valueMax = y_max
    plot.yValueAxis.labelTextFormat = "%.0f"
    plot.xValueAxis.valueMin = 0
    plot.xValueAxis.valueMax = len(values) - 1
    drawing.add(plot)
    return drawing


def _instrument_row(result: dict[str, object]) -> tuple[str, str, str, str]:
    config = result.get("configuration", {}) or {}
    metrics = result.get("metrics", {}) or {}
    return (
        str(config.get("instrument_id", "—")),
        _money(metrics.get("net_pnl")),
        _percent(metrics.get("win_rate_percent")),
        str(metrics.get("total_trades", "—")),
    )


def build_backtest_report_pdf(
    result: dict[str, object], *, sibling_results: list[dict[str, object]] | None = None
) -> bytes:
    """Builds the full, multi-page PDF for one backtest result.

    `sibling_results` (optional): every OTHER instrument's own
    `BacktestResult` from the SAME historical multi-instrument run
    (resolved by the caller via `result_backtest_ids` on the run's own
    `DjangoBacktestRunRepository` row - never a second universe-
    resolution mechanism). When supplied and non-empty, adds Page 4
    ("Results by Instrument") - otherwise Page 4 is omitted entirely,
    matching the on-screen behavior (a single-instrument run never
    shows "Results by Instrument")."""
    config = result.get("configuration", {}) or {}
    metrics = result.get("metrics", {}) or {}
    validation = result.get("validation", {}) or {}
    mtm_curve = result.get("mark_to_market_curve", []) or []
    trades = result.get("trades", []) or []

    buffer = io.BytesIO()
    footer_lines = _footer_lines(result)

    def _draw_footer(canvas, doc) -> None:  # noqa: ANN001 - reportlab callback signature
        canvas.saveState()
        canvas.setFont("Helvetica", 7)
        y = _MARGIN - 0.3 * cm
        canvas.setStrokeColor(colors.HexColor("#d7dbe0"))
        canvas.line(_MARGIN, y + 0.35 * cm, _PAGE_SIZE[0] - _MARGIN, y + 0.35 * cm)
        for line in reversed(footer_lines):
            canvas.setFillColor(colors.HexColor("#5b6572"))
            canvas.drawString(_MARGIN, y, line[:170])
            y -= 0.28 * cm
        canvas.restoreState()

    frame = Frame(
        _MARGIN,
        _MARGIN + _FOOTER_HEIGHT,
        _PAGE_SIZE[0] - 2 * _MARGIN,
        _PAGE_SIZE[1] - 2 * _MARGIN - _FOOTER_HEIGHT,
        id="body",
    )
    template = PageTemplate(id="reportPage", frames=[frame], onPage=_draw_footer)
    doc = BaseDocTemplate(
        buffer,
        pagesize=_PAGE_SIZE,
        pageTemplates=[template],
        title=f"Backtest Report - {config.get('strategy_id', '')} on {config.get('instrument_id', '')}",
    )

    story: list[object] = []

    # --- Page 1: Summary --------------------------------------------------
    story.append(Paragraph("Backtest Report", _TITLE))
    story.append(
        Paragraph(
            f"{config.get('strategy_id', '—')} "
            f"(spec {config.get('specification_version', '—')}, "
            f"code {config.get('code_version', '—')}, "
            f"config v{config.get('configuration_version', '—')}) on "
            f"{config.get('instrument_id', '—')}",
            _BODY,
        )
    )
    story.append(
        Paragraph(
            f"Backtest ID: {result.get('backtest_id', '—')} &nbsp;|&nbsp; "
            f"Generated: {result.get('generated_at', '—')}",
            _SMALL,
        )
    )
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph("Configuration", _H2))
    config_rows = [
        ["Timeframe", str(config.get("timeframe", "—"))],
        ["Date range", f"{config.get('start', '—')} to {config.get('end', '—')}"],
        ["Position sizing", str(config.get("position_sizing_mode", "—"))],
        ["Position size value", str(config.get("position_size_value", "—"))],
        ["Initial capital", _money(config.get("initial_capital"))],
        ["Final capital", _money(metrics.get("final_capital"))],
        ["Net P&L", _money(metrics.get("net_pnl"))],
        ["Return %", _percent(metrics.get("return_percent"))],
    ]
    config_table = Table(config_rows, colWidths=[5.5 * cm, None])
    config_table.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#5b6572")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    story.append(config_table)
    story.append(Spacer(1, 0.4 * cm))
    story.append(Paragraph("Key Metrics", _H2))
    story.append(
        _kpi_table(
            [
                ("Win Rate", _percent(metrics.get("win_rate_percent"))),
                ("Profit Factor", _ratio(metrics.get("profit_factor"))),
                ("Max Drawdown", _percent(metrics.get("max_drawdown_percent"))),
                ("Sharpe (trade-level)", _ratio(metrics.get("sharpe_ratio_trade_level"))),
                ("Total Trades", str(metrics.get("total_trades", "—"))),
                ("Total Signals", str(validation.get("signal_count", "—"))),
            ]
        )
    )
    story.append(Spacer(1, 0.4 * cm))

    equity_values = [float(p.get("total_equity") or 0) for p in mtm_curve]
    drawdown_values = [float(p.get("drawdown_percent") or 0) for p in mtm_curve]
    chart_width = (_PAGE_SIZE[0] - 2 * _MARGIN - 0.5 * cm) / 2
    chart_row = Table(
        [
            [
                _curve_chart(
                    "Equity Curve (mark-to-market)",
                    equity_values,
                    width=chart_width,
                    height=4.5 * cm,
                    color=colors.HexColor("#2f7d4f"),
                ),
                _curve_chart(
                    "Drawdown Curve (%)",
                    drawdown_values,
                    width=chart_width,
                    height=4.5 * cm,
                    color=colors.HexColor("#c0392b"),
                ),
            ]
        ],
        colWidths=[chart_width, chart_width],
    )
    story.append(chart_row)
    story.append(
        Paragraph(
            "LIMITATION: the curves above are mark-to-market (valued at each bar's own close "
            "price while a position is open) - a real, but simplified, view of intrabar risk.",
            _SMALL,
        )
    )

    # --- Page 2: Signal/Trade breakdown ------------------------------------
    story.append(PageBreak())
    story.append(Paragraph("Signal / Trade Breakdown", _TITLE))
    story.append(Paragraph("Signals and Trades", _H2))
    validation_rows = [
        ["Signals Generated", str(validation.get("signal_count", "—"))],
        ["Trades Taken", str(validation.get("trade_count", "—"))],
        [
            "Skipped Signals (same-direction, position already open)",
            str(validation.get("skipped_signals", "—")),
        ],
        ["Rejected Trades (insufficient capital)", str(validation.get("rejected_trades", "—"))],
        ["Warm-up Bars", str(validation.get("warmup_bars", "—"))],
        ["Data Gaps", str(validation.get("data_gaps_note", "—"))],
    ]
    validation_table = Table(validation_rows, colWidths=[9 * cm, None])
    validation_table.setStyle(
        TableStyle(
            [
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d7dbe0")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(validation_table)
    story.append(Spacer(1, 0.4 * cm))

    story.append(Paragraph("Pass % / Fail %", _H2))
    winning = int(metrics.get("winning_trades") or 0)
    losing = int(metrics.get("losing_trades") or 0)
    total = int(metrics.get("total_trades") or 0)
    pass_pct = (winning / total * 100) if total else None
    fail_pct = (losing / total * 100) if total else None
    story.append(
        Paragraph(
            "Definition: Pass % = winning trades &divide; total trades &times; 100. "
            "Fail % = losing trades &divide; total trades &times; 100. "
            "(A trade with a net P&amp;L of exactly zero counts as neither, so these need not "
            "sum to 100%.)",
            _SMALL,
        )
    )
    story.append(
        _kpi_table(
            [
                ("Pass % (Winning)", f"{pass_pct:.2f}%" if pass_pct is not None else "—"),
                ("Fail % (Losing)", f"{fail_pct:.2f}%" if fail_pct is not None else "—"),
                ("Winning Trades", str(winning)),
                ("Losing Trades", str(losing)),
                ("Total Profit (gross)", _money(metrics.get("gross_profit"))),
                ("Total Loss (gross)", _money(metrics.get("gross_loss"))),
            ]
        )
    )
    story.append(Spacer(1, 0.4 * cm))

    story.append(Paragraph("Investment vs. Returns", _H2))
    story.append(
        _kpi_table(
            [
                ("Initial Capital", _money(config.get("initial_capital"))),
                ("Final Capital", _money(metrics.get("final_capital"))),
                ("Return %", _percent(metrics.get("return_percent"))),
            ]
        )
    )

    # --- Page 3: Ratio Analysis --------------------------------------------
    story.append(PageBreak())
    story.append(Paragraph("Ratio Analysis", _TITLE))
    story.append(
        Paragraph(
            "Only ratios genuinely computable from this backtest's own real trade data are "
            "shown - none are estimated or industry-typical placeholders.",
            _BODY,
        )
    )
    story.append(Spacer(1, 0.3 * cm))
    story.append(
        _kpi_table(
            [
                ("Profit Factor", _ratio(metrics.get("profit_factor"))),
                ("Sharpe Ratio (trade-level, non-annualized)", _ratio(metrics.get("sharpe_ratio_trade_level"))),
                (
                    "Sortino Ratio (trade-level, non-annualized)",
                    _ratio(metrics.get("sortino_ratio_trade_level")),
                ),
            ],
            columns=3,
        )
    )
    story.append(Spacer(1, 0.3 * cm))
    story.append(
        Paragraph(
            "Profit Factor = gross profit &divide; gross loss. Sharpe/Sortino are computed "
            "directly from this run's own trade-level P&L series, NOT annualized (this "
            "project has no established, honest trading-day-annualization convention for an "
            "intraday-only backtest window). A Calmar ratio was considered and deliberately "
            "excluded for the same reason - see CHECKPOINT_BACKTEST-PDF-A_SUMMARY.md.",
            _SMALL,
        )
    )

    # --- Page 4 (optional): Results by Instrument --------------------------
    if sibling_results:
        story.append(PageBreak())
        story.append(Paragraph("Results by Instrument", _TITLE))
        story.append(
            Paragraph(
                "Per-instrument breakdown from the same multi-instrument historical run - "
                "NOT a sector-wise breakdown (this project has no sector/fundamental data "
                "source; confirmed directly, see the recon in "
                "CHECKPOINT_BACKTEST-PDF-A_SUMMARY.md).",
                _BODY,
            )
        )
        story.append(Spacer(1, 0.3 * cm))
        header = ["Instrument", "Net P&L", "Win Rate", "Total Trades"]
        rows = [header] + [_instrument_row(result)] + [_instrument_row(r) for r in sibling_results]
        instrument_table = Table(rows, colWidths=[5 * cm, 4 * cm, 3 * cm, 3 * cm])
        instrument_table.setStyle(
            TableStyle(
                [
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d7dbe0")),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f7f8fa")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(instrument_table)

    doc.build(story)
    return buffer.getvalue()


__all__ = ["build_backtest_report_pdf"]
