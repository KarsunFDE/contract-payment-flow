# ADR 0006 — Agentic SF-30 Post-Award Modification Workflow

Date: 2026-06-09
Status: Proposed
Decision-makers: Pair 2
Supersedes: none — supplements ADR-0004 (AI SF-30 Helper), ADR-0005 (RAG Retrieval Architecture), ADR-0003 (Bedrock LLM Anchor)

---

## Context

ADR-0004 established the SF-30 helper pipeline state order and grounding rules.
ADR-0005 built the retrieval layer (`retrieve_node`, confidence gate, faithfulness
gate) and committed Phase 2 (2026-06-10) to wiring `create_agent` + `StateGraph`
into the full state machine. This ADR defines **that agentic layer**: the
end-to-end workflow that takes a CO-uploaded SF-30, populates the contract-
modification web form via agent tool calls, drafts the Block 14 rationale through
the existing grounded pipeline, and routes the completed form through the hard CO
approval gate before submission.

Scope is **strictly post-award contract modifications** (FAR Part 43 / DFARS 243),
SF-30 used as the modification instrument. SF-30 "Amendment of Solicitation"
(pre-award) remains **out of scope** per ADR-0004 Alternative #5 and the PRD
non-goals (solicitation drafting is Pair 1 turf).

This ADR is the **single-agent, tool-using form-fill workflow** for the SF-30
helper. It is distinct from the PRD M3 multi-agent adjudication flow
(anomaly-detector + adjudicator + decision-router for invoice/mod disposition).
M3 decides *whether* an item is auto-approved / escalated / returned; this workflow
*assembles and grounds a single SF-30 modification package* that always terminates
at the CO hard gate.

Current state (per `docs/retrieval-ingestion-integration-plan.md`, verified on
`dev` 2026-06-04): corpus live on Atlas Local (`far_vector_idx` + `far_text_idx`
READY), `retrieve_node` implemented (hybrid RRF + cross-encoder, fail-closed
audit), confidence/faithfulness gates specified. No agent harness, no form-fill
tool layer, no upload-extraction node yet.

---

## Decision

Deploy a LangGraph `StateGraph` (per ADR-0005 §1 — LangGraph is primary
orchestration; `create_agent` is the agent harness built on it) implementing the
following workflow inside the AI Orchestrator (Python/FastAPI, behind the Spring
Boot API Gateway per ADR-0001).

### Workflow State Order (hard rule, not convention)

```
CO upload SF-30
  → extract_node (Blocks 1–12 field values + provenance)
  → validate_extraction_node
  → classify_modification_node (Block 13, dense retrieval — ADR-0005 §4)
  → [Block 14 grounded sub-pipeline — ADR-0005 unchanged]
        retrieve_node → confidence_check_node (≥0.85)
        → draft_node (Haiku) → faithfulness_gate_node (≥0.85)
  → assemble_form_node (agent tool calls populate the web form)
  → CO HITL GATE (approve / deny)
        deny  → supersede + restart from extract_node (fresh)
        approve → [if bilateral (FAR 43.103(a)): contractor consent gate
                    — contractor signs Block 15; no consent → not submitted]
                → CO-triggered submit (irreversible, FAR 43.102)
  → audit (append-only, every node)
```

### Workflow Diagram

Each node is tagged with what executes it:
`[AI]` = LLM call via Bedrock (Claude Haiku; Sonnet only on confidence-fail
rerank), `[TOOL]` = deterministic / programmatic (vector search, threshold check,
tool-call form writes, REST), `[HUMAN]` = CO action. `[AI->TOOL]` = an AI agent
deciding which programmatic tool to call (the reasoning is AI; the write is
deterministic and allow-listed).

```
  LEGEND:  [AI] LLM (Bedrock Claude)   [TOOL] programmatic/deterministic
           [HUMAN] CO action           [AI->TOOL] AI agent invokes a tool

                  +-------------------------------+
                  |   CO uploads SF-30   [HUMAN]   |
                  +---------------+---------------+
                                  |
                                  v
                  +-------------------------------+
                  |   extract_node     [TOOL+AI]  |  A: PyMuPDF [TOOL]
                  |   A: PyMuPDF text+bbox [TOOL] |     text + bbox
                  |   B: Haiku maps spans -> [AI] |  B: Haiku [AI] maps
                  |      Blocks 1-12 fields       |     spans -> fields
                  |   (OCR fallback: Tesseract)   |  bbox = provenance
                  +---------------+---------------+
                                  |
                                  v
                  +-------------------------------+
                  |   validate_extraction  [TOOL] |  threshold + provenance
                  |   (no fabrication; flag low   |  check, deterministic
                  |    confidence)                |
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
                  |  (set_basics / set_funding /  |       |
                  |   set_block_14_rationale)     |       |
                  +---------------+---------------+       |
                                  |                       |
                                  v                       |
                  +-------------------------------+       |
                  |   CO HITL GATE (hard) [HUMAN] |<------+
                  |  shows: extracted fields +    |
                  |  provenance, draft, citations,|
                  |  confidence + faithfulness    |
                  |  scores, model id + version   |
                  +------+-----------------+------+
                    deny |                 | approve
                         v                 v
        +----------------------+   +-----------------------------+
        | supersede + restart  |   | bilateral?         [TOOL]   |
        |   [TOOL]             |   | (Block 13 / FAR 43.103)     |
        | audit prior pkg,     |   +----+-------------------+----+
        | re-run from extract  |   unil |              bilat |
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
                   +----------> (loop back to extract_node)

  Note: a confidence or faithfulness failure does not dead-end --
  it sets gate_status and surfaces at the same CO HITL gate, where
  the CO may retry, edit manually, or escalate.

  AI vs programmatic summary:
    [AI]       confidence_check, draft_node, faithfulness_gate
               (Bedrock Claude calls)
    [TOOL+AI]  extract_node = PyMuPDF text+bbox [TOOL] then Haiku
               span->field mapping [AI]; bbox is the provenance
    [AI->TOOL] classify_modification_node, assemble_form_node
               (agent reasons -> deterministic tool/retrieval)
    [TOOL]     PyMuPDF (+Tesseract OCR fallback), validate_extraction,
               retrieve_node, bilateral/unilateral branch,
               supersede/restart, submit REST write
    [HUMAN]    upload, the CO HITL gate, contractor consent
               (bilateral only), submit trigger
```

Steps cannot be reordered. The Block 14 sub-pipeline is **ADR-0005 verbatim** —
this ADR adds the upload/extract front end, the form-fill tool layer, and the
approve→submit back end around it. No grounding gate is removed or relaxed.

### Model Strategy (inherits ADR-0004 / ADR-0005 — no override)

- **Block 14 draft:** Claude Haiku primary (`draft_node`), Sonnet fallback only on
  confidence-fail rerank. Unchanged from ADR-0004 §Model Strategy and ADR-0005 §4.
- **Extraction + agent orchestration/tool-routing:** Claude Haiku. Extraction is a
  bounded structured-field task; it does not warrant Sonnet.
- No new model tier. No auto-escalation beyond the ADR-0004 Sonnet fallback.

> The originating plan proposed Sonnet for drafting. Rejected — contradicts the
> cost-minimizing Haiku-primary decision in ADR-0004/0005. Haiku stands.

### Upload + Extraction (new — REQ-EXTRACT)

The CO uploads a partially-completed SF-30 (PDF or structured form export). The
`extract_node` parses it into typed Block 1–12 field values in two stages:

- **Stage A — text + coordinates `[TOOL]`: PyMuPDF (`fitz`).** `page.get_text("dict")`
  yields the document's text spans *with bounding boxes* (page index + rect).
  Deterministic, fast, pure-Python, no external service. The bounding boxes are the
  source of the provenance spans below — provenance is produced by PyMuPDF, **not**
  inferred by the LLM.
- **Stage B — semantic field mapping `[AI]`: Haiku.** The LLM maps the extracted
  text spans onto the typed SF-30 Block 1–12 fields. Each mapped value is paired
  with the PyMuPDF bbox it came from.

**OCR fallback (scanned SF-30s).** PyMuPDF does not OCR. A scanned/faxed SF-30 with
no text layer yields no text — `extract_node` falls back to OCR via
`page.get_textpage_ocr()` (PyMuPDF's integrated Tesseract; Tesseract must be
installed in the container). If OCR is also unavailable or low-confidence, the
fields are flagged for manual CO entry — never fabricated.

- **Grounded extraction, never fabrication.** Every extracted value must carry a
  provenance span (PyMuPDF page + bounding region, or source field path) tracing it
  back to the uploaded document. A value that cannot be traced is **not invented** —
  the field is left empty and flagged for CO entry.
- **Per-field confidence.** Each extracted field gets an extraction confidence.
  Below threshold → field flagged `EXTRACTION_LOW_CONFIDENCE`, surfaced to the CO,
  never silently populated.
- **PII handling (per ADR-0005 §6).** Block 8 (contractor name/address) and other
  PII are extracted as plaintext field values only. Extracted PII is **never**
  embedded or sent to the vector index. Block 14 retrieval query is the CO's
  modification intent + non-PII context only.
- **Block routing reuses ADR-0005 §4.** Blocks 1–10/12 map to structured form
  fields from extraction; **Block 13 (13A–13E)** → dense classify (modification
  type/authority); **Block 14** → full hybrid RAG (the rationale narrative).
  Blocks 15–16 (signatures) are never AI-generated. (Blocks 9A/9B and 11 are
  solicitation-amendment items — pre-award, out of scope.)

### Form-Fill Tool Layer (new — REQ-FORM)

The agent populates the contract-modification web form through a **bounded,
allow-listed tool set**, writing to the existing `ContractModification` record in
contract-modification-service via the API Gateway. The tools map extracted/derived
values onto the real model fields (verified on `dev` 2026-06-09 —
`ContractModification.java` + `ContractModificationCreateRequest.java`):

| Tool | Writes (real model fields) | SF-30 block |
|---|---|---|
| `set_modification_basics(...)` | `contractNumber`, `modificationNumber`, `modType`, `farAuthority`, `effectiveDate`, `agencyId` | 1, 2, 3, 10A, 13 |
| `set_funding_pop(...)` | `fundingDelta`, `popStart`, `popEnd`, `contractorConsentRequired` | 12 |
| `set_block_14_rationale(...)` | `description` (= the SF-30 change rationale) + `sections.changeNarrative`, `sections.priceCostImpact`, `sections.fundingCitation` | 14 |

`set_block_14_rationale` carries the grounded draft plus its FAR/DFARS citation
mapping and confidence/faithfulness scores as accompanying audit metadata.

**Target the right entity.** The agent writes only to `ContractModification`
(post-award, FAR Part 43). It must **never** touch the separate `Amendment` model /
`POST /{id}/amendments` endpoint — that is FAR 15.206 pre-award *solicitation*
amendment, out of scope per ADR-0004 Alt #5.

**Hard bounds on agent agency:**
- All tool calls write a **draft** record (`status = "DRAFT"`) — fully reversible,
  pre-gate. (No DRAFT-vs-submitted distinction is enforced today — the wizard
  creates directly as `MODIFICATION_REQUEST`; this workflow introduces the DRAFT
  status so the CO gate is what transitions DRAFT → `MODIFICATION_REQUEST`.)
- There is **no `submit_modification` tool exposed to the agent.** Submission is a
  CO-only UI action (FAR 43.102 — only the CO executes a modification). The agent
  cannot self-submit regardless of model confidence (PRD bounded-autonomy +
  REQ-AGT-2).
- Every tool call writes an audit record (correlation_id-threaded, ADR-0005 §12).

### CO Hard Gate (inherits ADR-0004 §CO Gate UI + HITL)

Before any CO action, the gate UI must display (ADR-0004 §CO Gate UI Requirements):
- Extracted Block 1–12 values **with their provenance spans** (new) and any
  low-confidence extraction flags.
- Block 13 classified type/authority + governing FAR 43.103 citation.
- Block 14 draft text, retrieved FAR/DFARS clause IDs + excerpts, citation mapping,
  confidence score, faithfulness score, and model ID + version.

CO actions:
- **Approve** → the workflow resumes. For a **unilateral** mod (FAR 43.103(b)) the
  CO triggers submission directly. For a **bilateral** mod (FAR 43.103(a)) approval
  routes through the contractor-consent gate (below) *before* submission. Submission
  is the irreversible, recorded human decision.
- **Deny** → per ADR-0004 §CO Rejection / Edit Handling, the prior package
  (extraction + retrieval + draft) is invalidated **entirely** and marked
  **superseded and non-reusable** in the audit log. The workflow restarts from
  `extract_node` against the corrected scope. No stale extraction or retrieval
  carries forward. Restart is **not** a silent discard — the supersession event is
  audited.

### Bilateral vs Unilateral — Contractor Consent (new — REQ-CONSENT)

FAR 43.103 splits modifications by who must sign:

- **Bilateral (FAR 43.103(a)) — supplemental agreement.** Signed by **both** the
  contractor and the CO. Used for negotiated equitable adjustments, definitizing
  letter contracts, and any change to terms the contractor must agree to. The
  contractor's signature (SF-30 **Block 15**) is the legal expression of consent.
- **Unilateral (FAR 43.103(b)).** Signed by the CO only — administrative changes,
  change orders, and changes authorized by an existing contract clause (Changes,
  Options, etc.). No contractor consent required.

`classify_modification_node` (Block 13 / FAR 43.103 A–E) already determines the
modification type; it sets `contractorConsentRequired` on the draft via
`set_funding_pop`. When that flag is true, the workflow adds a **contractor-consent
gate** on the approve path:

- After the CO approves the assembled package, a bilateral mod **cannot** transition
  `DRAFT → MODIFICATION_REQUEST` until contractor consent (Block 15 signature) is
  **recorded** as an explicit human action. Unilateral mods skip this gate and the
  CO submits directly.
- **Consent is never AI-generated.** Same bar as Blocks 15–16 signatures — the agent
  has no tool to attest, sign, or infer contractor consent. It records only an actual
  contractor signature event captured through the UI.
- **Fail-closed.** A bilateral mod with `contractorConsentRequired = true` and no
  recorded consent is blocked at submission, mirroring the CO-only submit bound. The
  contract-modification-service write path enforces this — the agent is not the
  boundary.
- The consent event is audited (`contractor_consent_recorded`, below), carrying the
  contractor identity, Block 15 signature reference, and timestamp.

### Pause / Resume (REQ-AGT-3)

The CO gate is a LangGraph **interrupt** with a persisted checkpoint. A paused
package survives a multi-day human delay and a container restart, and resumes
**without regeneration** on approve. (Deny intentionally regenerates from scratch —
that is the correct behavior, not lost work.) Checkpoint store is the existing
MongoDB instance (no new infra).

### Context Handling (no compression)

Per the originating plan, a single SF-30 package is short-lived and small (one
document + retrieved chunks + one draft). **No summarization/compression node is
added.** The full state and full audit trail are retained verbatim for DCAA
replay — compression would risk audit-completeness. This is a deliberate non-
decision, recorded so it is not re-litigated.

### Retry Policy (inherits ADR-0004 / ADR-0005 §10)

Max 4 retries, exponential backoff, 20% jitter, applied to extraction, Bedrock,
and retrieval failures. Retry tests must pass in CI before any Bedrock endpoint is
called. Extraction failure that cannot recover → field flagged, CO completes
manually; never a fabricated value, never a silent blank.

### Audit Log (inherits ADR-0004 §Audit Log + ADR-0005 §12)

Append-only, DCAA-auditable, correlation_id-threaded across every node. New event
types this ADR adds:
- `document_uploaded` — upload identity, timestamp, document hash.
- `field_extracted` — block, value, provenance span, extraction confidence, model.
- `form_field_written` — which tool wrote which block to the draft record.
- `co_decision` — approve/deny, CO identity + role + timestamp.
- `contractor_consent_recorded` — on a bilateral mod, contractor identity, Block 15
  signature reference, timestamp (the FAR 43.103(a) consent event).
- `package_superseded` — on deny, marks the prior extraction/retrieval/draft chain
  non-reusable.
- `modification_submitted` — on approve, the irreversible execution record.

---

## State Schema Additions (extends ADR-0005 §1 TypedDict)

New fields on the LangGraph state dict (existing ADR-0005 fields unchanged):

| Field | Type | Description |
|---|---|---|
| `uploaded_document_ref` | string | Reference/hash of the uploaded SF-30 |
| `extracted_fields` | dict | Block → {value, provenance, confidence} |
| `form_draft_id` | string | The draft modification record being populated |
| `co_decision` | `pending` \| `approved` \| `denied` | CO gate outcome |
| `modification_bilateral` | bool | FAR 43.103(a) bilateral (consent required) vs (b) unilateral |
| `contractor_consent` | `not_required` \| `pending` \| `recorded` | Block 15 consent state |

`gate_status` gains two values: `EXTRACTION_LOW_CONFIDENCE_AWAITING_CO_REVIEW` and
`AWAITING_CONTRACTOR_CONSENT` (alongside the ADR-0005 `RAG_FAILED_*` and
`FAITHFULNESS_FAILED_*` states).

---

## Code-Grounded Integration Notes (verified on `dev`, 2026-06-09)

This workflow spans the AI Orchestrator (Python) and contract-modification-service
(Spring Boot). The current code carries gaps that are **hard prerequisites** for
this ADR — not optional cleanups. Each is deliberate brownfield debt
(`brownfield-debt.md`); this workflow is the trigger to close it on the write path.

1. **Block 14 must route through the real `/retrieve`, not the brownfield drafter.**
   `POST /draft-contract-modification` (`app/main.py`) is the deliberately-broken
   stub: no Pydantic response model and a 1-in-3 `{"clause_id": null}` drift
   (Item 4), legacy `LLMChain` path (Item 5), no correlation_id (Item 6). The
   agentic `draft_node` must consume the ADR-0005 `/retrieve` read path
   (`app/retrieval/router.py` — fail-closed audit, gateway identity headers,
   hybrid RRF + rerank) and the Phase-2 confidence/faithfulness nodes. The stub
   endpoint is not in this workflow's call graph.

2. **Submit (FAR 43.102) is not enforceable until the write path checks CO role.**
   `ContractModificationController` reads `@RequestHeader(value="X-User",
   defaultValue="anonymous")` — a single header that **defaults to anonymous with
   no role check** on `create`, `update`, and `publish`. The CO-only submit gate
   this ADR mandates cannot hold until the write/publish endpoints verify an
   authenticated CO identity at the API Gateway (matching the `/retrieve`
   `_require_identity` 401 pattern). **Blocker for the approve→submit step.**

3. **Submit audit must be synchronous + transactional, not fire-and-forget.**
   `AuditLogger.recordAsync` (Item 2) flushes the HTTP response before the audit
   row is written, runs outside any transaction, and silently loses the record on
   a crash between flush and write. The `modification_submitted` (and `co_decision`,
   `package_superseded`) events this ADR requires are DCAA-traceability records —
   they must be written **synchronously in the same transaction** as the state
   transition, fail-closed, consistent with the ADR-0005 `/retrieve` audit
   discipline (results withheld if the audit write fails). The async logger path
   is not acceptable for these events.

4. **One identity convention across the seam (integration-plan B1).** Three header
   conventions exist today: retrieval (`X-Tenant-Id` / `X-User-Id` / `X-User-Role`),
   ingestion (`+ X-User-Name` / `X-Agency-Id`), contract-modification-service
   (single `X-User`). This workflow's correlation_id and CO-role audit must thread
   intact from upload → extract → retrieve → form-write → submit, so the services
   must agree on one gateway-asserted identity convention before E2E. Pick the
   `/retrieve` convention as the standard.

5. **Tenant scoping on the write path (Item 10).** `agencyId` is on the model and
   DTO but unenforced — `listAll()` returns all agencies, `create`/`update` never
   cross-check the JWT agency claim. ADR-0005 §11 tenant isolation is enforced in
   retrieval but not on the form-write side. The agent must not be the boundary;
   the contract-modification-service write path must scope by the gateway-asserted
   agency, or this workflow re-exposes the cross-tenant gap on every form write.

6. **SF-30 instance upload is net-new.** The existing `corpus-upload` component +
   `CorpusService` handle **FAR/DFARS source documents** (stage → CO-approve →
   ingest to the vector store), not SF-30 modification instances. The two-step
   stage/approve UX pattern is reusable, but the upload endpoint, the stored SF-30
   artifact, and `extract_node` are all new — no existing endpoint accepts an
   uploaded SF-30 for extraction.

---

## Alternatives Considered

1. **Sonnet for rationale drafting (as originally planned).** Rejected —
   contradicts the Haiku-primary cost decision in ADR-0004/0005. Sonnet stays the
   confidence-fail fallback only.
2. **Ungrounded agentic drafting (skip RAG, draft free-form from the upload).**
   Rejected — this is ADR-0004 Alternative #1 (already rejected): ungrounded FAR
   citations are a compliance violation. The agent wraps the ADR-0005 grounded
   pipeline; it does not replace it.
3. **Agent holds a `submit_modification` tool (full autonomy to file the mod).**
   Rejected — FAR 43.102 reserves modification execution to the CO. Submission is a
   CO-only UI action; the agent's tool set is draft-write only.
4. **Edit-in-place on deny (re-use prior extraction/retrieval).** Rejected — ADR-0004
   requires deny to invalidate prior grounding entirely and re-run from scratch. No
   stale context carries forward.
5. **Context compression / summarization node.** Rejected for this workflow — the
   package is small and short-lived; compression would risk audit completeness for
   no token benefit.
6. **Extraction library: PyMuPDF vs pdfplumber vs AWS Textract.** **PyMuPDF chosen**
   — it returns text *with bounding boxes* in one fast pure-Python call, which
   produces the mandated provenance spans deterministically (provenance is not
   left to the LLM). `pdfplumber` also gives coordinates but is slower and weaker on
   complex layouts. AWS Textract does OCR + form-field detection natively (best for
   scanned SF-30s) but adds an external service, per-page cost, and a data-egress
   path for SBU content — held as the fallback if PyMuPDF's AGPL license is rejected
   or if scanned-form volume makes Tesseract OCR insufficient. PyMuPDF + Tesseract
   OCR fallback covers both digital and scanned forms in-container.
7. **Treating this as the PRD M3 multi-agent flow.** Rejected as a conflation — M3
   is the anomaly-detector/adjudicator/decision-router disposition engine. This is
   the SF-30 form-assembly workflow that always terminates at the CO gate. They are
   complementary, not the same agent.
8. **Agent attests / auto-populates contractor consent for bilateral mods.** Rejected
   — a bilateral supplemental agreement (FAR 43.103(a)) requires the contractor's
   actual signature (Block 15). Consent is a recorded human act, never AI-generated,
   held to the same bar as the CO-only submit and the never-AI-generated signature
   blocks. The agent records a real consent event; it cannot manufacture one.

---

## Consequences

- The AI Orchestrator gains an `extract_node` (document parsing) and a form-fill
  tool layer calling contract-modification-service via the API Gateway.
- Document extraction adds **PyMuPDF (`fitz`)** to `requirements.txt` for text +
  bounding-box extraction, plus **Tesseract** in the Dockerfile for the
  `get_textpage_ocr()` scanned-form fallback. Both run in-container at request
  time — no new external API.
- **License flag: PyMuPDF is AGPL-3.0** (or a paid commercial license) — stricter
  copyleft than the MIT/Apache deps elsewhere in the stack. Confirm AGPL is
  acceptable for this deployment, or budget a commercial license. (AWS Textract is
  the fallback option if the license is rejected — see Alternatives #6.)
- The LangGraph checkpoint store (MongoDB) must persist paused packages across
  multi-day delays and restarts (REQ-AGT-3) — checkpointer wired in Phase 2.
- Provenance spans for extracted fields are a new audit field set — the gate UI
  must render them so the CO can verify each value against the source document.
- Submission remains a CO-only UI action; the contract-modification-service submit
  endpoint must reject any caller identity that is not an authenticated CO
  (FAR 43.102), enforced at the API Gateway.
- **Bilateral mods gate on contractor consent.** When `contractorConsentRequired` is
  true (FAR 43.103(a)), the contract-modification-service must persist the consent
  state and reject `DRAFT → MODIFICATION_REQUEST` until a contractor signature (Block
  15) is recorded — fail-closed, mirroring the CO-only submit bound. The
  `contractorConsentRequired` field already exists on the model; the consent-state
  persistence and the gate check are new.
- All ADR-0004 and ADR-0005 gates (confidence 0.85, faithfulness 0.85, retry tests,
  audit schema, CO role verification) remain prerequisites — this ADR adds to them,
  removes none.
- This ADR realizes ADR-0005 Phase 2 (`create_agent` + `StateGraph`, 2026-06-10):
  the agent harness and full state machine specified here are that deliverable.

**Hard prerequisites before the approve→submit path can go live** (from
Code-Grounded Integration Notes — all are existing brownfield debt this workflow
forces closed on the write path):

- contract-modification-service `create`/`update`/`publish` must verify an
  authenticated CO identity (close Item 2's anonymous-default header gap) — without
  it the FAR 43.102 submit gate is cosmetic.
- The `modification_submitted` / `co_decision` / `package_superseded` audit writes
  must be synchronous + transactional + fail-closed (replace `recordAsync`, Item 2).
- One gateway-asserted identity convention across ai-orchestrator and
  contract-modification-service (integration-plan B1) so correlation_id + role
  thread intact.
- Write-path agency scoping (Item 10) so form writes don't re-open the cross-tenant
  gap.
- A new SF-30 upload endpoint + stored artifact + `extract_node` (no existing
  endpoint accepts an SF-30 instance).

## Rollback Story

If document extraction proves unreliable (persistent low-confidence parsing across
SF-30 formats), the workflow degrades gracefully: the agent presents the CO with an
empty form and the raw uploaded document side-by-side, and the CO enters Block 1–12
manually. The Block 14 grounded pipeline (ADR-0005) is unaffected and still drafts
from the CO's typed modification intent. The audit log still captures the upload,
the extraction attempt, per-field confidence, and the CO decision. No silent
failure path — extraction failure falls back to manual entry, never to a fabricated
field.
