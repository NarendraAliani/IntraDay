# src/intraday/application/reporting/contracts.py
#
# Checkpoint 32 Part 7-8: ONE common report-metadata contract and the
# report catalogue, so no report type invents its own parallel metadata
# shape. Reuses existing canonical vocabulary wherever it already
# exists (`BacktestTrustLevel`, `DataQualityLabel`) - never a second,
# competing trust/quality enum (Part 13's explicit instruction).
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum

from intraday.domain.shared_kernel.contracts import InstrumentId, Timeframe, ensure_utc
from intraday.research.backtesting.contracts import BacktestTrustLevel, DataQualityLabel


class ReportStatus(str, Enum):
    """A report TYPE's own implementation status - "is this report kind
    buildable at all today" - distinct from `trust_level`/`quality_status`
    on an individual `ReportMetadata` instance, which describe the DATA
    a specific report was built from, not whether the report type
    exists yet. Never invented per-report-type; every report in
    `REPORT_CATALOGUE` uses exactly this enum (Part 13)."""

    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    PLANNED = "PLANNED"
    BLOCKED = "BLOCKED"
    NOT_YET_IMPLEMENTED = "NOT_YET_IMPLEMENTED"
    RESEARCH_ONLY = "RESEARCH_ONLY"


class ReportType(str, Enum):
    """The report catalogue (Part 8) - exactly the ten report kinds this
    checkpoint's brief names, no more, no fewer."""

    BACKTEST_REPORT = "BACKTEST_REPORT"
    BACKTEST_COMPARISON_REPORT = "BACKTEST_COMPARISON_REPORT"
    STRATEGY_RESEARCH_REPORT = "STRATEGY_RESEARCH_REPORT"
    MARKET_DATA_QUALITY_REPORT = "MARKET_DATA_QUALITY_REPORT"
    SIGNAL_REPORT = "SIGNAL_REPORT"
    PORTFOLIO_REPORT = "PORTFOLIO_REPORT"
    RISK_REPORT = "RISK_REPORT"
    PRODUCTION_REPORT = "PRODUCTION_REPORT"
    AUDIT_REPORT = "AUDIT_REPORT"
    SYSTEM_HEALTH_REPORT = "SYSTEM_HEALTH_REPORT"
    COMMUNICATION_DELIVERY_REPORT = "COMMUNICATION_DELIVERY_REPORT"
    DAILY_SESSION_REPORT = "DAILY_SESSION_REPORT"


@dataclass(frozen=True, slots=True)
class ReportCatalogueEntry:
    """Describes a report TYPE (not an instance) - purpose, ownership,
    and current buildability. `REPORT_CATALOGUE` below is the single,
    authoritative list; nothing else in this codebase should hand-write
    a second list of "what reports exist"."""

    report_type: ReportType
    status: ReportStatus
    purpose: str
    owner: str  # the bounded context/layer responsible for the underlying data
    required_data: str
    future_data_dependencies: str
    ui_surface: str


REPORT_CATALOGUE: tuple[ReportCatalogueEntry, ...] = (
    ReportCatalogueEntry(
        report_type=ReportType.BACKTEST_REPORT,
        status=ReportStatus.AVAILABLE,
        purpose="Present one backtest run's full result set - configuration, "
        "trades, costs, equity, validation status, trust level.",
        owner="research.backtesting",
        required_data="BacktestResult (already produced by run_backtest())",
        future_data_dependencies="none beyond what already exists",
        ui_surface="Backtesting Workbench results panel (existing)",
    ),
    ReportCatalogueEntry(
        report_type=ReportType.BACKTEST_COMPARISON_REPORT,
        status=ReportStatus.AVAILABLE,
        purpose="Compare two or more backtest results side by side, warning on "
        "cost-model/data-quality mismatches.",
        owner="research.backtesting",
        required_data="Two or more BacktestResult records",
        future_data_dependencies="none beyond what already exists",
        ui_surface="Comparison page (existing)",
    ),
    ReportCatalogueEntry(
        report_type=ReportType.STRATEGY_RESEARCH_REPORT,
        status=ReportStatus.PARTIAL,
        purpose="Summarize a strategy's overall research status across every "
        "backtest run against it (not just one run).",
        owner="research.backtesting",
        required_data="StrategyResearchStatusRecord (exists); no cross-run "
        "aggregation view exists yet",
        future_data_dependencies="a cross-run aggregation query/service",
        ui_surface="Strategy Monitor page (existing, single-run only today)",
    ),
    ReportCatalogueEntry(
        report_type=ReportType.MARKET_DATA_QUALITY_REPORT,
        status=ReportStatus.AVAILABLE,
        purpose="Show the TRADING_GRADE_BAR six-condition classification, "
        "evidence, and current SAMPLE_BAR status for the live market-data "
        "pipeline.",
        owner="control_plane.market_data_health / domain.market_data",
        required_data="docs/research/TRADING_GRADE_BAR_VALIDATION.md's findings, "
        "structured this checkpoint (market_data_quality_report.py)",
        future_data_dependencies="a persisted, continuously-updated evidence store "
        "once live WebSocket ingestion exists",
        ui_surface="Reports Overview page (new, this checkpoint)",
    ),
    ReportCatalogueEntry(
        report_type=ReportType.SIGNAL_REPORT,
        status=ReportStatus.AVAILABLE,
        purpose="Signals Generated -> Validated -> Communicated -> Execution "
        "Approved/Blocked -> Orders Submitted/Filled/Rejected, reconciled "
        "against real ledger rows so the funnel's truth is never fabricated "
        "(Checkpoint 38 Part 16).",
        owner="communication / application.services.paper_trading (via their "
        "respective persisted ledgers)",
        required_data="CommunicationLedgerRecord (Checkpoint 37) + "
        "PaperOrderRecord.signal_id (Checkpoint 36) - no dedicated Signal "
        "persistence table exists yet (see ACTIVE_PRODUCT_GAP_REGISTER.md); "
        "'signals generated/validated' is honestly derived from "
        "VALIDATED_SIGNAL communication events, not a separate signal ledger",
        future_data_dependencies="a dedicated Signal persistence table would let "
        "this report distinguish REJECTED signals (never communicated at all) "
        "from ones that were communicated - currently indistinguishable from "
        "'no signal fired'",
        ui_surface="Reports Overview page (new, this checkpoint)",
    ),
    ReportCatalogueEntry(
        report_type=ReportType.PORTFOLIO_REPORT,
        status=ReportStatus.PARTIAL,
        purpose="Multi-instrument portfolio backtest attribution and aggregate "
        "P&L/costs/equity.",
        owner="research.backtesting",
        required_data="PortfolioBacktestResult (exists, Checkpoint 28); no "
        "dedicated presentation surface beyond the raw result",
        future_data_dependencies="a dedicated portfolio report view",
        ui_surface="Reports Overview page (placeholder only, this checkpoint)",
    ),
    ReportCatalogueEntry(
        report_type=ReportType.RISK_REPORT,
        status=ReportStatus.PARTIAL,
        purpose="Risk-engine exposure/limit-utilization reporting, including "
        "risk-breach events (rejected orders and their reason codes).",
        owner="trading_engine.risk_engine",
        required_data="Checkpoint 34: a real risk-gating engine "
        "(evaluate_order_risk()/OrderRiskDecision) now exists and produces "
        "auditable APPROVED/REJECTED decisions for paper orders - no dedicated "
        "presentation surface beyond the raw decision exists yet",
        future_data_dependencies="a dedicated risk-breach report view aggregating "
        "OrderRiskDecision history",
        ui_surface="Paper Trading page (risk status only, this checkpoint)",
    ),
    ReportCatalogueEntry(
        report_type=ReportType.PRODUCTION_REPORT,
        status=ReportStatus.PLANNED,
        purpose="Live production reconciliation/P&L summaries.",
        owner="control_plane.reconciliation / domain.trade",
        required_data="no live trading exists yet - by design (this project has "
        "never placed an order)",
        future_data_dependencies="paper/live trading capability, itself gated "
        "behind RESEARCH_READY and TRADING_GRADE_BAR",
        ui_surface="Reports Overview page (placeholder only, this checkpoint)",
    ),
    ReportCatalogueEntry(
        report_type=ReportType.AUDIT_REPORT,
        status=ReportStatus.PARTIAL,
        purpose="Present the existing audit trail (configuration changes, "
        "activations) as a human-readable report.",
        owner="control_plane / domain.audit",
        required_data="AuditLogEntry-style records exist for configuration "
        "changes (Checkpoint 11+); no dedicated report assembler yet",
        future_data_dependencies="a report assembler over existing audit records",
        ui_surface="Reports Overview page (placeholder only, this checkpoint)",
    ),
    ReportCatalogueEntry(
        report_type=ReportType.SYSTEM_HEALTH_REPORT,
        status=ReportStatus.PARTIAL,
        purpose="Aggregate operational health (market-data connection, provider "
        "status) into one report.",
        owner="control_plane.market_data_health",
        required_data="MarketDataHealthStatus exists; no cross-subsystem "
        "aggregation report exists yet",
        future_data_dependencies="a report assembler once more subsystems exist "
        "to aggregate (risk engine, order management, etc.)",
        ui_surface="Reports Overview page (placeholder only, this checkpoint)",
    ),
    ReportCatalogueEntry(
        report_type=ReportType.COMMUNICATION_DELIVERY_REPORT,
        status=ReportStatus.AVAILABLE,
        purpose="Was a signal actually communicated? Aggregate delivery "
        "outcomes (sent/failed/skipped-duplicate) by channel and template, "
        "distinguishing communication truth from execution truth - a signal "
        "can be fully communicated whether or not any order ever resulted.",
        owner="communication / infrastructure.persistence.communication_ledger_repository",
        required_data="CommunicationLedgerRecord (Checkpoint 37 Part 7) - real "
        "delivery attempts, not placeholders",
        future_data_dependencies="none beyond what already exists",
        ui_surface="Reports Overview page (new, this checkpoint)",
    ),
    ReportCatalogueEntry(
        report_type=ReportType.DAILY_SESSION_REPORT,
        status=ReportStatus.AVAILABLE,
        purpose="Checkpoint 64.10: 'what happened today?' - one summary "
        "spanning signals (now backed by the real SignalRecord ledger, "
        "Checkpoint 62.x/64.9's Signal Operations Center enrichment), risk "
        "outcomes, paper orders/positions, and communication delivery, "
        "without requiring the operator to inspect multiple screens.",
        owner="infrastructure.persistence.signal_repository / "
        "communication_ledger_repository / paper_ledger_repository (all "
        "pre-existing) - this report only aggregates, never a new engine",
        required_data="SignalRecord (Checkpoint 62.x), TradePlanRecord "
        "(Checkpoint 64.7), CommunicationLedgerRecord (Checkpoint 37), "
        "PaperOrderRecord/Position (Checkpoint 35/36) - all real, all "
        "already persisted by the time this report runs",
        future_data_dependencies="a persisted per-session boundary marker "
        "(currently a session is identified by calendar date, via "
        "signal_timestamp/created_at range, not a dedicated Session row) "
        "would make multi-session-per-day scenarios unambiguous",
        ui_surface="Reports Overview page (new, this checkpoint - backend "
        "endpoint only, no dedicated frontend screen yet)",
    ),
)


@dataclass(frozen=True, slots=True)
class ReportMetadata:
    """The ONE shared metadata shape every report instance carries,
    regardless of `report_type` - Part 7's explicit "do not create
    duplicated metadata models in each report type." Fields that do not
    apply to a given report type are simply `None` (e.g. `strategy_identity`
    on a `MARKET_DATA_QUALITY_REPORT`), never a report-type-specific
    subclass with a different shape."""

    report_id: str
    report_type: ReportType
    title: str
    generated_at: datetime
    generated_by: str
    data_source: str
    data_identity: str
    strategy_identity: str | None
    timeframe: Timeframe | None
    instrument_universe: tuple[InstrumentId, ...]
    trust_level: BacktestTrustLevel | None
    quality_status: DataQualityLabel | None
    report_status: ReportStatus
    version: str
    period_start: date | None
    period_end: date | None

    def __post_init__(self) -> None:
        ensure_utc(self.generated_at, field_name="ReportMetadata.generated_at")
        if not self.report_id:
            raise ValueError("ReportMetadata.report_id must not be empty")
        if not self.title:
            raise ValueError("ReportMetadata.title must not be empty")
        if (
            self.period_start is not None
            and self.period_end is not None
            and self.period_start > self.period_end
        ):
            raise ValueError("ReportMetadata.period_start must not be after period_end")
