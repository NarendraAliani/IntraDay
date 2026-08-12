# src/intraday/settings/base.py
#
# Shared Django settings common to every environment (Checkpoint 4).
# Environment-specific modules (development.py, testing.py, paper.py,
# production.py) import everything from here with `from .base import *`
# and override only what must differ. No business logic; no models.
from __future__ import annotations

import os
from pathlib import Path

import structlog

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")

# ---------------------------------------------------------------------------
# Installed apps: framework-level, plus (as of Checkpoint 7) the single
# persistence app. `intraday.infrastructure.persistence` holds the ONLY
# business-adjacent Django models in this codebase — versioned
# configuration records (RiskConfigurationVersion, UniverseVersion,
# StrategyVersionRecord) and their active-pointer tables. See
# docs/architecture/PERSISTENCE_ARCHITECTURE.md. `django.contrib.admin`
# is included because Checkpoint 3 §2 named Django's admin as a primary
# architectural reason for choosing Django (control-plane/governance/
# audit review screens); no admin registrations exist yet.
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "channels",
    "intraday.infrastructure.persistence",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "intraday.urls"
ASGI_APPLICATION = "intraday.asgi.application"
WSGI_APPLICATION = "intraday.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# ---------------------------------------------------------------------------
# Time architecture (Checkpoint 3 §19): UTC is the sole canonical internal
# representation. IST conversion happens only at the presentation/session
# boundary, owned by domain/session in a later checkpoint — never here.
# ---------------------------------------------------------------------------
USE_TZ = True
TIME_ZONE = "UTC"

LANGUAGE_CODE = "en-us"
USE_I18N = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---------------------------------------------------------------------------
# PostgreSQL (Checkpoint 3 §4: sole relational engine / system of record).
# Configured entirely from environment variables — no credentials here.
# No SQLite fallback in base.py; testing.py documents its own narrow,
# justified exception (see that file).
# ---------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", ""),
        "USER": os.environ.get("POSTGRES_USER", ""),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
        "HOST": os.environ.get("POSTGRES_HOST", ""),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 60,
        # Fail fast rather than hang indefinitely if PostgreSQL is
        # unreachable (Checkpoint 7): psycopg has no default connect
        # timeout, so a firewalled/absent host previously caused any
        # DB-touching command (including `manage.py makemigrations`'s own
        # migration-history consistency check) to hang rather than error.
        "OPTIONS": {"connect_timeout": int(os.environ.get("POSTGRES_CONNECT_TIMEOUT", "5"))},
    }
}

# ---------------------------------------------------------------------------
# Redis-backed infrastructure (Checkpoint 4 §3 — see
# docs/architecture/TECHNOLOGY_MAPPING.md §5 for the full 7-role taxonomy).
# Redis is never a system of record; only cache/messaging/coordination.
# ---------------------------------------------------------------------------
REDIS_URL = os.environ.get("REDIS_URL", "")

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
    }
}

CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "UTC"
CELERY_ENABLE_UTC = True

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [REDIS_URL]},
    }
}

# ---------------------------------------------------------------------------
# Django REST Framework — infrastructure only, no business views registered
# here. DecimalField default behaviour left at DRF's default (string
# representation) to preserve financial precision (Checkpoint 3 §18) once
# real financial fields exist.
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "COERCE_DECIMAL_TO_STRING": True,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "IntraDay API",
    "DESCRIPTION": (
        "Application-layer contracts for the IntraDay platform. "
        "Checkpoint 4: only infrastructure endpoints (health/version) exist; "
        "no domain contracts have been added yet."
    ),
    "VERSION": "0.4.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

# ---------------------------------------------------------------------------
# Logging (Checkpoint 3 §11): structlog-based structured JSON logging.
# Operational logs only — never the audit trail (control_plane/audit owns
# that, in a later checkpoint, as durable Postgres rows, not log lines).
# ---------------------------------------------------------------------------
_LOG_LEVEL = os.environ.get("DJANGO_LOG_LEVEL", "INFO")

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "structured": {
            "()": structlog.stdlib.ProcessorFormatter,
            "processor": structlog.processors.JSONRenderer(),
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "structured",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": _LOG_LEVEL,
    },
}
