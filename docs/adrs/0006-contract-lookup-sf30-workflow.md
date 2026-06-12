# ADR 0006 (Alternative) — Contract-Lookup SF-30 Modification Workflow

*An alternative to ADR-0006 — same workflow, contract-number lookup instead of SF-30 upload.*

Date: 2026-06-10
Status: Proposed
Decision-makers: Pair 2
Relationship: **Alternative to ADR-0006** — same workflow, with the **upload + extraction
front end replaced by a contract-number lookup**. Supplements ADR-0004 (AI SF-30 Helper),
ADR-0005 (RAG Retrieval Architecture), ADR-0003 (Bedrock LLM Anchor). The ADR-0006 downstream
(classify → grounded draft → CO gate → submit → audit) is retained unchanged.

> **What changed from ADR-0006.** ADR-0006 had the CO *upload a partially-completed SF-30*,
> then parse it with PyMuPDF. That was circular (the SF-30 is this workflow's *output*) and
> contradicted ADR-0005 §4, which already sources Blocks 1–12 from *structured DB queries
> against the contract record*. This alternative corrects this: the CO **enters a contract
> number**, the system **looks the contract up in the government contract-of-record** and
> auto-fills the static SF-30 blocks. No upload, no PyMuPDF, no OCR, no AGPL dependency.

---

## Context

ADR-0004 established the SF-30 helper pipeline and grounding rules; ADR-0005 built the
retrieval layer and the per-block routing (§4); ADR-0006 specified the agentic LangGraph
workflow. ADR-0006 assumed the CO uploads an SF-30 to be parsed — but the SF-30 is the
document this workflow *produces*, and ADR-0005 §4 already says the static blocks (1–12) come
from the contract record via structured lookup, not from a parsed document.

This ADR defines the corrected front end: the CO **types a contract number and states the
change** (what funding / period-of-performance / scope change is wanted). The system
**resolves the contract number against the government contract-of-record**, auto-fills the
static SF-30 blocks from the authoritative record, classifies the modification type, drafts
the rationale through the ADR-0005 grounded pipeline, and routes the assembled form through
the hard CO approval gate before submission.

Scope remains **strictly post-award contract modifications** (FAR Part 43 / DFARS 243). SF-30
"Amendment of Solicitation" (pre-award) stays out of scope.

Current state (per `docs/retrieval-ingestion-integration-plan.md`, verified on `dev`): corpus
live on Atlas Local, `retrieve_node` implemented with fail-closed audit, confidence/faithfulness
gates specified. The in-system contract-of-record (`Award` / `Contract` / `Vendor` records) is
seeded in fixtures. No contract-lookup endpoint, no agent harness, no form-fill tool layer yet.

---

## Decision

Deploy a LangGraph `StateGraph` (per ADR-0005 §1) in the AI Orchestrator implementing the
workflow below. The input is a **contract number + the CO's stated change**; there is no
document upload.

### Workflow State Order (hard rule, not convention)

```
CO enters contract number + states the change (funding / PoP / scope)
  → lookup_node (resolve contract # against the contract-of-record, agency-scoped)
  → validate_lookup_node (found? exactly one match? within CO's agency?)
  → populate static fields (Blocks 1,2,3,6,7,8,10A,10B,12 from the record)
  → classify_modification_node (Block 13, dense retrieval — ADR-0005 §4)
  → [Block 14 grounded sub-pipeline — ADR-0005 unchanged]
        retrieve_node → confidence_check_node (≥0.85)
        → draft_node (Haiku) → faithfulness_gate_node (≥0.85)
  → assemble_form_node (agent tool calls populate the web form DRAFT)
  → CO HITL GATE (approve / deny)
        deny  → supersede + restart (fresh)
        approve → [if bilateral (FAR 43.103(a)): contractor consent gate
                    — contractor signs Block 15; no consent → not submitted]
                → CO-triggered submit (irreversible, FAR 43.102)
  → audit (append-only, every node)
```

### Workflow Diagram

Each node is tagged with what executes it:
`[AI]` = LLM via Bedrock (Claude Haiku; Sonnet only on confidence-fail rerank),
`[TOOL]` = deterministic / programmatic, `[HUMAN]` = CO action,
`[AI->TOOL]` = AI agent invokes an allow-listed tool.

```
  LEGEND:  [AI] LLM (Bedrock Claude)   [TOOL] programmatic/deterministic
           [HUMAN] CO action           [AI->TOOL] AI agent invokes a tool

                  +-------------------------------+
                  | CO enters contract # + states |
                  |   the change         [HUMAN]  |
                  +---------------+---------------+
                                  |
                                  v
                  +-------------------------------+
                  |   lookup_node          [TOOL] |  query contract-of-
                  |   resolve contract # against  |  record by # via SAM.gov
                  |   the contract-of-record      |  API, programmatically
                  |   (agency-scoped)             |  (MOCK in Phase 1)
                  +---------------+---------------+
                                  |
                                  v
                  +-------------------------------+
                  |   validate_lookup      [TOOL] |  found? one match?
                  |   (no fabrication; flag        |  in CO's agency?
                  |    not-found / ambiguous)     |  else -> CO review
                  +---------------+---------------+
                                  |
                                  v
                  +-------------------------------+
                  |  populate static fields [TOOL]|  Blocks 1,2,3,6,7,8,
                  |  from the contract record     |  10A,10B,12 auto-fill
                  |  (authoritative, not guessed) |  source-of-record cite
                  +---------------+---------------+
                                  |
                                  v
                  +-------------------------------+
                  | classify_modification         |  dense retrieve [TOOL]
                  |   node            [AI->TOOL]  |  feeds Haiku [AI]
                  |   (Block 13, FAR 43.103 A-E)  |  classifier
                  +---------------+---------------+
                                  |
  +===============================v=============================+
  |  Block 14 grounded sub-pipeline   (ADR-0005, verbatim)      |
  |                                                             |
  |   retrieve_node      confidence_check  --( < 0.85 )--+      |
  |     [TOOL]      -->     [AI]                          |      |
  |   (/retrieve:               |                        |      |
  |    hybrid RRF +             | >= 0.85                |      |
  |    cross-encoder,           v                        |      |
  |    no LLM)            draft_node  [AI]               |      |
  |                       (Haiku generates)             |      |
  |                             |                        |      |
  |                             v                        |      |
  |                  faithfulness_gate  --( < 0.85 )--+  |      |
  |                       [AI]   |                    |  |      |
  |                  (RAGAS judge)|                   |  |      |
  +==============================|====================|==|======+
                                 | >= 0.85            |  |
                                 v                    v  v
                  +-------------------------------+   gate_status =
                  | assemble_form_node [AI->TOOL] |   *_AWAITING_
                  |  agent reasons, then calls    |   CO_REVIEW
                  |  allow-listed write tools ->  |       |
                  |  ContractModification DRAFT   |       |
                  +---------------+---------------+       |
                                  |                       |
                                  v                       |
                  +-------------------------------+       |
                  |   CO HITL GATE (hard) [HUMAN] |<------+
                  |  shows: looked-up fields +    |
                  |  source-of-record cite, draft,|
                  |  citations, confidence +      |
                  |  faithfulness, model id       |
                  +------+-----------------+------+
                    deny |                 | approve
                         v                 v
        +----------------------+   +-----------------------------+
        | supersede + restart  |   | bilateral?         [TOOL]   |
        |   [TOOL]             |   | (Block 13 / FAR 43.103)     |
        | audit prior pkg,     |   +----+-------------------+----+
        | re-run from lookup   |   unil |              bilat |
        +----------+-----------+ 43.103(b)          43.103(a)
                   |                 |                    v
                   |                 |    +-----------------------------+
                   |                 |    | contractor consent [HUMAN]  |
                   |                 |    | contractor signs Block 15;  |
                   |                 |    | no consent -> NOT submitted |
                   |                 |    +--------------+--------------+
                   |                 |                   | consent recorded
                   |                 v                   v
                   |        +-----------------------------+
                   |        | CO-triggered submit         |
                   |        |   [HUMAN]->[TOOL]           |
                   |        | irreversible, FAR 43.102,   |
                   |        | DRAFT -> MODIFICATION_REQ   |
                   |        +-----------------------------+
                   |
                   +----------> (loop back to lookup_node)

  Note: a not-found / ambiguous lookup, or a confidence/faithfulness
  failure, does not dead-end -- it sets gate_status and surfaces at the
  CO HITL gate, where the CO may retry, edit manually, or escalate.

  AI vs programmatic summary:
    [AI]       confidence_check, draft_node, faithfulness_gate
               (Bedrock Claude calls)
    [AI->TOOL] classify_modification_node, assemble_form_node
               (agent reasons -> deterministic tool/retrieval)
    [TOOL]     lookup_node, validate_lookup, populate static fields,
               retrieve_node, bilateral/unilateral branch,
               supersede/restart, submit REST write
    [HUMAN]    contract-# entry + change statement, CO HITL gate,
               contractor consent (bilateral only), submit trigger
```

Steps cannot be reordered. The Block 14 sub-pipeline is **ADR-0005 verbatim**. This ADR
replaces ADR-0006's upload/extract front end with the lookup front end; the form-fill tool
layer, CO gate, submit, and audit are otherwise as ADR-0006.

### Model Strategy (inherits ADR-0004 / ADR-0005 — no override)

- **Block 14 draft:** Claude Haiku primary (`draft_node`), Sonnet fallback only on
  confidence-fail rerank.
- **Classification + agent orchestration:** Claude Haiku.
- **Lookup is not an LLM step** — it is a deterministic keyed database query. No model is
  involved in resolving the contract number or filling the static fields.

### Contract Lookup (new — REQ-LOOKUP, replaces REQ-EXTRACT)

The CO enters a **contract number** (the base contract being modified, e.g. `GS-35F-0001V`)
and states the change. `lookup_node` resolves it against the government contract-of-record:

- **Source of record = the SAM.gov API, fetched programmatically.** The contract-of-record is
  resolved through the official **SAM.gov API** — the **Contract Awards API**
  (`open.gsa.gov/api/contract-awards/`) for contract terms + mod history (keyed by PIID) and the
  **Entity Management API** (`open.gsa.gov/api/entity-api/`) for contractor entity data
  (UEI / CAGE / address → Block 8). The fetch is **deterministic backend code in `lookup_node`,
  never an AI/agent tool call** (consistent with "Lookup is not an LLM step"): the agent has no
  SAM.gov tool and cannot widen the query, spoof a record, or cross the agency boundary.
- **Mock-backed in Phase 1 (PRD §4 non-goal).** The PRD lists "Real DUNS / SAM.gov vendor
  verification" as *mock only*. So Phase 1 ships a **mock SAM.gov client that implements the live
  API's request/response shape**, seeded from the in-system `Award` / `Contract` / `Vendor`
  fixtures. Swapping the mock for the live SAM.gov adapter is a **client-internal change**; the
  lookup interface and the workflow do not change.
- **Keyed lookup, not fuzzy extraction.** The contract number either resolves to exactly one
  record or it does not. There is no per-field extraction confidence — the looked-up values
  are authoritative. The failure modes are **not-found**, **multiple matches**, or
  **cross-agency** — each flags to the CO via
  `gate_status = "CONTRACT_NOT_FOUND_AWAITING_CO_REVIEW"`; nothing is fabricated.
- **Agency-scoped (tenant isolation, ADR-0005 §11).** The lookup is filtered to the CO's
  agency — a CO cannot resolve another agency's contract. Enforced in `lookup_node`, not
  trusted from the request.
- **Provenance = source-of-record citation** (not a PyMuPDF bbox). Every auto-filled field
  carries: source system (e.g. `SAM.gov` / `contract-of-record`), record id (e.g. PIID), field
  path, and fetch timestamp. Deterministic and auditable — produced by the lookup, never by
  the LLM.

**What is looked up vs. what the CO provides:**

| SF-30 content | Source |
|---|---|
| Blocks 1, 2, 3, 6, 7, 8, 10A, 10B, 12 (contract id, mod #, dates, offices, contractor, accounting) | **Looked up** from the contract-of-record (mod # = next in the contract's mod history) |
| The change itself — funding delta, PoP change, scope (drives Block 13 + 14) | **CO-stated** — this is new information that does not yet exist in any record |
| Block 13 (13A–13E) modification type/authority | **Classified** by `classify_modification_node` (dense retrieval vs FAR 43.103) |
| Block 14 description / rationale | **RAG-drafted** (ADR-0005 grounded pipeline) |
| Blocks 15–16 signatures | CO / contractor in the UI — never AI-generated |

### Form-Fill Tool Layer (as ADR-0006)

The agent writes to the existing `ContractModification` record via a bounded, allow-listed
tool set (mapping to the real model fields). It writes only a **draft** (`status = "DRAFT"`);
there is **no `submit_modification` tool** — submission is a CO-only UI action (FAR 43.102). It
targets only `ContractModification`, never the pre-award `Amendment` model.

| Tool | Writes (real model fields) | SF-30 block |
|---|---|---|
| `set_modification_basics(...)` | `contractNumber`, `modificationNumber`, `modType`, `farAuthority`, `effectiveDate`, `agencyId` | 1, 2, 3, 10A, 13 |
| `set_funding_pop(...)` | `fundingDelta`, `popStart`, `popEnd`, `contractorConsentRequired` | 12 |
| `set_block_14_rationale(...)` | `description` + `sections.changeNarrative`, `sections.priceCostImpact`, `sections.fundingCitation` | 14 |

### CO Hard Gate (inherits ADR-0004 §CO Gate UI + HITL)

Before any CO action, the gate UI must display:

- The auto-filled Blocks 1–12 **with their source-of-record citation** (system + record id +
  fetch time) and any not-found/ambiguous flags.
- Block 13 classified type/authority + governing FAR 43.103 citation.
- Block 14 draft text, retrieved FAR/DFARS clause IDs + excerpts, citation mapping, confidence
  score, faithfulness score, and model ID + version.

CO actions: **Approve** → for a **unilateral** mod (FAR 43.103(b)) the CO triggers submission
directly (irreversible, recorded); for a **bilateral** mod (FAR 43.103(a)) approval routes
through the contractor-consent gate (below) *before* submission. **Deny** → prior package
invalidated and marked superseded; workflow restarts from `lookup_node`; the supersession event
is audited (never a silent discard).

### Bilateral vs Unilateral — Contractor Consent (new — REQ-CONSENT)

FAR 43.103 splits modifications by who must sign:

- **Bilateral (FAR 43.103(a)) — supplemental agreement.** Signed by **both** the contractor
  and the CO. Used for negotiated equitable adjustments, definitizing letter contracts, and any
  change to terms the contractor must agree to. The contractor's signature (SF-30 **Block 15**)
  is the legal expression of consent.
- **Unilateral (FAR 43.103(b)).** Signed by the CO only — administrative changes, change
  orders, and changes authorized by an existing contract clause (Changes, Options, etc.). No
  contractor consent required.

`classify_modification_node` (Block 13 / FAR 43.103 A–E) already determines the modification
type; it sets `contractorConsentRequired` on the draft via `set_funding_pop`. When that flag is
true, the workflow adds a **contractor-consent gate** on the approve path:

- After the CO approves the assembled package, a bilateral mod **cannot** transition
  `DRAFT → MODIFICATION_REQUEST` until contractor consent (Block 15 signature) is **recorded**
  as an explicit human action. Unilateral mods skip this gate and the CO submits directly.
- **Consent is never AI-generated.** Same bar as the Blocks 15–16 signatures (already never
  AI-generated above) — the agent has no tool to attest, sign, or infer contractor consent. It
  records only an actual contractor signature event captured through the UI.
- **Fail-closed.** A bilateral mod with `contractorConsentRequired = true` and no recorded
  consent is blocked at submission, mirroring the CO-only submit bound. The
  contract-modification-service write path enforces this — the agent is not the boundary.
- The consent event is audited (`contractor_consent_recorded`, below), carrying the contractor
  identity, Block 15 signature reference, and timestamp.

### Pause / Resume, Retry, Context (as ADR-0006)

The CO gate is a LangGraph **interrupt** with a persisted MongoDB checkpoint; a paused package
survives a multi-day delay and a restart and resumes without regeneration on approve (deny
regenerates from scratch). Retry policy inherits ADR-0004/0005 §10 (max 4, backoff + 20%
jitter) and applies to the lookup, Bedrock, and retrieval calls. No summarization/compression
node — the package is small and the full audit trail is retained for DCAA replay.

### Audit Log (inherits ADR-0004 / ADR-0005 §12)

Append-only, DCAA-auditable, correlation_id-threaded. Event types (revised front end):

- `contract_lookup` — contract # queried, source system, record id, fetch timestamp, match
  result (found / not-found / ambiguous / cross-agency-rejected).
- `static_fields_populated` — which blocks were auto-filled from which record + source citation.
- `form_field_written` — which tool wrote which block to the draft.
- `co_decision` — approve/deny, CO identity + role + timestamp.
- `contractor_consent_recorded` — on a bilateral mod, contractor identity, Block 15 signature
  reference, timestamp (the FAR 43.103(a) consent event).
- `package_superseded` — on deny, prior chain marked non-reusable.
- `modification_submitted` — on approve, the irreversible execution record.

---

## State Schema Additions (extends ADR-0005 §1 TypedDict)

| Field | Type | Description |
|---|---|---|
| `contract_number` | string | The base contract # the CO entered |
| `change_request` | dict | CO-stated change (funding delta, PoP, scope) — drives Blocks 13/14 |
| `contract_record` | dict | The looked-up record + source-of-record citation |
| `populated_fields` | dict | Block → {value, source_citation} |
| `form_draft_id` | string | The draft modification record being populated |
| `co_decision` | `pending` \| `approved` \| `denied` | CO gate outcome |
| `modification_bilateral` | bool | FAR 43.103(a) bilateral (consent required) vs (b) unilateral |
| `contractor_consent` | `not_required` \| `pending` \| `recorded` | Block 15 consent state |

`gate_status` gains `CONTRACT_NOT_FOUND_AWAITING_CO_REVIEW` (replacing ADR-0006's
`EXTRACTION_LOW_CONFIDENCE_*`) and `AWAITING_CONTRACTOR_CONSENT`, alongside the ADR-0005
`RAG_FAILED_*` and `FAITHFULNESS_FAILED_*` states.

---

## Code-Grounded Integration Notes (verified on `dev`)

1. **Block 14 must route through the real `/retrieve`, not the brownfield drafter.**
   `POST /draft-contract-modification` (`app/main.py`) is the deliberately-broken stub
   (Item 4/5/6). The agentic `draft_node` consumes the ADR-0005 `/retrieve` read path + the
   Phase-2 gate nodes.
2. **Submit (FAR 43.102) is not enforceable until the write path checks CO role.**
   `ContractModificationController` reads `@RequestHeader(value="X-User",
   defaultValue="anonymous")` — no role check on `create`/`update`/`publish`. **Blocker for
   approve→submit.**
3. **Submit audit must be synchronous + transactional.** `AuditLogger.recordAsync` (Item 2)
   flushes the response before writing and loses the row on crash. `modification_submitted` /
   `co_decision` / `package_superseded` must be written synchronously in-transaction,
   fail-closed.
4. **One identity convention across the seam (B1).** Retrieval uses `X-Tenant-Id` /
   `X-User-Id` / `X-User-Role`; contract-modification-service uses a single `X-User`.
   Standardize on the `/retrieve` convention so correlation_id + role thread intact.
5. **Tenant scoping on both the lookup and the write path (Item 10).** `agencyId` is on the
   model/DTO but unenforced (`listAll()` returns all agencies). The new `lookup_node` *and* the
   form-write path must scope by the gateway-asserted agency, or this workflow re-exposes the
   cross-tenant gap.
6. **The contract-lookup endpoint is net-new.** No current endpoint resolves a contract
   *number* to a full contract-of-record for the AI flow (`GET /api/contract-modifications/{id}`
   is by Mongo id; `Award`/`Contract` have no lookup-by-number controller). Phase 1 backs it
   with a **mock SAM.gov client** shaped to the live SAM.gov API (Contract Awards + Entity
   Management), seeded from the in-system records; the live adapter is a later client-internal
   swap. The fetch is programmatic `lookup_node` code, never an AI tool.

---

## Alternatives Considered

1. **Upload a partial SF-30 + extract (ADR-0006's approach).** Superseded — circular (the SF-30
   is the output), required PyMuPDF + Tesseract OCR + an AGPL dependency, and contradicted
   ADR-0005 §4 (which sources Blocks 1–12 from the contract record). Lookup is authoritative,
   license-free, and §4-consistent.
2. **Live SAM.gov integration in Phase 1.** Rejected for Phase 1 — the PRD §4 marks real SAM.gov
   verification as mock-only, and a live call adds external auth, egress of SBU data, and
   availability risk. The **SAM.gov API is the chosen contract-of-record interface, called
   programmatically** (deterministic `lookup_node`, never the AI); Phase 1 backs it with a mock
   client implementing that API's shape, and the live adapter is a later client-internal swap.
3. **CO types all of Blocks 1–12 manually (no lookup).** Rejected — re-keying authoritative
   contract data is error-prone and the data already exists in the system of record. Lookup
   removes transcription error and grounds the static blocks in the contract record. (Manual
   entry remains the rollback path.)
4. **Ungrounded rationale drafting.** Rejected (ADR-0004 Alt #1) — ungrounded FAR citations are
   a compliance violation. Block 14 stays on the ADR-0005 grounded pipeline.
5. **Agent holds a `submit_modification` tool.** Rejected — FAR 43.102 reserves execution to
   the CO. Submission is a CO-only UI action.
6. **Agent attests / auto-populates contractor consent for bilateral mods.** Rejected — a
   bilateral supplemental agreement (FAR 43.103(a)) requires the contractor's actual signature
   (Block 15). Consent is a recorded human act, never AI-generated, held to the same bar as the
   CO-only submit and the never-AI-generated signature blocks. The agent records a real consent
   event; it cannot manufacture one.

---

## Consequences

- The AI Orchestrator gains a `lookup_node` + a contract-of-record client (a **mock SAM.gov
  client** shaped to the live SAM.gov API in Phase 1; live adapter later) and a form-fill tool
  layer. The client is called programmatically — the agent never fetches from SAM.gov.
- **No PyMuPDF, no Tesseract, no AGPL license flag** — the document-parsing dependency and its
  license concern (ADR-0006) are removed entirely. Net simplification.
- **New external-dependency risk (production):** the **SAM.gov API**'s availability + auth (rate
  limits, API key, egress). The lookup must retry (4/backoff/jitter), trip a circuit breaker on
  repeated failure, and write an audit record on every lookup outcome; a failed/ambiguous lookup
  surfaces to the CO and never fabricates a record. The Phase-1 mock client exercises the same
  failure surfaces so the live swap inherits the handling.
- Provenance shifts from PyMuPDF bbox to a **source-of-record citation** (system + record id +
  fetch time); the gate UI must render it so the CO can verify each auto-filled value against
  the system of record.
- **Now consistent with ADR-0005 §4** — Blocks 1–12 come from structured DB lookup exactly as
  §4 specifies (ADR-0006's extraction was the divergence).
- Submission remains CO-only (FAR 43.102), enforced at the API Gateway.
- **Bilateral mods gate on contractor consent.** When `contractorConsentRequired` is true (FAR
  43.103(a)), the contract-modification-service must persist the consent state and reject
  `DRAFT → MODIFICATION_REQUEST` until a contractor signature (Block 15) is recorded —
  fail-closed, mirroring the CO-only submit bound. The `contractorConsentRequired` field already
  exists on the model; the consent-state persistence and the gate check are new.
- All ADR-0004 / ADR-0005 gates (confidence 0.85, faithfulness 0.85, retry tests, audit schema,
  CO role verification) remain prerequisites.

**Hard prerequisites before approve→submit can go live** (existing brownfield debt this
workflow forces closed on the write path):

- CO-identity verification on `create`/`update`/`publish` (close the anonymous-default header
  gap).
- Synchronous + transactional + fail-closed audit for the submit/decision/supersede events
  (replace `recordAsync`).
- One gateway-asserted identity convention across services (B1).
- Agency scoping on the `lookup_node` and the write path (Item 10).
- A new contract-lookup endpoint (by contract number) + the contract-of-record client.

## Rollback Story

If the lookup proves unreliable or the contract-of-record is unavailable, the workflow degrades
gracefully: the CO enters Blocks 1–12 manually (the existing SF-30 wizard already supports
manual entry). The Block 14 grounded pipeline (ADR-0005) is unaffected and still drafts from the
CO's stated change. The audit log still records the lookup attempt, the source-of-record
citation (or its absence), and the CO decision. No silent failure path — a failed lookup falls
back to manual entry, never to a fabricated contract record.
