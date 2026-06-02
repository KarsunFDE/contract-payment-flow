# ADR 0005 — RAG Retrieval Architecture for Post-Award SF-30 AI Assistance

Date: 2026-06-02
Status: **Accepted**
Decision-makers: Pair 2
Supersedes: Supplements ADR-0004 (AI SF-30 Helper), ADR-0003 (Bedrock LLM Anchor)

---

## Context

ADR-0004 established the pipeline state order and grounding requirements for the AI-assisted SF-30 helper. This ADR defines **how** the retrieval layer is built: the LangChain version and what its APIs actually provide, the vector store infrastructure, the embedding model choice, retrieval patterns per SF-30 block, and all operational concerns (security, observability, chunking, failure, multi-tenancy, HITL).

Current state:
- MongoDB container running with seed data (contract records, FAR corpus stubs)
- AI Orchestrator is Python/FastAPI (per ADR-0001)
- Bedrock/Claude is the LLM anchor (per ADR-0003)
- No vector index exists yet
- No embedding pipeline exists yet

---


## Decision

### 1. LangChain Package Versions

**Python minimum: 3.10** (3.9 dropped in LangChain 1.0).

| Package | Role | Version pin |
|---|---|---|
| `langchain>=1.0` | `create_agent`, agent primitives | `^1.0` |
| `langchain-core` | `BaseRetriever`, `Document` schema, base classes | `^1.0` |
| `langchain-mongodb` | `MongoDBAtlasVectorSearch` vectorstore | `^0.5` |
| `langchain-aws` | `BedrockEmbeddings`, `ChatBedrock` | `^0.3` |
| `langchain-text-splitters` | `RecursiveCharacterTextSplitter` | `^0.3` |
| `langchain-community` | `BM25Retriever`, `CacheBackedEmbeddings` | `^0.3` |
| `langgraph>=1.0` | **Primary orchestration** — all pipeline state (CO input → retrieve → validate → draft → gate) | `^1.0` |

**Hard rules:**
- Do not install `langchain-classic` — any import from it fails CI
- Do not use the LCEL `|` pipe operator for orchestration — use LangGraph nodes
- Do not use `create_retrieval_chain` or `create_stuff_documents_chain` — LCEL-based, not our pattern

**LangGraph pipeline state schema:** The pipeline maintains a typed state dictionary with fields for: `query`, `sf30_block`, `tenant_id`, `documents` (retrieved chunks), `confidence` (float), `draft` (generated text), and `gate_status` (`pending` | `passed` | `RAG_FAILED_AWAITING_CO_REVIEW` | `FAITHFULNESS_FAILED_AWAITING_CO_REVIEW`). Each LangGraph node reads from and writes to this state. State schema must use `TypedDict` format (required by LangGraph v1.0).

---

### 2. Vector Store: MongoDB Atlas Local

**Decision:** Replace the existing `mongo` Docker container with `mongodb/mongodb-atlas-local`. This single container provides both standard MongoDB AND Atlas Vector Search via the embedded `mongot` (Atlas Search engine).

**Docker image:** `mongodb/mongodb-atlas-local`

**docker-compose.yml changes:**
- Replace the `mongo:7` service with the `mongodb/mongodb-atlas-local` image
- Keep port `27017:27017` so existing Spring Boot connection strings are unchanged
- Set environment variable `DO_NOT_TRACK=1` to disable telemetry
- Mount a named volume for `data/db` to persist data across restarts
- Add a healthcheck using `mongosh --eval "db.adminCommand('ping')"` (30s interval, 10s timeout, 3 retries)

**Capabilities confirmed (MongoDB official docs):**
- Up to 8,192 vector dimensions
- `$vectorSearch` aggregation stage for Approximate Nearest Neighbor (ANN) and Exact Nearest Neighbor (ENN)
- Atlas Search for BM25 sparse retrieval
- Standard MongoDB CRUD — all existing seed data and collections carry over unchanged

**LangChain integration:** Use `MongoDBAtlasVectorSearch` from `langchain-mongodb`, passing a PyMongo collection reference, the `BedrockEmbeddings` instance, an index name (`far_vector_idx`), the field containing the embedding vector (`embedding`), and the field containing the source text (`chunk_text`). Call `vectorstore.similarity_search()` directly inside LangGraph nodes — do not wrap in a Runnable retriever chain.

---

### 3. Embedding Model Selection

**Decision: Amazon Titan Text Embeddings V2**
Model ID: `amazon.titan-embed-text-v2:0`

| Criterion | Titan V2 | Cohere Embed English v3 | Decision |
|---|---|---|---|
| Model ID | `amazon.titan-embed-text-v2:0` | `cohere.embed-english-v3` | — |
| Auth | AWS Bedrock credentials only | AWS Bedrock credentials only | Tie |
| Token limit | 8,192 tokens | 512 tokens | **Titan wins** |
| Dimensions | 256 / 512 / 1,024 (configurable) | Fixed (vendor-defined) | **Titan wins** |
| Cost | Pay-per-token, AWS native pricing | $0.0001 / 1k tokens | Comparable |
| FedRAMP coverage | In-scope within AWS GovCloud | In-scope within AWS GovCloud | Tie |
| FAR doc suitability | Long contract text fits in 8k window | Contract clauses get truncated at 512 tokens | **Titan wins** |

**FAR Part 42/43/32/52 and DFARS 242/243/232 clauses regularly exceed 512 tokens.** Cohere's 512-token limit would truncate critical clause text. Titan V2's 8,192-token window embeds full clauses without truncation.

**Configured dimensions: 512** (not 1,024) — reduces MongoDB storage and `$vectorSearch` latency with minimal recall degradation for English legal text.

**Configuration:** Use `BedrockEmbeddings` from `langchain-aws` with `model_id="amazon.titan-embed-text-v2:0"`, `dimensions=512`, `normalize=True`, and `region_name="us-east-1"`.

**Vector index specification (Atlas Local):**
- Index type: `knnVector` on the `embedding` field
- Dimensions: `512`
- Similarity metric: `cosine`
- Additional indexed fields (non-vector): `chunk_text` (string), `far_part` (string), `clause_number` (string), `tenant_id` (string)
- Dynamic mapping: disabled — only the declared fields above are indexed

---

### 4. Retrieval Patterns by SF-30 Block

SF-30 post-award (Blocks 1–16C) has distinct data-needs per block. Not every block requires RAG.

| SF-30 Block | Field | Data Source | Retrieval Type |
|---|---|---|---|
| 1 | Contract ID No. | Contract record | Structured DB query |
| 2 | Amendment/Modification No. | Contract record | Structured DB query |
| 3 | Effective Date | Input / contract record | Structured DB query |
| 6 | Issued By (Contracting Office) | Agency reference data | Sparse keyword lookup |
| 7 | Administered By | Agency reference data | Sparse keyword lookup |
| 8 | Contractor Name/Address | Contractor record | Sparse keyword lookup |
| 10A | Contract/Order No. being modified | Contract record | Structured DB query |
| 10B | Dated | Contract record | Structured DB query |
| 11 | Modification type (A–E per FAR 43.103) | FAR 43.103 definitions | **Dense retrieval** — semantic match to modification type |
| 12 | Accounting and Appropriation Data | Financial records | Structured DB query |
| **13** | **Description of Modification/Rationale** | **FAR Part 42/43/32/52, DFARS 242/243/232, WAWF/PIEE corpus** | **Hybrid retrieval (dense + sparse) + re-rank** |
| 14 | Contractor Signer Name/Title | Input / contract record | Not AI-generated |
| 15 | Contractor Signature | CO UI action | Not AI-generated |
| 16A | Contracting Officer Name/Title | CO identity from auth | Not AI-generated |
| 16B–C | CO Signature + Date | CO UI action | Not AI-generated |

**Block 13 is the only block requiring full hybrid RAG.** Block 11 needs dense-only retrieval for classification. All other blocks pull from structured records.

**Block 13 pipeline (LangGraph nodes):**

1. `retrieve_node` — runs two parallel searches against the FAR/DFARS, WAWF/PIEE corpus: dense `$vectorSearch` via Titan V2 (k=20) and sparse `$search` BM25 (k=20). Results are merged using Reciprocal Rank Fusion (RRF) with weights 0.6 dense / 0.4 sparse to produce a combined candidate set. Cross-encoder re-ranking then narrows to the top 8 chunks, stored in `state["documents"]`.
2. `confidence_check_node` — Haiku acts as LLM-as-judge, scoring each retrieved chunk 0.0–1.0 for relevance to the CO's modification query. Scores aggregate to `state["confidence"]`. Gate: score ≥ 0.85 → proceed to draft; score < 0.85 → `gate_status = "RAG_FAILED_AWAITING_CO_REVIEW"`.
3. `draft_node` — Haiku generates Block 13 draft text grounded in `state["documents"]`. Only reached if confidence gate passed.
4. `faithfulness_gate_node` — RAGAS faithfulness judge (Claude Haiku, `temperature=0`) scores `state["draft"]` against `state["documents"]`. Score < 0.85 → `gate_status = "FAITHFULNESS_FAILED_AWAITING_CO_REVIEW"`, surface to CO: faithfulness score, which retrieved chunks the draft diverged from, and the full draft text. Score ≥ 0.85 → `gate_status = "passed"`. This gate catches post-retrieval hallucination — fabricated FAR citations not present in the retrieved chunks — which the `confidence_check_node` cannot detect.

**Block 11 pipeline (LangGraph node):**

1. `classify_modification_node` — dense retrieval (k=5, cosine) against FAR 43.103 type definitions. Haiku classifies the modification into types A–E and stores the result in state.

---

### 5. Re-ranking Strategy

**Decision: `CrossEncoderReranker` with `cross-encoder/ms-marco-MiniLM-L-6-v2`**

Reasoning: No additional API cost — the cross-encoder runs locally inside the AI Orchestrator container on CPU. No new external dependency. 22M parameter model with strong passage re-ranking performance.

Implementation: Use `CrossEncoderReranker` from `langchain-community` wrapping `HuggingFaceCrossEncoder`. Called inside `retrieve_node` after RRF fusion, before results are written to `state["documents"]`. `top_n=8`.

The model (`cross-encoder/ms-marco-MiniLM-L-6-v2`) must be downloaded at container build time — add to `requirements.txt` and pre-download in the `Dockerfile`. Do not pull at runtime.

> **Approved fallback:** MongoDB Atlas `$vectorSearch` with built-in `reciprocalRankFusion` — zero extra infra, approved without team vote if cross-encoder proves too slow.
> **Requires team approval:** Any reranker that makes an external API call (Cohere Rerank, Voyage, etc.).

---

### 6. Security for SAL Government Information

Post-award contract data is Sensitive but Unclassified (SBU) under FAR 4.4 / NARA CUI framework. Controls applied at the retrieval layer:

**Network isolation:**
- MongoDB Atlas Local container exposed only on `localhost` inside Docker network — never on a public port
- No direct MongoDB access from outside the Docker Compose network
- All Bedrock calls go over HTTPS via AWS SDK (no cleartext)

**Encryption:**
- MongoDB Atlas Local: encryption at rest enabled (WiredTiger encryption)
- TLS 1.2+ enforced on all MongoDB connections (`tls=true` in connection string)
- Bedrock: data in transit is encrypted by AWS (TLS 1.2+)

**Access control:**
- MongoDB RBAC: AI Orchestrator has a dedicated MongoDB user with read-only access to the FAR/DFARS, WAWF/PIEE corpus collection and read-write on the audit log collection
- No CO or end-user has direct MongoDB access
- Bedrock: IAM role scoped to `bedrock:InvokeModel` on `amazon.titan-embed-text-v2:0` and Claude models only

**Embeddings and PII:**
- Do NOT embed Personally Identifiable Information (contractor EIN, individual names, addresses)
- PII fields (Block 8: contractor name/address) are stored as plaintext metadata in MongoDB — never vectorized
- FAR/DFARS, WAWF/PIEE corpus chunks only — no contract-instance data goes into the vector index

**Tenant isolation (see Section 11):**
- All vector queries include mandatory `tenant_id` pre-filter — no cross-contract leakage
- Applied inside the LangGraph `retrieve_node`, not trusting the application layer to set it

**Audit trail:**
- Every retrieval operation logged with user identity, role, timestamp, query text, and chunk IDs retrieved (append-only, per ADR-0004)
- Retrieval logs are immutable — MongoDB insert-only collection with no update/delete permissions for the AI Orchestrator role

---

### 7. RAG Observability

**Decision: LangFuse (self-hosted) + structured JSON retrieval logs in MongoDB**

LangSmith requires a paid subscription — rejected on budget. LangFuse Community Edition is open-source, self-hosted, and integrates with LangGraph via a callback handler (`langfuse.callback.CallbackHandler`). LangFuse runs as an additional service inside Docker Compose and communicates on the internal Docker network only.

**Metrics captured per retrieval request:**

| Metric | Source |
|---|---|
| Query latency (total) | LangFuse trace |
| Embedding latency | LangFuse span |
| `$vectorSearch` latency | LangFuse span |
| Chunks retrieved (count, IDs) | LangFuse metadata |
| Re-rank scores | LangFuse metadata |
| Confidence score | Custom ADR-0004 gate |
| Cache hit/miss | Custom log |
| Bedrock token usage | LangFuse + Bedrock SDK |
| Model ID + version | LangFuse metadata |

**RAGAS Evaluation (offline, not real-time):**

RAGAS is an evaluation framework for RAG pipelines that uses LLM-as-a-judge to score retrieval quality. Run against a golden test set — not on live production traffic.

| RAGAS Metric | What it measures |
|---|---|
| **Faithfulness** | Is the generated Block 13 draft faithful to retrieved FAR clauses? |
| **Answer Relevancy** | Does the draft actually address the CO's modification intent? |
| **Context Precision** | Were the retrieved chunks actually relevant? (retrieval precision) |
| **Context Recall** | Were all necessary FAR clauses retrieved? (retrieval recall) |

**Faithfulness is the primary quality gate.** A faithfulness score < 0.85 triggers CO escalation via `gate_status = "FAITHFULNESS_FAILED_AWAITING_CO_REVIEW"` (inline, enforced by `faithfulness_gate_node` in the LangGraph pipeline). Faithfulness is also the named regression signal for CI.

**CI regression gate (blocks merge):** On any PR touching `retrieve_node`, `draft_node`, prompt templates, or the embedding pipeline — run RAGAS faithfulness against the golden set. If `faithfulness_score < baseline_faithfulness × 0.95` (relative 5% drop), CI fails and the PR is blocked. Baseline is stored in `eval/faithfulness_baseline.json` in the repo root and updated manually after intentional quality improvements.

- **Golden set:** 10 Block 13 samples minimum (query + ground-truth FAR citations + expected draft), stored in `eval/golden_set.json`. RAGAS judge must run at `temperature=0` for CI determinism — nondeterministic judge runs cause false-positive CI failures.
- **CI scope:** PRs not touching the above files skip the faithfulness regression gate.

Run full RAGAS evaluation (all four metrics):
- On every corpus update (new FAR version ingested)
- Weekly against the golden set — updates `eval/faithfulness_baseline.json` if faithfulness improves

**LLM-as-a-Judge for Retrieval (inline, on every request):**

This is the `confidence_check_node` described in Section 4. Haiku scores each retrieved FAR clause excerpt for relevance to the CO's modification query (0.0–1.0 per chunk). Scores aggregate to the pipeline confidence signal. Below 0.85 → `RAG_FAILED_AWAITING_CO_REVIEW`. This is LLM-as-a-judge applied at retrieval time — not post-generation evaluation.

---

### 8. Anti-Patterns to Avoid

| Anti-Pattern | Why Harmful | Our Mitigation |
|---|---|---|
| Splitting FAR clauses mid-sentence | Breaks citation integrity — chunk no longer maps to a real clause | Section-boundary chunking rules (see Section 13) |
| Embedding PII/contractor data | Leaks sensitive info via similarity search | PII stored as plaintext metadata only, never vectorized |
| Stale embeddings after model change | Old vectors are incompatible with new embedding model | Embedding model version tagged on every chunk; index rebuilt on model change |
| Missing provenance metadata | Can't trace a citation back to its source chunk | Every chunk stores `source_document`, `far_part`, `clause_number`, `ingested_by` |
| No confidence gate | Hallucinated FAR citations reach the CO | ADR-0004 0.85 threshold enforced in `confidence_check_node` |
| Retrieval without re-ranking | Top-k by cosine distance ≠ top-k by relevance | Cross-encoder re-ranking inside `retrieve_node` on every Block 13 query |
| Treating all SF-30 blocks as RAG | Wastes Bedrock calls on fields that are direct DB lookups | Block-routing table (Section 4) |
| Single retrieval strategy for all queries | FAR clause numbers need keyword match; modification rationale needs semantic match | Hybrid dense + sparse with RRF fusion |
| No faithfulness gate | Confidence gate checks retrieval quality, not generation quality — LLM can hallucinate FAR citations not present in retrieved chunks while still passing the 0.85 confidence gate | `faithfulness_gate_node` after `draft_node`; CI regression block on golden set |
| Synchronous ingestion during CO request | Blocks the pipeline during embedding | Ingestion is offline/async; corpus indexed at startup and on FAR updates only |
| No fallback on vector search failure | Total outage if `mongot` crashes | Fallback to BM25-only `$search` on `$vectorSearch` failure |
| LCEL chains or Runnables for orchestration | Unsupported pattern in v1.0, removed at v2.0 | CI import linter bans LCEL orchestration patterns and `langchain-classic` |

---

### 9. Index Management

**Index creation:** Use `MongoDBAtlasVectorSearch.from_documents()` from `langchain-mongodb` — pass the chunk documents, `BedrockEmbeddings` instance, the target collection, and `index_name="far_vector_idx"`. This is a one-time setup operation run by the ingestion pipeline, not at application runtime.

**Index version tracking:** Every document in the vector collection stores these metadata fields:
- `embedding_model`: Bedrock model ID (e.g., `amazon.titan-embed-text-v2:0`)
- `embedding_dimensions`: integer (e.g., `512`)
- `embedding_model_version`: short string (e.g., `v2`)
- `indexed_at`: ISO 8601 timestamp of ingestion

**On embedding model change (e.g., Titan V2 → V3):**

> **Warning:** This requires team confirmation before execution — it touches production index data.

1. Use `mongodump` to export the existing `far_corpus` collection as a backup before any changes
2. Create new index `far_vector_idx_v3` alongside existing `far_vector_idx_v2`
3. Re-embed all documents with the new model → insert into the `v3` collection
4. Run RAGAS evaluation on both indexes — confirm v3 recall ≥ v2 recall
5. Update the `retrieve_node` index name to `far_vector_idx_v3`
6. Drop `far_vector_idx_v2` after one sprint of stable validation

Never swap indexes without RAGAS comparison. Never drop the old index on the same day as cutover.

**Routine maintenance:**
- Monitor index size: 512 dims × 4 bytes × N chunks → alert if exceeding 2GB (scale signal)
- Rebuild index after bulk corpus updates; incremental inserts are handled by Atlas Local automatically
- No manual `mongot` tuning required — the local deployment manages index rebuild scheduling

---

### 10. Failure Handling

All failure handling is aligned with ADR-0004 retry policy: max 4 retries, exponential backoff, 20% jitter.

| Failure Mode | Detection | Response |
|---|---|---|
| Bedrock `ThrottlingException` | AWS SDK exception | Retry (max 4, backoff + jitter). After 4: log, enter `RAG_FAILED_AWAITING_CO_REVIEW` |
| Bedrock timeout | `ConnectTimeoutError` | Same retry policy as throttling |
| `$vectorSearch` failure | `OperationFailure` from pymongo | Fallback: run BM25-only `$search`. Log fallback in audit record. Do not fail silently. |
| MongoDB connection failure | `ConnectionFailure` | Circuit breaker (3 consecutive failures → open). Surface error to CO with audit record. |
| Confidence below 0.85 | Score check in `confidence_check_node` | Enter `RAG_FAILED_AWAITING_CO_REVIEW`. Surface: failure reason, retry count, query metadata, retrieved chunks. Never leave form blank. |
| Faithfulness below 0.85 | RAGAS judge score in `faithfulness_gate_node` | Enter `FAITHFULNESS_FAILED_AWAITING_CO_REVIEW`. Surface: faithfulness score, which retrieved chunks the draft diverged from, full draft text. CO decides: retry, edit draft manually, or escalate. |
| Partial retrieval (< 3 chunks) | Chunk count check | Log warning. Below 3 chunks: treat as confidence failure → escalate. |
| Embedding failure | Exception in `BedrockEmbeddings` | Do not proceed to draft. Queue retry. Audit record must capture the failure. |
| Re-ranker failure | Exception in `CrossEncoderReranker` | Fallback to unranked top-k from the fused results. Log degraded mode in audit record. |
| Stale cache / version mismatch | Embedding model version field check | Invalidate cache entry. Re-embed. |

**No silent failure paths.** Every failure state produces an audit record. Every failure that blocks draft generation escalates to a named gate state visible to the CO.

---

### 11. Multi-Tenant Retrieval

**The vector store contains only FAR Part 42/43/32/52, DFARS 242/243/232, WAWF/PIEE documents — all public law, no contract-instance data.** There is no per-contract or per-agency isolation required in the vector index.

Every CO queries the same shared FAR/DFARS, WAWF/PIEE corpus. Isolation is applied at the audit log level, not the retrieval level.

**Vector store:** No `tenant_id` filter on vector queries. All indexed documents are global FAR/DFARS, WAWF/PIEE corpus. No per-contract documents enter the vector index.

**Audit log isolation:** Every retrieval log is scoped to `user_id` + `contract_id` (the contract the CO is modifying). A CO cannot view another CO's retrieval audit records. This is enforced at the audit log query layer via the existing auth/RBAC controls, not inside the vector search.

**Structured DB lookups (Blocks 1–10, 12):** Already scoped by contract ID at the application layer. No change needed here.

---

### 12. Provenance and Ingestion Logging

**Every chunk ingested into the vector store carries full lineage metadata.** Required fields per chunk document:

| Field | Type | Description |
|---|---|---|
| `chunk_id` | UUID | Unique identifier for this chunk |
| `chunk_text` | string | The raw text content embedded |
| `chunk_sequence` | integer | Position of this chunk within its source document |
| `source_document.title` | string | Document title (e.g., "FAR Part 43 — Contract Modifications") |
| `source_document.far_part` | string | FAR part number (e.g., `"43"`) |
| `source_document.subpart` | string | FAR subpart (e.g., `"43.1"`) |
| `source_document.clause_number` | string | Clause identifier (e.g., `"43.103"`) |
| `source_document.url` | string | Canonical URL of the source document |
| `document_version` | date string | Date of the FAR corpus version ingested |
| `ingestion_timestamp` | ISO 8601 | When this chunk was ingested |
| `ingested_by.user_id` | string | Identity of the corpus admin who triggered ingestion |
| `ingested_by.role` | string | Role (always `contracting_officer` — CO is the only role in the system) |
| `ingested_by.service` | string | Service that performed ingestion (`ai-orchestrator-ingestion`) |
| `embedding_model` | string | Bedrock model ID used to generate the embedding |
| `embedding_dimensions` | integer | Dimension count of the stored vector |
| `embedding_model_version` | string | Short version tag (e.g., `v2`) |
| `tenant_id` | string | Namespace — `far_corpus_global` for FAR/DFARS, WAWF/PIEE documents |
| `embedding` | float array | The vector representation |

**Every retrieval operation logs to the audit collection.** Required fields per retrieval log:

| Field | Type | Description |
|---|---|---|
| `retrieval_id` | UUID | Unique identifier for this retrieval event |
| `sf30_block` | string | Which SF-30 block triggered this retrieval (e.g., `"13"`) |
| `contract_id` | string | The contract number being modified |
| `tenant_id` | string | The tenant namespace used in the query filter |
| `user_id` | string | CO identity |
| `role` | string | `contracting_officer` |
| `timestamp` | ISO 8601 | When retrieval was executed |
| `query_text` | string | The CO's modification description passed as the retrieval query |
| `retrieval_strategy` | string | e.g., `hybrid_rrf_reranked` |
| `chunks_retrieved` | UUID array | IDs of the chunks returned to the pipeline |
| `retrieval_scores` | float array | Pre-rerank scores |
| `reranked_scores` | float array | Post-rerank scores |
| `confidence` | float | Aggregated LLM-as-judge confidence score |
| `embedding_model` | string | Model used to embed the query |
| `llm_model` | string | Haiku or Sonnet model ID used for confidence check |
| `cache_hit` | boolean | Whether embedding was served from cache |
| `latency_ms` | integer | Total retrieval latency in milliseconds |

This is the "who done it and how it was constructed" trail for every retrieval event. Audit records must satisfy DCAA traceability requirements for government contract data.

---

### 13. Chunking Strategy

**FAR Part 42/43/32/52 / DFARS 242/243/232 / WAWF / PIEE document structure** is hierarchical: Part → Subpart → Section → Clause. For example: FAR Part 43 → Subpart 43.1 (General) → 43.103 (Types of contract modifications). Chunks must respect this structure.

**Decision: Section-boundary chunking using `RecursiveCharacterTextSplitter` from `langchain-text-splitters`**

Use established LangChain tooling — do not write a custom chunker unless section parsing fails for a specific FAR source format. Any custom parser requires team approval per Guideline 6.

**Configuration:**
- `chunk_size`: 512 tokens (Titan V2 sweet spot; well within the 8,192 token input window)
- `chunk_overlap`: 64 tokens (~12% overlap for context continuity across chunk boundaries)
- `separators` in priority order: double newline (between clauses/sections), single newline (between paragraphs), period-space (between sentences as last resort)

**Chunking rules:**
1. Split at clause/section boundaries first — prefer `\n\n` splits over sentence splits
2. Never split a FAR clause number from its definition text (e.g., "43.103(a)" and its governing sentence must remain in the same chunk)
3. Each chunk must inherit `far_part`, `subpart`, and `clause_number` metadata from its parent section header
4. Discard fragments shorter than 100 characters — these are page numbers, headers, or artifacts

**chunk_size: 512** chosen because 512-token chunks provide sufficient context to ground a FAR citation without diluting the retrieval precision signal. This also aligns with our 512-dimension embedding choice — both reflect the same semantic granularity expectation.

---

### 14. Startup Cache

**Decision: `CacheBackedEmbeddings` from `langchain-community` + pre-warm query on startup**

`CacheBackedEmbeddings` wraps the `BedrockEmbeddings` instance and caches computed embedding vectors. Identical chunk text will not re-trigger a Bedrock API call — the cached vector is returned immediately. This is especially useful during ingestion pipeline reruns and warmup.

**Cache backend:** Use a MongoDB-backed byte store to keep the cache persistent across container restarts and keep infrastructure to one database (no Redis dependency).

**Cache TTL:** No TTL on the embedding cache — embeddings are deterministic for identical text + identical model version. Cache is invalidated on embedding model version change (all entries with the old model version are invalid and must be purged).

**Query result cache:** Not implemented. Retrieval results change as the corpus updates and caching them would create audit integrity issues (stale results would be non-traceable to current corpus state).

**Pre-warm at startup:** On AI Orchestrator startup, execute one warmup `$vectorSearch` query against the FAR corpus. This forces `mongot` to load the vector index into memory so the first real CO query does not pay a cold-start penalty. The warmup query is a representative Block 13 query (e.g., a common modification type query against FAR 43.103).

---

### 15. HITL Stages for RAG

HITL (Human-in-the-Loop) is a hard compliance requirement per ADR-0004. The RAG pipeline has these human gates:

| Stage | HITL Trigger | Human Action Required |
|---|---|---|
| **Corpus ingestion** | New FAR/DFARS/WAWF/PIEE version or corpus update | CO reviews and approves new FAR/DFARS/WAWF/PIEE document batch before ingestion to vector store (CO is the only role in the system) |
| **Retrieval review** | CO gate UI (pre-approval) | CO sees retrieved FAR/DFARS clause IDs, excerpts, and citation mapping before approving the draft |
| **Confidence failure** | Score < 0.85 | CO sees failure reason, retry history, retrieved chunks. CO decides: retry with modified query, escalate, or complete manually |
| **CO rejection/edit** | CO rejects AI draft | RAG re-runs from scratch against corrected SF-30 scope. Prior retrieval marked superseded. |
| **Superseded retrieval** | After any CO rejection | Prior retrieval records are non-reusable; audit log captures supersession event |

CO rejection invalidates prior retrieval entirely — new retrieval starts fresh with no stale context (per ADR-0004).

---

### 16. LangChain v1.0 Tools Inventory for Our System

Established tools we use — no custom implementation needed for any of these:

| Tool | Package | Our Use |
|---|---|---|
| `StateGraph` | `langgraph` | **Primary orchestration** — all pipeline nodes and state transitions |
| `create_agent` | `langchain` | Agent harness (built on LangGraph) |
| `MongoDBAtlasVectorSearch` | `langchain-mongodb` | Vector store for FAR/DFARS, WAWF/PIEE corpus; called directly inside LangGraph nodes |
| `BedrockEmbeddings` | `langchain-aws` | Titan V2 embeddings via Bedrock |
| `ChatBedrock` | `langchain-aws` | Claude Haiku/Sonnet invocation inside LangGraph nodes |
| `BM25Retriever` | `langchain-community` | Sparse retrieval for hybrid search (keyword/clause number match) |
| `CrossEncoderReranker` | `langchain-community` | Local cross-encoder re-ranking inside `retrieve_node` |
| `RecursiveCharacterTextSplitter` | `langchain-text-splitters` | FAR/DFARS/WAWF/PIEE document chunking (offline ingestion pipeline) |
| `CacheBackedEmbeddings` | `langchain-community` | Embedding cache (avoids re-embedding identical text) |
| `BaseRetriever`, `Document` | `langchain-core` | Type contracts used inside LangGraph node signatures |

**Not used (do not introduce):**
- `create_retrieval_chain` — LCEL-based, not our pattern
- `create_stuff_documents_chain` — LCEL-based, not our pattern
- LCEL `|` pipe operator for orchestration
- `EnsembleRetriever` as a Runnable — implement RRF fusion as plain Python inside the retrieve node
- Any import from `langchain-classic`

**Requires team approval before use (custom or non-standard):**
- Custom chunk parser beyond `RecursiveCharacterTextSplitter`
- Any reranker requiring an external API call (Cohere Rerank API, Voyage, etc.)
- Any vector store other than `MongoDBAtlasVectorSearch`
- Any use of LCEL or Runnables for orchestration (must go through LangGraph instead)

---

## Migration Plan: MongoDB → MongoDB Atlas Local

> **Downtime is acceptable.** Sequential replacement — no parallel-run required.

### Step 1: Backup (before touching anything)

1. While the old `mongo:7` container is still running, use `mongodump` to export all collections to a local backup directory
2. Verify the backup is complete — document counts must match what was in the running container

### Step 2: Swap the Container

1. Stop and remove the old `mongo:7` container
2. Update `docker-compose.yml`: replace the `mongo:7` service with `mongodb/mongodb-atlas-local` on port `27017:27017`
3. Start the new container and confirm it passes its healthcheck
4. Confirm `mongot` (Atlas Search engine) is active inside the container via a `mongosh` admin command

### Step 3: Restore Seed Data

1. Use `mongorestore` to import the backup into Atlas Local (port 27017)
2. Verify all collection document counts match the backup

### Step 4: Embedding Pipeline

1. Create the `far_corpus` collection in Atlas Local
2. Load FAR Part 42/43/32/52, DFARS 242/243/232, WAWF/PIEE source documents
3. Chunk with `RecursiveCharacterTextSplitter` (512 tokens, 64 overlap)
4. Embed with Titan V2 via Bedrock — **team must explicitly load the `.env` bearer token before this step**
5. Insert all chunks with full provenance metadata

### Step 5: Vector Index Creation

1. Create the `$vectorSearch` index `far_vector_idx` (512 dims, cosine similarity, on the `embedding` field)
2. Create the Atlas Search index `far_text_idx` (BM25, on the `chunk_text` field)
3. Verify both indexes are ACTIVE via `mongosh` before proceeding

### Step 6: Verify and Go Live

1. Execute at least 10 representative Block 13 queries covering different modification types
2. Verify retrieved chunks include correct FAR/DFARS clause citations with provenance metadata
3. Confirm confidence scores meet the 0.85 threshold on the golden test set
4. Verify all Spring Boot services operate normally (CRUD, existing seed data accessible)

### Step 7: Cleanup

1. Archive the `mongodump` backup to cold storage
2. Remove any remaining `mongo:7` image references from docker-compose

---

## Consequences

- AI Orchestrator now requires `langchain>=1.0`, Python `>=3.10`
- Vector index must be built before ANY SF-30 AI-assist flow goes live — no index means no retrieval means no draft
- Embedding pipeline requires Bedrock bearer token — team must explicitly enable the `.env` before Phase 3
- `cross-encoder/ms-marco-MiniLM-L-6-v2` must be downloaded at container build time (not runtime) — add to `requirements.txt` and `Dockerfile`
- LangFuse requires its own Docker service in `docker-compose.yml` plus two new env vars (`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`)
- Corpus admin role must be defined in auth before corpus ingestion can begin (HITL gate requirement)
- Any `from langchain_classic import` anywhere in the codebase fails CI — linter rule required
- Block 13 retrieval adds ~300–500ms latency per CO query (embedding + vector search + re-rank) — within acceptable UX range; baseline in LangFuse from day one
- CI faithfulness regression gate requires Bedrock access in the CI environment and `eval/faithfulness_baseline.json` committed to the repo root
- `eval/golden_set.json` (10+ Block 13 samples) must be created and committed before the CI gate is enforced — gate is warn-only until golden set exists

---

