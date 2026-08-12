# reports

> Architecture placeholder — no business logic. Created during the foundational architecture checkpoint.

## Responsibility

Generated output artifacts (not source of truth; reproducible from research/control_plane per Rule 5.6).

**`reports/` vs. `data/analytics_reports`, clarified at Checkpoint 2 (Section 15):**
`data/analytics_reports` is queryable structured *data* (a metrics/results
table an application can read back and render multiple ways). `reports/`
holds the *finished, human-readable documents* rendered from that data (e.g.
a PDF/HTML/markdown backtest report) — a presentation artifact, not a query
target. Both are downstream of the same source data; neither is authoritative
input to trading logic.

## Depends On

research/research_reports, control_plane

## Must Not Depend On

Being treated as authoritative input

