/**
 * Corpus ingestion models (ADR-0005 Phase 1 — write path).
 *
 * Mirrors the ai-orchestrator ingestion router contracts:
 *   UploadResponse  ← POST /corpus/upload
 *   IngestRequest   → POST /corpus/ingest
 *   IngestResponse  ← POST /corpus/ingest
 */

/** Returned after staging a document for CO review (HITL upload step). */
export interface CorpusUploadResponse {
  staged_document_id: string;
  title: string;
  size_bytes: number;
  status: string; // "staged_awaiting_ingest"
}

/** Provenance metadata the CO supplies alongside the file. */
export interface CorpusDocumentMetadata {
  title: string; // e.g. "FAR Part 43 — Contract Modifications"
  far_part: string; // e.g. "43"
  subpart?: string; // e.g. "43.1"
  clause_number?: string; // e.g. "43.103"
  source_url?: string; // canonical URL of the source document
}

/** Body for the CO-approved ingestion step. */
export interface CorpusIngestRequest {
  staged_document_ids: string[];
  user_id: string; // CO identity approving the batch (HITL §15)
  tenant_id: string; // "far_corpus_global" or an agency id
  document_version: string; // date of the FAR corpus version
}

/** Chunk summary returned after ingestion completes. */
export interface CorpusIngestResponse {
  documents_ingested: number;
  chunks_inserted: number;
  chunks_discarded: number;
  cache_hits: number;
}
