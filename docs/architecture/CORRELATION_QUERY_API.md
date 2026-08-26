# Correlation Query API (Checkpoint 64.82)

**This API exposes recorded relationships. It does not establish causality
beyond the relationships already represented in the domain.**

Read that sentence before reading anything else on this page. Every value
returned here is a stored identifier that some other part of the platform
already wrote. Nothing on this surface is derived, inferred, matched by
timestamp or price, or reconstructed by similarity.

## Why it exists

Checkpoint 64.81 made the traceability chain mechanically joinable by adding
`SignalRecord.scan_run_id`, `SignalRecord.strategy_version_identifier`,
`PaperTradeRecord.signal_id`, and canonical `field_id` on evidence rows. But
nothing could *traverse* that chain over HTTP: a researcher had to page the
signals API, then the orders API, then the trades API, and re-join by hand on
the client — a per-signal fan-out that neither scaled nor was auditable.

This checkpoint adds the traversal, server-side, in bounded queries, as a
**read model**. It creates no table, no migration, no write path, and no
second source of truth.

## Endpoints

All four are `GET`-only and require an authenticated session.

| Endpoint | Answers |
| --- | --- |
| `GET /api/v1/correlation/signals/{signal_id}/trace/` | The complete recorded lineage of one signal |
| `GET /api/v1/correlation/runs/{scan_run_id}/signals/` | Every signal recorded against one scanner run, each as a full trace |
| `GET /api/v1/correlation/strategies/{strategy_id}/configurations/{specification_version}/{code_version}/{configuration_version}/trace/` | One configuration, the features it requires, and the signals of its exact version |
| `GET /api/v1/correlation/trades/{trade_id}/trace/` | Reverse lookup: realised outcome back to the decision |

### Why only four

The checkpoint directive listed six candidates. `signals/{id}/orders/` and
`signals/{id}/trades/` are deliberately **not** built: both are strict subsets
of `signals/{id}/trace/`, which already returns `orders[]` and `trades[]` in
the same round trip at the same query cost. Adding them would create two more
contracts and two more OpenAPI schemas to keep consistent, for zero
information a caller cannot already obtain.

`trades/{id}/trace/` — listed as optional — *is* built, because outcome →
decision is a genuinely different traversal direction that no other endpoint
provides.

## Traversal rules

```
scan_run_id ──► SignalRecord.scan_run_id            (exact equality)
signal_id   ──► SignalEvidenceRecord.signal_id      (exact equality)
signal_id   ──► PaperOrderRecord.signal_id          (exact equality)
signal_id   ──► PaperTradeRecord.signal_id          (exact equality)
strategy version ──► SignalRecord.strategy_version_identifier (exact equality)
trade_id    ──► PaperTradeRecord.signal_id ──► the signal trace
```

Every arrow is string equality on a stored identifier. There is no `LIKE`, no
fuzzy match, no timestamp window, and no instrument-plus-time heuristic
anywhere in `correlation_repository.py`. A test seeds a manual trade that
shares instrument, direction, and timestamp with a real signal and asserts the
trace still reports `signal_id: null`.

## Null / missing-relationship semantics

| Field | `null` / `[]` means |
| --- | --- |
| `scan_run_id` | The signal was genuinely not produced by a tracked scanner run — replay sessions and direct service calls are real, supported workflows — or it predates 64.81 |
| `strategy_version_identifier` | Recorded before version tracking existed. **Never** back-filled from the strategy's current active version, which would attribute a past decision to code that did not make it |
| `evidence` (`[]`) | No evidence row exists. This is *not* a claim that no feature was involved |
| `evidence[].field_id` | The row carries no feature name, or the name resolves to no registered field. Legacy two-element `[label, value]` rows are always `null` here |
| `orders` / `trades` (`[]`) | No paper order/trade carries this signal's id |
| `realized_pnl` | **No trade is linked.** Deliberately distinct from `0`, which means a linked trade that broke even. A test asserts both states are separable on the wire |
| `signal_id` on a trade trace | A manually-submitted trade, or one predating 64.81. The traversal stops there |
| `scan_started_at` / `timeframe` / `status` on a run | The scanner-progress singleton no longer holds this run's id (each run overwrites it). `run_metadata_available: false` says so explicitly — the platform genuinely does not retain per-run scanner history |

An unknown `scan_run_id` returns `signal_count: 0` rather than a 404: stored
data cannot distinguish "this run produced no signals" from "this run id never
existed", and inventing that distinction would be a fabricated fact.

## Required features vs. explaining evidence vs. causality

Three different things, kept apart on purpose:

- **`required_features`** is a *declaration by the configuration*. It is what
  the strategy's own `required_features(config)` returns — computed by calling
  the strategy, never reimplemented. It says nothing about any particular
  signal.
- **`evidence`** is what the strategy *chose to cite* for one specific signal.
- **Causality** is claimed by neither. A strategy may REQUIRE a feature without
  ever CITING it, and citing a feature is not proof it caused the decision.

The two lists are returned separately and are never merged. A test asserts a
signal citing nothing keeps an empty `evidence` list even when its
configuration requires features.

## Market Data → Outcome

Every trace carries `market_data_outcome_status`.

**Updated by Checkpoint 64.83.** 64.82 always returned the placeholder
`"ARCHIVE_API_NOT_IMPLEMENTED"` because no archive API existed to consult.
64.83 built that API and the field is now resolved against the real 64.73
archive projection, taking one of `ARCHIVE_NOT_AVAILABLE`, `ARCHIVE_PARTIAL`,
`ARCHIVE_COMPLETE_NOT_RECONCILED`, `ARCHIVE_RECONCILED`, or
`ARCHIVE_RECONCILIATION_FAILED`.

It reports whether archived market-data evidence exists for the *same*
instrument and *same* trading date as the decision — correlation, not
causality. It does **not** claim the strategy read that data, that the data
produced the signal, or that it caused the realised P&L; the platform stores
no such link.

See `MARKET_DATA_ARCHIVE_QUERY_API.md` for the full semantics.

## Authorization and security

Every view is `IsAuthenticated`, matching the read-only `signal_views`,
`paper_trading_views`, and `strategy_configuration_views` endpoints these
responses are composed from. No new auth mechanism and no new capability token
were introduced. The data returned is the same data those endpoints already
expose to any authenticated user — this checkpoint changes the *shape* of the
answer, never who may ask.

No credential, Dhan token, secret, or internal stack trace is reachable from
any response: no such field is read by the read model, and unknown ids return
a structured `ApiError` body, never a traceback. Write verbs return `405`.

## Performance

| Path | Queries |
| --- | --- |
| Single signal trace | 4, fixed, regardless of order/trade/evidence count |
| Scan run trace (N signals) | 5, fixed, regardless of N |
| Strategy configuration trace | Bounded, independent of signal count |

All related rows are fetched with `__in` lookups and grouped in memory — never
one query per signal. `signal_id` is unique or indexed on every table
involved, and `scan_run_id` is indexed, so these remain index lookups as the
tables grow.

`test_m_scan_run_trace_query_count_is_bounded_and_independent_of_signal_count`
measures the query count for a 2-signal run and a 12-signal run and asserts
they are **identical**. That is a stronger guarantee than pinning one magic
number: it fails for any implementation whose cost grows with N, while
remaining stable if an unrelated query is legitimately added to the path.

## Gainz

Gainz remains disabled and unimplemented, and no Gainz-specific query path
exists here. This read-only correlation API is nonetheless the intended
foundation for future Gainz attribution: attribution requires exactly this
chain — decision → version → evidence → outcome — and it must be built on
recorded relationships rather than on inferred ones, which is why the "never
fabricate a link" rule is enforced by tests rather than by convention.

## NSE_FNO

Frozen and untouched. No option, OI, IV, Greeks, or option-chain data is read
or referenced by this surface.
