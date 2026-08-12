# signal_intelligence/signal_verification

> Architecture placeholder — no business logic. Created during the foundational architecture checkpoint.

## Responsibility

Verifies realized signal outcomes against theoretical expectation for ongoing
strategy trust scoring. **Answers "was the strategy wrong?"** — compares
`domain/signal`'s original prediction against
`signal_intelligence/theoretical_outcome`'s idealized MFE/MAE/conditional
expectancy, independent of how (or how well) any resulting order was
executed. See Checkpoint 2 Section 5 for the companion "was execution poor?"
question, answered instead by `trading_engine/execution_management` and
`domain/trade` (execution slippage vs. order intent), never by this
directory.

## Depends On

signal_intelligence/theoretical_outcome, domain/signal

## Must Not Depend On

Execution concerns

