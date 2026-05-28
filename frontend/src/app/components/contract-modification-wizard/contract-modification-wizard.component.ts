import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { ContractModificationService } from '../../services/contract-modification.service';
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
          <input name="agencyId" [(ngModel)]="model.agencyId" placeholder="GSA-FAS"/>
        </label>
        <label><span class="label-text">Base contract #</span>
          <input name="contractNumber" [(ngModel)]="model.contractNumber" placeholder="GS-35F-0001V"/>
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
      <button class="secondary" (click)="aiDraft('changeNarrative')">▦ AI-draft rationale</button>
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
      <button class="secondary" (click)="aiDraft('priceCostImpact')">▦ AI-draft price/cost impact</button>
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
    agencyId: 'GSA-FAS',
    title: '',
    description: '',
    status: 'MODIFICATION_REQUEST',
    contractNumber: '',
    modificationNumber: '',
    modType: 'bilateral_supplemental',
    farAuthority: '',
    fundingDelta: undefined,
    contractorConsentRequired: true,
  };

  sections: ContractModificationSections = {};

  constructor(private svc: ContractModificationService, private router: Router) {}

  onModTypeChange(): void {
    // Bilateral supplemental agreements require contractor consent (FAR 43.103).
    this.model.contractorConsentRequired = this.model.modType === 'bilateral_supplemental';
  }

  back(): void {
    if (this.step > 0) this.step--;
  }

  next(): void {
    if (this.step < this.steps.length - 1) this.step++;
  }

  aiDraft(section: 'changeNarrative' | 'priceCostImpact'): void {
    // Stubbed — in W2 this hits POST /draft-contract-modification through the
    // gateway. For instructor demo, populate plausible placeholder text.
    if (section === 'changeNarrative') {
      this.sections.changeNarrative = `RATIONALE. This ${this.formatType(this.model.modType)} to contract ${this.model.contractNumber || '[contract #]'} is issued under ${this.model.farAuthority || 'the Changes clause'}.\n\nThe Government requires the following change: ${this.model.title || '[title]'}. ${this.model.description || ''}\n\nFUNDING/POP IMPACT. Net obligation change of $${(this.model.fundingDelta || 0).toLocaleString()}. ${this.model.popStart ? 'Period of performance revised.' : 'No change to period of performance.'}\n\n[AI-DRAFTED placeholder — to be reviewed by COR / CO before the SF-30 is issued. Item 4 / Item 5 surface.]`;
    } else {
      this.sections.priceCostImpact = `PRICE/COST IMPACT (FAR 43.204).\n\nProposed equitable adjustment: $${(this.model.fundingDelta || 0).toLocaleString()}.\nBasis of estimate: contractor proposal under review; independent Government cost estimate pending.\nDCAA audit: ${Math.abs(this.model.fundingDelta || 0) > 750000 ? 'required (over TINA threshold — certified cost or pricing data)' : 'not required at this dollar value'}.\n\n[AI-DRAFTED placeholder.]`;
    }
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
