# src/intraday/urls.py
#
# Root URL configuration. Infrastructure endpoints (/healthz, /readyz,
# /version) were established at Checkpoint 4. Checkpoint 8 adds the first
# business API — the configuration read/activate resources — mounted
# under /api/v1/config/, delegating to infrastructure/api/urls.py.
# Checkpoint 11 adds the authentication API — login/logout/session —
# mounted under /api/v1/auth/, delegating to
# infrastructure/api/auth_urls.py. Mounted before /api/v1/config/ since
# it is the boundary that now protects it. Checkpoint 12 adds the
# read-only audit API under /api/v1/audit/, delegating to
# infrastructure/api/audit_urls.py.
from __future__ import annotations

from django.contrib import admin
from django.urls import include, path

from intraday.application.gateways.health import healthz, readyz, version

urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz", healthz, name="healthz"),
    path("readyz", readyz, name="readyz"),
    path("version", version, name="version"),
    path("api/v1/auth/", include("intraday.infrastructure.api.auth_urls")),
    path("api/v1/config/", include("intraday.infrastructure.api.urls")),
    path("api/v1/audit/", include("intraday.infrastructure.api.audit_urls")),
    # Checkpoint 64.82: the read-only correlation query surface - a read
    # model over relationships 64.81 already persists. No new table, no
    # write path, no second source of truth.
    path("api/v1/correlation/", include("intraday.infrastructure.api.correlation_urls")),
    # Checkpoint 64.83: the read-only archive + reconciliation query
    # surface - a read model over the 64.73 archive projection and the
    # 64.79 reconciliation comparator. No new table, no write path, no
    # second archive and no second reconciliation engine.
    path("api/v1/market-data/", include("intraday.infrastructure.api.market_data_archive_urls")),
]
