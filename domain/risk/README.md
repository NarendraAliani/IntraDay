# domain/risk

> Architecture placeholder — no business logic. Created during the foundational architecture checkpoint.

## Responsibility

Canonical risk contracts (limits, exposure rules, kill-switch triggers) that every order must pass through (Rule 5.2). No strategy may bypass this contract.

## Depends On

domain/shared_kernel, domain/portfolio

## Must Not Depend On

Strategy-specific logic

