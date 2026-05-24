# ADR-0001 — Aspect commitment: post-award-contract-administration

**Status:** Accepted
**Date:** 2026-05-24 (W1 Wed PM, Cohort #1)
**Decision-makers:** Pair 2 + Cohort #1 instructor

## Context

Per D-045 (Karsun-aspect anchoring from Day 1) and D-058 (W1 Thu deadline for
all pair brownfields), each cohort pair commits to a federal-acquisitions aspect
from `skills/scenario-design-planning/references/karsun-domain-aspects.yml`
on W1 Wednesday morning via cohort-wide claim vote.

For Cohort #1, three pair-project repos were pre-created on the KarsunFDE
GitHub org with working titles + anchor descriptions (`grants-portal-modern`,
`contract-payment-flow`, `foia-response-pipeline`). The Wed-AM vote allocated
each pair to one of the three.

## Decision

**Pair 2 commits to `post-award-contract-administration`** as the federal-
acquisitions aspect anchoring all programme work from W1 Thu (Phase 1 start)
through W6 Thu (Final Defense, Cohort #1 = Thu 2 Jul per holiday compression).

The commitment binds:

- Phase 1 (W1 Thu → W3 Fri): AI Adoption into the renamed brownfield —
  LLM-assisted modification-rationale drafting, RAG over FAR Part 42/43/32
  + prior contract modifications for precedent surfacing, single-agent
  invoice-review assistant flagging anomalies.
- Phase 2 (W4 → W6): Modernization driven by Phase-1 discoveries —
  strangler-fig migration of legacy invoice-processing PL/SQL to a modernized
  service; HITL gates on payment authorization (OWASP LLM06 Excessive Agency
  defense); AIOps detection of invoice-pattern anomalies indicating vendor
  distress or fraud.

## Aspect summary (excerpt — full content in `domain-mapping.md`)

| Field | Value |
|-------|-------|
| Primary entity | `ContractModification` |
| Workflow | modification-request → performance-monitoring → invoice-processing → closeout |
| Regulatory anchors | FAR Part 42, FAR Part 43, FAR Part 32 |
| Key stakeholders | COR, CO, vendor program manager, DCAA auditor |
| Agent shape | single-agent (per `karsun-domain-aspects.yml`) |
| Modernization integration target | legacy PL/SQL invoice-processing migration |

## Distinctness from `acquire-gov` training-project

Lifecycle stage is **after** award; vocabulary shifts to modifications +
invoices + closeout. acquire-gov covers the full FAR Part 15 + 42 lifecycle,
but the Pair 2 work anchors specifically on the post-award half:

- Idempotency dominates (invoice processing — no double-pay).
- Audit-trail completeness for every modification + invoice is the Phase 2
  modernization anchor.
- Long retention (5+ years contract life + 3+ years post-closeout audit window)
  makes the closeout-service a distinct concern from active-contract services.

## Consequences

- All pair work tracks against this aspect's regulatory NFRs (FedRAMP MOD,
  long-retention, DCAA-auditable).
- War-room scenarios + scenario-alternatives prompts for Pair 2 will skew
  post-award-flavored (e.g., "DCAA flags a Q3 invoice batch as anomalous —
  what's the runbook?").
- W6 Final Defense uses this aspect's stakeholder vocabulary (CO/COR/DCAA, not
  PI/peer-reviewer or FOIA-officer).

## Related

- D-045 — Karsun-aspect-from-W1-Wed anchoring decision
- D-058 — W1 Thu deadline for pair brownfields
- D-059 — pair-brownfield-generator B1 design (this skill)
- `skills/scenario-design-planning/references/karsun-domain-aspects.yml#post-award-contract-administration`
- `domain-mapping.md` (companion doc — full rename trail + debt inventory)
- `docs/pair-unique-debt.md` (5 pair-unique debt items distinct from baseline)
- `BACKLOG.md` (4 stretch items, opt-in, aspirational)
