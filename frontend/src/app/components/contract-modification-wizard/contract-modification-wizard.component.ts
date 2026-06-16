import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { ContractModificationService } from '../../services/contract-modification.service';
import { AiService, ContractLookupResponse } from '../../services/ai.service';
import { ContractModification, ContractModificationCreate, ContractModificationSections } from '../../models/contract-modification';

/**
 * Multi-step SF-30 Contract-Modification Request Wizard (post-award, FAR Part 43).
 *
 * Steps:
 *   1. Basics      — contract #, mod #, mod type, FAR authority, effective date
 *   2. Funding/PoP — net funding delta, period-of-performance change
 *   3. Rationale   — scope-change narrative (AI-drafted via /draft-contract-modification)
 *   4. Price/Cost  — price/cost-impact analysis (FAR 43.204), funding citation
 *   5. Review      — confirm + submit (transitions to MODIFICATION_REQUEST)
 *
 * The simple "Issue new modification" path lives in the contract-admin
 * component; this wizard is the AI-assisted detailed path.
 *
 * Touches Item 4 (no Pydantic schema on AI output), Item 5 (legacy
 * LLMChain wired into the AI-orchestrator drafter), Item 9 (no
 * sanitization on description / rationale field).
 */
@Component({
  selector: 'app-contractModification-wizard',
  standalone: true,
  imports: [CommonModule, FormsModule],
  template: `
    <div class="page-header">
      <div>
        <h2>New contract modification — SF-30 wizard</h2>
        <div class="subtitle">FAR Part 43 · post-award · AI-assisted</div>
      </div>
    </div>

    <div class="stepper">
      <span class="step" *ngFor="let s of steps; let i = index"
            [class.active]="i === step"
            [class.complete]="i < step">{{ i + 1 }}. {{ s }}</span>
    </div>

    <!-- Step 1: Basics -->
    <div class="card" *ngIf="step === 0">
      <h3>1. Basics</h3>
      <label><span class="label-text">Modification title</span>
        <input name="title" [(ngModel)]="model.title" placeholder="e.g., Exercise Option Year 2 + add funds"/>
      </label>
      <div class="two-col">
        <label><span class="label-text">Agency ID</span>
          <input name="agencyId" [(ngModel)]="model.agencyId" placeholder="agency-gsa"/>
        </label>
        <label><span class="label-text">Base contract #</span>
          <input name="contractNumber" [(ngModel)]="model.contractNumber"
                 placeholder="GS-35F-0001V" (blur)="onContractBlur()"/>
          <span *ngIf="lookupNote" style="font-size:0.78rem;color:var(--color-fg-muted)">{{ lookupNote }}</span>
        </label>
        <label><span class="label-text">Modification # (SF-30)</span>
          <input name="modificationNumber" [(ngModel)]="model.modificationNumber" placeholder="P00003 / A00002"/>
        </label>
        <label><span class="label-text">Modification type</span>
          <select name="modType" [(ngModel)]="model.modType" (ngModelChange)="onModTypeChange()">
            <option value="unilateral_change_order">Unilateral — change order (FAR 52.243)</option>
            <option value="unilateral_admin">Unilateral — administrative (FAR 43.101)</option>
            <option value="bilateral_supplemental">Bilateral — supplemental agreement (FAR 43.103)</option>
          </select>
        </label>
        <label><span class="label-text">FAR authority</span>
          <input name="farAuthority" [(ngModel)]="model.farAuthority" placeholder="FAR 52.243-1 (Changes — FFP)"/>
        </label>
        <label><span class="label-text">Effective date</span>
          <input name="effectiveDate" type="date" [(ngModel)]="model.effectiveDate"/>
        </label>
      </div>
      <div class="hitl-banner" *ngIf="model.contractorConsentRequired">
        <strong>Contractor consent required.</strong> Bilateral supplemental
        agreements need the contractor's signature on the SF-30 before they
        take effect.
      </div>
    </div>

    <!-- Step 2: Funding / PoP -->
    <div class="card" *ngIf="step === 1">
      <h3>2. Funding &amp; period of performance</h3>
      <div class="two-col">
        <label><span class="label-text">Net funding delta ($)</span>
          <input name="fundingDelta" type="number" [(ngModel)]="model.fundingDelta"
                 placeholder="+18000000 (add) or -640000 (deobligate)"/>
        </label>
        <label><span class="label-text">Revised PoP start</span>
          <input name="popStart" type="date" [(ngModel)]="model.popStart"/>
        </label>
        <label><span class="label-text">Revised PoP end</span>
          <input name="popEnd" type="date" [(ngModel)]="model.popEnd"/>
        </label>
      </div>
      <p style="font-size:0.85rem;color:var(--color-fg-muted)">
        Positive funding delta adds funds; negative deobligates. Leave PoP
        fields blank if the period of performance is unchanged.
      </p>
    </div>

    <!-- Step 3: Rationale -->
    <div class="card" *ngIf="step === 2">
      <h3>3. Change rationale (scope-change narrative)</h3>
      <p style="font-size:0.85rem;color:var(--color-fg-muted)">
        AI-drafted via <code>POST /draft-contract-modification</code> (ai-orchestrator).
        ⚠ Debt Item 4 (no Pydantic schema), Item 5 (legacy LLMChain.run wired here),
        Item 9 (rationale stored raw).
      </p>
      <button class="secondary" (click)="aiDraft('changeNarrative')" [disabled]="drafting === 'changeNarrative'">
        {{ drafting === 'changeNarrative' ? '▦ Drafting…' : '▦ AI-draft rationale' }}
      </button>
      <span *ngIf="draftProvenance.changeNarrative" style="margin-left:0.5rem;font-size:0.8rem;color:var(--color-fg-muted)">
        {{ draftProvenance.changeNarrative }}
      </span>
      <textarea name="changeNarrative" rows="9" [(ngModel)]="sections.changeNarrative"
                style="margin-top:0.5rem"
                placeholder="Why is this modification needed? Cite the Changes-clause authority and describe the scope/funding/PoP impact."></textarea>
    </div>

    <!-- Step 4: Price / Cost impact -->
    <div class="card" *ngIf="step === 3">
      <h3>4. Price / cost-impact analysis</h3>
      <p style="font-size:0.85rem;color:var(--color-fg-muted)">
        FAR 43.204 — document the price/cost impact and the funding citation
        (line of accounting) supporting the obligation change.
      </p>
      <button class="secondary" (click)="aiDraft('priceCostImpact')" [disabled]="drafting === 'priceCostImpact'">
        {{ drafting === 'priceCostImpact' ? '▦ Drafting…' : '▦ AI-draft price/cost impact' }}
      </button>
      <span *ngIf="draftProvenance.priceCostImpact" style="margin-left:0.5rem;font-size:0.8rem;color:var(--color-fg-muted)">
        {{ draftProvenance.priceCostImpact }}
      </span>
      <textarea name="priceCostImpact" rows="6" [(ngModel)]="sections.priceCostImpact"
                style="margin-top:0.5rem"></textarea>
      <label style="margin-top:0.75rem"><span class="label-text">Funding citation</span>
        <input name="fundingCitation" [(ngModel)]="sections.fundingCitation"
               placeholder="e.g., FY26 O&amp;M 097-0100; LOA …"/>
      </label>
    </div>

    <!-- Step 5: Review -->
    <div class="card" *ngIf="step === 4">
      <h3>5. Review &amp; submit</h3>
      <p>Submitting records the modification request as
         <code>MODIFICATION_REQUEST</code>. CO sign-off required before the
         SF-30 is issued.</p>
      <table>
        <tbody>
          <tr><th>Title</th><td>{{ model.title || '—' }}</td></tr>
          <tr><th>Contract / Mod #</th><td>{{ model.contractNumber }} / {{ model.modificationNumber }}</td></tr>
          <tr><th>Type</th><td>{{ model.modType }}</td></tr>
          <tr><th>FAR authority</th><td>{{ model.farAuthority || '—' }}</td></tr>
          <tr><th>Funding delta</th><td>\${{ (model.fundingDelta || 0).toLocaleString() }}</td></tr>
          <tr><th>Contractor consent</th><td>{{ model.contractorConsentRequired ? 'Required (bilateral)' : 'Not required (unilateral)' }}</td></tr>
          <tr><th>Rationale length</th><td>{{ (sections.changeNarrative || '').length }} chars</td></tr>
          <tr><th>Price/cost impact length</th><td>{{ (sections.priceCostImpact || '').length }} chars</td></tr>
        </tbody>
      </table>
    </div>

    <div style="margin-top:1rem;display:flex;gap:0.5rem;justify-content:space-between">
      <button class="secondary" (click)="back()" [disabled]="step === 0">← Back</button>
      <div>
        <button *ngIf="step < steps.length - 1" (click)="next()">Next →</button>
        <button *ngIf="step === steps.length - 1" (click)="submit()" [disabled]="submitting">
          {{ submitting ? 'Submitting…' : 'Submit modification request' }}
        </button>
      </div>
    </div>
    <div *ngIf="error" class="error-text">{{ error }}</div>
  `,
})
export class ContractModificationWizardComponent {
  steps = ['Basics', 'Funding / PoP', 'Rationale', 'Price / Cost', 'Review'];
  step = 0;
  submitting = false;
  error: string | null = null;

  model: ContractModificationCreate = {
    agencyId: 'agency-gsa',
    title: '',
    description: '',
    status: 'MODIFICATION_REQUEST',
    contractNumber: '',
    modificationNumber: '',
    modType: 'bilateral_supplemental',
    // Matches the default modType above; onModTypeChange keeps it in sync thereafter.
    farAuthority: 'FAR 43.103(a) — Supplemental Agreement',
    fundingDelta: undefined,
    contractorConsentRequired: true,
  };

  sections: ContractModificationSections = {};

  /** Which section is currently being AI-drafted (drives the button spinner). */
  drafting: 'changeNarrative' | 'priceCostImpact' | null = null;
  /** Provenance line shown next to each draft button (model + traced/stub). */
  draftProvenance: { changeNarrative?: string; priceCostImpact?: string } = {};
  /** Status line under the contract # field after a contract-of-record lookup. */
  lookupNote: string | null = null;
  /** Original (base) PoP from the contract-of-record lookup; feeds the AI draft. */
  popOriginalStart?: string;
  popOriginalEnd?: string;

  constructor(
    private svc: ContractModificationService,
    private ai: AiService,
    private router: Router,
  ) {}

  /**
   * Deterministic contract-of-record lookup (no LLM). On a "found" match, autofills
   * the SF-30 blocks the contract supplies — next mod # (block 2), effective date
   * (block 3), appropriation/funding citation (block 12). The CO can still override
   * any field. Tenant-scoped by agencyId, so the agency must match the seeded record.
   */
  onContractBlur(): void {
    const number = (this.model.contractNumber || '').trim();
    if (!number || !this.model.agencyId) { this.lookupNote = null; return; }
    this.lookupNote = 'Looking up contract-of-record…';
    this.ai.lookupContract(number, this.model.agencyId).subscribe({
      next: (res: ContractLookupResponse) => {
        if (res.match !== 'found' || !res.static_fields) {
          this.lookupNote = `No contract-of-record match (${res.match}) — fill fields manually`;
          return;
        }
        const f = res.static_fields;
        if (f['2']) this.model.modificationNumber = f['2'];
        if (f['3']) this.model.effectiveDate = f['3'];
        if (f['12']) this.sections.fundingCitation = f['12'];
        // Original (base) PoP from the contract-of-record — feeds the AI draft so
        // it cites real dates instead of [Insert original base period dates].
        if (f['popStart']) this.popOriginalStart = f['popStart'];
        if (f['popEnd']) this.popOriginalEnd = f['popEnd'];
        this.lookupNote = `Auto-filled from ${res.source_citation?.system ?? 'contract-of-record'}`;
      },
      error: () => { this.lookupNote = 'Lookup unavailable — fill fields manually'; },
    });
  }

  /**
   * FAR authority is a function of the modification action, not the base contract,
   * so it derives from the mod type (not the contract-of-record lookup). The CO can
   * still override the field manually after selecting a type.
   */
  private readonly farAuthorityByType: Record<string, string> = {
    unilateral_change_order: 'FAR 52.243-1 — Changes',
    unilateral_admin:        'FAR 43.101 — Administrative change',
    bilateral_supplemental:  'FAR 43.103(a) — Supplemental Agreement',
  };

  onModTypeChange(): void {
    // Bilateral supplemental agreements require contractor consent (FAR 43.103).
    this.model.contractorConsentRequired = this.model.modType === 'bilateral_supplemental';
    // Derive the FAR authority from the selected type.
    const authority = this.farAuthorityByType[this.model.modType ?? ''];
    if (authority) this.model.farAuthority = authority;
  }

  back(): void {
    if (this.step > 0) this.step--;
  }

  next(): void {
    if (this.step < this.steps.length - 1) this.step++;
  }

  aiDraft(section: 'changeNarrative' | 'priceCostImpact'): void {
    // Real call to ai-orchestrator: prompt | ChatBedrock | parser, traced by
    // LangSmith. Falls back to a deterministic local draft if the service is
    // unreachable so the wizard still works offline.
    this.drafting = section;
    this.ai.draftSection({
      kind: section === 'changeNarrative' ? 'rationale' : 'price_cost',
      title: this.model.title,
      contract_number: this.model.contractNumber,
      mod_type: this.model.modType,
      far_authority: this.model.farAuthority,
      funding_delta: this.model.fundingDelta,
      pop_changed: !!this.model.popStart || !!this.model.popEnd,
      pop_original_start: this.popOriginalStart,
      pop_original_end: this.popOriginalEnd,
      pop_revised_start: this.model.popStart,
      pop_revised_end: this.model.popEnd,
    }).subscribe({
      next: (res) => {
        this.sections[section] = res.draft;
        this.draftProvenance[section] = res.stub
          ? `stub fallback · ${res.model}`
          : `${res.model}${res.traced ? ' · traced (LangSmith)' : ''}`;
        this.drafting = null;
      },
      error: () => {
        this.sections[section] = this.localDraft(section);
        this.draftProvenance[section] = 'offline draft (service unreachable)';
        this.drafting = null;
      },
    });
  }

  /** Deterministic local fallback used only when ai-orchestrator is unreachable. */
  private localDraft(section: 'changeNarrative' | 'priceCostImpact'): string {
    if (section === 'changeNarrative') {
      return `RATIONALE. This ${this.formatType(this.model.modType)} to contract ${this.model.contractNumber || '[contract #]'} is issued under ${this.model.farAuthority || 'the Changes clause'}.\n\nThe Government requires the following change: ${this.model.title || '[title]'}. ${this.model.description || ''}\n\nFUNDING/POP IMPACT. Net obligation change of $${(this.model.fundingDelta || 0).toLocaleString()}. ${this.model.popStart ? 'Period of performance revised.' : 'No change to period of performance.'}`;
    }
    return `PRICE/COST IMPACT (FAR 43.204).\n\nProposed equitable adjustment: $${(this.model.fundingDelta || 0).toLocaleString()}.\nBasis of estimate: contractor proposal under review; independent Government cost estimate pending.\nDCAA audit: ${Math.abs(this.model.fundingDelta || 0) > 750000 ? 'required (over TINA threshold — certified cost or pricing data)' : 'not required at this dollar value'}.`;
  }

  private formatType(t?: string): string {
    switch (t) {
      case 'unilateral_change_order': return 'unilateral change order';
      case 'unilateral_admin': return 'unilateral administrative modification';
      case 'bilateral_supplemental': return 'bilateral supplemental agreement';
      default: return 'modification';
    }
  }

  submit(): void {
    this.submitting = true;
    this.error = null;
    const payload: ContractModificationCreate = {
      ...this.model,
      status: 'MODIFICATION_REQUEST',
      // The change rationale doubles as the description (⚠ Item 9 — stored raw).
      description: this.sections.changeNarrative || this.model.description,
      sections: this.sections,
    };
    this.svc.create(payload).subscribe({
      next: (s: ContractModification) => {
        this.submitting = false;
        this.router.navigate(['/contractModifications', s.id || 'mod-new', 'edit']);
      },
      error: () => {
        // Brownfield reality: create may fail; for instructor demo, still
        // route to the list as if it succeeded.
        this.submitting = false;
        this.router.navigate(['/contractModifications']);
      },
    });
  }
}
