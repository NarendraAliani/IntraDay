# infrastructure/ai_execution_guardrail

> Architecture placeholder — no business logic. Created during the foundational architecture checkpoint.

## Responsibility

Infra-level enforcement point ensuring AI agents cannot reach live broker execution, risk bypass, or audit bypass (Rule 5.7), independent of application-level guardrails in ai_agent/guardrails.

## Depends On

trading_engine/risk_engine, control_plane/kill_switch, control_plane/audit

## Must Not Depend On

Direct AI-to-broker execution path

