# Retrieval + Ingestion Integration Plan (ADR-0005 Phase 1 → Joint E2E)

Status: written 2026-06-04, after `dev_ingestion` (PR #6) and `dev_retrival` (PR #5) merged to `dev`.
Supersedes the execution portion of `docs/week1-retrieval-task-split.md` (that plan is **complete** — both halves are implemented, merged, and individually verified). This document covers what remains: making the two pipelines work *together*, live, end to end.

---

## 1. Where we are (verified against `dev`, 2026-06-04)

### Week-1 plan feasibility verdict: ✅ executed, contract held

The write-path/read-path split worked as designed. Verified on `dev`:

| Week-1 deliverable | State |
|---|---|
| Day 0 frozen contract files (`config.py`, `db.py`, `schemas.py`, `main.py`) | ✅ intact, both routers registered (`main.py:65-66,79-80`) |
| Ingestion: chunker, embedder, pipeline, router, `create_indexes.py`, `seed_corpus.py` | ✅ implemented + hardened (3 Codex review rounds: 6 HIGH, 6 MEDIUM, 4 LOW fixed) |
| Retrieval: retriever, fusion, reranker, failures, audit logger, `/retrieve` | ✅ implemented; hybrid $vectorSearch + BM25, RRF 0.6/0.4, cross-encoder top-8, circuit breaker, fail-closed audit |
| Frontend corpus upload UI + route guard | ✅ built, `ng build` passes |
| Indexes live on Atlas Local | ✅ `far_vector_idx` + `far_text_idx` reached READY (live-verified 2026-06-03) |
| Schema contract (`ChunkDocument`) honored by both sides | ✅ ingestion writes the exact §12 field set (+ one extra: `chunk_ref`, harmless to reads); retrieval reads `chunk_text`/`embedding`/`tenant_id`/`source_document` per contract |
| Embedding parity (Titan V2, 512d, normalize=True) | ✅ both sides build `BedrockEmbeddings` from the same frozen `config.py` constants — vectors cannot drift |
| Tenant isolation §11 inside both query types | ✅ dense `pre_filter` (`retriever.py:83`) + sparse in-`$search` filter (`retriever.py:137-139`); `tenant_id` is a filter field in both indexes |

### What does NOT yet work

The corpus is **empty** and **no request can travel the full path** (browser → gateway → orchestrator). Everything below is about closing that.

---

## 2. Blockers (must resolve before E2E sign-off)

### B1 — Identity-header mismatch between the two paths ⚠ NEW, surfaced by the merge

The two halves invented **different gateway-identity conventions** in isolation:

| Path | Headers read | Where |
|---|---|---|
| Ingestion (`require_corpus_admin`) | `X-User-Id`, `X-User-Role`, `X-User-Name`, `X-Agency-Id` | `app/ingestion/auth.py:49-70` |
| Retrieval (`_require_identity`) | `X-Tenant-Id`, `X-User-Id` | `app/retrieval/router.py:103-104` |

Ingestion derives the writable tenant from `X-Agency-Id`; retrieval derives the tenant filter from `X-Tenant-Id`. Same concept, two names. The gateway (which currently forwards **neither**) would have to emit both sets, and the audit trail would record tenants under two different header sources.

**Decision needed (team, ~30 min):** pick ONE convention. Recommendation: standardize on the ingestion set (`X-User-Id` / `X-User-Role` / `X-User-Name` / `X-Agency-Id`) since it carries role info the retrieval audit record also wants (`RetrievalAuditRecord.role` is currently hardcoded `"contracting_officer"`), and change `retrieval/router.py` to read `X-Agency-Id` (alias or rename). One-file change on the retrieval side + tests.

### B2 — Gateway is broken for every AI endpoint (pre-existing, now load-bearing)

Live-probed 2026-06-03 (see `docs/context/review.md` finding 1). Three independent failures stack:

1. **No StripPrefix**: `RouteConfig.java:32` forwards the full `/api/ai/...` path; FastAPI serves `/corpus/*`, `/retrieve` — so even authenticated calls 404.
2. **JWT 401 wall**: `SecurityConfig.java` permits only `/actuator/**` + `/api/public/**`; the configured issuer (`:8090`) is not in docker-compose, so no caller can mint a token.
3. **No identity-header forwarding**: nothing injects the `X-User-*` / `X-Tenant-Id` headers both auth dependencies trust. Until the gateway does this *and strips inbound copies*, the "network-isolated, gateway-asserted" trust model both sides documented is fiction — anyone reaching :8000 can spoof any principal.

The gateway is **neither person's file** under the week-1 split — this is the single biggest unowned work item. Assign an owner explicitly.

**Fix shape:** StripPrefix(2) on the `ai` route; a dev-mode auth story (mock issuer container, or a dev-profile permitAll on `/api/ai/**` with header injection from a stub filter); JWT-claims → `X-*` header mapping filter that also strips client-supplied copies.

### B3 — `far_corpus` is empty: live seed ingest never ran

Code is ready (`scripts/seed_corpus.py`, provenance fixes verified by dry-run); the live run is gated on:

1. Stack up: `docker-compose -f infra/docker/docker-compose.yml --env-file ../../.env up --build` (must point at repo-root `.env`; compose's default lookup beside the compose file finds nothing. `--build` matters — a stale orchestrator image bit us once already).
2. Indexes READY (`python -m scripts.create_indexes` — idempotent).
3. **Fresh Bedrock bearer token** — the wired token was issued 2026-06-03 ~22:11 with a 12 h life: **it is expired**. Refresh in `.env` before the run.
4. Host-run scripts need explicit env (no dotenv loader in `config.py`):
   `MONGO_URL=mongodb://app:app_dev_password@localhost:27017/?directConnection=true` + `AWS_BEARER_TOKEN_BEDROCK=...`
5. Run `python -m scripts.seed_corpus`; verify `far_corpus.countDocuments() > 0`, sample doc has 512-float `embedding`, `chunk_text`, `tenant_id == "far_corpus_global"`. `GET :8000/corpus/stats` is the quick smoke check.

### B4 — Stale vector index must be dropped + recreated

The dev `far_vector_idx` created 2026-06-03 was built **before** `chunk_text` was removed from the filter fields (Codex L1). `create_indexes.py` is idempotent-by-name and will *skip* it. Drop `far_vector_idx` via `mongosh`, re-run the script, confirm READY. (`far_text_idx` unchanged — leave it.)

### B5 — Local dev environments out of sync with merged `requirements.txt`

Verified on this machine 2026-06-04: the merged suite **cannot even collect** —
`ModuleNotFoundError: No module named 'langchain_mongodb'` (Person B's dep, never installed here). Version drift also present: installed `langchain 1.2.15` / `langchain-aws 1.4.5` / `langchain-community 0.4.1` / `sentence-transformers 5.4.1` vs pins `1.3.4` / `1.5.0` / `0.4.2` / `5.5.1`.

**Both partners:** `pip install -r services/ai-orchestrator/requirements.txt` after pulling `dev`, then confirm `python -m pytest tests/ -m "not brownfield_debt"` green (last known good: 66 passed on `dev_ingestion`; retrieval suite green on `dev_retrival`; **merged suite has never been run green anywhere** — do this first).

### B6 — Frontend corpus URLs use the wrong gateway convention

`corpus.service.ts` posts to `${apiGatewayUrl}/corpus/*`; the established convention is `${apiGatewayUrl}/api/ai/...` (see `invoice-review.service.ts`). One-file fix, but pointless until B2 lands — sequence it with the gateway work.

---

## 3. Design constraints not yet addressed (decide before they calcify)

| # | Constraint | Detail | Owner |
|---|---|---|---|
| C1 | **ADR §16 deviations need formal confirmation** | (a) `CacheBackedEmbeddings` → custom `MongoCachedEmbedder` (the ADR-named class lives only in banned `langchain_classic`); (b) `chunk_text` dropped from vector-index filter fields (ADR §3 lists it). Both implemented and documented in-code; ADR text still says otherwise. One standup + two one-line ADR edits. | Team |
| C2 | **`retrieval_audit` insert-only is aspirational** | `db.py:46-47` says "the MongoDB role restriction enforces it server-side" — no such role exists; everything connects as the root `app` user. The fail-closed audit gate (no unaudited retrieval) is real; the immutability claim is not. Either create the restricted role in compose init or soften the comment + ticket it. | B / infra |
| C3 | **Audit landscape is now three-shaped** | Retrieval events → `retrieval_audit` (`RetrievalAuditRecord`, has `correlation_id`); ingestion runs → `ingestion_audit` (own shape, **no correlation_id**); brownfield Item 6 (W1-Tue debt) wants W3C `traceparent` everywhere. When Item 6 is worked, thread one correlation scheme through both audit collections rather than inventing a third. | Both |
| C4 | **Retrieval has no consumer** | Nothing calls `POST /retrieve`: `main.py`'s `/rag/clause-search` is still the lexical stub, `/answer-qa` doesn't retrieve, frontend has no retrieval UI. Phase 1 scope ends at the endpoint — fine — but W2 generation work must route through `/retrieve` (or its internals), not grow a parallel path. | B (W2) |
| C5 | **Query embeddings are uncached** | Retrieval builds raw `BedrockEmbeddings` (`retriever.py:38`) — no `MongoCachedEmbedder`. Consequence: `RetrievalAuditRecord.cache_hit` is always `False`, and every dense query costs a Bedrock call. Acceptable for Phase 1; revisit if query volume or token cost matters. Note: with no/expired Bedrock creds, dense fails → every request silently degrades to BM25-only (flagged `degraded`, but easy to miss). | B |
| C6 | **`chunk_ref` is outside the frozen schema** | Ingestion writes a 13th field (`chunk_ref`, sha256 idempotency key + unique index) not in `ChunkDocument`. Harmless to reads, but the "schemas.py mirrors ADR §12 exactly" rule is now bent. Add it to the schema + ADR §12 at the next agreed unfreeze. | Both |
| C7 | **Clause-header regex never fires on real corpus formats** | Markdown-prefixed headers (`# FAR 43.103 — ...`, the actual seed format) don't match `CLAUSE_HEADER_PATTERN`; seed files work only because each is single-clause and frontmatter supplies metadata. The §13 rule-2/3 inheritance machinery is untested against multi-clause documents. Must be fixed before ingesting real FAR parts. | A (deferred, pre-real-corpus) |
| C8 | **Golden set is unvalidated AI mock** | `eval/golden_set.json` (11 samples) needs CO review before any RAGAS gate can be more than WARN-ONLY. `eval/faithfulness_baseline.json` + `scripts/verify_e2e.py` don't exist yet (were blocked on `/retrieve`, which now exists — unblocked). | A+B joint |
| C9 | **The `langchain_classic` CI ban is honor-system** | The lint step is commented out (deliberate brownfield Item 12). Grep is clean today; know the gate is fictional until W-whatever re-enables it. | Team |

---

## 4. Execution plan

### Phase 0 — Sync (both, ~½ day) — do first, everything depends on it
1. Both: pull `dev`, `pip install -r requirements.txt`, run merged suite → green (B5).
2. Rebuild + bring up the stack with `--build` and `--env-file ../../.env`; fresh Bedrock token in `.env` (B3.1–.3).
3. Drop stale `far_vector_idx`, re-run `create_indexes.py`, both indexes READY (B4).

### Phase 1 — Data goes live (A, ~½ day)
4. `python -m scripts.seed_corpus` → verify counts, sample-doc shape, `GET /corpus/stats` (B3.5).

### Phase 2 — Read path proves itself (B, ~½ day; needs Phase 1)
5. Direct-to-:8000 `/retrieve` smoke: ≥10 golden-set queries with `X-Tenant-Id`/`X-User-Id` headers; hand-verify FAR citations + provenance in returned chunks, fused vs reranked ordering sane, one `RetrievalAuditRecord` per request.
6. Degraded-mode drills: kill Bedrock token → confirm BM25-only fallback + `degraded:true`; pause mongo → confirm circuit breaker + 503; both audit-recorded.

### Phase 3 — Identity + gateway (team decision, then ~1 day, unowned → assign)
7. Decide single identity-header convention (B1) → retrieval router conforms (small PR + tests).
8. Gateway: StripPrefix, dev auth story, JWT→`X-*` mapping filter with inbound-header stripping (B2). This is the trust-model lynchpin for BOTH paths.
9. Frontend: `corpus.service.ts` → `/api/ai/corpus/...` (B6).
10. Full E2E: Angular upload → ingest → `/corpus/stats` shows new doc → `/retrieve` returns its chunks.

### Phase 4 — Evaluation + paperwork (joint, end of week)
11. `scripts/verify_e2e.py` (now unblocked); first RAGAS run populates `faithfulness_baseline.json` (WARN-ONLY until C8 CO validation).
12. ADR-0005 §16 updates for C1; ticket/decide C2, C6; record C7 as a pre-real-corpus gate.

### Explicitly out of scope (Phase 2 of ADR-0005 / later weeks)
- `StateGraph` orchestration, LangFuse, confidence scoring (`confidence`/`llm_model` audit fields stay null).
- Wiring `/retrieve` into generation endpoints (C4 — W2).
- Real FAR corpus ingestion (gated on C7 regex work).
- Debt items 4/5/6 (structured output, legacy chain, correlation IDs) — scheduled separately; C3 notes the intersection.

---

## 5. Sequencing summary

```
Phase 0 (sync: deps, stack, token, index recreate)
   └─→ Phase 1 (seed ingest)  ──→ Phase 2 (retrieve verification)
   └─→ Phase 3.7 (header decision) → 3.8 (gateway) → 3.9 (frontend URLs) → 3.10 (full E2E)
Phase 4 after 2 + 3.10
```

Phases 1–2 and 3 are parallelizable across partners; Phase 3 needs the team decision (B1) first and a named owner for the gateway (B2).
