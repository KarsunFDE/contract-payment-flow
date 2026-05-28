import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { HttpClient } from '@angular/common/http';
import { environment } from '../../../environments/environment';
import { FIXTURE_INVOICES } from '../../services/mock-fixtures';
import { InvoiceReview } from '../../models/invoice-review';

/**
 * Invoice processing queue (post-award, FAR Part 32 / WAWF).
 *
 * COR reviews incoming payment requests: matches each invoice to its WAWF
 * receiving report, runs the FAR 32.905 proper-invoice checklist, and
 * certifies for payment or returns as improper (within 7 days).
 *
 * NOTE: the *deep* version (multi-agent anomaly detection + HITL interrupt
 * nodes) is W3 cohort work. This component is the corrected single-agent
 * shape — it replaces the renamed-TEP source-selection panel.
 *
 * ⚠ Item 3 — POST /api/invoice-reviews has no circuit breaker / idempotency key.
 */
@Component({
  selector: 'app-invoiceReview-panel',
  standalone: true,
  imports: [CommonModule],
  template: `
    <div class="page-header">
      <div>
        <h2>Invoice processing queue</h2>
        <div class="subtitle">FAR 32.905 · WAWF receiving-report match · prompt payment</div>
      </div>
      <button (click)="createReview()">+ Start invoice review</button>
    </div>

    <table>
      <thead>
        <tr>
          <th>Invoice #</th><th>Contract</th><th>Amount</th>
          <th>RR match</th><th>Proper?</th><th>Status</th><th>Prompt-pay due</th>
        </tr>
      </thead>
      <tbody>
        <tr *ngFor="let inv of invoices">
          <td><strong>{{ inv.invoiceNumber }}</strong></td>
          <td><code>{{ inv.contractNumber }}</code></td>
          <td>\${{ inv.invoiceAmount.toLocaleString() }}</td>
          <td>{{ inv.receivingReportRef || '— unmatched' }}</td>
          <td>{{ isProper(inv) ? '✓' : '✗ ' + missingCount(inv) + ' missing' }}</td>
          <td><span class="badge" [ngClass]="badgeFor(inv.paymentStatus)">{{ inv.paymentStatus }}</span></td>
          <td>{{ inv.promptPayDueDate ? (inv.promptPayDueDate | date:'shortDate') : '—' }}</td>
        </tr>
      </tbody>
    </table>

    <div class="card" style="margin-top:1rem" *ngIf="selected as inv">
      <h3>Proper-invoice checklist — {{ inv.invoiceNumber }} (FAR 32.905)</h3>
      <ul>
        <li>Contractor name + address: {{ inv.properInvoiceChecks.contractorNameAddress ? '✓' : '✗' }}</li>
        <li>Invoice date: {{ inv.properInvoiceChecks.invoiceDate ? '✓' : '✗' }}</li>
        <li>Contract number: {{ inv.properInvoiceChecks.contractNumber ? '✓' : '✗' }}</li>
        <li>Description of supplies/services: {{ inv.properInvoiceChecks.descriptionOfSuppliesServices ? '✓' : '✗' }}</li>
        <li>Quantities + unit prices: {{ inv.properInvoiceChecks.quantitiesUnitPrices ? '✓' : '✗' }}</li>
        <li>Shipping + payment terms: {{ inv.properInvoiceChecks.shippingPaymentTerms ? '✓' : '✗' }}</li>
        <li>Payee name + address: {{ inv.properInvoiceChecks.payeeNameAddress ? '✓' : '✗' }}</li>
      </ul>
      <div class="hitl-banner" *ngIf="inv.returnReason">
        <strong>Returned improper.</strong> {{ inv.returnReason }}
      </div>
      <p *ngIf="inv.dcaaFlags.length"><strong>DCAA flags:</strong> {{ inv.dcaaFlags.join(', ') }}</p>
    </div>

    <p style="margin-top:1rem;font-size:0.85rem;color:var(--color-fg-muted)">
      <em>Deep multi-agent anomaly detection + HITL interrupt nodes are W3 cohort work.</em>
    </p>
    <pre *ngIf="result">{{ result | json }}</pre>
    <p *ngIf="error" style="color: crimson">{{ error }}</p>
  `,
})
export class InvoiceReviewPanelComponent {
  invoices: InvoiceReview[] = FIXTURE_INVOICES;
  selected: InvoiceReview | null = FIXTURE_INVOICES.find((i) => i.paymentStatus === 'improper_returned') ?? FIXTURE_INVOICES[0] ?? null;
  result: unknown = null;
  error: string | null = null;

  constructor(private http: HttpClient) {}

  isProper(inv: InvoiceReview): boolean {
    return Object.values(inv.properInvoiceChecks).every(Boolean);
  }

  missingCount(inv: InvoiceReview): number {
    return Object.values(inv.properInvoiceChecks).filter((v) => !v).length;
  }

  badgeFor(status: string): string {
    if (status === 'paid' || status === 'certified') return 'published';
    if (status === 'improper_returned') return 'urgent';
    if (status === 'proper') return 'review';
    return 'draft';
  }

  createReview(): void {
    this.error = null;
    // ⚠ Item 3 — no idempotency key / circuit breaker on this state-mutating call.
    this.http
      .post(`${environment.apiGatewayUrl}/api/invoice-reviews`, {
        contractNumber: this.invoices[0]?.contractNumber ?? 'GS-35F-0001V',
      })
      .subscribe({
        next: (r) => (this.result = r),
        error: (e) => (this.error = `Failed: ${e.message ?? e}`),
      });
  }
}
