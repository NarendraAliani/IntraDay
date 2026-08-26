# Correlation Traceability

**Introduced:** Checkpoint 64.81
**Scope:** metadata only. Nothing in this document changes a trading
decision, a computed feature value, a risk outcome, a fill, or a P&L
number. Every mechanism described here EXPOSES or PERSISTS a
relationship that the platform already made; none of it creates one.

---

## The one rule

> An identifier is either genuinely traceable, or it is `null`.

There is no third option. No component described here infers an
identifier from a label, a name, a timestamp proximity, or a string
match. Where a relationship cannot be proven from data the platform
already recorded, the field is left blank and serialized as `null`.

This is the data-model-level continuation of Checkpoint 64.80-F3's
"never invent a correlation" rule. It is also why **no data migration
back-fills historical rows**: nothing stored on a pre-64.81 record could
prove which scan run, signal, or strategy version produced it, and a
plausible guess is precisely the failure mode this layer exists to
prevent.

---

## The chain

```
Market Data -> Features -> Strategy (config + version) -> Scanner Run
            -> Signal -> Paper Order -> Paper Trade -> Outcome
```

Status of each link **after** Checkpoint 64.81. These labels are
deliberately conservative — the chain is *not* complete end to end.

| Link | Status | Mechanism |
|---|---|---|
| Market Data -> Features | **FOUND** | Feature engine computes from `Bar`; unchanged. |
| Market Data -> Scanner | **FOUND** | Scanner reads the same closed-bar set; unchanged. |
| Features -> Strategy | **FOUND** *(was PARTIAL)* | `required_features(config)` exposed on the strategy-configuration API, resolved to canonical `field_id`. |
| Features -> Scanner | **NOT APPLICABLE** | The scanner does not select on features. |
| Features -> Signal | **PARTIAL** *(was NOT AVAILABLE)* | Signal evidence now carries `feature_name` + `field_id`. Partial because evidence covers only the features a strategy chose to *explain* with, not every feature it read. |
| Scanner -> Strategy | **FOUND** | Worker fans out per strategy; unchanged. |
| Scanner Run -> Signal | **FOUND** *(was PARTIAL)* | `SignalRecord.scan_run_id` propagates the existing `ScannerScanProgress.scan_id`. |
| Strategy -> Signal | **FOUND** | `derive_signal_id()` hashes all three version components; unchanged. |
| Signal -> Paper Order | **FOUND** *(was PARTIAL)* | `PaperOrderRecord.signal_id` existed since Checkpoint 36; now exposed on the API. |
| Signal -> Paper Trade | **FOUND** *(was PARTIAL)* | `PaperTradeRecord.signal_id`, resolved by ID join from the trade's own entry order. |
| Paper Trade -> Strategy Version | **FOUND** *(was NOT FOUND)* | `strategy_version_identifier` on both order and trade. |
| Paper Trade -> Outcome | **FOUND** | Realised P&L already on `PaperTradeRecord`; unchanged. |
| Market Data -> Outcome (archive-qualified) | **NOT YET IMPLEMENTED** | Requires the archive/reconciliation APIs, deliberately out of scope. |

---

## Feature identity: the `field_id` vs `feature_name` distinction

This distinction is the single most misunderstood part of the platform,
and getting it wrong is what blocked correlation for 80 checkpoints.

- **`field_id`** — a canonical entry in
  `signal_intelligence/feature_engine/field_registry.py`: `"ema"`,
  `"atr"`, `"macd_hist"`, `"close"`. Stable, registered, describable.
- **`feature_name`** — a *parameterized* name a strategy actually asks
  for and that a `FeatureValue` actually carries: `"ema_12"`,
  `"macd_hist_12_26_9"`, `"close"`.

`Strategy.required_features(config)` returns **feature names, not field
IDs** — despite its own docstring historically saying otherwise.
`"ema_12"` is not a key in the registry; `"ema"` is.

Resolution between the two is done by **one** function,
`field_registry.parse_feature_name()`, which strips the suffix of
trailing all-digit segments. That algorithm was not invented for
traceability — it is the exact parse
`application/services/strategy_execution.compute_feature_series()` has
used since Checkpoint 64.49 to dispatch a feature to its compute
function. It was *lifted* into the registry, and the dispatcher now
calls it, so the resolver can never drift from the code that actually
computes the feature.

`resolve_feature_name()` returns `field_id=None` when the parsed kind is
not a registered field. It never guesses.

### Architectural constraint

`.importlinter` contract 4 forbids `intraday.trading_engine` from
importing `intraday.signal_intelligence`. The strategy evidence layer
lives in `trading_engine` and therefore **cannot** resolve `field_id`
itself. So:

- the **strategy** supplies `feature_name`, verbatim from the
  `FeatureValue` it already read (authoritative, never guessed);
- the **infrastructure/API boundary** — permitted to import both —
  resolves `feature_name -> field_id`.

---

## Strategy version identity

The canonical flattened form is:

```
"{specification_version}:{code_version}:{configuration_version}"
```

This is **not new**. It is byte-for-byte the `target_identifier` that
`DjangoStrategyVersionRepository.activate()` already writes into
`AuditLogEntry.version_identifier` (see *Strategy Version identity
flattening* in `AUDITABILITY.md`). Reusing it means a paper P&L row
joins directly to the activation audit trail. No second version scheme
was introduced.

Stored as `strategy_version_identifier` on `PaperOrderRecord` and
`PaperTradeRecord`.

> **Do not confuse this with `PaperPositionRecord.strategy_version`**,
> which predates it and means something narrower — the
> `configuration_version` *alone*. That field's meaning is unchanged.
> The new field is deliberately named differently so that one name never
> carries two business meanings across tables.

---

## Scanner run identity

`ScannerScanProgress.scan_id` already existed (Checkpoint 64.18),
written by the worker as `clock.isoformat()` at the start of each
`aggregate_now()` cycle. Checkpoint 64.81 introduced **no new scanner
identity, model, lifecycle, or scheduling** — it only propagates that
existing value down to the signals a run actually produced, via an
optional `scan_run_id` parameter threaded through
`promote_bars_and_trigger_signals -> run_active_loop_tick ->
evaluate_and_submit -> SignalRecorder`.

Every parameter defaults to `None`, so callers that are genuinely not
scanner runs — the REST-ingestion tick, replay paper sessions, direct
service calls in tests — are unaffected and record no run id.

**Write-once in practice:** `record_signal()` adds `scan_run_id` to its
`update_or_create` defaults *only* when the caller supplied one. A later
re-record of the same deterministic signal from a non-scanner caller
therefore cannot blank the run that genuinely produced it.

---

## Signal -> Paper Trade: why a join, not a new field

`domain.trade.Trade` is produced by the paper broker's own round-trip
matching and already carries the `order_ids` that opened and closed it.
Those orders already store `signal_id` and (as of 64.81)
`strategy_version_identifier`.

`paper_ledger_repository._trade_traceability()` therefore resolves the
trade's identity by **exact `order_id` equality** against the order
ledger at `sync_trades()` time. This is an ID join over a relationship
both sides already record — not inference, not string matching. Where
several of a trade's orders carry a value, the first in `order_ids`
order wins: that is the entry order, the decision the trade is
attributable to.

Threading a second copy through the broker was rejected: a duplicated
field can disagree with the ledger, and the join required **no change
whatsoever** to fill logic, matching, or P&L.

---

## Database fields

All four are additive, blank-default `CharField`s (migration
`0031`). Blank means "no traceable relationship recorded" — the same
meaning `PaperOrderRecord.signal_id` has carried since Checkpoint 36.
The API maps blank to `null`.

| Table | Column | Indexed |
|---|---|---|
| `SignalRecord` | `scan_run_id` | yes |
| `PaperOrderRecord` | `strategy_version_identifier` | no |
| `PaperTradeRecord` | `signal_id` | yes |
| `PaperTradeRecord` | `strategy_version_identifier` | no |

Two fields were **not** added because an audit found they already
existed: `PaperOrderRecord.signal_id` and `ScannerScanProgress.scan_id`.

### Evidence field shape

`SignalEvidenceRecord.fields` is a `JSONField`. Pre-64.81 rows are
2-element `[label, value]`; new rows are 3-element
`[label, value, feature_name]`. Both lengths are decoded by one
function, `evidence_field_to_view()`. `SIGNAL_EVIDENCE_SCHEMA_VERSION`
was deliberately **not** bumped: the shape is a strict superset and
every existing reader keeps working, which is exactly the condition its
own docstring sets for leaving it alone.

---

## Known limitation: `required_features` is not resolvable for every configuration

`required_features()` is specified over a *validated* configuration and
reads values directly (e.g. `require_int(config.values,
"fast_lookback")`). A stored configuration whose values are incomplete,
or whose types no longer satisfy the strategy's *current* schema, makes
it raise — a real possibility, since configurations are immutable while
strategy code keeps evolving.

In that case the API returns `required_features: null`. It does **not**
return `[]`, which would falsely assert "this strategy needs no
features", and it does not invent plausible names. See
`_resolved_required_features()` in `strategy_configuration_views.py`.

---

## Relevance to future research attribution

This layer is a prerequisite for any trustworthy future attribution
analysis, because such analysis asks questions that were previously
unanswerable from stored data:

1. *Which feature values supported this signal?* — needs evidence rows
   keyed by canonical `field_id`, not free-text labels.
2. *Which scanner run and strategy produced it?* — needs
   `scan_run_id` and strategy attribution on the signal.
3. *Which exact version made the decision?* — needs
   `strategy_version_identifier`, so results from two configurations of
   the same strategy are never pooled together.
4. *What happened afterwards?* — needs `signal_id` on the trade so a
   realised P&L row is attributable to the decision that caused it.

Without these, any attribution would have to *infer* the links —
reintroducing exactly the fabricated correlations this platform refuses
to produce.

The specific future-research relevance of this layer is discussed in
`taskReport.md`, which is the artifact this project's own
repository-scanning guards designate for that discussion.
