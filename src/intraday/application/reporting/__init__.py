# src/intraday/application/reporting/__init__.py
#
# Checkpoint 32 Part 7-9: reporting foundation. Application-layer, not a
# new bounded context - `.importlinter` contract 3 ("Application ->
# bounded contexts -> domain layering") already permits the application
# layer to read from multiple bounded contexts (research.backtesting,
# control_plane, etc.) and compose them, which is exactly what report
# assembly is. No new contract entry is needed; this module is reached
# the same way `application.services.backtesting` already is.
#
# Re-exports the public surface so callers (API views, future report
# generators) import from `application.reporting`, never reaching into
# individual submodules - mirrors `research.backtesting.__init__`'s own
# single-re-export-surface discipline (Checkpoint 27/30).
from __future__ import annotations

from intraday.application.reporting.contracts import (
    REPORT_CATALOGUE,
    ReportCatalogueEntry,
    ReportMetadata,
    ReportStatus,
    ReportType,
)

__all__ = [
    "REPORT_CATALOGUE",
    "ReportCatalogueEntry",
    "ReportMetadata",
    "ReportStatus",
    "ReportType",
]
