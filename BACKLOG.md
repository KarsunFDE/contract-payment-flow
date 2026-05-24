# Stretch Backlog — contract-payment-flow

> Aspirational work items. Pair may pursue any of these for differentiation
> credit in W3 + W6 retro. **Not assessed** — rubric does NOT penalize pairs
> who skip the backlog. Items are defendable on the merits (architecture +
> reasoning) even if unbuilt.
>
> Authored by `pair-brownfield-generator` on 2026-05-24 per D-059.
> Recipe: `cohort_1_pair_2_contract`.

## Items (4 total)

### arch-event-driven-workflow — Event-driven workflow orchestration (Kafka / Kinesis / SQS)

**Category:** architecture
**Difficulty:** substantial
**Aspect fit:** any (rated high for post-award — payment state machine
  is the canonical event-source workload)

Replace synchronous REST chains for contract-modification state transitions
(modification-request → performance-monitoring → invoice-processing → closeout)
with an event bus. Each transition emits an event; downstream services
subscribe. Decouples timing, supports replay, exercises EDA reasoning.

**Why this would be defendable in W3+W6 retro:**

Cohort defends in retro: "what would EDA buy this aspect specifically,
and what's the cost vs current REST orchestration?" Even unbuilt, the
ADR + sequence diagram demonstrate distributed-systems thinking. For
post-award specifically, the modification-state-machine + invoice-payment
sequence are textbook EDA candidates — DCAA audit trail benefits from
immutable event log.

---

### cap-aspect-export-fedramp-package — FedRAMP package export — generate ATO-evidence bundle

**Category:** capability
**Difficulty:** substantial
**Aspect fit:** any (Pair 2 — direct W6 deliverable artifact)

Synthesize a FedRAMP MOD-style evidence package from current
system state: SSP excerpts, audit-log summary, security-control
mappings, vulnerability scan results. Useful for W6 deliverability.

**Why this would be defendable in W3+W6 retro:**

Direct W6 client-deliverability artifact. Pairs who build it
demonstrate "I understand what Karsun customers need at handoff."
For post-award specifically, the long-retention NFR + DCAA-auditable
posture make this a near-mandatory shape — FedRAMP package export
is what the customer asks for when migrating off the legacy stack.

---

### perf-aspect-async-job-queue — Async job queue for slow contract-modification operations

**Category:** performance
**Difficulty:** substantial
**Aspect fit:** any (Pair 2 — slow payment reconciliation is the canonical
  use case)

Convert blocking operations (bulk-export, batch-import, long-RAG
synthesis, slow payment reconciliation runs) to async jobs with status
polling endpoint. Improves perceived latency + frees connection-pool.

**Why this would be defendable in W3+W6 retro:**

Every federal system eventually does this. Pairs who build it have
W5 AIOps SRE-pattern evidence. For post-award specifically, the monthly
invoice-reconciliation batch is a real-world fit — DCAA-style auditors
want a job-status endpoint to query, not a hanging HTTP call.

---

### gov-runbook-as-code — Runbook-as-code: incident response runbooks executable from CLI

**Category:** governance
**Difficulty:** modest
**Aspect fit:** any (Pair 2 — payment-failure runbooks specifically)

Convert ops runbooks (e.g., "Bedrock 429 cascade response", "double-payment
rollback procedure", "invoice-processing pipeline stuck") into
executable scripts with audit logging. Pairs add 2-3 runbooks
for their aspect's likely incidents.

**Why this would be defendable in W3+W6 retro:**

W6 deliverability artifact. Pairs demo "if this incident fires
Sunday 3am, what runs?" — direct Karsun handoff value. For post-award
specifically, the runbook set should include double-payment rollback,
contract-modification version-conflict, and DCAA audit-trail integrity
check.

---

## Items considered but not included

The Pair 2 distribution recipe (`cohort_1_pair_2_contract` in
`stretch-backlog-pool.yml`) lists 5 items. Per the SKILL's
`stretch_backlog_count` parameter (set to 4 for Cohort #1, matching
Pair 1's pattern), we kept the first 4 (the architecture + capability +
performance + governance spread) and deferred:

- `gov-aspect-aiops-cost-dashboard` — Per-tenant AIOps cost dashboard
  (Bedrock + RAG + infra). Pair may add this back if W5 AIOps work
  generates dashboard appetite. Substantial difficulty.

## Cross-pair note

Other pairs in this cohort have different stretch backlogs — overlap is
allowed (these items are aspirational), but each pair's set is curated to
their aspect's fit:

- Pair 1 (grants-portal-modern): cap-aspect-public-api, arch-saga-multi-step-aspect,
  gov-aspect-pii-tokenization, perf-vector-cache-hot-queries
- Pair 3 (foia-response-pipeline): cap-aspect-mobile-friendly-public,
  gov-aspect-data-retention-policy, perf-aspect-search-pgvector,
  gov-aspect-changelog-from-audit

W3+W6 retro discussion: "you took item X — was it worth it? what did you learn?"
