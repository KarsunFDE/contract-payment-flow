import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { ContractModification } from '../../models/contract-modification';
import { ContractModificationService } from '../../services/contract-modification.service';

/**
 * ContractModification list view.
 *
 * ⚠ DELIBERATE BROWNFIELD DEBT — Item 8 in docs/brownfield-debt.md ⚠
 *
 * This component hardcodes `http://localhost:8081/api/contract-modifications` —
 * bypassing the API gateway at :8080. Compare with
 * {@link ../../services/contract-modification.service.ts} which uses
 * `environment.apiGatewayUrl`.
 *
 * The hardcode was introduced "temporarily" by a developer who couldn't
 * get the gateway running locally and was never reverted. Cohort fixes
 * in W4 Tue API modernization patterns.
 *
 * CLOSED (Item 8, instructor-approved early): the hardcoded :8081 URL + raw
 * HttpClient are removed; this view now goes through ContractModificationService,
 * which routes via environment.apiGatewayUrl (:8080). All API calls now route
 * through the gateway (the Item 8 "fixed looks like"). The gateway is reachable
 * in dev via the gateway.dev-no-auth flag (no OIDC issuer runs locally).
 */
@Component({
  selector: 'app-contractModification-list',
  standalone: true,
  imports: [CommonModule, RouterLink],
  template: `
    <h2>ContractModifications</h2>
    <p>
      <a routerLink="/contractModifications/new"><button>+ New contractModification</button></a>
    </p>
    <div *ngIf="loading">Loading…</div>
    <div *ngIf="error" style="color: crimson">{{ error }}</div>
    <table *ngIf="!loading && !error">
      <thead>
        <tr><th>Title</th><th>Agency</th><th>Status</th><th>ID</th></tr>
      </thead>
      <tbody>
        <tr *ngFor="let s of contractModifications">
          <td><a [routerLink]="['/contractModifications', s.id, 'edit']">{{ s.title || '(untitled)' }}</a></td>
          <td>{{ s.agencyId }}</td>
          <td>{{ s.status }}</td>
          <td><code>{{ s.id }}</code></td>
        </tr>
        <tr *ngIf="contractModifications.length === 0">
          <td colspan="4"><em>No contractModifications yet. Create one!</em></td>
        </tr>
      </tbody>
    </table>
  `,
})
export class ContractModificationListComponent implements OnInit {
  contractModifications: ContractModification[] = [];
  loading = true;
  error: string | null = null;

  constructor(private svc: ContractModificationService) {}

  ngOnInit(): void {
    // Item 8 CLOSED — route through the gateway via the shared service.
    this.svc.list().subscribe({
      next: (data) => {
        this.contractModifications = data || [];
        this.loading = false;
      },
      error: (err) => {
        this.error = `Failed to load contractModifications: ${err.message ?? err}`;
        this.loading = false;
      },
    });
  }
}
