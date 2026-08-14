# File: src/intraday/infrastructure/persistence/models.py
#
# Django ORM models for the persistence foundation (Checkpoint 7). These
# are the ONLY Django models in the codebase so far — one immutable
# "version" table plus one mutable "active pointer" table per persisted
# configuration concept (RiskConfiguration, Universe, StrategyVersion),
# per Checkpoint 7 §6: an active pointer is modeled SEPARATELY from
# immutable versioned data so activating a version never mutates
# historical rows.
#
# Business rules (positivity, required-reason-on-rejection, etc.) are
# NOT re-implemented here — those live exclusively in the domain
# contracts (Checkpoint 5) and are re-validated by
# application/config_schema loaders before a repository ever sees a
# value. What IS enforced here are PERSISTENCE invariants: uniqueness,
# non-null, and the small set of check constraints that are cheap and
# valuable to also assert at the database level as a second line of
# defense (Checkpoint 7 §11) — not a re-implementation of domain logic,
# a backstop against it ever being bypassed.
from __future__ import annotations

from collections.abc import Iterable

from django.db import models
from django.db.models.base import ModelBase


class RiskConfigurationVersion(models.Model):
    """One immutable, versioned RiskLimits record.

    Numeric precision: `NUMERIC(14, 2)` — INR values up to
    999,999,999,999.99 (twelve digits before the decimal point, two
    after, i.e. paise precision). This comfortably covers intraday
    position-scale money for a single account without inventing headroom
    that isn't justified yet; revisit if a future checkpoint's scale
    requirements exceed it.

    Never updated after creation — the application layer only ever calls
    `save()` (insert), never `update()`, on this table.
    """

    risk_configuration_id = models.CharField(max_length=100)
    version = models.CharField(max_length=100)
    max_intraday_loss = models.DecimalField(max_digits=14, decimal_places=2)
    max_position_size = models.DecimalField(max_digits=14, decimal_places=2)
    max_per_trade_risk = models.DecimalField(max_digits=14, decimal_places=2)
    # Set explicitly by the application layer from the domain record's own
    # timestamp (never auto_now_add) so the persisted value matches
    # exactly what was validated, not "whenever the INSERT happened".
    created_at = models.DateTimeField()

    class Meta:
        app_label = "persistence"
        constraints = [
            models.UniqueConstraint(
                fields=["risk_configuration_id", "version"],
                name="uniq_risk_configuration_version",
            ),
            models.CheckConstraint(
                condition=models.Q(max_intraday_loss__gt=0),
                name="risk_max_intraday_loss_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(max_position_size__gt=0),
                name="risk_max_position_size_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(max_per_trade_risk__gt=0),
                name="risk_max_per_trade_risk_positive",
            ),
        ]
        indexes = [models.Index(fields=["risk_configuration_id", "created_at"])]


class ActiveRiskConfiguration(models.Model):
    """Mutable pointer to the currently active `RiskConfigurationVersion`
    for one `risk_configuration_id`. This table is the ONLY mutable state
    in the risk-configuration persistence model — `active_version` is
    updated in place when an operator activates a different version;
    `RiskConfigurationVersion` rows are never touched."""

    risk_configuration_id = models.CharField(max_length=100, unique=True)
    active_version = models.CharField(max_length=100)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "persistence"


class UniverseVersion(models.Model):
    """One immutable, versioned Universe record.

    `members` is stored as a single JSONB column (`[{"instrument_id":
    ..., "status": ...}, ...]`) rather than a related table — a universe
    is read/written as one atomic unit (Checkpoint 5's `Universe`
    dataclass already treats `members` as one immutable tuple), and a
    typical universe's member count does not justify the extra join a
    separate table would introduce. Revisit if a future checkpoint needs
    to query/filter individual members at the database level.
    """

    universe_id = models.CharField(max_length=100)
    version = models.CharField(max_length=100)
    exchange = models.CharField(max_length=10, choices=[("NSE", "NSE"), ("BSE", "BSE")])
    members = models.JSONField(default=list)
    created_at = models.DateTimeField()

    class Meta:
        app_label = "persistence"
        constraints = [
            models.UniqueConstraint(
                fields=["universe_id", "version"], name="uniq_universe_version"
            ),
        ]
        indexes = [models.Index(fields=["universe_id", "created_at"])]


class ActiveUniverse(models.Model):
    """Mutable pointer to the currently active `UniverseVersion` for one
    `universe_id`. Modeled separately from `UniverseVersion` for the same
    reason as `ActiveRiskConfiguration` above."""

    universe_id = models.CharField(max_length=100, unique=True)
    active_version = models.CharField(max_length=100)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "persistence"


class StrategyVersionRecord(models.Model):
    """One immutable `StrategyVersion` record.

    Identity is the tuple (strategy_id, specification_version,
    code_version, configuration_version) — matching
    `domain.strategy.StrategyVersion`'s own shape, where
    `universe_version` may legitimately differ across otherwise-identical
    records without creating a new strategy-version identity.
    """

    strategy_id = models.CharField(max_length=100)
    specification_version = models.CharField(max_length=100)
    code_version = models.CharField(max_length=100)
    configuration_version = models.CharField(max_length=100)
    universe_version = models.CharField(max_length=100)
    timeframe = models.CharField(max_length=10)
    maturity_state = models.CharField(max_length=20)
    created_at = models.DateTimeField()

    class Meta:
        app_label = "persistence"
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "strategy_id",
                    "specification_version",
                    "code_version",
                    "configuration_version",
                ],
                name="uniq_strategy_version_identity",
            ),
        ]
        indexes = [models.Index(fields=["strategy_id", "created_at"])]


class ActiveStrategyVersion(models.Model):
    """Mutable pointer to the currently active `StrategyVersionRecord`
    identity for one `strategy_id`. Modeled separately from
    `StrategyVersionRecord` for the same reason as
    `ActiveRiskConfiguration` above."""

    strategy_id = models.CharField(max_length=100, unique=True)
    active_specification_version = models.CharField(max_length=100)
    active_code_version = models.CharField(max_length=100)
    active_configuration_version = models.CharField(max_length=100)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "persistence"


class AuditLogEntry(models.Model):
    """Durable, append-only control-plane audit record (Checkpoint 12).
    Scope: risk-configuration activation only — see
    `control_plane.audit.events` for why the field names are already
    generic (`resource_type`/`resource_id`) rather than
    `risk_configuration_id`-specific, without building out
    universe/strategy auditing this checkpoint.

    Field-by-field:

    - `occurred_at`: UTC, set explicitly by the writer (never
      `auto_now_add`) so it matches the moment the state change itself
      was computed, not "whenever the INSERT statement ran" — same
      convention as `RiskConfigurationVersion.created_at`. Indexed:
      audit queries are chronological by nature.
    - `actor_username`: a plain string SNAPSHOT of `User.get_username()`,
      NOT a ForeignKey to `auth.User`. A ForeignKey would either cascade-
      delete audit history if the user is later deleted (destroying the
      historical record an audit trail exists to preserve) or require
      `on_delete=PROTECT` (blocking user deletion forever, an operational
      trap). A plain string survives both deletion and username reuse
      concerns are the same trade-off `git blame` makes with historical
      author names — acceptable and standard for an append-only log.
    - `actor_user_id`: the numeric primary key at the time of the
      action, stored as a plain integer (NOT a ForeignKey, same
      reasoning as `actor_username`) — lets a query correlate multiple
      audit rows to "the same account" even across a username change,
      without creating any cascade/deletion coupling. Nullable is not
      needed: every write path requires a real authenticated actor (see
      `DjangoRiskConfigurationRepository.activate()`) — there is no code
      path that creates a row without one.
    - `action`: a stable string token, e.g. `"configuration.activate"` —
      mirrors the `configuration.activate`/`configuration.read`
      capability vocabulary already established in
      `infrastructure/api/permissions.py` (Checkpoint 11), not a new,
      separate naming scheme.
    - `resource_type`/`resource_id`: which control-plane resource was
      acted on (`"risk_configuration"`, the configuration id) — generic
      enough to extend to universe/strategy without a schema change.
    - `version_identifier`: the version that was the target of the
      activation request.
    - `previous_version`: the version that was active immediately before
      this event (nullable — `None` when there was no prior active
      version, e.g. the very first activation for a configuration id).
      Answers "what changed from what," the minimum context needed for
      the record to be meaningful on its own.
    - `outcome`: one of `ActivationOutcome`'s three values — never a
      free-text field, so queries can group/filter reliably.
    - `request_id`: a UUID4 string minted once per HTTP request in
      `infrastructure/api/risk_views.py` (no pre-existing
      request/correlation-id infrastructure was found in this codebase —
      see docs/architecture/AUDITABILITY.md — a full observability
      system was judged out of scope for this checkpoint; this is the
      smallest useful addition, generated inline, not a new middleware).

    Never stored: passwords, session ids, CSRF tokens, cookies, request
    headers, or the raw request body — see docs/architecture/
    AUDITABILITY.md's Sensitive Data Policy.
    """

    occurred_at = models.DateTimeField(db_index=True)
    actor_username = models.CharField(max_length=150)
    actor_user_id = models.PositiveIntegerField()
    action = models.CharField(max_length=100)
    resource_type = models.CharField(max_length=50)
    resource_id = models.CharField(max_length=100)
    version_identifier = models.CharField(max_length=100)
    previous_version = models.CharField(max_length=100, null=True, blank=True)
    outcome = models.CharField(
        max_length=20,
        choices=[
            ("activated", "activated"),
            ("already_active", "already_active"),
            ("rejected", "rejected"),
            # Checkpoint 22: a fourth, narrowly-scoped outcome for
            # provider-credential changes (a save is not a configuration
            # "activation" - there is no version to activate - but is
            # still exactly the kind of security-sensitive change this
            # audit trail exists to record).
            ("updated", "updated"),
        ],
    )
    request_id = models.CharField(max_length=36)

    class Meta:
        app_label = "persistence"
        indexes = [
            models.Index(fields=["resource_type", "resource_id", "occurred_at"]),
        ]

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Application-level append-only enforcement (Checkpoint 12 §7):
        a row may only ever be INSERTed, never UPDATEd. `self._state.adding`
        is Django's own marker for "this instance has not been saved
        before" — False on any subsequent `.save()` call against an
        already-persisted row (e.g. `existing_row.outcome = "activated";
        existing_row.save()`), which this method refuses. True database-
        level immutability (revoking UPDATE/DELETE at the SQL grant
        level, or a rejecting trigger) is a stronger guarantee than this
        and was judged out of scope for this checkpoint — see
        docs/architecture/AUDITABILITY.md's Append-Only Enforcement
        section for the explicit limitation."""
        if not self._state.adding:
            raise RuntimeError(
                "AuditLogEntry rows are append-only and cannot be updated after creation."
            )
        super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )

    def delete(
        self, using: str | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        """No normal application code path calls this, and it is refused
        outright — an audit trail with a working delete method is not an
        audit trail."""
        raise RuntimeError("AuditLogEntry rows cannot be deleted through the application.")


# ---------------------------------------------------------------------------
# Checkpoint 22: operational provider settings (Dhan broker connectivity,
# Telegram/Discord notification channels). Deliberately THREE small,
# concrete models — one per provider — rather than one generic
# key-value/EAV credential table: each provider's field set is small,
# fixed, and known from official documentation (Checkpoint 22 §2), so a
# concrete model gives real columns, real types, and lets the database
# itself express "this provider has exactly these fields" instead of an
# untyped generic store that could hold anything.
#
# Each table is an application-level SINGLETON: exactly one row is ever
# expected to exist (one Dhan account, one Telegram bot, one Discord
# webhook per deployment — never per-user). Enforced by convention in
# the repository layer (`infrastructure/persistence/repositories.py`'s
# `get_or_create` pattern), not a database constraint — matching this
# codebase's existing precedent of expressing some invariants at the
# application layer (e.g. `AuditLogEntry`'s append-only `save()`
# override) rather than reaching for triggers/constraints for every
# rule.
#
# Secrets are never stored in plaintext — `encrypted_*` fields hold
# `Fernet`-encrypted bytes (see `infrastructure/persistence/encryption.py`),
# and are NEVER included in any API response or log line
# (`infrastructure/api/settings_views.py` only ever returns
# configured/not-configured booleans and masked display values).
# ---------------------------------------------------------------------------


class DhanCredential(models.Model):
    """Dhan broker connectivity configuration. Field names match the
    official DhanHQ v2 authentication scheme exactly
    (https://dhanhq.co/docs/v2/authentication/): `dhanClientId` (not
    secret — an account identifier, stored in plaintext) and
    `access-token` (a JWT, genuinely secret — stored encrypted)."""

    client_id = models.CharField(max_length=100, blank=True, default="")
    encrypted_access_token = models.BinaryField(null=True, blank=True)
    enabled = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by_username = models.CharField(max_length=150, blank=True, default="")

    class Meta:
        app_label = "persistence"


class TelegramCredential(models.Model):
    """Telegram bot notification configuration. `bot_token` is secret
    (stored encrypted); `channel_id` is a destination identifier, not
    inherently secret, but still never exposed to the frontend beyond a
    configured/not-configured indicator (Checkpoint 22 §15: "treat all
    communication configuration as controlled configuration")."""

    encrypted_bot_token = models.BinaryField(null=True, blank=True)
    channel_id = models.CharField(max_length=100, blank=True, default="")
    enabled = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by_username = models.CharField(max_length=150, blank=True, default="")

    class Meta:
        app_label = "persistence"


class DiscordCredential(models.Model):
    """Discord webhook notification configuration. The webhook URL
    itself (`https://discord.com/api/webhooks/{id}/{token}`) IS the
    credential — stored encrypted in its entirety, never split into a
    separate "id"/"token" pair the official API doesn't ask for."""

    encrypted_webhook_url = models.BinaryField(null=True, blank=True)
    enabled = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by_username = models.CharField(max_length=150, blank=True, default="")

    class Meta:
        app_label = "persistence"


class ProviderConnectionStatus(models.Model):
    """Reusable connection-status tracking, shared structurally across
    all three providers (Checkpoint 22 §12) — one row per provider,
    keyed by `provider`. A "Test Connection" action
    (`infrastructure/api/settings_views.py`) updates the matching row;
    saving credentials does NOT (Checkpoint 22 §14: configured is never
    conflated with connected).

    `failure_reason_safe` is a human-readable, pre-sanitized string —
    the writer is responsible for never putting a token/secret into it
    (Checkpoint 22 §24); this column itself has no way to enforce that,
    documented as the boundary responsibility of
    `application/services/provider_connectivity.py`."""

    PROVIDER_CHOICES = [("dhan", "dhan"), ("telegram", "telegram"), ("discord", "discord")]
    STATUS_CHOICES = [
        (value, value)
        for value in (
            "NOT_CONFIGURED",
            "CONFIGURED",
            "CONNECTING",
            "CONNECTED",
            "DISCONNECTED",
            "AUTHENTICATION_FAILED",
            "TOKEN_EXPIRED",
            "CONNECTION_ERROR",
            "DISABLED",
        )
    ]

    provider = models.CharField(max_length=32, choices=PROVIDER_CHOICES, unique=True)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default="NOT_CONFIGURED")
    last_checked_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_failure_at = models.DateTimeField(null=True, blank=True)
    failure_reason_safe = models.CharField(max_length=255, blank=True, default="")
    latency_ms = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        app_label = "persistence"
