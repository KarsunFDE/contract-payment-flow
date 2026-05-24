import { Routes } from '@angular/router';
import { ContractModificationListComponent } from './components/contractModification-list/contractModification-list.component';
import { ContractModificationCreateComponent } from './components/contractModification-create/contractModification-create.component';
import { InvoiceReviewPanelComponent } from './components/invoiceReview-panel/invoiceReview-panel.component';
import { OfficerDashboardComponent } from './components/officer-dashboard/officer-dashboard.component';
import { ReportsHubComponent } from './components/reports-hub/reports-hub.component';
import { ContractModificationWizardComponent } from './components/contractModification-wizard/contractModification-wizard.component';
import { ContractModificationEditorComponent } from './components/contractModification-editor/contractModification-editor.component';
import { AmendmentEditorComponent } from './components/amendment-editor/amendment-editor.component';
import { QnaTriageComponent } from './components/qna-triage/qna-triage.component';
import { ProposalIntakeComponent } from './components/proposal-intake/proposal-intake.component';
import { PublicOpportunitiesComponent } from './components/public-opportunities/public-opportunities.component';
import { OpportunityDetailComponent } from './components/opportunity-detail/opportunity-detail.component';
import { VendorDirectoryComponent } from './components/vendor-directory/vendor-directory.component';
import { VendorDetailComponent } from './components/vendor-detail/vendor-detail.component';
import { VendorPortalComponent } from './components/vendor-portal/vendor-portal.component';
import { EvaluatorWorkspaceComponent } from './components/evaluator-workspace/evaluator-workspace.component';
import { ConsensusSsddComponent } from './components/consensus-ssdd/consensus-ssdd.component';
import { AwardRecordComponent } from './components/award-record/award-record.component';
import { ContractAdminComponent } from './components/contract-admin/contract-admin.component';
import { CparReviewComponent } from './components/cpar-review/cpar-review.component';
import { AdminUsersComponent } from './components/admin-users/admin-users.component';
import { AdminConfigComponent } from './components/admin-config/admin-config.component';
import { AuditSearchComponent } from './components/audit-search/audit-search.component';
import { FindingsTrackerComponent } from './components/findings-tracker/findings-tracker.component';
import { roleGuard } from './services/role.guard';

export const routes: Routes = [
  { path: '', redirectTo: 'dashboard', pathMatch: 'full' },

  // — Officer landing + reports
  {
    path: 'dashboard',
    component: OfficerDashboardComponent,
    canMatch: [roleGuard('contracting_officer', 'contract_specialist', 'program_manager', 'ssa', 'sys_admin')],
  },
  {
    path: 'reports',
    component: ReportsHubComponent,
    canMatch: [roleGuard('contracting_officer', 'program_manager', 'ssa', 'sys_admin', 'oig_reviewer')],
  },
  // Drill-down report routes alias back to the hub (filter via query params in W5).
  { path: 'reports/pipeline', component: ReportsHubComponent },
  { path: 'reports/vendor-past-performance', component: ReportsHubComponent },
  { path: 'reports/contract-spend', component: ReportsHubComponent },

  // — ContractModification lifecycle
  // NOTE: /contractModifications still routes to the LEGACY ContractModificationListComponent
  // which hardcodes http://localhost:8081 (Item 8). PRESERVED as the W4 Tue
  // teaching artifact. New components route through environment.apiGatewayUrl.
  { path: 'contractModifications', component: ContractModificationListComponent },
  {
    path: 'contractModifications/new',
    component: ContractModificationWizardComponent,
    canMatch: [roleGuard('contracting_officer', 'contract_specialist')],
  },
  // Legacy single-page create form kept available under a sub-route so the
  // brownfield baseline is still demoable.
  { path: 'contractModifications/new-legacy', component: ContractModificationCreateComponent },
  { path: 'contractModifications/:id/edit', component: ContractModificationEditorComponent },
  {
    path: 'contractModifications/:id/amendments',
    component: AmendmentEditorComponent,
    canMatch: [roleGuard('contracting_officer', 'contract_specialist', 'program_manager')],
  },
  {
    path: 'contractModifications/:id/qa',
    component: QnaTriageComponent,
    canMatch: [roleGuard('contracting_officer', 'contract_specialist')],
  },
  {
    path: 'contractModifications/:id/proposals',
    component: ProposalIntakeComponent,
    canMatch: [roleGuard('contracting_officer', 'contract_specialist')],
  },

  // — Public-facing
  { path: 'public/opportunities', component: PublicOpportunitiesComponent },
  { path: 'public/opportunities/:id', component: OpportunityDetailComponent },

  // — Vendor management + portal
  {
    path: 'vendors',
    component: VendorDirectoryComponent,
    canMatch: [roleGuard('contracting_officer', 'contract_specialist', 'evaluator', 'program_manager', 'sys_admin')],
  },
  {
    path: 'vendors/:id',
    component: VendorDetailComponent,
    canMatch: [roleGuard('contracting_officer', 'contract_specialist', 'evaluator', 'program_manager', 'sys_admin')],
  },
  {
    path: 'vendor/proposals',
    component: VendorPortalComponent,
    canMatch: [roleGuard('vendor')],
  },

  // — InvoiceReview + source selection
  // Legacy invoiceReview-panel kept under a sub-route for instructor comparison.
  { path: 'invoiceReviews', component: InvoiceReviewPanelComponent },
  {
    path: 'invoiceReview/workspace',
    component: EvaluatorWorkspaceComponent,
    canMatch: [roleGuard('evaluator', 'contracting_officer', 'sys_admin')],
  },
  {
    path: 'invoiceReview/:solId/consensus',
    component: ConsensusSsddComponent,
    canMatch: [roleGuard('ssa', 'contracting_officer', 'sys_admin')],
  },

  // — Post-award
  { path: 'awards/:id', component: AwardRecordComponent },
  {
    path: 'contracts/:id/admin',
    component: ContractAdminComponent,
    canMatch: [roleGuard('contracting_officer', 'program_manager', 'sys_admin', 'oig_reviewer')],
  },
  { path: 'contracts/:id/cpars', component: CparReviewComponent },

  // — Admin
  { path: 'admin/users', component: AdminUsersComponent, canMatch: [roleGuard('sys_admin')] },
  { path: 'admin/config', component: AdminConfigComponent, canMatch: [roleGuard('sys_admin')] },
  {
    path: 'admin/audit',
    component: AuditSearchComponent,
    canMatch: [roleGuard('sys_admin', 'oig_reviewer')],
  },
  {
    path: 'admin/findings',
    component: FindingsTrackerComponent,
    canMatch: [roleGuard('sys_admin', 'oig_reviewer')],
  },

  // — Catch-all → dashboard
  { path: '**', redirectTo: 'dashboard' },
];
