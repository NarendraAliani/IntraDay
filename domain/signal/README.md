# domain/signal

> Architecture placeholder — no business logic. Created during the foundational architecture checkpoint.

## Responsibility

Canonical Signal object location (Section 8): signal_id, strategy_id/version, instrument, timing, direction, entry/stop/targets, score, confidence, contributing factors, regime, session, risk/reward, quantity, status, verification, expiry. Object itself is not implemented yet.

## Depends On

domain/shared_kernel, domain/strategy, domain/instrument

## Must Not Depend On

Risk engine implementation, order management implementation

