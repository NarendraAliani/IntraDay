# ai_agent

> Architecture placeholder — no business logic. Created during the foundational architecture checkpoint.

## Responsibility

AI-agent/project state boundary (Rule 5.7). Defines what AI agents may and may not do; enforced jointly with control_plane/kill_switch and infrastructure/ai_execution_guardrail.

**AI Authority Model, clarified at Checkpoint 2 (Section 11):**

```
AI Agent Capability            Governance / Approval              Trading Authority
(read / propose / analyze)  →  (human or governed process   →    (execute)
ai_agent/proposals,             copies an approved proposal
ai_agent/research_assist        into its real domain home)
```

`ai_agent/` is **write-isolated**: an AI-attributed process may write only
inside `ai_agent/` (its own proposals and session state). It has no write
path — structurally, not merely by convention — into `research/`, `config/`,
`trading_engine/`, or `infrastructure/`. A proposal becomes effective only
when a human (or a governed application process acting under
`application/gateways`) reads it from `ai_agent/proposals` and manually
applies it as a real change in its proper home (e.g. a new
`research/strategy_specifications` entry, a `config/risk` change) — that act
of copying-with-approval *is* the governance gate; there is no separate
"approval" directory because approval is not a data concept, it is an action
performed by an actor outside `ai_agent/`. This gives two independent layers
preventing "AI → Broker direct access": (1) structural — no dependency edge
from `ai_agent/` to `trading_engine/execution_management` or
`infrastructure/brokers` exists in the dependency graph; (2) runtime —
`infrastructure/ai_execution_guardrail` is a second, independent enforcement
point that would still block execution even if (1) were somehow violated by
a future code change.

## Depends On

control_plane/audit

## Must Not Depend On

Live broker execution path, risk engine bypass, deployment gates, authentication

