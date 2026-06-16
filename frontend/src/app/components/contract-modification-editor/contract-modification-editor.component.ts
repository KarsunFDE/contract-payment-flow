import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { ContractModification } from '../../models/contract-modification';
import { FIXTURE_CONTRACT_MODIFICATIONS } from '../../services/mock-fixtures';
import { AiService } from '../../services/ai.service';

/**
 * Pre-publication editor for a draft ContractModification.
 *
 * Includes a side-panel clause-library lookup (RAG over FAR/DFARS),
 * which is the W2 anchor surface (hybrid lexical + vector). The
 * search input here is the W2 Wed retrieval-boundary work surface
 * — must filter by agency_id (Item 10).
 */
@Component({
  selector: 'app-contractModification-editor',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink],
  template: `
    <div class="page-header">
      <div>
        <h2>{{ contractModification?.title || 'Draft contractModification' }}</h2>
        <div class="subtitle">
          <span class="badge" [ngClass]="(contractModification?.status || 'draft').toLowerCase()">{{ contractModification?.status }}</span>
          · NAICS {{ contractModification?.naics }} · {{ contractModification?.contractType }}
        </div>
      </div>
      <div>
        <a [routerLink]="['/contractModifications', id, 'amendments']"><button class="secondary">Amendments</button></a>
        <a [routerLink]="['/contractModifications', id, 'qa']"><button class="secondary">Q&amp;A triage</button></a>
        <a [routerLink]="['/contractModifications', id, 'proposals']"><button class="secondary">Proposals</button></a>
      </div>
    </div>

    <div class="two-col">
      <div>
        <div class="card">
          <h3>Section C — Statement of Work</h3>
          <textarea rows="8" [(ngModel)]="sectionC"></textarea>
        </div>
        <div class="card">
          <h3>Section L — Instructions to Offerors</h3>
          <textarea rows="8" [(ngModel)]="sectionL"></textarea>
        </div>
        <div class="card">
          <h3>Section M — InvoiceReview Factors</h3>
          <textarea rows="6" [(ngModel)]="sectionM"></textarea>
        </div>
      </div>

      <div>
        <div class="card">
          <h3>Clause library (RAG)</h3>
          <p style="font-size:0.8rem;color:var(--color-fg-muted)">
            Hybrid lexical + Atlas Vector Search over FAR/DFARS.
            <em>Filtered by agency_id — Item 10 surface.</em>
          </p>
          <input [(ngModel)]="clauseQuery" (keyup.enter)="searchClauses()" placeholder="e.g., bilateral supplemental agreement consent"/>
          <button (click)="searchClauses()" style="margin-top:0.5rem" [disabled]="searching">
            {{ searching ? 'Searching…' : 'Search' }}
          </button>
          <p *ngIf="searchInfo" style="font-size:0.75rem;color:var(--color-fg-muted);margin-top:0.4rem">{{ searchInfo }}</p>
          <ul *ngIf="clauseResults.length > 0">
            <li *ngFor="let c of clauseResults">
              <strong>{{ c.id }}</strong> — {{ c.title }}
              <button class="secondary" style="font-size:0.75rem;padding:0.1rem 0.35rem">Insert</button>
            </li>
          </ul>
        </div>

        <div class="card">
          <h3>State transition</h3>
          <select [(ngModel)]="targetState">
            <option value="DRAFT">DRAFT</option>
            <option value="INTERNAL_REVIEW">INTERNAL_REVIEW</option>
            <option value="READY_TO_PUBLISH">READY_TO_PUBLISH</option>
            <option value="PUBLISHED">PUBLISHED (CO only)</option>
            <option value="CANCELLED">CANCELLED</option>
          </select>
          <button style="margin-top:0.5rem">Transition</button>
          <p style="font-size:0.75rem;color:var(--color-fg-muted);margin-top:0.5rem">
            ⚠ Transitions audit-logged (Item 2 race surface).
          </p>
        </div>
      </div>
    </div>
  `,
})
export class ContractModificationEditorComponent implements OnInit {
  id = '';
  contractModification: ContractModification | null = null;
  sectionC = '';
  sectionL = '';
  sectionM = '';
  clauseQuery = '';
  clauseResults: { id: string; title: string }[] = [];
  targetState = 'INTERNAL_REVIEW';
  searching = false;
  searchInfo = '';

  constructor(private route: ActivatedRoute, private ai: AiService) {}

  ngOnInit(): void {
    this.id = this.route.snapshot.params['id'];
    this.contractModification = FIXTURE_CONTRACT_MODIFICATIONS.find((s) => s.id === this.id)
      ?? FIXTURE_CONTRACT_MODIFICATIONS[0];
    this.sectionC = `C.1 SCOPE. ${this.contractModification.description}`;
    this.sectionL = 'L.5.2 Volume I (Technical) — 60 pages…';
    this.sectionM = 'M.3.1 Technical Approach (40%)\nM.3.2 Management Approach (25%)\nM.3.3 Past Performance (20%)\nM.3.4 Price (15%)';
  }

  searchClauses(): void {
    const q = this.clauseQuery.trim();
    if (!q) return;
    this.searching = true;
    this.searchInfo = '';
    // Real hybrid RAG over the FAR/DFARS corpus in ai-orchestrator.
    this.ai.clauseSearch(q).subscribe({
      next: (res) => {
        // Dedup by clause id — a clause split into multiple chunks would otherwise
        // appear several times (chunks are ranked, so the first kept = highest score).
        const seen = new Set<string>();
        this.clauseResults = res.chunks
          .map((c) => ({
            id: c.source_document?.clause_number || c.source_document?.far_part || c.chunk_id,
            title: c.source_document?.title || c.chunk_text.slice(0, 90) + '…',
          }))
          .filter((c) => (seen.has(c.id) ? false : seen.add(c.id)));
        this.searchInfo = `${this.clauseResults.length} clause(s) · ${res.retrieval_strategy} · ${res.latency_ms} ms`
          + (res.degraded ? ' · degraded' : '');
        this.searching = false;
      },
      error: () => {
        // Fallback so the panel still demonstrates if retrieval is unavailable.
        this.clauseResults = [
          { id: '52.212-4', title: 'Contract Terms and Conditions—Commercial Items' },
          { id: '43.103', title: 'Types of contract modifications (bilateral / unilateral)' },
        ];
        this.searchInfo = 'sample results (retrieval service unreachable)';
        this.searching = false;
      },
    });
  }
}
