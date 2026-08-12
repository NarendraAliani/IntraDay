# File: src/intraday/infrastructure/api/auth_urls.py
#
# URL routes for the Checkpoint 11 authentication API, mounted at
# /api/v1/auth/ by the root URLconf (intraday/urls.py). Kept in its own
# urls module, separate from infrastructure/api/urls.py's configuration
# routes, since authentication is a distinct concern from the
# configuration resource API (Checkpoint 8) it protects.
from __future__ import annotations

from django.urls import path

from intraday.infrastructure.api import auth_views

app_name = "auth_api"

urlpatterns = [
    path("login/", auth_views.login_view, name="login"),
    path("logout/", auth_views.logout_view, name="logout"),
    path("session/", auth_views.session_view, name="session"),
]
