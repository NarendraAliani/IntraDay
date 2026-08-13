# File: src/intraday/infrastructure/api/audit_urls.py
#
# URL routes for the Checkpoint 12 audit read API, mounted at
# /api/v1/audit/ by the root URLconf. Scope: risk-configuration
# activation events only (see audit_views.py).
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
]
