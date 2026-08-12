# File: src/intraday/infrastructure/api/urls.py
#
# URL routes for the Checkpoint 8 configuration API, mounted at
# /api/v1/config/ by the root URLconf (intraday/urls.py). Versioning
# strategy: a single "/api/v1/" prefix (Checkpoint 8 §14) — no multiple
# API versions introduced.
#
# Route ordering matters: each resource's "active/" literal path is
# declared BEFORE its "<version>/" pattern, so a request for
# ".../active/" is never captured by the more general version pattern.
from __future__ import annotations

from django.urls import path

from intraday.infrastructure.api import risk_views, strategy_views, universe_views

app_name = "config_api"

urlpatterns = [
    # --- Risk configuration ---------------------------------------------
    path("risk/<str:configuration_id>/", risk_views.list_versions, name="risk-list"),
    path("risk/<str:configuration_id>/active/", risk_views.get_active, name="risk-active"),
    path("risk/<str:configuration_id>/<str:version>/", risk_views.get_version, name="risk-version"),
    path(
        "risk/<str:configuration_id>/<str:version>/activate/",
        risk_views.activate,
        name="risk-activate",
    ),
    # --- Universe --------------------------------------------------------
    path("universe/<str:universe_id>/", universe_views.list_versions, name="universe-list"),
    path("universe/<str:universe_id>/active/", universe_views.get_active, name="universe-active"),
    path(
        "universe/<str:universe_id>/<str:version>/",
        universe_views.get_version,
        name="universe-version",
    ),
    path(
        "universe/<str:universe_id>/<str:version>/activate/",
        universe_views.activate,
        name="universe-activate",
    ),
    # --- Strategy version --------------------------------------------------
    path("strategy/<str:strategy_id>/", strategy_views.list_versions, name="strategy-list"),
    path("strategy/<str:strategy_id>/active/", strategy_views.get_active, name="strategy-active"),
    path(
        "strategy/<str:strategy_id>/<str:specification_version>/<str:code_version>/"
        "<str:configuration_version>/",
        strategy_views.get_version,
        name="strategy-version",
    ),
    path(
        "strategy/<str:strategy_id>/<str:specification_version>/<str:code_version>/"
        "<str:configuration_version>/activate/",
        strategy_views.activate,
        name="strategy-activate",
    ),
]
