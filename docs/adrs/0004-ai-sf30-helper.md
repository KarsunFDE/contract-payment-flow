# ADR 0004 — AI-Assisted SF-30 Helper for Post-Award Contract Modifications

Date: 2026-06-02
Status: Proposed
Decision-makers: Pair 2

## Context

Contracting Officers (COs) performing post-award contract modifications under FAR Part 43 / DFARS 243 must complete SF-30 forms. Errors in rationale language, clause citations, and modification justifications create compliance risk and payment delays downstream. The project needs an AI-assisted interface that helps COs draft SF-30 content grounded in the actual FAR Part 42/43/32/52, DFARS 242/243/232, WAWF/PIEE corpus — not free-form generation.

Scope is strictly **post-award modifications** (FAR Part 43 / DFARS 243). Pre-award solicitation amendments (SF-30 "Amendment of Solicitation" use) are **out of scope**.

Human-in-the-loop (HITL) CO approval is a hard compliance gate — not optional, not risk-tiered. Every AI-drafted package must be reviewed and approved by a CO before any record is committed.

## Decision

Deploy an AI Orchestrator (Python/FastAPI, behind the Spring Boot API Gateway per ADR-0001) implementing the following pipeline:

### Model Strategy
- **Primary:** Claude Haiku (via AWS Bedrock, per ADR-0003) for RAG extraction and SF-30 draft field population — cost-minimizing path.
- **Fallback:** Claude Sonnet (via AWS Bedrock) invoked only when Haiku RAG confidence fails first pass and reranking is needed.
- No other model tiers. No auto-escalation beyond Sonnet.

### Pipeline State Order (hard rule, not convention)
```
CO input → retrieve (RAG) → confidence-check → citation-check → threshold-gate → draft → grounded package → CO HITL gate
```
Gate entry is blocked unless grounding metadata has passed threshold. Steps cannot be reordered.

### RAG Grounding Requirements (REQ-RAG-1)
- Corpus: FAR Part 42/43/32/52, DFARS 242/243/232, WAWF/PIEE clause text.
- Confidence threshold: **0.85** — drafts below threshold are withheld, never shipped.
- Every AI-drafted rationale must cite a real FAR/DFARS clause traceable to a retrieved corpus excerpt. The system must never auto-generate a citation it cannot trace to a retrieved source.
- On threshold failure: enter `RAG_FAILED_AWAITING_CO_REVIEW` gate state. Surface failure reason, retry history, and query metadata to CO. Never leave the form blank with only an error message — that path produces no audit record.

### Retry Policy
- Max retries: **4**
- Backoff: exponential with **20% jitter**
- Tests for retry behavior must pass before any AWS Bedrock endpoint is ever called. No exceptions.

### Streaming
- Never emit model tokens to the client before grounding is complete.
- Enforced order: retrieve → confidence-check → citation-check → threshold → THEN stream the validated draft package.
- Ungrounded tokens must never reach the wire.

### CO Gate UI Requirements
Before the CO can take any approval action, the gate UI must display:
- Retrieved FAR/DFARS clause IDs and excerpts
- Citation mapping (which draft text maps to which clause)
- Confidence score
- Model ID and version used

### CO Rejection / Edit Handling
CO reject or edit invalidates prior retrieval entirely. RAG re-runs against the corrected SF-30 scope from scratch. Prior grounding records are marked **superseded and non-reusable** in the audit log. No stale retrieval carries forward.

### Audit Log
- Append-only, DCAA-auditable. Each entry captures: input payload, model ID + version, retrieved FAR/DFARS clauses + excerpts, citations used, CO identity + role + timestamp + decision.
- Must not replicate the audit-log race bug documented in `pair-unique-debt.md`.

## Alternatives Considered

1. **Free-form LLM generation (no RAG grounding).** Rejected — ungrounded FAR/DFARS citations are a compliance violation. CO cannot verify a citation that has no traceable corpus source.
2. **Sonnet for all requests.** Rejected — cost-prohibitive. Haiku handles the common path; Sonnet reserved for confidence-failure reranking only.
3. **Client-side streaming before grounding completes.** Rejected — ungrounded tokens on the wire violate the pipeline state order and create audit gaps.
4. **Risk-tiered HITL (skip CO review for low-risk changes).** Rejected — HITL is a compliance and audit requirement, not a UX optimization. All actions require CO approval regardless of perceived risk level.
5. **Pre-award solicitation amendments.** Out of scope for this ADR. SF-30 amendment-of-solicitation use cases deferred.

## Consequences

- AI Orchestrator service (Python/FastAPI) must expose endpoints consumed by the Angular SPA CO interface.
- FAR Part 42/43/32/52, DFARS 242/243/232, WAWF/PIEE corpus must be embedded and indexed before any Bedrock invocation is attempted.
- Retry policy tests must pass in CI before the Bedrock `.env` bearer token is loaded — enforced by test gate.
- Audit log schema must be defined and versioned before any SF-30 AI-assist flow goes live.
- CO role verification is a prerequisite for accessing the SF-30 helper — unauthenticated or non-CO roles must be rejected at the API Gateway.

## Rollback Story

If RAG grounding proves unreliable against the FAR/DFARS, WAWF/PIEE corpus (persistent sub-threshold confidence), the helper degrades gracefully: present the CO with the raw retrieved clause excerpts and an empty draft field rather than a hallucinated fill. CO completes the form manually. Audit log still captures the retrieval attempt, confidence score, and CO decision. No silent failure path.
