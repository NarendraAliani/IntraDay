# src/intraday/urls.py
#
# Root URL configuration. Infrastructure endpoints (/healthz, /readyz,
# /version) were established at Checkpoint 4. Checkpoint 8 adds the first
# business API — the configuration read/activate resources — mounted
# under /api/v1/config/, delegating to infrastructure/api/urls.py.
# Checkpoint 11 adds the authentication API — login/logout/session —
# mounted under /api/v1/auth/, delegating to
# infrastructure/api/auth_urls.py. Mounted before /api/v1/config/ since
# it is the boundary that now protects it.
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
]
