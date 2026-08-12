# src/intraday/urls.py
#
# Root URL configuration (Checkpoint 4). Only infrastructure endpoints
# exist: /healthz, /readyz, /version. No business endpoints (signals,
# orders, positions, strategies, broker) are wired here — those are added
# in later checkpoints via intraday.application.gateways once real domain
# contracts exist.
from __future__ import annotations

from django.contrib import admin
from django.urls import path

from intraday.application.gateways.health import healthz, readyz, version

urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz", healthz, name="healthz"),
    path("readyz", readyz, name="readyz"),
    path("version", version, name="version"),
]
