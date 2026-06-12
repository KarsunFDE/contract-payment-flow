# M3 Agent Workflow — Implementation Task Split (2 people)

**Date:** 2026-06-12
**Status:** Plan — validated against ADR-0004/0005/0006, PRD §6, and the `services/ai-orchestrator` codebase on `dev`
**Source spec:** [`docs/specs/m3.md`](../specs/m3.md)
**Goal:** Decompose the m3.md agent workflow into two independent workstreams with **disjoint file ownership**, so two people build in parallel without merge conflicts.

---

## TL;DR

- **Person A** = deterministic write path: SAM.gov lookup → form-fill → CO gate → consent → submit (m3.md Phases 1, 3, 4, 5).
- **Person B** = AI/retrieval path + multi-agent triage: classify → grounded draft pipeline → anomaly/adjudicator/router (m3.md Phases 2, 7).
- **Foundation phase** (one person or pair, FIRST) freezes every shared contract; after it lands, A and B touch disjoint files only.
- The whole agent graph is **net-new** under `app/workflow/` — it does not exist yet. No collision with existing modules.

---

## Codebase reality check

What actually exists in `services/ai-orchestrator/app/` today (ADR-0005 **Phase 1** = the retrieval *layer*, not the StateGraph):

| Exists | Net-new for M3 |
|---|---|
| `retrieval/` (retriever, router `/retrieve`, fusion, reranker, failures) | **all of `app/workflow/`** (state, graph, nodes, clients) |
| `ingestion/` (chunker, embedder, pipeline) | the LangGraph `StateGraph` + every node |
| `bedrock_client.py` (`invoke_model`) | triage flow (anomaly/adjudicator/router) |
| `db.py` (frozen Day-0 contract file) | SAM.gov mock client + contracts seed |
| `audit/logger.py` (**retrieval-only** audit) | **workflow/triage audit schema + writer** |
| `main.py`, `config.py`, `schemas.py` | form-fill + submit client to Java service |

ADR-0005 §1 names this exact work as its **Phase 2** ("`create_agent` + `StateGraph` — full typed state machine"). M3 *is* that phase.

---

## Consistency findings & risks (read before starting)

m3.md is the design; these are the points where it diverges from the real code/ADRs. Each is resolved in the Foundation phase or flagged as a cross-service prerequisite.

1. **Audit API mismatch (must fix in Foundation).** m3.md Phase 6 calls `audit.record_event(state, type, details)` / `write_audit_record({...})` with a free dict. The real `app/audit/logger.py` only has `write_audit_record(record: RetrievalAuditRecord)` — a **retrieval-specific Pydantic record**, insert-only to the `retrieval_audit` collection. Workflow/triage events (`contract_lookup`, `co_decision`, `modification_submitted`, `item_triaged`, `auto_processed`…) need a **new `WorkflowAuditRecord` schema + `record_event(...)` writer** to a separate `workflow_audit` collection. → Foundation owns `app/workflow/audit_events.py`; do **not** edit the existing `audit/logger.py`.

2. **`bedrock_client` has no `parse_json` and no `model_version` (must fix in Foundation/B).** Real `invoke_model(prompt, *, system, max_tokens, temperature)` returns `{body, model, region, stub}` — **no `parse_json` function, no `model_version` key**. m3.md `classify_modification_node` uses both. Resolution: B adds a new `app/workflow/llm.py` wrapper (`call_json(...)` → Pydantic-validated parse; derive version from `model`). Do **not** edit `bedrock_client.py`. Note its **stub fallback** (returns `"[stub]…"` text when AWS creds absent) — `call_json` must handle a non-JSON stub without crashing the graph in dev.

3. **`langgraph-checkpoint-mongodb` is NOT installed (must add in Foundation).** Phase 4 `runner.py` imports `MongoDBSaver` from `langgraph.checkpoint.mongodb`. Not in `requirements.txt`. → Foundation adds the pin (+ Dockerfile if a build-time step is needed). This is the only edit to the shared `requirements.txt`; do it once, up front.

4. **No `contracts` collection / no `get_contracts()` (Foundation + A).** `db.py` is a **frozen Day-0 contract file** with no contract handle, and the ai-orchestrator Mongo has no contract records (those live in the Java contract-modification-service). The mock SAM.gov client can read `db.get_db()["contracts"]` **without editing `db.py`**, but the collection must be **seeded** with agency-scoped records shaped to the SAM.gov Contract Awards / Entity response. → Foundation/A delivers a seed fixture; do not modify `db.py`.

5. **`retrieve_client` design — reuse the `/retrieve` pipeline, don't re-roll it (B).** The full ADR-0005 read path (hybrid → RRF → rerank → **fail-closed audit**) lives inside `retrieval/router.py:retrieve()`, gated on `X-Tenant-Id / X-User-Id / X-User-Role` and length-capped. m3.md's `retrieve_client.retrieve(query, sf30_block, contract_id)` omits identity/tenant and misuses `contract_id` (which is **audit metadata only — never a retrieval filter**, ADR-0005 §11). → B's `retrieve_client` must thread `tenant_id`(=agency) + user/role + `correlation_id`, not contract_id-as-filter. Prefer calling the router's core over duplicating fusion/rerank/audit.

6. **State schema must add `correlation_id` + `tenant_id` (Foundation).** ADR-0005 §1/§7/§12 **mandate** a `correlation_id` (UUID at request entry, threaded through every node *and* every audit record) and a `tenant_id`. m3.md `WorkflowState` has neither (agency is buried in `change_request`). Field names also drift: ADR-0005 uses `documents`/`confidence`/`draft`; m3.md uses `retrieved_chunks`/`block_14_draft`. → Foundation freezes the reconciled `WorkflowState` (add `correlation_id`, `tenant_id`/`agency_id`; pick one name per field and document the mapping).

7. **`confidence_check_node` is a Haiku LLM-judge, not a mean (B).** m3.md Step 2.2 shows `_mean_score(retrieved_chunks)`. ADR-0005 §4 is explicit: Haiku scores each chunk 0–1 (LLM-as-judge) → aggregate ≥0.85. Build the ADR-0005 version, not the mean.

8. **Do NOT thread through `legacy_chain.py` or the `/draft-contract-modification` stub (B + debt).** PRD §11 sequences the multi-agent build *after* the W2 v1.0 migration (debt **Item 5**, still `locked: true`); ADR-0006 Integration Note 1 says Block 14 must use the real `/retrieve`, not the deliberately-broken stub. The new `draft_node` calls `/retrieve` + the `llm.py` wrapper directly. New workflow modules are **additive** — they must not touch the debt-locked endpoints/tests (Items 4 & 5), or CI debt-enforcement trips without the `debt-touch-approved` label.

9. **REQ-AGT-5 is out of scope for this plan.** PRD REQ-AGT-5 (relational "every prior mod on this contract + rationale lineage") is the **W03-SA-3** Postgres recursive-CTE KG deliverable, not the agent graph. m3.md does not cover it; this task split does not deliver it. Tracked separately.

10. **Cross-service prerequisites block real submit (A5 — flag, likely not 2-person scope).** ADR-0006 Integration Notes 2–5: the Java `ContractModificationController` defaults `X-User=anonymous` with no role check, audit is async (`recordAsync`), identity convention differs (`X-User` vs `X-Tenant-Id/...`), and `agencyId` is unenforced on the write path. A5 can build the `submit_node` + workflow audit, but **real FAR 43.102 CO-only enforcement + agency scoping live in the Java service** — a separate prerequisite. Build the node fail-closed; note the enforcement gap.

---

## Foundation phase (do FIRST — blocks both; one person or pair, both review)

Deliver a graph of **no-op passthrough nodes** that compiles + invokes end-to-end (m3.md Phase 0 exit). Each person later swaps real impl into their own module. Freeze these files; changing them afterward = one PR, both review.

| File | Contents (frozen contract) | Resolves finding |
|---|---|---|
| `app/workflow/state.py` | `WorkflowState` — m3.md Step 0.1 **+ `correlation_id`, `tenant_id`/`agency_id`**; reconcile field names with ADR-0005 §1 | #6 |
| `app/workflow/triage_state.py` | `TriageState(WorkflowState)` — Step 7.0 | — |
| `app/workflow/graph.py` | `build_graph()` — creates builder, calls `nodes_lookup.register(b)`, `nodes_classify.register(b)`, `nodes_retrieval.register(b)`, `nodes_form.register(b)`, `nodes_gate.register(b)` in fixed order. **Never edited again.** | — |
| `app/workflow/nodes_*.py` | five stub modules, each `def register(builder): ...` adding no-op nodes + edges so compile passes | — |
| `app/workflow/audit_events.py` | `WorkflowAuditRecord` (Pydantic) + `record_event(state, event_type, details)` → `workflow_audit` collection, synchronous/fail-closed | #1 |
| `app/workflow/clients.py` | `SamGovClient` Protocol; `retrieve_client.retrieve(...)` signature (threads tenant/user/role/correlation_id); stub bodies | #5 |
| `app/workflow/llm.py` | `call_json(prompt, system, schema)` wrapping `bedrock_client.invoke_model` — Pydantic parse, stub-safe, exposes model+version | #2 |
| `requirements.txt` | add `langgraph-checkpoint-mongodb` pin | #3 |
| `main.py` | mount net-new `workflow` + `triage` routers (stub) — single wiring edit | — |
| seed fixture | `contracts` collection, agency-scoped, SAM.gov-shaped | #4 |

**Exit:** `build_graph().compile().invoke({...})` runs through stubs; triage skeleton compiles; `record_event` writes to `workflow_audit`; contracts seed loads.

---

## Person A — deterministic write path (lookup → form → gate → submit)

m3.md Phases 1, 3, 4, 5. Files **only A touches:**

| Task | File(s) | m3.md |
|---|---|---|
| A1 — SAM.gov mock client | `sam_gov_client.py`, `mock_sam_gov_client.py` (reads `db.get_db()["contracts"]`, agency-scoped) | Step 1.4 |
| A2 — lookup nodes | `contract_lookup.py`, `nodes_lookup.py` (`lookup_node`, `validate_lookup_node`, `populate_fields_node`); writes edge `populate → "classify"` | Steps 1.1–1.3 |
| A3 — form-fill tools | `form_tools.py`, `modification_client.py` (HTTP client → Java service :8081), `nodes_form.py` (`assemble_form_node`); writes edge `assemble → "co_gate"` | Phase 3 |
| A4 — CO gate + checkpointer | `nodes_gate.py` (`co_gate_node`, `route_after_co_gate`), `runner.py` (`MongoDBSaver`) | Phase 4 |
| A5 — consent + submit | extend `nodes_gate.py` (`route_after_approve`, `consent_gate_node`, `submit_node`, `supersede_node`); fail-closed, audit each event | Phase 5 |
| A-tests | `test_lookup.py`, `test_form_tools.py`, `test_gate.py`, `test_submit.py` | — |

A imports nothing of B's. Cross-seam edges A writes (string targets): `populate → "classify"`, `assemble → "co_gate"`.
**Flag for A5:** real CO-role/agency enforcement is a Java-side prerequisite (finding #10) — build the node, note the gap.

---

## Person B — AI/retrieval path + multi-agent triage

m3.md Phases 2, 7. Files **only B touches:**

| Task | File(s) | m3.md |
|---|---|---|
| B1 — classify + consent rule | `far_rules.py`, `nodes_classify.py` (`classify_modification_node` via `llm.py`, `derive_consent_node`) | Steps 2.1, 2.1b |
| B2 — grounded sub-pipeline | `retrieve_client.py` (wraps `/retrieve`, threads tenant/identity — finding #5), `nodes_retrieval.py` (`retrieve_node`, `confidence_check_node` = **Haiku judge**, `draft_node`, `faithfulness_gate_node`, `route_after_confidence`); writes edges `confidence → "co_gate"` (fail), `faithfulness → "assemble"` | Steps 2.2–2.4 |
| B3 — anomaly + adjudicator | `anomaly_rules.py`, `nodes_triage.py` (`anomaly_detector_node`, `adjudicator_node`) | Steps 7.1–7.2 |
| B4 — policy + router | `auto_approval_policy.py`, extend `nodes_triage.py` (`decision_router_node`) | Steps 7.3–7.4 |
| B5 — lanes + triage graph | `mock_executor.py`, `execution_log.py`, extend `nodes_triage.py` (`auto_process_node`, `return_route_node`), `triage_graph.py` (`build_triage_graph` — imports A's `build_graph` as the `hitl_escalate` compiled subgraph) | Step 7.5 |
| B-tests | `test_far_rules.py`, `test_classify.py`, `test_retrieval.py`, `test_anomaly.py`, `test_auto_approval_policy.py`, `test_decision_router.py` | — |

B imports A only via `build_graph` (the Phase-0 stub is enough to build against the whole time).
**Flag for B:** keep structured-output parsing in the new workflow modules; never touch the debt-locked stub endpoints/tests (finding #8).

---

## Conflict-avoidance rules

1. **Frozen after Foundation:** `state.py`, `triage_state.py`, `graph.py`, `clients.py`, `llm.py`, `audit_events.py`, `requirements.txt`, `main.py`, `db.py` (already frozen). Need a change? One PR, both review, before resuming.
2. **No shared node module.** A → `nodes_lookup/form/gate.py`; B → `nodes_classify/retrieval/triage.py`. Zero overlap.
3. **Each node module owns its nodes + its outgoing edges**, written by the **upstream** owner, targeting downstream nodes **by string name**. Phase-0 stubs guarantee the graph always compiles.
4. **One-way dependency:** B imports A (`build_graph`); A imports nothing of B's. No cycle.
5. **Do not edit existing modules** `bedrock_client.py`, `audit/logger.py`, `db.py`, `retrieval/*` — wrap them from new `app/workflow/` files instead.
6. Branch per task off the Foundation commit; small PRs.

---

## Sequencing

```
Foundation (blocks both; resolves findings #1-#6 + seeds)
        │
   ┌────┴────┐
   A1→A2     B1→B2        (parallel, independent)
   A3        B3→B4
   A4→A5     B5 (builds against Phase-0 build_graph stub)
        └────┬────┘
        Integration: B5 wires triage over A's real workflow; full end-to-end test
```

Only hard constraints: **Foundation before anything**, **B5 integration last**.

---

## Open items / cross-service prerequisites (not in the 2-person ai-orchestrator scope)

- **Java write-path debt** (ADR-0006 Notes 2–5): CO-identity + role check on `create/update/publish`, synchronous/transactional audit (replace `recordAsync`), one identity convention (B1), agency scoping. Blocks *real* approve→submit. (debt Items 2, 10 + B1)
- **REQ-AGT-5** relational lineage → W03-SA-3 Postgres recursive-CTE KG (separate deliverable).
- **LangFuse** (ADR-0005 §7) deferred to its own phase; M3 uses structured `workflow_audit` + `correlation_id`.
- **debt Items 4 & 5** stay locked — M3 must not "fix" them incidentally without `debt-touch-approved`.
