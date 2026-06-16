import { Injectable } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';

/**
 * AiService — calls the ai-orchestrator AI-draft + clause-retrieval endpoints.
 *
 * Shared by the SF-30 wizard (AI-draft rationale / price-cost) and the
 * modification editor (clause-library search), matching the codebase convention
 * that all HTTP lives in a service, not inline in components.
 *
 * DEV wiring: hits ai-orchestrator directly on its published port
 * (environment.aiOrchestratorUrl), bypassing the gateway (which has no dev auth
 * server). The draft path runs a LangChain Runnable on AWS Bedrock and is traced
 * by LangSmith automatically. The clause-search path runs the real hybrid RAG
 * retrieval over the FAR/DFARS corpus; ai-orchestrator validates the identity
 * headers we pass for the retrieval audit trail.
 */
export interface DraftSectionRequest {
  kind: 'rationale' | 'price_cost';
  title?: string;
  contract_number?: string;
  mod_type?: string;
  far_authority?: string;
  funding_delta?: number;
  pop_changed?: boolean;
  pop_original_start?: string;
  pop_original_end?: string;
  pop_revised_start?: string;
  pop_revised_end?: string;
  constraints?: string;
}

export interface DraftSectionResponse {
  draft: string;
  model: string;
  traced: boolean;
  stub: boolean;
}

export interface ClauseHit {
  chunk_id: string;
  chunk_text: string;
  score: number | null;
  source_document?: { title?: string; clause_number?: string; far_part?: string } | null;
}

export interface RetrieveResponse {
  correlation_id: string;
  chunks: ClauseHit[];
  retrieval_strategy: string;
  latency_ms: number;
  chunk_count: number;
  degraded: boolean;
}

export interface ContractLookupResponse {
  match: 'found' | 'not_found' | 'ambiguous';
  /** SF-30 block positions → authoritative value (e.g. "2", "3", "12"). */
  static_fields?: Record<string, string>;
  source_citation?: { system?: string; record_id?: string; fetched_at?: string };
}

@Injectable({ providedIn: 'root' })
export class AiService {
  private readonly base = environment.aiOrchestratorUrl;

  constructor(private http: HttpClient) {}

  /** AI-draft an SF-30 wizard section (real Bedrock call, LangSmith-traced). */
  draftSection(req: DraftSectionRequest): Observable<DraftSectionResponse> {
    return this.http.post<DraftSectionResponse>(`${this.base}/draft-section`, req);
  }

  /**
   * Resolve the contract-of-record for SF-30 autofill (deterministic backend
   * lookup, no LLM). Tenant-scoped by agencyId — must match the seeded contract's
   * agency or the lookup returns match: "not_found".
   */
  lookupContract(contractNumber: string, agencyId: string): Observable<ContractLookupResponse> {
    return this.http.post<ContractLookupResponse>(
      `${this.base}/workflow/contract-lookup`,
      { contract_number: contractNumber, agency_id: agencyId },
    );
  }

  /**
   * Hybrid RAG over the FAR/DFARS corpus. ai-orchestrator's /retrieve requires
   * gateway-asserted identity headers; in this dev path we supply them directly.
   */
  clauseSearch(query: string, agencyId = 'GSA-FAS', userId = 'co-reeves',
               role = 'contracting_officer'): Observable<RetrieveResponse> {
    const headers = new HttpHeaders({
      'X-Tenant-Id': agencyId,
      'X-User-Id': userId,
      'X-User-Role': role,
    });
    return this.http.post<RetrieveResponse>(
      `${this.base}/retrieve/`,
      { query, sf30_block: '13', contract_id: 'demo-contract' },
      { headers },
    );
  }
}
