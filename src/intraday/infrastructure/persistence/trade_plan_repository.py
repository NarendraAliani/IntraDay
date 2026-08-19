# File: src/intraday/infrastructure/persistence/trade_plan_repository.py
#
# Checkpoint 64.7: Django ORM implementation of `TradePlanRepository`.
from __future__ import annotations

from intraday.application.repositories.trade_plan import TradePlanRecordView
from intraday.infrastructure.persistence.models import TradePlanRecord
from intraday.trading_engine.strategy_execution.contracts import TradePlan


def _to_view(row: TradePlanRecord) -> TradePlanRecordView:
    return TradePlanRecordView(
        signal_id=row.signal_id,
        strategy_id=row.strategy_id,
        code_version=row.code_version,
        calculation_method=row.calculation_method,
        entry_price=row.entry_price,
        stop_loss=row.stop_loss,
        target_1=row.target_1,
        target_2=row.target_2,
        target_3=row.target_3,
        trailing_stop_loss=row.trailing_stop_loss,
        generated_at=row.generated_at,
    )


class DjangoTradePlanRepository:
    def save(self, signal_id: str, plan: TradePlan) -> TradePlanRecordView:
        row, _created = TradePlanRecord.objects.update_or_create(
            signal_id=signal_id,
            defaults={
                "strategy_id": plan.strategy_id,
                "code_version": plan.code_version,
                "calculation_method": plan.calculation_method,
                "entry_price": plan.entry_price,
                "stop_loss": plan.stop_loss,
                "target_1": plan.target_1,
                "target_2": plan.target_2,
                "target_3": plan.target_3,
                "trailing_stop_loss": plan.trailing_stop_loss,
                "generated_at": plan.generated_at,
            },
        )
        return _to_view(row)

    def get_by_signal_id(self, signal_id: str) -> TradePlanRecordView | None:
        row = TradePlanRecord.objects.filter(signal_id=signal_id).first()
        return _to_view(row) if row is not None else None


__all__ = ["DjangoTradePlanRepository"]
