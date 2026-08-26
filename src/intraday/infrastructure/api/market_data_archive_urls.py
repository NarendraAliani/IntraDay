# File: src/intraday/infrastructure/api/market_data_archive_urls.py
#
# URL routes for the Checkpoint 64.83 read-only archive / reconciliation
# query surface, mounted at /api/v1/market-data/ by the root URLconf -
# mirroring exactly how /api/v1/correlation/ (correlation_urls.py, 64.82)
# and /api/v1/audit/ (audit_urls.py) are mounted.
#
# `<str:trading_date>` rather than `<slug>` or a date converter: the view
# parses and VALIDATES the date itself so that a malformed date returns a
# typed 400 with a message naming the expected format, instead of a bare
# routing 404 that would be indistinguishable from "this date has no
# archived data" - two answers a caller must be able to tell apart.
from __future__ import annotations

from django.urls import path

from intraday.infrastructure.api import market_data_archive_views

app_name = "market_data_archive_api"

urlpatterns = [
    path(
        "archive/<str:trading_date>/",
        market_data_archive_views.archive_day,
        name="market-data-archive-day",
    ),
    path(
        "reconciliation/<str:trading_date>/",
        market_data_archive_views.reconciliation_day,
        name="market-data-reconciliation-day",
    ),
]
