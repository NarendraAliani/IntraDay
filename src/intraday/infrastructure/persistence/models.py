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


class StrategyConfigurationRecord(models.Model):
    """One immutable set of strategy parameter VALUES (Checkpoint 26).

    Distinct from and layered on top of `StrategyVersionRecord`/
    `ActiveStrategyVersion` above (Checkpoint 8/13), which remain the
    version-IDENTITY/activation-pointer records - this table is the
    genuinely new piece: the actual parameter values a
    `configuration_version` label points at. Same identity tuple
    (strategy_id, specification_version, code_version,
    configuration_version) as `StrategyVersionRecord`, deliberately not
    a ForeignKey to it - a configuration can be validated and saved
    before a matching `StrategyVersionRecord`/activation exists (Part 11
    "material configuration changes must create a NEW version" implies
    configuration authoring is a precursor step, not the same act as
    activation).

    `parameter_values` is a single JSONField, following the exact
    `UniverseVersion.members` precedent (Checkpoint 5/8): a
    configuration's parameter set is read/written as one atomic unit, and
    its size never justifies a per-parameter row/table.
    """

    strategy_id = models.CharField(max_length=100)
    specification_version = models.CharField(max_length=100)
    code_version = models.CharField(max_length=100)
    configuration_version = models.CharField(max_length=100)
    parameter_values = models.JSONField(default=dict)
    created_at = models.DateTimeField()
    created_by = models.CharField(max_length=150)

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
                name="uniq_strategy_configuration_identity",
            ),
        ]
        indexes = [models.Index(fields=["strategy_id", "created_at"])]


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


class LiveQuoteObservation(models.Model):
    """Checkpoint 23: an append-only observation log of live-fetched
    quotes (Checkpoint 23 §10 - "persist enough live data to support
    manual verification, debugging, replay later, auditability"). One
    row per (instrument, refresh) - never overwritten, never updated -
    so a full history of every observed price/timestamp for the
    configured observation universe is preserved for replay/audit.

    Retention (Checkpoint 23 §10's explicit "document the retention
    assumptions"): NOT rotated or capped by this checkpoint. Given this
    checkpoint's explicit-trigger, four-symbol, REST-polling design
    (never a continuous multi-second stream - see
    docs/architecture/LIVE_MARKET_DATA_ARCHITECTURE.md), row growth is
    inherently bounded by how often an operator manually presses
    Refresh - a few thousand rows per trading day at worst, not an
    unbounded tick firehose. A retention/rotation policy is an explicit,
    documented limitation to revisit before the observation universe or
    refresh cadence grows (e.g. if a future checkpoint introduces
    automatic/scheduled polling)."""

    instrument_symbol = models.CharField(max_length=32)
    exchange = models.CharField(max_length=8, default="NSE")
    last_price = models.DecimalField(max_digits=14, decimal_places=4)
    source_timestamp = models.DateTimeField()
    fetched_at = models.DateTimeField()
    open_price = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    high_price = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    low_price = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    close_price = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)

    class Meta:
        app_label = "persistence"
        indexes = [
            models.Index(fields=["instrument_symbol", "-fetched_at"]),
        ]


class MarketDataHealthStatus(models.Model):
    """Checkpoint 23: singleton (get_or_create(pk=1), matching Checkpoint
    22's provider-credential singleton convention) tracking of the most
    recent live market-data refresh attempt's outcome - raw facts only
    (`control_plane.market_data_health.evaluator.evaluate_health()`
    turns this into a classified state; this model makes no
    classification judgement of its own)."""

    last_success_at = models.DateTimeField(null=True, blank=True)
    last_failure_at = models.DateTimeField(null=True, blank=True)
    last_error_safe = models.CharField(max_length=255, blank=True, default="")
    consecutive_failures = models.PositiveIntegerField(default=0)

    class Meta:
        app_label = "persistence"


class AggregatedBarObservation(models.Model):
    """Checkpoint 24A: a persisted, aggregated bar built from
    `LiveQuoteObservation` rows
    (`domain.market_data.aggregation.aggregate_quotes_into_bars`).

    Unlike `LiveQuoteObservation` (append-only), this table is an
    UPSERT-by-identity projection - `(instrument_symbol, timeframe,
    interval_start)` is unique, and a row is replaced in place when
    aggregation is re-run (a FORMING bar becoming CLOSED, or a
    previously-CLOSED bar being revised by a late-arriving observation
    - both are intended, documented behavior, not a bug - see
    `domain/market_data/aggregation.py`'s own module docstring)."""

    instrument_symbol = models.CharField(max_length=32)
    exchange = models.CharField(max_length=8, default="NSE")
    timeframe = models.CharField(max_length=8)
    interval_start = models.DateTimeField()
    interval_end = models.DateTimeField()
    open_price = models.DecimalField(max_digits=14, decimal_places=4)
    high_price = models.DecimalField(max_digits=14, decimal_places=4)
    low_price = models.DecimalField(max_digits=14, decimal_places=4)
    close_price = models.DecimalField(max_digits=14, decimal_places=4)
    status = models.CharField(max_length=8, choices=[("FORMING", "FORMING"), ("CLOSED", "CLOSED")])
    observation_count = models.PositiveIntegerField()
    data_source = models.CharField(max_length=32)
    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "persistence"
        constraints = [
            models.UniqueConstraint(
                fields=["instrument_symbol", "timeframe", "interval_start"],
                name="unique_bar_per_instrument_timeframe_interval",
            )
        ]
        indexes = [
            models.Index(fields=["timeframe", "-interval_start"]),
        ]


class BacktestResultRecord(models.Model):
    """Checkpoint 27: one immutable, persisted `BacktestResult`
    (research.backtesting.contracts). `result_payload` is a single
    JSONField holding the full serialized result (configuration,
    metrics, equity curve, trade ledger) - mirrors the established
    "flexible content JSONField" precedent (`UniverseVersion.members`,
    `StrategyConfigurationRecord.parameter_values`) rather than a
    relational trade/equity-point schema, which the POC scope of this
    checkpoint does not require. `backtest_id` is the engine's own
    deterministic hash (never a random UUID - see `engine.py`), so
    re-running an identical configuration against identical data
    upserts the same row rather than creating a duplicate."""

    backtest_id = models.CharField(max_length=64, unique=True)
    strategy_id = models.CharField(max_length=100)
    result_payload = models.JSONField()
    created_at = models.DateTimeField()
    created_by = models.CharField(max_length=150)

    class Meta:
        app_label = "persistence"
        indexes = [models.Index(fields=["strategy_id", "created_at"])]


class WatchlistRecord(models.Model):
    """Checkpoint 27 Part 19: a lightweight, research-oriented named
    instrument list - usable as a backtest universe. Deliberately NOT a
    live order screen (no quantity, no side, no order-related field
    anywhere on this model)."""

    name = models.CharField(max_length=100)
    owner_username = models.CharField(max_length=150)
    instrument_ids = models.JSONField(default=list)
    created_at = models.DateTimeField()

    class Meta:
        app_label = "persistence"
        constraints = [
            models.UniqueConstraint(
                fields=["owner_username", "name"], name="uniq_watchlist_per_owner"
            )
        ]


class StrategyResearchStatusRecord(models.Model):
    """Checkpoint 27 Part 20: research-monitor pause/resume state for one
    strategy_id. Deliberately a SEPARATE, small state set
    (RESEARCH_ACTIVE/RESEARCH_PAUSED/DISABLED) from
    `domain.strategy.StrategyMaturityState` - this concept is "is this
    strategy currently included in research/backtesting activity", not a
    trading-lifecycle maturity state, and must never be confused with or
    imply live-trading authorization (Part 20's own explicit warning)."""

    strategy_id = models.CharField(max_length=100, unique=True)
    status = models.CharField(
        max_length=20,
        choices=[
            ("RESEARCH_ACTIVE", "RESEARCH_ACTIVE"),
            ("RESEARCH_PAUSED", "RESEARCH_PAUSED"),
            ("DISABLED", "DISABLED"),
        ],
        default="RESEARCH_ACTIVE",
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.CharField(max_length=150, default="")

    class Meta:
        app_label = "persistence"


class KillSwitchState(models.Model):
    """Checkpoint 34 Part 11: the FIRST real kill-switch implementation
    this project has ever had - Checkpoint 33's audit found every prior
    reference to a "kill switch" was documentation/prose only. Singleton
    (`get_or_create(pk=1)`, matching every other singleton state model
    in this file). `enabled=True` means the switch is ENGAGED (trading
    halted) - named `enabled` rather than `engaged` to match
    `domain.risk.contracts.TradingHaltStatus`'s own HALTED/ACTIVE
    vocabulary at the repository boundary (`TradingHaltStatus.HALTED`
    <-> `enabled=True`). Never deletes history - `reset()` sets
    `enabled=False` and records a NEW audit event, it does not erase the
    engage event."""

    enabled = models.BooleanField(default=False)
    reason = models.CharField(max_length=500, blank=True, default="")
    actor_username = models.CharField(max_length=150, blank=True, default="")
    changed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        app_label = "persistence"


class PaperOrderRecord(models.Model):
    """Checkpoint 34 Part 12: the persistent paper-trading order ledger.
    Deliberately a SEPARATE model from `PaperTradeRecord`/
    `PaperPositionRecord` (Part 12's explicit "keep Order/Trade/Position
    as distinct concepts... do not collapse everything into one table").
    `state_history` is an append-only JSON log of every
    `domain.order.events.OrderEvent` this order has experienced -
    reconstructable audit trail without a second events table this
    checkpoint's scope does not need."""

    order_id = models.CharField(max_length=100, unique=True)
    idempotency_key = models.CharField(max_length=100, unique=True)
    correlation_id = models.CharField(max_length=30)
    instrument_id = models.CharField(max_length=100)
    strategy_id = models.CharField(max_length=100)
    signal_id = models.CharField(max_length=100, blank=True, default="")
    """Checkpoint 36 Part 6: strategy-generated orders carry a
    `signal_id` for full lineage (strategy version -> signal ID -> order
    ID -> trade ID -> position ID). Blank for manually-submitted paper
    orders (Checkpoint 35's order-entry form has no strategy signal
    behind it) - never fabricated."""
    side = models.CharField(max_length=10)
    order_type = models.CharField(max_length=20)
    quantity = models.DecimalField(max_digits=18, decimal_places=4)
    filled_quantity = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    limit_price = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    trigger_price = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    status = models.CharField(max_length=20)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField(auto_now=True)
    state_history = models.JSONField(default=list)

    class Meta:
        app_label = "persistence"
        indexes = [models.Index(fields=["instrument_id", "status"])]


class PaperTradeRecord(models.Model):
    """Checkpoint 34 Part 12: one completed round trip (entry + exit) in
    the paper ledger - mirrors `domain.trade.Trade` exactly."""

    trade_id = models.CharField(max_length=100, unique=True)
    strategy_id = models.CharField(max_length=100)
    instrument_id = models.CharField(max_length=100)
    direction = models.CharField(max_length=10)
    order_ids = models.JSONField(default=list)
    entry_price = models.DecimalField(max_digits=18, decimal_places=4)
    exit_price = models.DecimalField(max_digits=18, decimal_places=4)
    quantity = models.DecimalField(max_digits=18, decimal_places=4)
    realized_pnl = models.DecimalField(max_digits=18, decimal_places=4)
    costs = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    opened_at = models.DateTimeField()
    closed_at = models.DateTimeField()

    class Meta:
        app_label = "persistence"


class PaperPositionRecord(models.Model):
    """Checkpoint 34 Part 12: current/historical position snapshots in
    the paper ledger - mirrors `domain.position.Position` exactly.
    Upserted per instrument while OPEN (one open position per
    instrument, matching this checkpoint's own risk-engine "instrument
    already has a pending/open order" duplicate check); a new row is
    created once a position closes, so history is never overwritten."""

    position_id = models.CharField(max_length=100, unique=True)
    instrument_id = models.CharField(max_length=100)
    direction = models.CharField(max_length=10)
    quantity = models.DecimalField(max_digits=18, decimal_places=4)
    average_entry_price = models.DecimalField(max_digits=18, decimal_places=4)
    realized_pnl = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    unrealized_pnl = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    opened_at = models.DateTimeField()
    closed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, default="OPEN")

    # Checkpoint 43 Part 3/5: position-management lineage/exit-plan
    # fields, ALL nullable/blank-default so every position created
    # before this checkpoint (and every position a strategy with no
    # ExitPlan produces, e.g. ema_crossover without the opt-in policy)
    # continues to mean exactly what `ManagedPosition.exit_plan=None`
    # already means - "no automatic exit rule exists for this
    # position," never a fabricated default.
    strategy_id = models.CharField(max_length=100, blank=True, default="")
    strategy_version = models.CharField(max_length=20, blank=True, default="")
    entry_order_id = models.CharField(max_length=100, blank=True, default="")
    stop_loss = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    target_1 = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    target_2 = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    target_3 = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    trailing_stop_distance = models.DecimalField(
        max_digits=18, decimal_places=4, null=True, blank=True
    )
    lifecycle_status = models.CharField(max_length=20, default="OPEN")
    remaining_quantity = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    highest_favorable_price = models.DecimalField(
        max_digits=18, decimal_places=4, null=True, blank=True
    )
    exit_reason = models.CharField(max_length=30, blank=True, default="")

    class Meta:
        app_label = "persistence"
        indexes = [models.Index(fields=["instrument_id", "status"])]


class PaperFundsRecord(models.Model):
    """Checkpoint 34 Part 12: singleton paper-account capital state -
    mirrors `domain.broker.Funds` exactly (deliberately simple, no
    SPAN/exposure-margin replication - see `Funds`'s own docstring)."""

    available_balance = models.DecimalField(max_digits=18, decimal_places=4)
    utilized_margin = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "persistence"


class CommunicationLedgerRecord(models.Model):
    """Checkpoint 37 Part 7: one row per delivery ATTEMPT (not per
    event) - a `SignalCommunicationEvent` fanned out to N configured
    providers produces N rows. Answers "was this signal communicated?"
    without ever storing a secret (bot tokens/webhook URLs never touch
    this table - only `destination_masked`, mirroring `TelegramCredential`/
    `DiscordCredential`'s own encrypted-elsewhere, masked-here pattern).
    `(signal_id, event_id, channel)` is the natural idempotency key -
    `already_sent()` (infrastructure/persistence/communication_ledger_repository.py)
    queries on it before ever calling a provider's `send()`."""

    communication_id = models.CharField(max_length=64, primary_key=True)
    signal_id = models.CharField(max_length=100)
    event_id = models.CharField(max_length=64)
    channel = models.CharField(max_length=32)
    provider = models.CharField(max_length=32)
    destination_masked = models.CharField(max_length=100, blank=True, default="")
    template_id = models.CharField(max_length=64)
    template_version = models.CharField(max_length=16)
    created_at = models.DateTimeField()
    attempted_at = models.DateTimeField(null=True, blank=True)
    delivery_status = models.CharField(max_length=32)
    provider_message_id = models.CharField(max_length=100, blank=True, default="")
    error_code = models.CharField(max_length=64, blank=True, default="")
    error_message = models.CharField(max_length=500, blank=True, default="")
    retry_count = models.PositiveIntegerField(default=0)
    correlation_id = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        app_label = "persistence"
        indexes = [
            models.Index(fields=["signal_id", "event_id", "channel"]),
        ]


class EmergencySquareOffEvent(models.Model):
    """Checkpoint 48 Part 3: the DURABLE authority for one kill-switch
    halt event's emergency-square-off lifecycle - replacing the
    cache-only `cache.add()` claim Checkpoint 46/47 used
    (`infrastructure/api/emergency_square_off_trigger.py`'s previous
    `_SQUARE_OFF_HANDLED_KEY_PREFIX`).

    The bug this closes: a pure `cache.add()` claim marks a halt event
    "handled" the INSTANT it is claimed - not when square-off actually
    finishes. A process crash between those two moments left the event
    permanently "handled" in cache (24h TTL) with positions possibly
    still open, and nothing would ever retry it. A database row survives
    a process crash; the cache did not model "in progress" as a
    distinct, inspectable state at all.

    `halt_identity` is the kill switch's own `changed_at.isoformat()` -
    the same identity Checkpoint 46 used - unique per row, one row per
    halt event, never per-attempt (multiple attempts update the SAME
    row, `attempt_count` incrementing) so history is auditable without
    a separate events table this checkpoint's scope does not need.

    Status vocabulary (deliberately NOT copying the user's suggested
    names verbatim where this project's own existing vocabulary -
    `PositionLifecycleStatus`, `TradingHaltStatus` - already reads
    naturally alongside it):

    NOT_STARTED          - row exists (created on first sighting of the
                            halt), no attempt has run yet.
    IN_PROGRESS           - an attempt is currently running (or crashed
                            mid-run - see `claimed_at` staleness below).
    COMPLETED             - square-off ran AND reconciliation confirmed
                            zero open exposure. Terminal - never re-run.
    FAILED_RETRYABLE       - an attempt raised an exception, OR finished
                            but left `positions_failed` non-empty, OR
                            finished but reconciliation still shows open
                            exposure - the NEXT tick is expected to
                            retry it. Not terminal.
    RECONCILIATION_REQUIRED - square-off itself reported success (every
                            position it attempted closed) but the POST
                            reconciliation still found a divergence -
                            distinguished from FAILED_RETRYABLE because
                            here submitting exit orders is not obviously
                            the right next action (the divergence may be
                            a broker/local bookkeeping mismatch, not
                            remaining exposure) - flagged for operator
                            attention rather than blindly retried
                            indefinitely, though the next tick MAY still
                            retry it (see `emergency_square_off_trigger.py`).

    `claimed_at` is the moment the CURRENT attempt was claimed - used to
    detect a crashed-mid-run attempt (an `IN_PROGRESS` row whose
    `claimed_at` is older than `_IN_PROGRESS_STALENESS_SECONDS` is
    treated as abandoned and reclaimed, not as "someone else is handling
    it"). This is what makes the state machine restart-safe: NOT_STARTED
    or FAILED_RETRYABLE or a STALE IN_PROGRESS are all reclaimable;
    a FRESH IN_PROGRESS (another worker genuinely mid-run right now) is
    not - preventing two concurrent attempts from both submitting exit
    orders for the same position."""

    halt_identity = models.CharField(max_length=64, unique=True)
    status = models.CharField(max_length=32, default="NOT_STARTED")
    attempt_count = models.PositiveIntegerField(default=0)
    claimed_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    positions_closed = models.PositiveIntegerField(default=0)
    positions_failed = models.JSONField(default=list)
    reconciliation_divergence_count = models.IntegerField(null=True, blank=True)
    last_error = models.CharField(max_length=1000, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "persistence"


class EODRun(models.Model):
    """Checkpoint 51 Part 11: the durable EOD-lifecycle state machine -
    ONE row per calendar trading date, deliberately reusing the exact
    crash-recovery design proven for `EmergencySquareOffEvent`
    (Checkpoint 48/Decision 202) rather than inventing a new pattern -
    the same lesson applies identically here: EOD force-closes every
    open PAPER position, so a crash mid-run must never be able to
    permanently mark the day "closed" while positions remain open.

    `eod_date` is the identity (one EOD per trading day, never per
    attempt - retries update the SAME row, `attempt_count`
    incrementing). Status vocabulary deliberately mirrors
    `EmergencySquareOffEvent`'s own (`NOT_STARTED` -> `IN_PROGRESS` ->
    `COMPLETED` / `FAILED_RETRYABLE`) rather than inventing a fourth
    vocabulary for what is structurally the same problem (force-close
    exposure, verify zero, record the outcome, survive a crash)."""

    eod_date = models.DateField(unique=True)
    status = models.CharField(max_length=32, default="NOT_STARTED")
    attempt_count = models.PositiveIntegerField(default=0)
    claimed_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    positions_closed = models.PositiveIntegerField(default=0)
    positions_failed = models.JSONField(default=list)
    reconciliation_divergence_count = models.IntegerField(null=True, blank=True)
    total_realized_pnl = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    last_error = models.CharField(max_length=1000, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "persistence"


class HistoricalBar(models.Model):
    """Checkpoint 63.x: the FIRST persisted, DB-first archive of raw
    historical OHLCV bars — the whole point of this checkpoint's
    architecture is that the scanner/backtester read ONLY from this
    table (via `DjangoHistoricalBarRepository`), never directly from an
    external historical-data API. Deliberately separate from
    `AggregatedBarObservation` above: that table is an upsert-by-
    identity projection built from LIVE quote polling, keyed on plain
    symbol strings, with no concept of "was this fetched from a
    historical archive or aggregated live" or of a bar-level
    `source`/`fetched_at` provenance trail — reusing it here would
    conflate two genuinely different pipelines (live ingestion vs.
    historical backfill) that this checkpoint's own architecture
    diagram requires to stay distinct.

    Uniqueness is `(instrument_id, timeframe, bar_timestamp)` — a
    historical bar's identity is what instrument/timeframe/close-time
    it represents, NEVER the auto-incrementing row id (Phase 2's
    explicit instruction). `bulk_upsert()`
    (`DjangoHistoricalBarRepository`) relies on this constraint to make
    re-fetching an already-cached range a safe no-op rather than a
    duplicate."""

    instrument_id = models.CharField(max_length=100)
    exchange = models.CharField(max_length=8)
    symbol = models.CharField(max_length=32)
    timeframe = models.CharField(max_length=8)
    bar_timestamp = models.DateTimeField()
    open_price = models.DecimalField(max_digits=18, decimal_places=4)
    high_price = models.DecimalField(max_digits=18, decimal_places=4)
    low_price = models.DecimalField(max_digits=18, decimal_places=4)
    close_price = models.DecimalField(max_digits=18, decimal_places=4)
    volume = models.DecimalField(max_digits=20, decimal_places=4)
    source = models.CharField(max_length=32)
    """Provenance: which pipeline stage produced this row, e.g.
    `"API_FETCH"` (freshly fetched from the historical provider this
    request) vs. a value indicating it was already present from a
    prior run - see `infrastructure.market_data_providers.
    synthetic_historical` for the one provider implementation that
    exists today, and its own docstring for why it is NOT a real Dhan
    historical-candle integration."""
    ingested_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "persistence"
        constraints = [
            models.UniqueConstraint(
                fields=["instrument_id", "timeframe", "bar_timestamp"],
                name="uq_historical_bar_identity",
            )
        ]
        indexes = [models.Index(fields=["instrument_id", "timeframe", "bar_timestamp"])]
        ordering = ["bar_timestamp"]


class BacktestRun(models.Model):
    """Checkpoint 63.x: a persistent, pollable record of one DB-first
    historical backtest run's progress — the state
    `HistoricalBacktestRunOrchestrator` mutates as it works and
    `GET .../historical-runs/{run_id}/progress/` reads back. `run_id` is
    a UUID (not the deterministic per-instrument `backtest_id` the
    underlying engine already produces - see `BacktestResultRecord` -
    since one `BacktestRun` spans MULTIPLE instruments/backtest_ids, it
    needs its own, separate identity).

    `phase` is the fine-grained state-machine value (Phase 14 of this
    checkpoint's brief); `status` is the coarse terminal/non-terminal
    outcome a caller checks first. Every numeric progress field here is
    updated from ACTUAL orchestrator work, never advanced on a timer -
    see the orchestrator's own docstring."""

    PHASE_CHOICES = [
        (p, p)
        for p in (
            "QUEUED",
            "ANALYZING_DATA_COVERAGE",
            "FETCHING_HISTORICAL_DATA",
            "VALIDATING_DATA",
            "PERSISTING_DATA",
            "PREPARING_SCAN",
            "SCANNING",
            "CALCULATING_RESULTS",
            "FINALIZING",
            "COMPLETED",
            "PARTIAL",
            "FAILED",
            "CANCELLED",
        )
    ]
    STATUS_CHOICES = [
        (s, s) for s in ("QUEUED", "RUNNING", "COMPLETED", "PARTIAL", "FAILED", "CANCELLED")
    ]

    run_id = models.CharField(max_length=64, unique=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="QUEUED")
    phase = models.CharField(max_length=32, choices=PHASE_CHOICES, default="QUEUED")

    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.CharField(max_length=150)

    start_date = models.DateField()
    end_date = models.DateField()
    timeframe = models.CharField(max_length=8)
    instrument_ids = models.JSONField(default=list)
    strategy_id = models.CharField(max_length=100)
    specification_version = models.CharField(max_length=32)
    code_version = models.CharField(max_length=32)
    configuration_version = models.CharField(max_length=100)
    """Widened from an initial 32-char guess after a real, reported
    `DataError: value too long` proved the actual generated value is
    longer than assumed - the SAME class of bug already found once
    before on `SignalRecord.timeframe` (Checkpoint 62.x). `100` matches
    every OTHER `configuration_version` column already in this
    codebase (`StrategyVersion`/`StrategyConfigurationSnapshot`) -
    this field was the one inconsistent outlier at `32`."""
    strategy_values = models.JSONField(default=dict)
    cost_model_name = models.CharField(max_length=32, default="FLAT_PERCENTAGE")
    initial_capital = models.DecimalField(max_digits=18, decimal_places=4)
    position_sizing_mode = models.CharField(max_length=32)
    position_size_value = models.DecimalField(max_digits=18, decimal_places=6)
    brokerage_percent = models.DecimalField(max_digits=8, decimal_places=4, default=0)
    slippage_percent = models.DecimalField(max_digits=8, decimal_places=4, default=0)

    total_instruments = models.PositiveIntegerField(default=0)
    completed_instruments = models.PositiveIntegerField(default=0)
    total_bars = models.PositiveIntegerField(default=0)
    scanned_bars = models.PositiveIntegerField(default=0)
    signals_generated = models.PositiveIntegerField(default=0)

    cache_hits = models.PositiveIntegerField(default=0)
    cache_misses = models.PositiveIntegerField(default=0)
    api_requests = models.PositiveIntegerField(default=0)

    failed_instruments = models.JSONField(default=list)
    """List of `{"instrument_id": ..., "reason": ...}` objects - Phase 6
    partial-failure disclosure, never silently dropped from the
    report."""
    result_backtest_ids = models.JSONField(default=dict)
    """`{instrument_id: backtest_id}` - one underlying, already-persisted
    `BacktestResultRecord` per successfully-scanned instrument (Phase 9
    Step 15/16: this run does not re-implement result persistence, it
    references the SAME `BacktestResultRepository` every other backtest
    uses)."""

    error_message = models.CharField(max_length=2000, blank=True, default="")
    progress_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    current_instrument = models.CharField(max_length=100, blank=True, default="")
    current_strategy = models.CharField(max_length=100, blank=True, default="")
    current_timestamp = models.DateTimeField(null=True, blank=True)
    message = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        app_label = "persistence"
        indexes = [models.Index(fields=["-created_at"])]
        ordering = ["-created_at"]


class WorkerRuntimeStatus(models.Model):
    """Checkpoint 64.3: THE "persist or expose runtime state" gap the
    review named - `manage.py run_market_data_worker --provider dhan`
    runs as a SEPARATE OS process from the Django web process serving
    the API/frontend, so the only way an operator can see its live
    state is through a shared, persisted row this worker process
    writes to and the API reads from - mirrors
    `ProviderConnectionStatus`'s own established "one row per provider,
    written by whichever process actually knows, read by the API"
    pattern (Checkpoint 22), never a new architecture.

    ONE singleton row (`provider="dhan"`, the only real provider this
    applies to) - updated by `WorkerHealthTracker` (infrastructure
    layer) on every aggregation pass, read by a plain GET view. Never
    carries a credential or a raw provider response body - only the
    same safe, already-derived facts `MarketDataWatchdogSnapshot`
    itself carries."""

    provider = models.CharField(max_length=32, unique=True, default="dhan")
    worker_state = models.CharField(max_length=32, default="STOPPED")
    token_state = models.CharField(max_length=32, default="UNCONFIGURED")
    watchdog_state = models.CharField(max_length=32, default="DISCONNECTED")
    last_packet_at = models.DateTimeField(null=True, blank=True)
    last_bar_at = models.DateTimeField(null=True, blank=True)
    reconnect_count = models.PositiveIntegerField(default=0)
    consecutive_failures = models.PositiveIntegerField(default=0)
    subscribed_instrument_count = models.PositiveIntegerField(default=0)
    last_error_safe = models.CharField(max_length=500, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "persistence"


class MarketDataSyncRun(models.Model):
    """Follow-up to Checkpoint 63.x: a persistent, pollable record of one
    manual "fetch real historical data from Dhan into the database" run
    - the same `run_id`-based create/poll shape `BacktestRun` already
    established, deliberately reused rather than inventing a second
    progress-tracking convention. Mutated by
    `MarketDataSyncRunOrchestrator` as it works through each instrument x
    timeframe combination, calling the SAME `HistoricalDataPreparationService.
    prepare()` coverage/fetch/persist pipeline the backtest orchestrator
    uses - this run has no scan/strategy step of its own, it exists
    purely to populate `HistoricalBar` so backtests (and, later, any
    other consumer) find real data already cached.

    `timeframes` is a LIST (not a single value) - the Settings page lets
    an operator check multiple timeframes (e.g. Daily + 5m + 1h) and
    fetch them all in one run, one combined progress bar covering every
    instrument x timeframe combination together (an explicit, approved
    design decision - see HistoricalMarketDataCard.tsx)."""

    STATUS_CHOICES = [
        (s, s) for s in ("QUEUED", "RUNNING", "COMPLETED", "PARTIAL", "FAILED", "CANCELLED")
    ]

    run_id = models.CharField(max_length=64, unique=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="QUEUED")

    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_by = models.CharField(max_length=150)

    start_date = models.DateField()
    end_date = models.DateField()
    timeframes = models.JSONField(default=list)
    instrument_ids = models.JSONField(default=list)

    total_combinations = models.PositiveIntegerField(default=0)
    """`len(instrument_ids) * len(timeframes)` - the unit of progress
    this run actually reports against, since one run now covers every
    instrument x timeframe pair, not just one per instrument."""
    completed_combinations = models.PositiveIntegerField(default=0)
    bars_fetched = models.PositiveIntegerField(default=0)
    bars_persisted = models.PositiveIntegerField(default=0)
    cache_hits = models.PositiveIntegerField(default=0)
    api_requests = models.PositiveIntegerField(default=0)

    failed_combinations = models.JSONField(default=list)
    """List of `{"instrument_id": ..., "timeframe": ..., "reason": ...}`
    objects - the same partial-failure disclosure convention
    `BacktestRun` uses, never silently dropped from the report."""

    progress_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    current_instrument = models.CharField(max_length=100, blank=True, default="")
    current_timeframe = models.CharField(max_length=8, blank=True, default="")
    message = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        app_label = "persistence"
        indexes = [models.Index(fields=["-created_at"])]
        ordering = ["-created_at"]


class SignalRecord(models.Model):
    """Checkpoint 62.x: the FIRST persisted, queryable record of a real
    strategy-generated signal - closes a gap a fresh audit this
    checkpoint found: `domain.signal.contracts.Signal` existed only as
    a value object, with no repository and no API anywhere in this
    project, making an honest "active signal monitor" UI impossible to
    build without either this table or fabricated data. Written from
    `PaperSignalExecutionService.evaluate_and_submit()`
    (`application/services/paper_signal_execution.py`) - the ONE real
    place a strategy's evaluated direction becomes a signal in this
    codebase - never a second, parallel signal-generation path, and
    NEVER for a skipped/neutral/already-processed evaluation (see that
    method's own early-return guards)."""

    signal_id = models.CharField(max_length=64, unique=True)
    strategy_id = models.CharField(max_length=100)
    instrument_id = models.CharField(max_length=100)
    direction = models.CharField(max_length=16)
    price = models.DecimalField(max_digits=18, decimal_places=4)
    timeframe = models.CharField(max_length=32, blank=True, default="")
    """Stores `str(signal.timeframe)` verbatim (matching `derive_signal_id()`'s
    own identity-hashing input exactly, e.g. `"Timeframe.ONE_MINUTE"` -
    the enum's default `str()`, not `.value`) - widened from an initial
    16-char guess after a real test failure (`DataError: value too
    long`) proved the actual string is longer than assumed."""
    signal_timestamp = models.DateTimeField()
    risk_status = models.CharField(max_length=16)
    risk_reason = models.CharField(max_length=1000, blank=True, default="")
    order_status = models.CharField(max_length=32, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "persistence"
        indexes = [models.Index(fields=["-signal_timestamp"])]
        ordering = ["-signal_timestamp"]
