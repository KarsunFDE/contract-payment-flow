import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { RoleService } from '../../services/role.service';
import { FIXTURE_CONTRACT_MODIFICATIONS, FIXTURE_INVOICES, FIXTURE_DELIVERABLES, FIXTURE_FINDINGS } from '../../services/mock-fixtures';
import { NotificationService } from '../../services/notification.service';

/**
 * Payment-ops Dashboard — role-aware landing for CO / COR / CS / PM.
 *
 * Post-award KPI tiles: invoices awaiting certification, payments on hold
 * (improper/returned), modifications pending CO signature, CDRLs overdue,
 * open DCAA/OIG flags.
 * Touches Item 8 (hardcoded URL lives in the contract-modification-list
 * component referenced below) — keeping the localized teaching
 * artifact intact.
 */
@Component({
  selector: 'app-officer-dashboard',
  standalone: true,
  imports: [CommonModule, RouterLink],
  template: `
    <div class="page-header">
      <div>
        <h2>{{ greeting() }}</h2>
        <div class="subtitle">{{ role.current.displayName }} · {{ role.current.authorityNote }}</div>
      </div>
      <div>
        <a routerLink="/contractModifications/new"><button>+ New SF-30 modification</button></a>
      </div>
    </div>

    <section class="kpi-grid">
      <div class="kpi-tile">
        <div class="kpi-value">{{ invoicesAwaitingCertification() }}</div>
        <div class="kpi-label">Invoices awaiting certification</div>
      </div>
      <div class="kpi-tile">
        <div class="kpi-value">{{ paymentsOnHold() }}</div>
        <div class="kpi-label">Payments on hold (improper)</div>
      </div>
      <div class="kpi-tile">
        <div class="kpi-value">{{ modsPendingSignature() }}</div>
        <div class="kpi-label">Mods pending CO signature</div>
      </div>
      <div class="kpi-tile">
        <div class="kpi-value">{{ cdrlsOverdue() }}</div>
        <div class="kpi-label">CDRLs overdue</div>
      </div>
      <div class="kpi-tile">
        <div class="kpi-value">{{ openFlags() }}</div>
        <div class="kpi-label">Open DCAA / OIG flags</div>
      </div>
    </section>

    <div class="two-col">
      <div class="card">
        <h3>Modification pipeline</h3>
        <table>
          <thead><tr><th>Modification</th><th>State</th><th>Funding Δ</th></tr></thead>
          <tbody>
            <tr *ngFor="let s of pipeline()">
              <td>
                <a [routerLink]="['/contractModifications', s.id, 'edit']">{{ s.title }}</a>
                <div style="font-size:0.75rem;color:var(--color-fg-muted)">{{ s.contractNumber }} · {{ s.modType }}</div>
              </td>
              <td><span class="badge" [ngClass]="(s.status || '').toLowerCase()">{{ s.status }}</span></td>
              <td>\${{ (s.fundingDelta || 0).toLocaleString() }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="card">
        <h3>Recent activity</h3>
        <ul>
          <li *ngFor="let n of recent()">
            <strong>{{ n.title }}</strong>
            <div style="font-size:0.85rem;color:var(--color-fg-muted)">{{ n.body }} · {{ n.createdAt | date:'short' }}</div>
          </li>
        </ul>
      </div>
    </div>

    <div class="card" style="margin-top:1rem">
      <h3>Quick links</h3>
      <p>
        <a routerLink="/contractModifications">All contractModifications</a> ·
        <a routerLink="/reports">All reports</a> ·
        <a routerLink="/vendors">Vendor directory</a> ·
        <a routerLink="/admin/audit">Audit log search</a>
      </p>
      <p style="font-size:0.8rem;color:var(--color-fg-muted)">
        ⚠ Legacy contractModification-list (Debt Item 8) is still wired at
        <a routerLink="/contractModifications">/contractModifications</a> — preserved
        as the W4 Tue API-modernization teaching artifact.
      </p>
    </div>
  `,
})
export class OfficerDashboardComponent {
  constructor(public role: RoleService, private notif: NotificationService) {}

  greeting(): string {
    const hour = new Date().getHours();
    const time = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening';
    return `${time}, ${this.role.current.displayName.split(' ')[0]}`;
  }

  invoicesAwaitingCertification(): number {
    return FIXTURE_INVOICES.filter((i) => ['received', 'proper'].includes(i.paymentStatus)).length;
  }

  paymentsOnHold(): number {
    return FIXTURE_INVOICES.filter((i) => i.paymentStatus === 'improper_returned').length;
  }

  modsPendingSignature(): number {
    return FIXTURE_CONTRACT_MODIFICATIONS.filter((m) => m.status === 'MODIFICATION_REQUEST').length;
  }

  cdrlsOverdue(): number {
    const now = Date.now();
    return FIXTURE_DELIVERABLES.filter((d) => d.status !== 'ACCEPTED' && new Date(d.dueAt).getTime() < now).length;
  }

  openFlags(): number {
    const dcaa = FIXTURE_INVOICES.reduce((n, i) => n + i.dcaaFlags.length, 0);
    const oig = FIXTURE_FINDINGS.filter((f) => ['OPEN', 'EVIDENCE_REQUESTED', 'IN_REMEDIATION'].includes(f.status)).length;
    return dcaa + oig;
  }

  pipeline() {
    return FIXTURE_CONTRACT_MODIFICATIONS.slice(0, 4);
  }

  recent() {
    // Read once from the notification service cache.
    let cache: any[] = [];
    this.notif.items$.subscribe((items) => (cache = items)).unsubscribe();
    return cache.slice(0, 4);
  }
}
