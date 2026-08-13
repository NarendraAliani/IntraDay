# File: src/intraday/infrastructure/api/audit_urls.py
#
# URL routes for the read-only audit API, mounted at /api/v1/audit/ by
# the root URLconf. Checkpoint 12 added risk-configuration; Checkpoint
# 13 added universe and strategy-version, completing the same pattern
# for all three configuration resources.
from __future__ import annotations

from django.urls import path

from intraday.infrastructure.api import audit_views

app_name = "audit_api"

urlpatterns = [
    path(
        "risk-configuration/<str:configuration_id>/",
        audit_views.list_risk_configuration_audit,
        name="risk-configuration-audit",
    ),
    path(
        "universe/<str:universe_id>/",
        audit_views.list_universe_audit,
        name="universe-audit",
    ),
    path(
        "strategy/<str:strategy_id>/",
        audit_views.list_strategy_version_audit,
        name="strategy-audit",
    ),
]
