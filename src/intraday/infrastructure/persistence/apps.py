# File: src/intraday/infrastructure/persistence/apps.py
#
# Django AppConfig for infrastructure/persistence (Checkpoint 7).
from __future__ import annotations

from django.apps import AppConfig


class PersistenceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "intraday.infrastructure.persistence"
    label = "persistence"
    verbose_name = "Persistence (infrastructure)"
