import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import {
  CorpusDocumentMetadata,
  CorpusIngestRequest,
  CorpusIngestResponse,
  CorpusUploadResponse,
} from '../models/corpus';

/**
 * Corpus ingestion service (ADR-0005 Phase 1 — write path).
 *
 * Talks to the ai-orchestrator /corpus endpoints through the API gateway.
 * Two-step HITL flow (§15): upload stages the document for CO review;
 * ingest runs the approved batch through chunk → embed → insert.
 */
@Injectable({ providedIn: 'root' })
export class CorpusService {
  constructor(private http: HttpClient) {}

  /** Stage one source document (md/txt) plus its provenance metadata. */
  uploadDocument(
    file: File,
    metadata: CorpusDocumentMetadata,
  ): Observable<CorpusUploadResponse> {
    // Multipart form — file plus the Form(...) fields the router expects.
    const form = new FormData();
    form.append('file', file, file.name);
    form.append('title', metadata.title);
    form.append('far_part', metadata.far_part);
    form.append('subpart', metadata.subpart ?? '');
    form.append('clause_number', metadata.clause_number ?? '');
    form.append('source_url', metadata.source_url ?? '');
    return this.http.post<CorpusUploadResponse>(
      `${environment.apiGatewayUrl}/corpus/upload`,
      form,
    );
  }

  /** Ingest CO-approved staged documents into the vector store. */
  ingestDocuments(request: CorpusIngestRequest): Observable<CorpusIngestResponse> {
    return this.http.post<CorpusIngestResponse>(
      `${environment.apiGatewayUrl}/corpus/ingest`,
      request,
    );
  }

  /** Corpus visibility — chunk counts by tenant / FAR part. */
  getCorpusStats(): Observable<Record<string, unknown>> {
    return this.http.get<Record<string, unknown>>(
      `${environment.apiGatewayUrl}/corpus/stats`,
    );
  }
}
