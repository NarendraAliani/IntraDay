# src/intraday/trading_engine/position_management/__init__.py
#
# Checkpoint 42 Part 3-5: the FIRST real code in this bounded context.
# `trading_engine`'s other sub-packages (`risk_engine`, `order_management`,
# `execution_management`, `broker_abstraction`, `session_management`,
# `strategy_execution`) were scaffolded at Checkpoint 4; this is the one
# that was still empty through Checkpoint 41 (`domain.position.contracts`'s
# own docstring named it explicitly: "populated by
# trading_engine/position_lifecycle - a later checkpoint"). Owns the
# managed-position lifecycle (entry -> monitoring -> exit) and the
# deterministic exit-evaluation rules - never broker-specific, never
# strategy-specific (a strategy DECLARES an `ExitPlan`; this package
# EVALUATES it against a current price, exactly the "broker executes
# orders, the strategy/risk/position layer determines WHY" separation
# Checkpoint 42 Part 4 requires).
