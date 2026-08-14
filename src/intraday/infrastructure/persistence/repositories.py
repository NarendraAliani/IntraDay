# File: src/intraday/infrastructure/persistence/repositories.py
#
# Django-ORM repository implementations (Checkpoint 7) — the ONLY place
# in this codebase that translates between Django model rows and
# domain/application dataclasses. Implements the Protocol interfaces
# declared in intraday.application.repositories. No Django Model,
# QuerySet, or ORM-specific exception crosses any public method's return
# type or raised-exception boundary — Django's IntegrityError is caught
# and re-raised as the technology-neutral DuplicateVersionError.
from __future__ import annotations

import datetime as _dt

from django.db import IntegrityError, transaction

from intraday.application.config_schema.records import (
    RiskConfigurationRecord,
    StrategyConfigurationSnapshot,
    StrategyVersionSnapshot,
    UniverseRecord,
)
from intraday.application.repositories import DuplicateVersionError
from intraday.control_plane.audit.events import ActivationOutcome, AuditEvent
from intraday.domain.risk.contracts import RiskLimits
from intraday.domain.shared_kernel.contracts import (
    Exchange,
    InstrumentId,
    StrategyId,
    Timeframe,
    Version,
)
from intraday.domain.strategy.contracts import StrategyMaturityState, StrategyVersion
from intraday.domain.universe.contracts import Universe, UniverseMember, UniverseMembershipStatus
from intraday.infrastructure.persistence.models import (
    ActiveRiskConfiguration,
    ActiveStrategyVersion,
    ActiveUniverse,
    AuditLogEntry,
    BacktestResultRecord,
    RiskConfigurationVersion,
    StrategyConfigurationRecord,
    StrategyResearchStatusRecord,
    StrategyVersionRecord,
    UniverseVersion,
    WatchlistRecord,
)

# --- Risk configuration ------------------------------------------------------


class DjangoRiskConfigurationRepository:
    """Django ORM implementation of `RiskConfigurationRepository`."""

    def save(self, record: RiskConfigurationRecord) -> None:
        try:
            RiskConfigurationVersion.objects.create(
                risk_configuration_id=record.risk_configuration_id,
                version=record.version.value,
                max_intraday_loss=record.limits.max_intraday_loss,
                max_position_size=record.limits.max_position_size,
                max_per_trade_risk=record.limits.max_per_trade_risk,
                created_at=record.created_at,
            )
        except IntegrityError as exc:
            raise DuplicateVersionError(
                f"risk configuration {record.risk_configuration_id!r} version "
                f"{record.version.value!r} already exists"
            ) from exc

    def get_version(
        self, risk_configuration_id: str, version: str
    ) -> RiskConfigurationRecord | None:
        row = RiskConfigurationVersion.objects.filter(
            risk_configuration_id=risk_configuration_id, version=version
        ).first()
        return _risk_row_to_record(row) if row is not None else None

    def get_active(self, risk_configuration_id: str) -> RiskConfigurationRecord | None:
        pointer = ActiveRiskConfiguration.objects.filter(
            risk_configuration_id=risk_configuration_id
        ).first()
        if pointer is None:
            return None
        return self.get_version(risk_configuration_id, pointer.active_version)

    def list_versions(self, risk_configuration_id: str) -> tuple[RiskConfigurationRecord, ...]:
        rows = RiskConfigurationVersion.objects.filter(
            risk_configuration_id=risk_configuration_id
        ).order_by("created_at")
        return tuple(_risk_row_to_record(row) for row in rows)

    def activate(
        self,
        risk_configuration_id: str,
        version: str,
        *,
        actor: str,
        actor_user_id: int,
        request_id: str,
    ) -> ActivationOutcome:
        """Checkpoint 12: state change + audit append happen inside one
        `transaction.atomic()` block — if the `AuditLogEntry.objects.create()`
        call below fails for any reason, Django rolls back the
        `ActiveRiskConfiguration` write too (verified by
        `test_activation_rolls_back_if_audit_write_fails`). This is the
        ONLY place a risk configuration's active pointer is written, so
        there is no code path that can change it without an accompanying
        audit row landing in the same commit."""
        if not RiskConfigurationVersion.objects.filter(
            risk_configuration_id=risk_configuration_id, version=version
        ).exists():
            # A rejected/failed attempt is recorded in its own,
            # independently-committed write — it must survive even
            # though the activation itself did not happen (Checkpoint 12
            # §9: "the system must not claim success when activation
            # failed," which cuts both ways - a failed attempt is not
            # silently unrecorded either).
            AuditLogEntry.objects.create(
                occurred_at=_dt.datetime.now(tz=_dt.UTC),
                actor_username=actor,
                actor_user_id=actor_user_id,
                action="configuration.activate",
                resource_type="risk_configuration",
                resource_id=risk_configuration_id,
                version_identifier=version,
                previous_version=None,
                outcome=ActivationOutcome.REJECTED.value,
                request_id=request_id,
            )
            raise ValueError(
                f"cannot activate unknown version {version!r} of "
                f"risk configuration {risk_configuration_id!r}"
            )

        with transaction.atomic():
            pointer, created = ActiveRiskConfiguration.objects.select_for_update().get_or_create(
                risk_configuration_id=risk_configuration_id,
                defaults={"active_version": version},
            )
            previous_version: str | None
            if created:
                outcome = ActivationOutcome.ACTIVATED
                previous_version = None
            elif pointer.active_version == version:
                outcome = ActivationOutcome.ALREADY_ACTIVE
                previous_version = version
            else:
                previous_version = pointer.active_version
                pointer.active_version = version
                pointer.save(update_fields=["active_version"])
                outcome = ActivationOutcome.ACTIVATED

            AuditLogEntry.objects.create(
                occurred_at=_dt.datetime.now(tz=_dt.UTC),
                actor_username=actor,
                actor_user_id=actor_user_id,
                action="configuration.activate",
                resource_type="risk_configuration",
                resource_id=risk_configuration_id,
                version_identifier=version,
                previous_version=previous_version,
                outcome=outcome.value,
                request_id=request_id,
            )
        return outcome


def _risk_row_to_record(row: RiskConfigurationVersion) -> RiskConfigurationRecord:
    return RiskConfigurationRecord(
        risk_configuration_id=row.risk_configuration_id,
        version=Version(value=row.version),
        limits=RiskLimits(
            max_intraday_loss=row.max_intraday_loss,
            max_position_size=row.max_position_size,
            max_per_trade_risk=row.max_per_trade_risk,
        ),
        created_at=row.created_at,
    )


# --- Universe -----------------------------------------------------------------


class DjangoUniverseRepository:
    """Django ORM implementation of `UniverseRepository`."""

    def save(self, universe: Universe) -> None:
        import datetime as _dt

        try:
            UniverseVersion.objects.create(
                universe_id=universe.universe_id,
                version=universe.version.value,
                exchange=universe.exchange.value,
                members=[
                    {"instrument_id": str(member.instrument_id), "status": member.status.value}
                    for member in universe.members
                ],
                created_at=_dt.datetime.now(tz=_dt.UTC),
            )
        except IntegrityError as exc:
            raise DuplicateVersionError(
                f"universe {universe.universe_id!r} version {universe.version.value!r} "
                "already exists"
            ) from exc

    def get_version(self, universe_id: str, version: str) -> UniverseRecord | None:
        row = UniverseVersion.objects.filter(universe_id=universe_id, version=version).first()
        return _universe_row_to_record(row) if row is not None else None

    def get_active(self, universe_id: str) -> UniverseRecord | None:
        pointer = ActiveUniverse.objects.filter(universe_id=universe_id).first()
        if pointer is None:
            return None
        return self.get_version(universe_id, pointer.active_version)

    def list_versions(self, universe_id: str) -> tuple[UniverseRecord, ...]:
        rows = UniverseVersion.objects.filter(universe_id=universe_id).order_by("created_at")
        return tuple(_universe_row_to_record(row) for row in rows)

    def activate(
        self, universe_id: str, version: str, *, actor: str, actor_user_id: int, request_id: str
    ) -> ActivationOutcome:
        """Checkpoint 13: mirrors `DjangoRiskConfigurationRepository.activate()`
        exactly — state change + audit append in one `transaction.atomic()`
        block; a rejected (invalid-target) attempt is audited in its own
        independently-committed write, since there is no successful state
        change to couple it to."""
        if not UniverseVersion.objects.filter(universe_id=universe_id, version=version).exists():
            AuditLogEntry.objects.create(
                occurred_at=_dt.datetime.now(tz=_dt.UTC),
                actor_username=actor,
                actor_user_id=actor_user_id,
                action="configuration.activate",
                resource_type="universe",
                resource_id=universe_id,
                version_identifier=version,
                previous_version=None,
                outcome=ActivationOutcome.REJECTED.value,
                request_id=request_id,
            )
            raise ValueError(
                f"cannot activate unknown version {version!r} of universe {universe_id!r}"
            )

        with transaction.atomic():
            pointer, created = ActiveUniverse.objects.select_for_update().get_or_create(
                universe_id=universe_id, defaults={"active_version": version}
            )
            previous_version: str | None
            if created:
                outcome = ActivationOutcome.ACTIVATED
                previous_version = None
            elif pointer.active_version == version:
                outcome = ActivationOutcome.ALREADY_ACTIVE
                previous_version = version
            else:
                previous_version = pointer.active_version
                pointer.active_version = version
                pointer.save(update_fields=["active_version"])
                outcome = ActivationOutcome.ACTIVATED

            AuditLogEntry.objects.create(
                occurred_at=_dt.datetime.now(tz=_dt.UTC),
                actor_username=actor,
                actor_user_id=actor_user_id,
                action="configuration.activate",
                resource_type="universe",
                resource_id=universe_id,
                version_identifier=version,
                previous_version=previous_version,
                outcome=outcome.value,
                request_id=request_id,
            )
        return outcome


def _universe_row_to_record(row: UniverseVersion) -> UniverseRecord:
    members = tuple(
        UniverseMember(
            instrument_id=InstrumentId(entry["instrument_id"]),
            status=UniverseMembershipStatus(entry["status"]),
        )
        for entry in row.members
    )
    universe = Universe(
        universe_id=row.universe_id,
        version=Version(value=row.version),
        exchange=Exchange(row.exchange),
        members=members,
    )
    return UniverseRecord(universe=universe, created_at=row.created_at)


# --- Strategy version -----------------------------------------------------------


class DjangoStrategyVersionRepository:
    """Django ORM implementation of `StrategyVersionRepository`."""

    def save(self, strategy_version: StrategyVersion) -> None:
        import datetime as _dt

        try:
            StrategyVersionRecord.objects.create(
                strategy_id=strategy_version.strategy_id,
                specification_version=strategy_version.specification_version.value,
                code_version=strategy_version.code_version.value,
                configuration_version=strategy_version.configuration_version.value,
                universe_version=strategy_version.universe_version.value,
                timeframe=strategy_version.timeframe.value,
                maturity_state=strategy_version.maturity_state.value,
                created_at=_dt.datetime.now(tz=_dt.UTC),
            )
        except IntegrityError as exc:
            raise DuplicateVersionError(
                f"strategy version identity already exists for {strategy_version.strategy_id!r}"
            ) from exc

    def get_version(
        self,
        strategy_id: str,
        specification_version: str,
        code_version: str,
        configuration_version: str,
    ) -> StrategyVersionSnapshot | None:
        row = StrategyVersionRecord.objects.filter(
            strategy_id=strategy_id,
            specification_version=specification_version,
            code_version=code_version,
            configuration_version=configuration_version,
        ).first()
        return _strategy_row_to_snapshot(row) if row is not None else None

    def get_active(self, strategy_id: str) -> StrategyVersionSnapshot | None:
        pointer = ActiveStrategyVersion.objects.filter(strategy_id=strategy_id).first()
        if pointer is None:
            return None
        return self.get_version(
            strategy_id,
            pointer.active_specification_version,
            pointer.active_code_version,
            pointer.active_configuration_version,
        )

    def list_versions(self, strategy_id: str) -> tuple[StrategyVersionSnapshot, ...]:
        rows = StrategyVersionRecord.objects.filter(strategy_id=strategy_id).order_by("created_at")
        return tuple(_strategy_row_to_snapshot(row) for row in rows)

    def activate(
        self,
        strategy_id: str,
        specification_version: str,
        code_version: str,
        configuration_version: str,
        *,
        actor: str,
        actor_user_id: int,
        request_id: str,
    ) -> ActivationOutcome:
        """Checkpoint 13: mirrors `DjangoRiskConfigurationRepository.activate()`.
        `AuditLogEntry.version_identifier` is a single string column, so
        the 3-tuple identity is flattened to `"{spec}:{code}:{config}"`
        for the audit row only — the domain/application identity itself
        (the 3-tuple passed to/from this method) is never flattened."""
        target_identifier = f"{specification_version}:{code_version}:{configuration_version}"
        if not StrategyVersionRecord.objects.filter(
            strategy_id=strategy_id,
            specification_version=specification_version,
            code_version=code_version,
            configuration_version=configuration_version,
        ).exists():
            AuditLogEntry.objects.create(
                occurred_at=_dt.datetime.now(tz=_dt.UTC),
                actor_username=actor,
                actor_user_id=actor_user_id,
                action="configuration.activate",
                resource_type="strategy_version",
                resource_id=strategy_id,
                version_identifier=target_identifier,
                previous_version=None,
                outcome=ActivationOutcome.REJECTED.value,
                request_id=request_id,
            )
            raise ValueError(
                f"cannot activate unknown strategy version identity for {strategy_id!r}"
            )

        with transaction.atomic():
            pointer, created = ActiveStrategyVersion.objects.select_for_update().get_or_create(
                strategy_id=strategy_id,
                defaults={
                    "active_specification_version": specification_version,
                    "active_code_version": code_version,
                    "active_configuration_version": configuration_version,
                },
            )
            previous_identifier: str | None
            if created:
                outcome = ActivationOutcome.ACTIVATED
                previous_identifier = None
            else:
                current_identifier = (
                    f"{pointer.active_specification_version}:"
                    f"{pointer.active_code_version}:{pointer.active_configuration_version}"
                )
                if current_identifier == target_identifier:
                    outcome = ActivationOutcome.ALREADY_ACTIVE
                    previous_identifier = current_identifier
                else:
                    previous_identifier = current_identifier
                    pointer.active_specification_version = specification_version
                    pointer.active_code_version = code_version
                    pointer.active_configuration_version = configuration_version
                    pointer.save(
                        update_fields=[
                            "active_specification_version",
                            "active_code_version",
                            "active_configuration_version",
                        ]
                    )
                    outcome = ActivationOutcome.ACTIVATED

            AuditLogEntry.objects.create(
                occurred_at=_dt.datetime.now(tz=_dt.UTC),
                actor_username=actor,
                actor_user_id=actor_user_id,
                action="configuration.activate",
                resource_type="strategy_version",
                resource_id=strategy_id,
                version_identifier=target_identifier,
                previous_version=previous_identifier,
                outcome=outcome.value,
                request_id=request_id,
            )
        return outcome


def _strategy_row_to_snapshot(row: StrategyVersionRecord) -> StrategyVersionSnapshot:
    strategy_version = StrategyVersion(
        strategy_id=StrategyId(row.strategy_id),
        specification_version=Version(value=row.specification_version),
        code_version=Version(value=row.code_version),
        configuration_version=Version(value=row.configuration_version),
        universe_version=Version(value=row.universe_version),
        timeframe=Timeframe(row.timeframe),
        maturity_state=StrategyMaturityState(row.maturity_state),
    )
    return StrategyVersionSnapshot(strategy_version=strategy_version, created_at=row.created_at)


# --- Strategy configuration values (Checkpoint 26) ------------------------


def _configuration_row_to_snapshot(
    row: StrategyConfigurationRecord,
) -> StrategyConfigurationSnapshot:
    return StrategyConfigurationSnapshot(
        strategy_id=row.strategy_id,
        specification_version=row.specification_version,
        code_version=row.code_version,
        configuration_version=row.configuration_version,
        parameter_values=dict(row.parameter_values),
        created_at=row.created_at,
        created_by=row.created_by,
    )


class DjangoStrategyConfigurationRepository:
    """Django ORM implementation of `StrategyConfigurationRepository`.
    Append-only: `save()` never updates an existing row - a materially
    different configuration must be saved under a new
    `configuration_version` (Part 11/12); attempting to reuse an
    existing identity raises `DuplicateVersionError`, the same
    technology-neutral error `DjangoStrategyVersionRepository.save()`
    already raises for the analogous case."""

    def save(self, snapshot: StrategyConfigurationSnapshot) -> None:
        try:
            StrategyConfigurationRecord.objects.create(
                strategy_id=snapshot.strategy_id,
                specification_version=snapshot.specification_version,
                code_version=snapshot.code_version,
                configuration_version=snapshot.configuration_version,
                parameter_values=snapshot.parameter_values,
                created_at=snapshot.created_at,
                created_by=snapshot.created_by,
            )
        except IntegrityError as exc:
            raise DuplicateVersionError(
                f"strategy configuration identity already exists for {snapshot.strategy_id!r}"
            ) from exc

    def get(
        self,
        strategy_id: str,
        specification_version: str,
        code_version: str,
        configuration_version: str,
    ) -> StrategyConfigurationSnapshot | None:
        row = StrategyConfigurationRecord.objects.filter(
            strategy_id=strategy_id,
            specification_version=specification_version,
            code_version=code_version,
            configuration_version=configuration_version,
        ).first()
        return _configuration_row_to_snapshot(row) if row is not None else None

    def list_for_strategy(self, strategy_id: str) -> tuple[StrategyConfigurationSnapshot, ...]:
        rows = StrategyConfigurationRecord.objects.filter(strategy_id=strategy_id).order_by(
            "created_at"
        )
        return tuple(_configuration_row_to_snapshot(row) for row in rows)


# --- Backtest results / watchlists / strategy research status (Checkpoint 27) --


class DjangoBacktestResultRepository:
    """Django ORM implementation of `BacktestResultRepository`. Upserts
    by `backtest_id` (the engine's own deterministic hash)."""

    def save(
        self,
        backtest_id: str,
        strategy_id: str,
        payload: dict[str, object],
        *,
        created_by: str,
        created_at: _dt.datetime,
    ) -> None:
        BacktestResultRecord.objects.update_or_create(
            backtest_id=backtest_id,
            defaults={
                "strategy_id": strategy_id,
                "result_payload": payload,
                "created_at": created_at,
                "created_by": created_by,
            },
        )

    def get(self, backtest_id: str) -> dict[str, object] | None:
        row = BacktestResultRecord.objects.filter(backtest_id=backtest_id).first()
        return dict(row.result_payload) if row is not None else None

    def list_for_strategy(self, strategy_id: str) -> tuple[dict[str, object], ...]:
        rows = BacktestResultRecord.objects.filter(strategy_id=strategy_id).order_by("-created_at")
        return tuple(dict(row.result_payload) for row in rows)


class DjangoWatchlistRepository:
    """Django ORM implementation of `WatchlistRepository`."""

    def save(
        self, name: str, owner: str, instrument_ids: list[str], *, created_at: _dt.datetime
    ) -> None:
        WatchlistRecord.objects.update_or_create(
            owner_username=owner,
            name=name,
            defaults={"instrument_ids": instrument_ids, "created_at": created_at},
        )

    def get(self, name: str, owner: str) -> list[str] | None:
        row = WatchlistRecord.objects.filter(owner_username=owner, name=name).first()
        return list(row.instrument_ids) if row is not None else None

    def list_for_owner(self, owner: str) -> tuple[str, ...]:
        rows = WatchlistRecord.objects.filter(owner_username=owner).order_by("name")
        return tuple(row.name for row in rows)

    def delete(self, name: str, owner: str) -> None:
        WatchlistRecord.objects.filter(owner_username=owner, name=name).delete()


class DjangoStrategyResearchStatusRepository:
    """Django ORM implementation of `StrategyResearchStatusRepository`."""

    def get_status(self, strategy_id: str) -> str | None:
        row = StrategyResearchStatusRecord.objects.filter(strategy_id=strategy_id).first()
        return row.status if row is not None else None

    def set_status(self, strategy_id: str, status: str, *, updated_by: str) -> None:
        StrategyResearchStatusRecord.objects.update_or_create(
            strategy_id=strategy_id, defaults={"status": status, "updated_by": updated_by}
        )

    def list_all(self) -> dict[str, str]:
        return {row.strategy_id: row.status for row in StrategyResearchStatusRecord.objects.all()}


# --- Audit (Checkpoint 12, read-only) -----------------------------------------


class DjangoAuditRepository:
    """Django ORM implementation of `AuditRepository`. Read-only by
    design — see that Protocol's docstring for why the write path is not
    exposed here (it lives inside `DjangoRiskConfigurationRepository.activate()`,
    the same transaction as the state change it records)."""

    def list_for_resource(self, resource_type: str, resource_id: str) -> tuple[AuditEvent, ...]:
        rows = AuditLogEntry.objects.filter(
            resource_type=resource_type, resource_id=resource_id
        ).order_by("-occurred_at")
        return tuple(_audit_row_to_event(row) for row in rows)


def _audit_row_to_event(row: AuditLogEntry) -> AuditEvent:
    return AuditEvent(
        actor=row.actor_username,
        action=row.action,
        resource_type=row.resource_type,
        resource_id=row.resource_id,
        version=row.version_identifier,
        previous_version=row.previous_version,
        outcome=ActivationOutcome(row.outcome),
        occurred_at=row.occurred_at,
        request_id=row.request_id,
    )
