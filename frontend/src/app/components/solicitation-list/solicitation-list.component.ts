import { Component, OnInit } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { CommonModule } from '@angular/common';
import { RouterLink } from '@angular/router';
import { ContractModification } from '../../models/contract_modification';

/**
 * ContractModification list view.
 *
 * ⚠ DELIBERATE BROWNFIELD DEBT — Item 8 in docs/brownfield-debt.md ⚠
 *
 * This component hardcodes `http://localhost:8081/api/contract-modifications` —
 * bypassing the API gateway at :8080. Compare with
 * {@link ../../services/contract_modification.service.ts} which uses
 * `environment.apiGatewayUrl`.
 *
 * The hardcode was introduced "temporarily" by a developer who couldn't
 * get the gateway running locally and was never reverted. Cohort fixes
 * in W4 Tue API modernization patterns.
 */
@Component({
  selector: 'app-contract_modification-list',
  standalone: true,
  imports: [CommonModule, RouterLink],
  template: `
    <h2>ContractModifications</h2>
    <p>
      <a routerLink="/contract_modifications/new"><button>+ New contract_modification</button></a>
    </p>
    <div *ngIf="loading">Loading…</div>
    <div *ngIf="error" style="color: crimson">{{ error }}</div>
    <table *ngIf="!loading && !error">
      <thead>
        <tr><th>Title</th><th>Agency</th><th>Status</th><th>ID</th></tr>
      </thead>
      <tbody>
        <tr *ngFor="let s of contract_modifications">
          <td>{{ s.title }}</td>
          <td>{{ s.agencyId }}</td>
          <td>{{ s.status }}</td>
          <td><code>{{ s.id }}</code></td>
        </tr>
        <tr *ngIf="contract_modifications.length === 0">
          <td colspan="4"><em>No contract_modifications yet. Create one!</em></td>
        </tr>
      </tbody>
    </table>
  `,
})
export class ContractModificationListComponent implements OnInit {
  // ⚠ Item 8 — hardcoded URL bypasses the API gateway at :8080.
  private apiUrl = 'http://localhost:8081/api/contract-modifications';

  contract_modifications: ContractModification[] = [];
  loading = true;
  error: string | null = null;

  constructor(private http: HttpClient) {}

  ngOnInit(): void {
    this.http.get<ContractModification[]>(this.apiUrl).subscribe({
      next: (data) => {
        this.contract_modifications = data || [];
        this.loading = false;
      },
      error: (err) => {
        this.error = `Failed to load contract_modifications: ${err.message ?? err}`;
        this.loading = false;
      },
    });
  }
}
