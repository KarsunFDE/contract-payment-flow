import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { CorpusService } from '../../services/corpus.service';
import {
  CorpusDocumentMetadata,
  CorpusUploadResponse,
} from '../../models/corpus';

/**
 * Corpus Upload (ADR-0005 Phase 1 — write path, HITL §15).
 *
 * CO-facing page for loading FAR/DFARS/WAWF/PIEE source documents into the
 * retrieval corpus. Two-step flow mirroring the HITL ingestion gate:
 *
 *   1. Upload — pick an md/txt file, fill provenance metadata (title,
 *      FAR part, clause, source URL), stage it for review.
 *   2. Ingest — review the staged batch, then approve ingestion
 *      (chunk → embed → insert into the vector store).
 *
 * Real government documents (full FAR 32 etc.) are not available yet —
 * this page is exercised with the seed stubs until they arrive.
 */
@Component({
  selector: 'app-corpus-upload',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="page-header">
      <div>
        <h2>Retrieval corpus upload</h2>
        <div class="subtitle">FAR / DFARS / WAWF / PIEE source documents · staged for CO approval before ingestion</div>
      </div>
    </div>

    <div class="two-col">
      <!-- Step 1: stage a document -->
      <div class="card">
        <h3>Upload source document</h3>
        <label><span class="label-text">Document file (md / txt)</span>
          <input type="file" accept=".md,.txt" (change)="onFileSelected($event)" />
        </label>
        <label><span class="label-text">Title</span>
          <input [(ngModel)]="metadata.title" placeholder="FAR Part 43 — Contract Modifications" />
        </label>
        <label><span class="label-text">FAR part</span>
          <input [(ngModel)]="metadata.far_part" placeholder="43" />
        </label>
        <label><span class="label-text">Subpart</span>
          <input [(ngModel)]="metadata.subpart" placeholder="43.1" />
        </label>
        <label><span class="label-text">Clause number</span>
          <input [(ngModel)]="metadata.clause_number" placeholder="43.103" />
        </label>
        <label><span class="label-text">Source URL</span>
          <input [(ngModel)]="metadata.source_url" placeholder="https://www.acquisition.gov/far/part-43" />
        </label>
        <button (click)="stageDocument()" [disabled]="!selectedFile || uploading">
          {{ uploading ? 'Uploading…' : 'Stage for review' }}
        </button>
        <p *ngIf="errorMessage" class="error">{{ errorMessage }}</p>
      </div>

      <!-- Step 2: review staged batch, approve ingestion (HITL gate) -->
      <div class="card">
        <h3>Staged batch — awaiting CO approval</h3>
        <table *ngIf="stagedDocuments.length; else emptyBatch">
          <thead><tr><th>Title</th><th>Size</th><th>Status</th></tr></thead>
          <tbody>
            <tr *ngFor="let doc of stagedDocuments">
              <td>{{ doc.title }}</td>
              <td>{{ doc.size_bytes }} B</td>
              <td><span class="badge">{{ doc.status }}</span></td>
            </tr>
          </tbody>
        </table>
        <ng-template #emptyBatch>
          <p>No documents staged yet.</p>
        </ng-template>
        <button (click)="approveIngestion()" [disabled]="!stagedDocuments.length || ingesting">
          {{ ingesting ? 'Ingesting…' : 'Approve + ingest batch' }}
        </button>
        <p *ngIf="ingestSummary">
          Ingested: {{ ingestSummary }}
        </p>
      </div>
    </div>
  `,
})
export class CorpusUploadComponent {
  /** File picked in step 1, awaiting metadata + staging. */
  selectedFile: File | null = null;

  /** Provenance metadata the CO fills in alongside the file. */
  metadata: CorpusDocumentMetadata = { title: '', far_part: '' };

  /** Documents staged this session, shown in the approval table. */
  stagedDocuments: CorpusUploadResponse[] = [];

  uploading = false;
  ingesting = false;
  errorMessage = '';
  ingestSummary = '';

  constructor(private corpusService: CorpusService) {}

  /** Capture the file selection from the input element. */
  onFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.selectedFile = input.files?.[0] ?? null;
  }

  /** Step 1 — upload the file + metadata, add result to the staged table. */
  stageDocument(): void {
    // TODO(A): validate metadata (title + far_part required), call
    //   corpusService.uploadDocument(), push response onto stagedDocuments,
    //   reset the form. Surface HTTP errors in errorMessage.
  }

  /** Step 2 — HITL approval: ingest every staged document. */
  approveIngestion(): void {
    // TODO(A): build CorpusIngestRequest from stagedDocuments ids
    //   (user_id from role service, tenant_id "far_corpus_global",
    //   document_version = today), call corpusService.ingestDocuments(),
    //   render chunk counts in ingestSummary, clear the staged table.
  }
}
