# File: src/intraday/infrastructure/persistence/management/commands/provision_dhan_credentials.py
#
# Checkpoint 64.60: SECURE, EXPLICIT, operator-invoked bridge from the
# deployment/environment-provided Dhan credential into the SAME
# encrypted database record `POST /api/v1/config/settings/dhan/save/`
# writes to (64.59 proved that save->persist->read path is genuinely
# correct end to end). This command does NOT invent a parallel
# credential system - it constructs a `DhanSettingsService` over the
# exact same `DjangoDhanCredentialRepository` and calls the exact same
# `.save()` method the HTTP endpoint calls (`settings_views.py`'s
# `dhan_settings_save`), through the SAME Fernet encryption
# (`infrastructure/persistence/encryption.py`) and the SAME append-only
# audit trail (`_audit_credential_change`).
#
# Why this command exists (64.60's diagnosed root cause, carried from
# 64.59): the operator updates `.env`, but this codebase's documented,
# unconditional precedence rule (`provider_settings.py`'s own module
# docstring) is "a DATABASE value is NEVER overwritten by an
# environment variable automatically" - by design, not a bug. `.env`
# is a bootstrap/fallback source only. This command is the one
# deliberate, explicit, operator-invoked action that promotes an
# environment value into the database - nothing else in this codebase
# does that, and nothing this command adds runs automatically at
# startup, on a schedule, or in a background/Celery task. Running this
# command IS the "explicit provisioning" step; simply editing `.env`
# and restarting a process is NOT.
#
# Environment variable names: reused verbatim from the EXISTING
# convention already read throughout `provider_settings.py`'s
# `DhanSettingsService.get_display()`/`effective_credentials()` -
# `DHAN_CLIENT_ID` and `DHAN_ACCESS_TOKEN`. No new/second name is
# introduced for the same secret.
#
# Security discipline (Checkpoint 64.60 §2/§3/§12 of the directive):
# this command NEVER reads the raw `.env` file - it reads the process
# environment ONLY through `os.environ.get(...)`, the same mechanism
# Django's own settings loading already uses everywhere else in this
# project (`provider_settings.py`, `settings/base.py`) - and it NEVER
# prints, logs, or returns the access token / client id / any secret
# value. Only safe, already-established metadata fields
# (`DhanSettingsView`'s own shape) are ever written to stdout.
from __future__ import annotations

import os
import uuid

from django.core.management.base import BaseCommand, CommandError, CommandParser

from intraday.application.services.provider_settings import DhanSettingsService
from intraday.infrastructure.persistence.provider_settings_repositories import (
    DjangoDhanCredentialRepository,
)

DHAN_CLIENT_ID_ENV_VAR = "DHAN_CLIENT_ID"
DHAN_ACCESS_TOKEN_ENV_VAR = "DHAN_ACCESS_TOKEN"  # noqa: S105 - env var name, not a secret

PROVISIONING_ACTOR = "provision_dhan_credentials_command"
"""Distinct, greppable actor name in the existing append-only audit
trail (`AuditLogEntry`) - so an explicit environment->database
provisioning event is always distinguishable from a Settings UI/API
save performed by a real logged-in operator user."""


class Command(BaseCommand):
    help = (
        "Explicitly synchronizes the Dhan credential from the deployment "
        "environment (DHAN_CLIENT_ID / DHAN_ACCESS_TOKEN) into the "
        "existing encrypted database credential record - the SAME record "
        "POST /api/v1/config/settings/dhan/save/ writes to (Checkpoint "
        "64.59 proved that save/persist/read path is correct). This "
        "command NEVER runs automatically - it must be invoked "
        "deliberately by an operator every time the environment secret "
        "changes. It makes NO network call, contacts Dhan for nothing, "
        "and prints no credential material - only safe metadata "
        "(token_state, token_expires_at, enabled, configured, source)."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--enabled",
            action="store_true",
            default=None,
            help="Also set the Dhan credential's enabled flag to True as part "
            "of this provisioning run. Omitted by default - provisioning "
            "touches only client_id/access_token unless this flag is passed, "
            "leaving the existing enabled state untouched.",
        )

    def handle(self, *args: object, **options: object) -> None:
        client_id = os.environ.get(DHAN_CLIENT_ID_ENV_VAR) or None
        access_token = os.environ.get(DHAN_ACCESS_TOKEN_ENV_VAR) or None

        if not access_token:
            raise CommandError(
                f"{DHAN_ACCESS_TOKEN_ENV_VAR} is not set (or is blank) in the "
                "current process environment - refusing to provision. Nothing "
                "was written to the database. Set the environment secret and "
                "re-run this command explicitly."
            )

        repository = DjangoDhanCredentialRepository()
        service = DhanSettingsService(repository=repository)

        service.save(
            client_id=client_id,
            access_token=access_token,
            enabled=bool(options.get("enabled")) if options.get("enabled") else None,
            actor=PROVISIONING_ACTOR,
            actor_user_id=0,
            request_id=str(uuid.uuid4()),
        )

        # Re-read through a FRESH service instance (mirrors 64.59's own
        # cross-instance proof discipline) - never trust the in-memory
        # `service` object used for the write to also report the read,
        # so this genuinely proves the DATABASE, not a cached value.
        fresh_service = DhanSettingsService(repository=DjangoDhanCredentialRepository())
        view = fresh_service.get_display()

        self.stdout.write(
            self.style.SUCCESS(
                "Dhan credential provisioned from ENVIRONMENT_PROVISION into the "
                "database. Normal runtime will now read this value from the "
                "DATABASE (unchanged read precedence - see provider_settings.py)."
            )
        )
        self.stdout.write("  success=True")
        self.stdout.write("  source=ENVIRONMENT_PROVISION")
        self.stdout.write(f"  configured={view.access_token_configured}")
        self.stdout.write(f"  enabled={view.enabled}")
        self.stdout.write(f"  token_state={view.token_state.value}")
        self.stdout.write(f"  token_expires_at={view.token_expires_at}")
        self.stdout.write(f"  client_id_masked={view.client_id_masked}")
