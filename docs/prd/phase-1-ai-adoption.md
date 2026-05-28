# contract-payment-flow — Phase 1 PRD: AI Adoption

| | |
|---|---|
| **Product** | `contract-payment-flow` — post-award contract administration platform |
| **Aspect** | `post-award-contract-administration` (anchor: WAWF) |
| **Phase** | Phase 1 — AI Adoption |
| **Status** | Living draft — refined in planning sessions |
| **Owner** | Pair 2 |
| **Last updated** | 2026-05-28 |

> **This is a PRD, not a plan.** It states the problem, goals, boundaries, and
> what "done" looks like — the *what* and *why*. The *how* (endpoints, schemas,
> retrieval approach, gate primitives, thresholds) is left to the planning
> sessions and captured as ADRs. Requirements will change as we learn; material
> changes land in the [Change log](#13-change-log), and the
> [Open questions](#11-open-questions--to-plan) are the standing handoff to planning.

**Source of truth:** aspect commitment → [`../adrs/0001-post-award-contract-administration-commitment.md`](../adrs/0001-post-award-contract-administration-commitment.md) ·
rename trail + entities → [`../../domain-mapping.md`](../../domain-mapping.md) ·
inherited debt → [`../brownfield-debt.md`](../brownfield-debt.md) +
[`../pair-unique-debt.md`](../pair-unique-debt.md) · corpus → FAR Part 42
(Administration) + 43 (Modifications) + 32 (Financing) · scope caps →
`training-resources/instructor-handbook/per-pair-scope-boundaries.md`.

---

## 1. Background / sponsor objective

The sponsor mandate, as received:

> *"Our CORs and contracting officers spend days drafting the rationale for every
> contract modification and chasing invoice anomalies by hand. We want to pilot AI
> to draft modification rationales, surface precedent from past mods, and flag
> invoice anomalies — without an OIG or DCAA auditor ever being able to say the
> system authorized a payment or executed a modification a human was supposed to,
> or cited a FAR clause that doesn't exist."*

That is the whole brief. It doesn't say which endpoints, which models, what
"precedent" means, or where a human must stay in the loop — that's ours to plan.
Phase 1 disseminates it to a single intent: **introduce AI into the
modification-request → performance-monitoring → invoice-processing workflow, with
every payment- or modification-authorizing (irreversible) action routed through a
human, and every AI output traceable to a real FAR clause and an accountable
actor.**

Phase 1 is **adoption**, not modernization. We add AI on top of the platform as
it stands; fixing the legacy stack is Phase 2 (§12).

## 2. Current state

`contract-payment-flow` was generated from the `acquire-gov` template and carries
the same four-service shape, renamed to the post-award domain:

| Service | Stack | Port |
|---------|-------|------|
| `frontend/` | Angular 17 SPA — COR/CO UX | 4200 |
| `services/api-gateway/` | Spring Boot 2.7.18 + OAuth2 Resource Server (Java 11) | 8080 |
| `services/contract-modification-service/` | Spring Boot 2.7.18 + Postgres + MongoDB (Java 11) | 8081 |
| `services/invoice-review-service/` | Spring Boot 2.7.18 (Java 11) | 8082 |
| `services/ai-orchestrator/` | Python 3.11 + FastAPI + LangChain v1.0 (Bedrock) | 8000 |

(A `closeout-service` is anticipated but not yet scaffolded — long-retention,
audit-heavy; added in planning if needed.)

The platform runs, but the AI path today returns **raw, ungrounded model output
with no validation** — it will confidently cite a FAR Part 43 clause that doesn't
apply or doesn't exist in a modification rationale. That is the audit-defensibility
problem the sponsor named, and it's the thread Phase 1 pulls.

The platform carries **12 inherited debt items** ([`brownfield-debt.md`](../brownfield-debt.md))
shared with all pairs, plus **5 pair-unique items** ([`pair-unique-debt.md`](../pair-unique-debt.md)).
Adoption work surfaces — and may incidentally close — a few; deliberate
modernization of the rest is Phase 2.

> **Domain note:** post-award is **idempotency-dominated** — invoice processing
> must never double-pay — and **audit-completeness-dominated** (every modification
> and invoice is DCAA-auditable, 5+ year retention). Those NFRs shape Phase 1's
> HITL and audit requirements more than throughput does.

## 3. Goals

| # | Goal | Done = |
|---|------|--------|
| G1 | Speed up modification-rationale drafting | A COR/CO gets an AI-drafted modification rationale from a stated reason, on demand. |
| G2 | Ground every AI judgment in real FAR | Rationales and precedent answers cite the actual FAR Part 42/43/32 source; ungrounded ones are withheld, not shipped. |
| G3 | Make modification + invoice assistance safe | The flow runs with a human gate on every payment- or modification-authorizing (irreversible) step; no double-pay. |
| G4 | Be auditable by default | Every AI-assisted decision is reconstructable for DCAA/OIG: who, what, when, under which authority. |
| G5 | Be measurably correct | AI quality is gated by automated evaluation, and regressions are caught before they ship. |

## 4. Non-goals (Phase 1)

Boundaries are deliberate and sharp. Out of scope (most are Phase 2 or out-of-cohort):

- ❌ Framework/runtime modernization (Spring Boot/Java/`javax`→`jakarta`/AWS SDK hops).
- ❌ AI-security hardening of inherited debt; full multi-tenant isolation; AIOps/observability rollout.
- ❌ **Real payment authorization / Treasury IPAC** integration — simulated via mock services only.
- ❌ DCAA audit-response workflows (a separate aspect).
- ❌ Contract-creation / solicitation drafting (Pair 1 / training-project turf — this work is strictly **post-award**).
- ❌ Vendor CPARS narrative drafting (a separate aspect).
- ❌ Real DUNS / SAM.gov vendor verification (mock only).
- ❌ Closeout / deobligation workflows (would balloon to the whole contract lifecycle).
- ❌ Live PII — synthetic data only. Angular major-version hop. Managed Bedrock products.

## 5. Users

| Persona | Role | What Phase 1 gives them |
|---------|------|--------------------------|
| **Contracting Officer's Representative (COR)** | Monitors performance; initiates mods | AI-drafted modification rationales + precedent to review. |
| **Contracting Officer (CO)** | Holds the warrant; executes mods | Approval authority on every modification and any payment-affecting action — only the CO executes a mod (FAR 43.102). |
| **Vendor program manager** | Submits invoices/requests | Faster, clearer rationale + invoice feedback (via the CO/COR). |
| **DCAA auditor** | After-the-fact accountability | A replayable, complete trail for every modification and invoice, citing the governing clause. |

## 6. Capability requirements

Three capabilities in sequence; each one's gap is why the next exists. Stated as
outcomes — **the planning sessions decide how.** (Aspect agent shape is
**single-agent**.)

### M1 — LLM-assisted modification-rationale drafting
- **REQ-AID-1** The platform drafts a contract-modification rationale from a CO/COR-stated reason, surfacing the relevant FAR Part 43 references. *Done:* a CO/COR gets a reviewable draft rationale on demand.
- **REQ-AID-2** AI output is safe to consume — no malformed or ungrounded content silently passes downstream. *Done:* bad model output is caught before it reaches another service or the CO.
- **REQ-AID-3** AI usage is cost-controlled and observable. *Done:* cost is attributable per tenant/feature and runaway spend is bounded.
- **REQ-AID-4** No modification is issued without CO approval *(HITL)*. *Done:* issuance is impossible without a recorded human decision (FAR 43.102 — only the CO executes mods).

### M2 — Grounded retrieval
- **REQ-RAG-1** Regulatory judgments come from the actual FAR Part 42/43/32 corpus, with citations; prior contract modifications are retrievable to surface precedent. *Done:* every authoritative rationale/answer traces to a source clause or prior mod.
- **REQ-RAG-2** Low-confidence or ungrounded answers are withheld and escalated to a human, never shipped *(HITL)*. *Done:* below-bar answers route to review instead of returning.
- **REQ-RAG-3** One agency can never retrieve another agency's contracts or invoices. *Done:* cross-tenant retrieval is impossible and proven by test.
- **REQ-RAG-4** Retrieval quality is measured and protected from regression. *Done:* an evaluation gate blocks changes that degrade grounding.

### M3 — Assisted modification + invoice-review workflow
- **REQ-AGT-1** A single-agent assist runs modification-rationale drafting and invoice-anomaly flagging on synthetic contracts/invoices. *Done:* the flow runs end to end and produces a draft + flagged anomalies plus a gated authorization step.
- **REQ-AGT-2** Every payment- or modification-authorizing (irreversible) step stops for the CO; the agent cannot pass it, and processing is idempotent (no double-pay) *(HITL)*. *Done:* no code path auto-authorizes a payment/mod, and a replayed invoice does not double-process.
- **REQ-AGT-3** A paused decision survives a real-world human delay (hours or days) and resumes without loss or regeneration. *Done:* a run pauses for CO authorization and resumes intact after a restart.
- **REQ-AGT-4** Every gated decision is auditable for DCAA/OIG — who decided, what they saw, under which authority. *Done:* an auditor can reconstruct each modification/payment decision from the trail alone.
- **REQ-AGT-5** The data answers the relational questions a COR/CO asks (e.g. "every prior mod on this contract and its rationale lineage"). *Done:* the key cross-record question is answerable at interactive speed.

## 7. Principles (cross-cutting)

Non-negotiable; *how* they're implemented is planned.

- **Authority over accuracy.** Gates exist for accountability, not model quality. Payment/modification authorization is a **hard** gate; confidence never downgrades one.
- **Right-sized HITL.** Classify by reversibility × blast-radius. Gate what must be gated — no skipped authorizations, no gate sprawl.
- **Idempotency everywhere on the money path.** No invoice or payment action processes twice.
- **Grounded or withheld.** No authoritative rationale/answer ships without a real citation; when grounding is weak, escalate rather than guess.
- **Auditable by default.** Sensitive/AI-assisted decisions write an append-only, DCAA/OIG-replayable record.
- **Synthetic + FedRAMP-safe.** Synthetic data only; Bedrock is the sole LLM path (ADR `0002`); no direct third-party model API.
- **Eval as the gate.** Quality is proven by automated evaluation in CI, not manual inspection.

## 8. Domain model

Core entities (full inventory in [`domain-mapping.md`](../../domain-mapping.md)):
`ContractModification` (primary) and `InvoiceReview` (review), across stages
**modification-request → performance-monitoring → invoice-processing**. CO/COR
work is relational ("this contract's full modification + invoice lineage"), so the
model must support the key cross-record question at interactive speed (REQ-AGT-5).
The repo also inherits ~15 acquire-gov entities (incl. a legacy `ContractModification`
name collision — see `domain-mapping.md`) as raw material to reconcile in Phase 2 —
not Phase 1 scope.

## 9. Success metrics & Phase 1 exit

Done when the three capabilities work end to end and the following hold (these are
also the gate dimensions):

| Dimension | Exit outcome |
|-----------|--------------|
| Agent-flow architecture | The drafting + invoice-review flow runs end to end on synthetic data and survives a human-delay pause/resume. |
| Federal-authority semantics | Every hard gate names its governing FAR clause (43.102 mod execution; financing under Part 32); no payment/mod can be auto-executed. |
| HITL appropriateness | Gates are right-sized by reversibility × blast-radius — nothing authorizing is skipped; no double-pay; nothing trivial over-gated. |
| Relational integration | The CO/COR's modification-lineage question is answerable within an interactive budget. |
| Debt acknowledgement | The team can name which inherited/unique debt their AI work touched, surfaced, or closed — and which is deferred to Phase 2. |

Product signals: rationale-draft turnaround → minutes (G1); zero ungrounded
authoritative rationales in evaluation (G2); 100% of hard-gate decisions produce
an audit record, zero double-processed invoices (G3/G4).

## 10. Constraints & scope caps

- **One core entity, one workflow-stage MVP.** `ContractModification` + modification-rationale drafting. Other stages are referenced, not built.
- **Post-award only.** No solicitation/contract-creation drift (that's upstream / Pair 1 / training-project).
- **No real authority.** Payment and modification execution are simulated via mock services + audit logs only.
- **Synthetic data only.** No live PII anywhere.
- **Adopt, don't modernize.** Don't pre-fix inherited debt that Phase 2 owns; surface it, note the blast radius, defer it.

## 11. Open questions / to-plan

The deliberate handoff to planning — decided there and captured as ADRs.

- Rationale output schema + the FAR-43 reference fields a CO actually needs.
- Retrieval approach (chunking, embedding, dense/sparse/hybrid, reranking) over FAR Part 42/43/32 + prior mods.
- Precedent signal: how prior-modification similarity is computed and surfaced.
- The "withhold / escalate" confidence bar and how it's measured.
- Idempotency strategy on the invoice/payment path (keys, dedupe window).
- Authorization-gate primitives + how a paused authorization is persisted across a multi-day delay.
- How far correlation/tracing is threaded in Phase 1 vs. deferred to Phase 2.
- Which inherited/unique debt items are in-bounds to close incidentally vs. strictly deferred.

## 12. Phase 2 outline (refined at Phase 1 close-out)

Sketch only. Phase 2 = **modernization + operationalization**: framework/runtime
modernization; strangler-fig migration of legacy invoice-processing PL/SQL to a
modernized service; HITL gates on payment authorization (OWASP LLM06 excessive
agency); AIOps detection of invoice-pattern anomalies indicating vendor distress
or fraud; AI-security hardening of inherited + unique debt; observability;
client deliverability. A dedicated Phase 2 PRD supersedes this section.

## 13. Change log

| Date | Change | Driver |
|------|--------|--------|
| 2026-05-28 | Initial Phase 1 PRD disseminated from sponsor objective (brief altitude). | Phase 1 kickoff |
