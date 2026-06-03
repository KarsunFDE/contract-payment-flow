# Week 1 Task Split — Retrieval Layer (ADR-0005 Phase 1)

Scope: ADR-0005 Phase 1 (2026-06-03) — retrieval layer only. No `StateGraph`, no LangFuse this week.

Repo state on `dev`: compose already uses `mongodb/mongodb-atlas-local:8.0`. AI orchestrator at `services/ai-orchestrator/` (FastAPI). Seed FAR stubs exist at `data/seed/far-part-42-43-32/`.

Split principle: **write path vs read path**. Two pipelines, zero shared logic files.

---

## Day 0 — Pair together, one commit (avoids all later conflicts)

Shared files touched ONCE, together, then frozen for the week:

| File | Content |
|---|---|
| `services/ai-orchestrator/requirements.txt` | All pins: `langchain^1.0`, `langchain-mongodb^0.5`, `langchain-aws^0.3`, `langchain-community^0.3`, `langchain-text-splitters^0.3`, `pymongo`, `sentence-transformers` |
| `services/ai-orchestrator/app/main.py` | Register two empty routers: `ingestion.router`, `retrieval.router` |
| `services/ai-orchestrator/app/config.py` | Settings: Mongo URI, Bedrock region, model IDs, dims=512, index names |
| `services/ai-orchestrator/app/db.py` | PyMongo client factory, collection handles (`far_corpus`, `retrieval_audit`) |
| `services/ai-orchestrator/app/schemas.py` | Shared Pydantic models: chunk provenance doc (ADR §12 fields), audit record |
| `.env.example` | New vars both need |

After this commit, rule: **neither edits these without telling the other**. New deps → message partner, single-line append.

---

## Person A — Ingestion + Infra (write path)

Owns: corpus gets INTO Mongo.

**New files only:**

```
services/ai-orchestrator/app/ingestion/
  __init__.py
  router.py          # POST /corpus/upload, POST /corpus/ingest
  chunker.py         # RecursiveCharacterTextSplitter, 512 tok / 64 overlap, ADR §13 rules
  embedder.py        # BedrockEmbeddings Titan V2 512d + CacheBackedEmbeddings (Mongo byte store)
  pipeline.py        # chunk → embed → insert w/ full provenance metadata (ADR §12)
scripts/create_indexes.py   # far_vector_idx (knnVector 512 cosine) + far_text_idx (BM25)
services/ai-orchestrator/tests/test_chunker.py
services/ai-orchestrator/tests/test_ingestion_pipeline.py
infra/docker/docker-compose.yml   # owns: healthcheck, DO_NOT_TRACK=1, named volume (ADR §2)
```

**Frontend upload UI (also A — owns ingestion end-to-end):**

```
frontend/src/app/components/corpus-upload/corpus-upload.component.ts
frontend/src/app/services/corpus.service.ts
frontend/src/app/app.routes.ts   # one route line — A owns routes file this week
```

**Tasks:**

1. Verify Atlas Local: `mongot` active, healthcheck, volume persistence
2. Index creation script — both indexes ACTIVE check via `mongosh`
3. Chunker w/ ADR §13 rules (clause-number never split from definition text, discard fragments <100 chars, metadata inheritance from parent section header)
4. Embedding pipeline — Titan V2, `dimensions=512`, `normalize=True`, cache-backed
5. Ingest seed stubs from `data/seed/far-part-42-43-32/` as `tenant_id="far_corpus_global"` — real gov docs swap in later, pipeline stays the same
6. Upload endpoint + Angular upload component (md/txt accept, calls `/corpus/upload`)

---

## Person B — Retrieval + Audit (read path)

Owns: query gets OUT of Mongo.

**New files only:**

```
services/ai-orchestrator/app/retrieval/
  __init__.py
  router.py          # POST /retrieve (query, sf30_block, tenant_id, contract_id)
  retriever.py       # dense $vectorSearch k=20 + BM25 $search k=20, tenant_id pre-filter
  fusion.py          # RRF plain Python, 0.6 dense / 0.4 sparse (NOT EnsembleRetriever)
  reranker.py        # CrossEncoderReranker ms-marco-MiniLM-L-6-v2, top_n=8, fallback to fused top-k
  failures.py        # retry (4x, backoff+jitter), BM25-only fallback on $vectorSearch fail, circuit breaker
services/ai-orchestrator/app/audit/
  __init__.py
  logger.py          # structured JSON audit record w/ correlation_id (ADR §12 retrieval log fields)
services/ai-orchestrator/tests/test_fusion.py
services/ai-orchestrator/tests/test_retriever.py
services/ai-orchestrator/tests/test_audit_logger.py
services/ai-orchestrator/Dockerfile   # owns: pre-download cross-encoder at build time (ADR consequence)
```

**Tasks:**

1. Hybrid retrieval — `MongoDBAtlasVectorSearch.similarity_search()` direct call, no Runnable wrapper
2. Mandatory `tenant_id IN ["far_corpus_global", agency_id]` pre-filter inside retriever, not app layer
3. RRF fusion as plain function — unit-testable without Mongo
4. Cross-encoder rerank + degraded-mode fallback
5. Audit logger: `correlation_id` UUID at request entry, every field from ADR §12 table, insert-only collection
6. Failure handling per ADR §10 table — no silent failures

---

## Why this split holds

- A writes `far_corpus`, B reads it. Contract between them = `schemas.py` chunk shape, frozen Day 0.
- B blocked on real data? No — B tests against a handful of hand-inserted fixture chunks (insert via test setup), doesn't need A's pipeline done.
- Docker split: A owns `docker-compose.yml`, B owns `Dockerfile`. No overlap.
- Frontend all A. B never touches `frontend/`.
- Each owns own test files.

## Conflict watchlist (only 3 files)

1. `requirements.txt` — append-only, announce in chat before push
2. `app/main.py` — frozen after Day 0; both routers pre-registered
3. `app.routes.ts` — A only this week

## Branches

- A: `feat/retrieval-ingestion` off `dev`
- B: `feat/retrieval-query` off `dev`
- Merge A's index script + compose changes first so B can integration-test against real indexes.

> Note: ADR + orchestrator code live on `dev`. Checkout `dev` before starting.
