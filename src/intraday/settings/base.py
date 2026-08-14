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
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent

# ---------------------------------------------------------------------------
# .env loading (Checkpoint 17.1 fix). `python-dotenv` was already a
# declared dependency (pyproject.toml) and `.env.example`'s own header
# comment already claimed "manage.py... read `.env` via python-dotenv" —
# but no code anywhere actually called `load_dotenv()`, so a developer's
# local `.env` was silently never read by `manage.py runserver`/any other
# management command (only `docker compose`'s own `env_file:` directive
# actually worked). This is the concrete local-development defect
# Checkpoint 17.1 found and fixes — not a new environment-loading
# mechanism, just making the one already documented actually run.
# `override=False` (the default): real process/OS environment variables
# still always win over `.env`, so CI (which sets env vars directly, no
# `.env` file) and production (which must never read a stray `.env`) are
# both unaffected — this only fills gaps for local development.
# ---------------------------------------------------------------------------
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")

# ---------------------------------------------------------------------------
# Checkpoint 22: encryption-at-rest key for operational provider
# credentials (Dhan access token, Telegram bot token, Discord webhook
# URL) — see infrastructure/persistence/encryption.py for the full key-
# precedence policy (this value, or a development-only fallback derived
# from SECRET_KEY). Empty by default; production.py enforces that it is
# actually set before allowing the process to boot, mirroring
# SECRET_KEY's own existing enforcement pattern.
# ---------------------------------------------------------------------------
SETTINGS_ENCRYPTION_KEY = os.environ.get("SETTINGS_ENCRYPTION_KEY", "")

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
    "corsheaders",
    "channels",
    "intraday.infrastructure.persistence",
]

# `corsheaders` (Checkpoint 11): the Vite dev server (127.0.0.1:5173) and
# the Django dev server (127.0.0.1:8000) are different origins, so
# cookie-based session auth needs CORS to let the browser's fetch()
# actually read the response and attach cookies. CorsMiddleware must sit
# as early as possible — immediately after SecurityMiddleware, before
# anything that can short-circuit or generate a response (per
# django-cors-headers' own placement requirement) — and strictly before
# CommonMiddleware.
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# ---------------------------------------------------------------------------
# CORS / CSRF cross-origin allowlist (Checkpoint 11). Empty by default —
# no cross-origin access is permitted unless an environment module
# explicitly opts in (development.py adds the Vite dev server origins;
# production.py reads an explicit env var, never a wildcard). Never use
# CORS_ALLOW_ALL_ORIGINS=True or "*" with credentials — both are
# disallowed by browsers for credentialed requests anyway, and doing so
# would defeat the same-origin protection CORS exists to provide.
# ---------------------------------------------------------------------------
CORS_ALLOWED_ORIGINS: list[str] = []
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS: list[str] = []

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
    # Checkpoint 11: session-cookie auth only — no BasicAuthentication (DRF's
    # own default), which would invite sending credentials via an
    # `Authorization` header the browser client never needs and that would
    # be easy to misuse outside the browser. `DEFAULT_PERMISSION_CLASSES`
    # is deliberately left at DRF's built-in `AllowAny` default rather than
    # flipped to deny-by-default here: the existing infrastructure
    # endpoints (/healthz, /readyz, /version) must stay open for
    # orchestration probes with no code change, and every view that must
    # be protected (the configuration API, logout) declares its own
    # `permission_classes` explicitly instead of relying on a global
    # default — see infrastructure/api/{risk,universe,strategy}_views.py
    # and infrastructure/api/auth_views.py.
    # Checkpoint 17.2: a thin subclass of DRF's own SessionAuthentication
    # that returns a real `authenticate_header`, so an unauthenticated
    # request gets a genuine 401 instead of DRF's default 403-downgrade
    # (see infrastructure/api/authentication.py for the full root-cause
    # explanation) - this is what lets the frontend's session-expiry
    # handler (401-only, by design) distinguish "not authenticated" from
    # a real authorization denial (403, unaffected by this change).
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "intraday.infrastructure.api.authentication.Http401SessionAuthentication"
    ],
    # Login brute-force protection (Checkpoint 11 §26): DRF's own
    # cache-backed ScopedRateThrottle, applied only to the login view
    # (infrastructure/api/auth_views.py) via `throttle_scope = "login"`.
    # No new dependency or distributed rate-limiting subsystem was added -
    # this reuses the CACHES backend already configured per environment
    # (Redis in production/development, LocMemCache in testing).
    "DEFAULT_THROTTLE_RATES": {
        "login": "5/min",
        # Checkpoint 22 §23: protects external providers (Dhan/Telegram/
        # Discord) from being hammered by repeated manual "Test
        # Connection" clicks - not a health-monitoring system, just
        # server-side abuse protection, same mechanism (DRF's own
        # ScopedRateThrottle) and cache backend as the login throttle.
        "provider_connection_test": "10/min",
    },
}

SPECTACULAR_SETTINGS = {
    "TITLE": "IntraDay API",
    "DESCRIPTION": (
        "Application-layer contracts for the IntraDay platform. Infrastructure "
        "endpoints (/healthz, /readyz, /version), the Checkpoint 8 "
        "configuration API (read + version-activate for risk configuration, "
        "universe, and strategy version) under /api/v1/config/, and the "
        "Checkpoint 11 session-based authentication API under /api/v1/auth/. "
        "No trading, signal, broker, or market-data business logic exists yet."
    ),
    "VERSION": "0.11.0",
    "SERVE_INCLUDE_SCHEMA": False,
    # Checkpoint 22: `client_id_source`/`access_token_source`/`channel_id_source`/
    # `bot_token_source`/`webhook_source` all reuse the identical
    # ["DATABASE", "ENVIRONMENT", "UNCONFIGURED"] choice set
    # (ConfigurationSource in application/services/provider_settings.py) -
    # drf-spectacular otherwise emits a spurious "multiple names for the
    # same choice set" warning, since it can't tell which field-derived
    # name should represent the shared set. Forcing one canonical name
    # keeps `spectacular --fail-on-warn` clean.
    "ENUM_NAME_OVERRIDES": {
        "ProviderConfigurationSourceEnum": [
            ("DATABASE", "DATABASE"),
            ("ENVIRONMENT", "ENVIRONMENT"),
            ("UNCONFIGURED", "UNCONFIGURED"),
        ],
    },
}

# ---------------------------------------------------------------------------
# Session cookie security (Checkpoint 11). `SESSION_COOKIE_HTTPONLY` (True)
# and default `SESSION_COOKIE_SAMESITE` ("Lax") are Django's own secure
# defaults and are left unchanged. `SESSION_COOKIE_SECURE`/
# `CSRF_COOKIE_SECURE` are NOT set here (would break plain-HTTP local
# development) - production.py already sets both True (Checkpoint 4).
# `SESSION_COOKIE_AGE` bounds how long a control-plane session stays valid
# without requiring the user to re-authenticate; 8 hours (one trading-day
# shift) is a deliberate, documented choice, not Django's 2-week default,
# for a system that can trigger configuration state changes.
# ---------------------------------------------------------------------------
SESSION_COOKIE_AGE = 60 * 60 * 8

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
