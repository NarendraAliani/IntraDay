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

from django.db import IntegrityError, transaction

from intraday.application.config_schema.records import (
    RiskConfigurationRecord,
    StrategyVersionSnapshot,
    UniverseRecord,
)
from intraday.application.repositories import DuplicateVersionError
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
    RiskConfigurationVersion,
    StrategyVersionRecord,
    UniverseVersion,
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

    def activate(self, risk_configuration_id: str, version: str) -> None:
        with transaction.atomic():
            if not RiskConfigurationVersion.objects.filter(
                risk_configuration_id=risk_configuration_id, version=version
            ).exists():
                raise ValueError(
                    f"cannot activate unknown version {version!r} of "
                    f"risk configuration {risk_configuration_id!r}"
                )
            ActiveRiskConfiguration.objects.update_or_create(
                risk_configuration_id=risk_configuration_id,
                defaults={"active_version": version},
            )


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

    def activate(self, universe_id: str, version: str) -> None:
        with transaction.atomic():
            if not UniverseVersion.objects.filter(
                universe_id=universe_id, version=version
            ).exists():
                raise ValueError(
                    f"cannot activate unknown version {version!r} of universe {universe_id!r}"
                )
            ActiveUniverse.objects.update_or_create(
                universe_id=universe_id, defaults={"active_version": version}
            )


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
    ) -> None:
        with transaction.atomic():
            if not StrategyVersionRecord.objects.filter(
                strategy_id=strategy_id,
                specification_version=specification_version,
                code_version=code_version,
                configuration_version=configuration_version,
            ).exists():
                raise ValueError(
                    f"cannot activate unknown strategy version identity for {strategy_id!r}"
                )
            ActiveStrategyVersion.objects.update_or_create(
                strategy_id=strategy_id,
                defaults={
                    "active_specification_version": specification_version,
                    "active_code_version": code_version,
                    "active_configuration_version": configuration_version,
                },
            )


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
