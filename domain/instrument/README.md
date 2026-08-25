# domain/instrument

> Architecture placeholder — no business logic. Created during the foundational architecture checkpoint.

## Responsibility

Canonical instrument-identity contracts. Two sibling identities live here (Checkpoint 64.77 product-scope resolution): `Instrument` for NSE cash equities and reference indices, and `OptionContract` for NSE **stock options** — the platform's primary tradable instrument. `Instrument` still does not represent derivatives, by design: an option's identity is (underlying, expiry, strike, CE/PE), which the flat symbol-based equity contract cannot express, so options get their own contract rather than nullable derivative columns on the shared one. Index options (OPTIDX) are parseable but excluded from the active universe; BSE derivatives, futures, commodities, currency and crypto remain out of scope.

## Depends On

domain/shared_kernel

## Must Not Depend On

Derivatives, commodities, currency, crypto instrument types

