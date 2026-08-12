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

from django.db import models


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
