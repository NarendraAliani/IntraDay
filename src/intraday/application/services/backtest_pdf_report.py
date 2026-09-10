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
#     a multi-instrument run.
#   - Ratio Analysis is `profit_factor`/`sharpe_ratio_trade_level`/
#     `sortino_ratio_trade_level` ONLY - all three are already fully
#     computed fields on `result["metrics"]` (see
#     `research/backtesting/serialization.py::to_json_dict()`), zero
#     derivation needed. A Calmar ratio was considered and deliberately
#     EXCLUDED: it requires an ANNUALIZED return, and this project has
#     no established, honest trading-day-annualization convention for
#     an intraday-only backtest window. Named explicitly rather than
#     silently omitted - see CHECKPOINT_BACKTEST-PDF-A_SUMMARY.md.
#
# CHARTS: real vector line charts (reportlab's own
# `graphics.charts.lineplots.LinePlot`), built from the SAME
# `mark_to_market_curve` the frontend's `EquityCurveChart`/
# `DrawdownChart` already render - not a second, invented data series.
#
# CHECKPOINT-BACKTEST-PDF-C ADDS:
#   Issue 1 - a full per-trade ledger page (Trade #, Date, Entry Time/
#   Rate, Exit Time/Rate, Direction, Quantity, Total, P&L amount/%).
#   Every field is either copied verbatim from the SAME trade dicts
#   `TradeTable` (`BacktestingWorkbenchPage.tsx`) already renders, or
#   an HONESTLY-STATED simple derivation of them:
#     - "Total" = quantity x entry_price (the position's own entry
#       value) - not a field on the trade dict itself, but a one-line
#       arithmetic product of two fields that already are, stated as
#       such directly in the PDF's own column note.
#     - "P&L %" = net_pnl / Total x 100 - the trade's own net P&L
#       relative to its own entry position value, likewise stated
#       explicitly.
#   Paginated at 15 rows/page - reused verbatim from `TradeTable`'s
#   own `TRADES_PER_PAGE` constant, not a new, independently-chosen
#   number.
#
#   Issue 2 - the real layout bug the operator found (a long
#   skip-reason label overlapping the adjacent column's own value,
#   e.g. "...e-direction, position already open) 364"): EVERY table
#   cell that can ever hold operator-length text is now a `Paragraph`
#   (which reportlab genuinely WORD-WRAPS within its own column width)
#   instead of a bare Python `str` (which a reportlab `Table` does
#   NOT wrap - it draws past the cell's own right edge, overlapping
#   whatever is drawn next.  This was confirmed as the real, exact
#   root cause by rendering the pre-fix PDF from the same long-label
#   fixture this checkpoint's own test uses and visually finding the
#   overlap - not assumed.) The footer was ALSO switched from raw,
#   un-wrapped `canvas.drawString()` calls to a single wrapped
#   `Paragraph`, so a long disclaimer sentence grows the footer
#   downward within its own reserved band instead of silently
#   overflowing sideways past the page margin.
#
#   Issue 3 - `?run_id=` mode now includes every scanned instrument's
#   OWN complete report (Pages 1-4, trade ledger included) in ONE
#   file, not just a one-line summary row per sibling. Each
#   instrument's own section gets its OWN footer (that instrument's
#   own data-quality/cost-model facts, never another instrument's) via
#   a dedicated reportlab `PageTemplate` per instrument, switched with
#   `NextPageTemplate` - never one shared, potentially-wrong footer
#   stamped across every instrument's own pages.
#
# CHECKPOINT-BACKTEST-PDF-D ADDS:
#   Issue 1 - every rendered timestamp (Trade Ledger Entry/Exit Time,
#   the "Generated" line, the Configuration date range) is now
#   converted to IST (Asia/Kolkata) before rendering - the PDF is a
#   presentation boundary, and this project's own established
#   convention (`Bar.timestamp`/every derived backtest datetime is
#   stored/serialized in UTC; conversion happens only at the
#   presentation boundary) was being violated: the PDF was rendering
#   raw UTC. Reuses the SAME Asia/Kolkata offset every other
#   presentation boundary in this project already uses (see
#   `_INDIA_STANDARD_TIME` above), not a new convention.
#
#   Issue 2 - the old full per-instrument DIVIDER PAGE (operator
#   confirmed: wasted a whole page for one line of text) is replaced
#   with a running header BANNER ("Instrument N of M - <symbol>") at
#   the TOP of that instrument's own first content page - the combined
#   file stays just as navigable (the banner is still a clear, single-
#   glance visual break) without the wasted page.
from __future__ import annotations

import io
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

# CHECKPOINT-BACKTEST-PDF-D Issue 1: this project's own established
# convention - `Bar.timestamp`/every derived backtest timestamp is
# stored/serialized in UTC; IST conversion happens ONLY at the
# presentation boundary (see `calendar.py::INDIA_STANDARD_TIME`,
# `historical_client.py::_INDIA_STANDARD_TIME`, and the frontend's own
# `LiveMarketDataMonitor.tsx`/`LiveScannerConsole.tsx`
# `toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })` pattern). The
# PDF report is a presentation boundary and was found to render raw
# (UTC) times - fixed here by converting every rendered timestamp to
# IST before display, the same offset the rest of the project already
# uses, not a new convention.
_INDIA_STANDARD_TIME = ZoneInfo("Asia/Kolkata")

_PAGE_SIZE = A4
_MARGIN = 1.8 * cm
_FOOTER_HEIGHT = 3.4 * cm
# Reused verbatim from `TradeTable`'s own `TRADES_PER_PAGE` constant
# (`BacktestingWorkbenchPage.tsx`) - the same per-page row limit the
# on-screen trade ledger already uses, not a second, independently
# chosen number.
_TRADES_PER_PAGE = 15

_styles = getSampleStyleSheet()
_TITLE = ParagraphStyle("ReportTitle", parent=_styles["Title"], fontSize=16)
_H2 = ParagraphStyle("ReportH2", parent=_styles["Heading2"], spaceBefore=10, spaceAfter=4)
_BODY = _styles["BodyText"]
_SMALL = ParagraphStyle("Small", parent=_styles["BodyText"], fontSize=8, leading=10)
_CELL = ParagraphStyle("Cell", parent=_styles["BodyText"], fontSize=8, leading=10)
_CELL_LABEL = ParagraphStyle(
    "CellLabel", parent=_CELL, textColor=colors.HexColor("#5b6572")
)
_TABLE_TINY = ParagraphStyle("TableTiny", parent=_styles["BodyText"], fontSize=7, leading=8.5)
_TABLE_HEADER = ParagraphStyle(
    "TableHeader", parent=_TABLE_TINY, fontName="Helvetica-Bold", textColor=colors.HexColor("#1c2530")
)
_FOOTER_STYLE = ParagraphStyle(
    "Footer", parent=_styles["BodyText"], fontSize=6.5, leading=8.5,
    textColor=colors.HexColor("#5b6572"),
)
# CHECKPOINT-BACKTEST-PDF-D Issue 2: a running header BANNER at the top
# of each instrument's own first content page, replacing the old
# full divider PAGE the operator confirmed wasted a page for one line.
_RUNNING_HEADER = ParagraphStyle(
    "RunningHeader", parent=_styles["BodyText"], fontSize=10, leading=13,
    fontName="Helvetica-Bold", textColor=colors.white,
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


def _parse_ist(raw: object) -> datetime | None:
    """Parses an ISO 8601 timestamp string (`to_json_dict()`'s own
    `.isoformat()` calls - always UTC per this project's own
    established convention, see this module's own header comment) and
    converts it to IST. Returns `None` honestly if the value is
    missing or unparseable - never a fabricated timestamp."""
    if not raw:
        return None
    text = str(raw)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(_INDIA_STANDARD_TIME)


def _split_timestamp(raw: object) -> tuple[str, str]:
    """(date, time) from an ISO timestamp string, converted to IST
    (CHECKPOINT-BACKTEST-PDF-D Issue 1 - the PDF is a presentation
    boundary and must convert, same as `_format_ist_datetime()` below
    and the frontend's own `Asia/Kolkata` convention). Falls back to
    the raw string honestly if it is ever not parseable, never a
    fabricated date."""
    if not raw:
        return "—", "—"
    ist = _parse_ist(raw)
    if ist is None:
        return str(raw), ""
    return ist.date().isoformat(), ist.strftime("%H:%M:%S")


def _format_ist_datetime(raw: object) -> str:
    """A single-string IST timestamp (date + time), used for the
    report's "Generated" line and the configuration date range -
    CHECKPOINT-BACKTEST-PDF-D Issue 1."""
    if not raw:
        return "—"
    ist = _parse_ist(raw)
    if ist is None:
        return str(raw)
    return ist.strftime("%Y-%m-%d %H:%M:%S") + " IST"


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


def _footer_page_callback(result: dict[str, object]):
    """CHECKPOINT-BACKTEST-PDF-C Issue 2: the footer text is now a
    single wrapped `Paragraph` (real word-wrap within the reserved
    footer band) instead of raw, un-wrapped `canvas.drawString()`
    calls per line - a long disclaimer sentence grows the footer
    downward within its own space instead of silently running past the
    page's own right margin. Returns a closure bound to THIS result's
    own footer facts (Issue 3: each instrument's own pages get their
    own, correct footer, never another instrument's)."""
    footer_text = "<br/>".join(_footer_lines(result))
    footer_paragraph = Paragraph(footer_text, _FOOTER_STYLE)

    def _draw_footer(canvas, doc) -> None:  # noqa: ANN001 - reportlab callback signature
        canvas.saveState()
        divider_y = _MARGIN + _FOOTER_HEIGHT - 0.3 * cm
        canvas.setStrokeColor(colors.HexColor("#d7dbe0"))
        canvas.line(_MARGIN, divider_y, _PAGE_SIZE[0] - _MARGIN, divider_y)
        avail_width = _PAGE_SIZE[0] - 2 * _MARGIN
        _, height = footer_paragraph.wrap(avail_width, _FOOTER_HEIGHT)
        footer_paragraph.drawOn(canvas, _MARGIN, divider_y - 0.15 * cm - height)
        canvas.restoreState()

    return _draw_footer


def _kpi_table(rows: list[tuple[str, str]], *, columns: int = 3) -> Table:
    """A simple KPI grid, mirroring the visual intent of the frontend's
    own `.backtest-results__kpi`/`.dashboard__grid` card pattern
    (label above value) in the one layout PDF table cells can actually
    express - a grid of label/value pairs, `columns` wide."""
    cells: list[list[Paragraph]] = []
    row: list[Paragraph] = []
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


def _label_value_table(rows: list[list[str]], *, label_width: float) -> Table:
    """CHECKPOINT-BACKTEST-PDF-C Issue 2 fix: every cell is now a
    `Paragraph` (wraps within its own column) - the exact class of bug
    the operator found (a plain `str` cell does NOT wrap in a
    reportlab `Table`; long text overflows into the next column and
    visually overlaps whatever is drawn there)."""
    wrapped_rows = [
        [Paragraph(str(label), _CELL_LABEL), Paragraph(str(value), _CELL)] for label, value in rows
    ]
    table = Table(wrapped_rows, colWidths=[label_width, None])
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d7dbe0")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
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
    order) - the underlying real timestamps are shown in the trade
    ledger instead of being re-derived as chart tick labels here."""
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


def _instrument_row(result: dict[str, object]) -> list[Paragraph]:
    config = result.get("configuration", {}) or {}
    metrics = result.get("metrics", {}) or {}
    return [
        Paragraph(str(config.get("instrument_id", "—")), _TABLE_TINY),
        Paragraph(_money(metrics.get("net_pnl")), _TABLE_TINY),
        Paragraph(_percent(metrics.get("win_rate_percent")), _TABLE_TINY),
        Paragraph(str(metrics.get("total_trades", "—")), _TABLE_TINY),
    ]


def _trade_ledger_row(index: int, trade: dict[str, object]) -> list[Paragraph]:
    """CHECKPOINT-BACKTEST-PDF-C Issue 1: every value here is copied
    verbatim from the SAME trade dict `TradeTable` already renders,
    except "Total" and "P&L %", which are honest, stated one-line
    derivations of two already-present fields each (see this module's
    own header comment)."""
    entry_date, entry_time = _split_timestamp(trade.get("entry_timestamp"))
    _, exit_time = _split_timestamp(trade.get("exit_timestamp"))
    direction = "Long" if trade.get("direction") == "BULLISH" else "Short"

    total_value: Decimal | None
    try:
        total_value = Decimal(str(trade.get("quantity"))) * Decimal(str(trade.get("entry_price")))
    except (InvalidOperation, ValueError, TypeError):
        total_value = None

    pnl_percent: str
    net_pnl = trade.get("net_pnl")
    if total_value and total_value != 0 and net_pnl is not None:
        try:
            pnl_percent = _percent(Decimal(str(net_pnl)) / total_value * 100)
        except (InvalidOperation, ValueError):
            pnl_percent = "—"
    else:
        pnl_percent = "—"

    cells = [
        str(index),
        entry_date,
        entry_time,
        _money(trade.get("entry_price")),
        exit_time,
        _money(trade.get("exit_price")),
        direction,
        str(trade.get("quantity", "—")),
        _money(total_value) if total_value is not None else "—",
        _money(net_pnl),
        pnl_percent,
    ]
    return [Paragraph(cell, _TABLE_TINY) for cell in cells]


_TRADE_LEDGER_HEADER = [
    "#", "Date", "Entry Time", "Entry Rate", "Exit Time", "Exit Rate",
    "Direction", "Qty", "Total", "P&L", "P&L %",
]
_TRADE_LEDGER_COL_WIDTHS = [
    0.7 * cm, 1.8 * cm, 1.7 * cm, 1.9 * cm, 1.7 * cm, 1.9 * cm,
    1.3 * cm, 1.2 * cm, 2.1 * cm, 1.9 * cm, 1.4 * cm,
]


def _trade_ledger_table(rows: list[list[Paragraph]]) -> Table:
    header = [Paragraph(label, _TABLE_HEADER) for label in _TRADE_LEDGER_HEADER]
    table = Table([header] + rows, colWidths=_TRADE_LEDGER_COL_WIDTHS, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d7dbe0")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f7f8fa")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def _build_instrument_story(
    result: dict[str, object], *, running_header: tuple[int, int] | None = None
) -> list[object]:
    """Builds ONE instrument's own complete report content (Pages 1-3
    + the trade ledger) - the exact same content every single-
    instrument PDF already had, extracted into its own function so
    CHECKPOINT-BACKTEST-PDF-C Issue 3's multi-instrument mode can call
    it once per scanned instrument, never a duplicated/parallel
    per-instrument rendering path.

    `running_header` (CHECKPOINT-BACKTEST-PDF-D Issue 2): optional
    `(index, total)` - when given, a "Instrument N of M" running
    header banner is rendered at the TOP of this instrument's own
    first content page (in place of the old full divider PAGE, which
    the operator confirmed wasted a page for a single line of text)."""
    config = result.get("configuration", {}) or {}
    metrics = result.get("metrics", {}) or {}
    validation = result.get("validation", {}) or {}
    mtm_curve = result.get("mark_to_market_curve", []) or []
    trades = result.get("trades", []) or []

    story: list[object] = []

    if running_header is not None:
        index, total = running_header
        instrument_id = str(config.get("instrument_id", "—"))
        story.append(
            Table(
                [[Paragraph(f"Instrument {index} of {total} &mdash; {instrument_id}", _RUNNING_HEADER)]],
                colWidths=[_PAGE_SIZE[0] - 2 * _MARGIN],
                style=TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#1c2530")),
                        ("LEFTPADDING", (0, 0), (-1, -1), 8),
                        ("TOPPADDING", (0, 0), (-1, -1), 5),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                    ]
                ),
            )
        )
        story.append(Spacer(1, 0.3 * cm))

    # --- Page: Summary ------------------------------------------------
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
            f"Generated: {_format_ist_datetime(result.get('generated_at'))}",
            _SMALL,
        )
    )
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph("Configuration", _H2))
    story.append(
        _label_value_table(
            [
                ["Timeframe", str(config.get("timeframe", "—"))],
                [
                    "Date range",
                    f"{_format_ist_datetime(config.get('start'))} to "
                    f"{_format_ist_datetime(config.get('end'))}",
                ],
                ["Position sizing", str(config.get("position_sizing_mode", "—"))],
                ["Position size value", str(config.get("position_size_value", "—"))],
                ["Initial capital", _money(config.get("initial_capital"))],
                ["Final capital", _money(metrics.get("final_capital"))],
                ["Net P&L", _money(metrics.get("net_pnl"))],
                ["Return %", _percent(metrics.get("return_percent"))],
            ],
            label_width=5.5 * cm,
        )
    )
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
                    "Equity Curve (mark-to-market)", equity_values,
                    width=chart_width, height=4.5 * cm, color=colors.HexColor("#2f7d4f"),
                ),
                _curve_chart(
                    "Drawdown Curve (%)", drawdown_values,
                    width=chart_width, height=4.5 * cm, color=colors.HexColor("#c0392b"),
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

    # --- Page: Signal/Trade breakdown ----------------------------------
    story.append(PageBreak())
    story.append(Paragraph("Signal / Trade Breakdown", _TITLE))
    story.append(Paragraph("Signals and Trades", _H2))
    story.append(
        _label_value_table(
            [
                ["Signals Generated", str(validation.get("signal_count", "—"))],
                ["Trades Taken", str(validation.get("trade_count", "—"))],
                [
                    "Skipped Signals (same-direction, position already open)",
                    str(validation.get("skipped_signals", "—")),
                ],
                ["Rejected Trades (insufficient capital)", str(validation.get("rejected_trades", "—"))],
                ["Warm-up Bars", str(validation.get("warmup_bars", "—"))],
                ["Data Gaps", str(validation.get("data_gaps_note", "—"))],
            ],
            label_width=9 * cm,
        )
    )
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

    # --- Page: Ratio Analysis -------------------------------------------
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

    # --- Page(s): Trade Ledger (CHECKPOINT-BACKTEST-PDF-C Issue 1) -----
    story.append(PageBreak())
    story.append(Paragraph("Trade Ledger", _TITLE))
    story.append(
        Paragraph(
            "Every field below is copied directly from this backtest's own real trade "
            "records, except \"Total\" (= Qty &times; Entry Rate - this trade's own position "
            "value at entry) and \"P&amp;L %\" (= P&amp;L &divide; Total &times; 100) - both "
            "simple, stated arithmetic over already-computed fields, never a new computation. "
            "Entry/Exit Time and the Date column are shown in IST (Asia/Kolkata).",
            _SMALL,
        )
    )
    story.append(Spacer(1, 0.2 * cm))
    if not trades:
        story.append(Paragraph("No trades were taken in this backtest.", _BODY))
    else:
        for page_start in range(0, len(trades), _TRADES_PER_PAGE):
            page_trades = trades[page_start : page_start + _TRADES_PER_PAGE]
            rows = [
                _trade_ledger_row(page_start + i + 1, trade)
                for i, trade in enumerate(page_trades)
            ]
            story.append(_trade_ledger_table(rows))
            if page_start + _TRADES_PER_PAGE < len(trades):
                story.append(PageBreak())

    return story


def build_backtest_report_pdf(
    result: dict[str, object], *, sibling_results: list[dict[str, object]] | None = None
) -> bytes:
    """Builds the full PDF for one backtest result.

    `sibling_results` (optional): every OTHER instrument's own
    `BacktestResult` from the SAME historical multi-instrument run
    (resolved by the caller via `result_backtest_ids` on the run's own
    `DjangoBacktestRunRepository` row - never a second universe-
    resolution mechanism).

    When `sibling_results` is empty/`None` (the single-instrument
    case), the output is EXACTLY what it always was: one instrument's
    own complete report, unchanged from before CHECKPOINT-BACKTEST-PDF-C.

    When `sibling_results` is non-empty (CHECKPOINT-BACKTEST-PDF-C
    Issue 3), the output is a "Results by Instrument" index page
    followed by EVERY scanned instrument's own complete report in
    sequence (this result first, then each sibling), each behind its
    own clear divider page and with its own correct, per-instrument
    footer - never just a one-line summary row per sibling."""
    buffer = io.BytesIO()

    all_results = [result] + list(sibling_results or [])
    is_multi = len(all_results) > 1

    frame = Frame(
        _MARGIN,
        _MARGIN + _FOOTER_HEIGHT,
        _PAGE_SIZE[0] - 2 * _MARGIN,
        _PAGE_SIZE[1] - 2 * _MARGIN - _FOOTER_HEIGHT,
        id="body",
    )
    # One PageTemplate PER INSTRUMENT, each with its OWN footer closure
    # bound to that instrument's own data-quality/cost-model facts -
    # switched via `NextPageTemplate` right before that instrument's
    # own divider/content, so every page's footer is always correct
    # for the instrument it actually belongs to.
    page_templates = [
        PageTemplate(id=f"instrument-{i}", frames=[frame], onPage=_footer_page_callback(r))
        for i, r in enumerate(all_results)
    ]

    config = result.get("configuration", {}) or {}
    doc = BaseDocTemplate(
        buffer,
        pagesize=_PAGE_SIZE,
        pageTemplates=page_templates,
        title=f"Backtest Report - {config.get('strategy_id', '')} on {config.get('instrument_id', '')}",
    )

    story: list[object] = [NextPageTemplate("instrument-0")]

    if is_multi:
        story.append(Paragraph("Multi-Instrument Backtest Report", _TITLE))
        story.append(
            Paragraph(
                f"{len(all_results)} instruments from the same historical run - the complete, "
                "multi-page report for EVERY scanned instrument is included below in sequence, "
                "not only a summary row.",
                _BODY,
            )
        )
        story.append(Spacer(1, 0.3 * cm))
        story.append(Paragraph("Results by Instrument", _H2))
        story.append(
            Paragraph(
                "NOT a sector-wise breakdown (this project has no sector/fundamental data "
                "source; confirmed directly, see the recon in "
                "CHECKPOINT_BACKTEST-PDF-A_SUMMARY.md).",
                _SMALL,
            )
        )
        story.append(Spacer(1, 0.2 * cm))
        header = [Paragraph(h, _TABLE_HEADER) for h in ["Instrument", "Net P&L", "Win Rate", "Total Trades"]]
        rows = [header] + [_instrument_row(r) for r in all_results]
        instrument_table = Table(rows, colWidths=[5 * cm, 4 * cm, 3 * cm, 3 * cm])
        instrument_table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d7dbe0")),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f7f8fa")),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(instrument_table)
        story.append(PageBreak())

    for i, one_result in enumerate(all_results):
        # `NextPageTemplate` only takes effect on the NEXT page break
        # AFTER it is processed - it must therefore be appended BEFORE
        # this instrument's own leading `PageBreak()` (i > 0), not
        # after, or that leading break (and the content drawn on the
        # page it creates) would still render with the PREVIOUS
        # instrument's template/footer. A real off-by-one bug found
        # and fixed here directly (CHECKPOINT-BACKTEST-PDF-C), confirmed
        # via a real generated PDF's own per-page footer text before
        # this fix.
        story.append(NextPageTemplate(f"instrument-{i}"))
        if i > 0:
            story.append(PageBreak())
        # CHECKPOINT-BACKTEST-PDF-D Issue 2: no more separate divider
        # PAGE - a running header banner is rendered at the top of
        # this instrument's own first content page instead (see
        # `_build_instrument_story()`'s own `running_header` param).
        running_header = (i + 1, len(all_results)) if is_multi else None
        story.extend(_build_instrument_story(one_result, running_header=running_header))

    doc.build(story)
    return buffer.getvalue()


__all__ = ["build_backtest_report_pdf"]
