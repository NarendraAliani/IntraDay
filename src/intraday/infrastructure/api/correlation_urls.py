# File: src/intraday/infrastructure/api/correlation_urls.py
#
# URL routes for the Checkpoint 64.82 read-only correlation query
# surface, mounted at /api/v1/correlation/ by the root URLconf -
# mirroring exactly how /api/v1/audit/ (audit_urls.py) is mounted.
#
# A separate module rather than more entries in `api/urls.py` for the
# same reason the audit API is separate: this is its own top-level
# resource with its own prefix, not another /api/v1/config/ resource.
from __future__ import annotations

from django.urls import path

from intraday.infrastructure.api import correlation_views

app_name = "correlation_api"

urlpatterns = [
    # `<str:...>` matches any non-slash run, which is exactly right for
    # the timestamp-shaped `scan_run_id` (an ISO-8601 string containing
    # `:`, `-`, `.` and possibly `+`, but never `/`). The id is used
    # verbatim, never parsed or normalised.
    path(
        "runs/<str:scan_run_id>/signals/",
        correlation_views.scan_run_signals,
        name="correlation-scan-run-signals",
    ),
    path(
        "signals/<str:signal_id>/trace/",
        correlation_views.signal_trace,
        name="correlation-signal-trace",
    ),
    # Identity tuple ordered exactly as the existing
    # `strategy-engine-configuration-detail` route orders it, so the two
    # URLs read the same way.
    path(
        "strategies/<str:strategy_id>/configurations/"
        "<str:specification_version>/<str:code_version>/<str:configuration_version>/trace/",
        correlation_views.strategy_configuration_trace,
        name="correlation-strategy-configuration-trace",
    ),
    path(
        "trades/<str:trade_id>/trace/",
        correlation_views.trade_trace,
        name="correlation-trade-trace",
    ),
    # Checkpoint 64.89: the read-only historical research report -
    # traceability coverage, feature/outcome, feature interaction, symbol
    # robustness, time-of-day. Built entirely on the traversal above.
    path(
        "research/report/",
        correlation_views.research_report,
        name="correlation-research-report",
    ),
]
