import { Component, OnDestroy, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterLink, RouterLinkActive } from '@angular/router';
import { Subscription } from 'rxjs';
import { RoleService } from '../services/role.service';
import { Role, RoleProfile } from '../models/roles';

interface NavLink {
  label: string;
  route: string;
  roles: Role[];           // empty = visible to all authenticated
}
interface NavGroup {
  title: string;
  links: NavLink[];
}

const ALL_AUTHENTICATED: Role[] = [
  'contracting_officer', 'cor', 'contract_specialist', 'program_manager',
  'dcaa_auditor', 'ssa', 'evaluator', 'vendor', 'oig_reviewer', 'sys_admin',
];

// Post-award IA (FAR Part 42/43/32). The inherited pre-award surfaces
// (public opportunity search, source-selection consensus/SSDD, vendor proposals)
// still exist as routes/components but are intentionally NOT in the default nav
// per the post-award reshape — the cohort can grep + repurpose them (OQ-4).
const NAV: NavGroup[] = [
  {
    title: 'Workspace',
    links: [
      { label: 'Dashboard', route: '/dashboard', roles: ['contracting_officer', 'cor', 'contract_specialist', 'program_manager'] },
      { label: 'Contractor Portal', route: '/vendor/proposals', roles: ['vendor'] },
    ],
  },
  {
    title: 'Modifications',
    links: [
      { label: 'Modifications Index', route: '/contractModifications', roles: ['contracting_officer', 'cor', 'contract_specialist', 'program_manager'] },
      { label: 'New SF-30 Modification', route: '/contractModifications/new', roles: ['contracting_officer', 'cor', 'contract_specialist'] },
    ],
  },
  {
    title: 'Invoices & Payment',
    links: [
      { label: 'Invoice Queue', route: '/invoiceReviews', roles: ['contracting_officer', 'cor', 'dcaa_auditor'] },
      { label: 'DCAA Audit Trail', route: '/admin/audit', roles: ['dcaa_auditor', 'oig_reviewer', 'contracting_officer'] },
    ],
  },
  {
    title: 'Contract Performance',
    links: [
      { label: 'Contract Admin', route: '/contracts/ctr-0001/admin', roles: ['contracting_officer', 'cor', 'program_manager'] },
      { label: 'CPAR Reviews', route: '/contracts/ctr-0001/cpars', roles: ['contracting_officer', 'cor', 'program_manager', 'vendor'] },
      { label: 'Award Record', route: '/awards/aw-2026-001', roles: ['contracting_officer', 'cor', 'program_manager', 'vendor'] },
    ],
  },
  {
    title: 'Reports',
    links: [
      { label: 'All Reports', route: '/reports', roles: ['contracting_officer', 'cor', 'program_manager', 'sys_admin', 'oig_reviewer'] },
    ],
  },
  {
    title: 'Contractors',
    links: [
      { label: 'Contractor Directory', route: '/vendors', roles: ['contracting_officer', 'cor', 'contract_specialist', 'program_manager'] },
    ],
  },
  {
    title: 'Admin',
    links: [
      { label: 'User & Role Admin', route: '/admin/users', roles: ['sys_admin'] },
      { label: 'System Config', route: '/admin/config', roles: ['sys_admin'] },
      { label: 'Audit Log Search', route: '/admin/audit', roles: ['sys_admin', 'oig_reviewer'] },
      { label: 'OIG Findings Tracker', route: '/admin/findings', roles: ['sys_admin', 'oig_reviewer'] },
    ],
  },
];

@Component({
  selector: 'app-sidebar-nav',
  standalone: true,
  imports: [CommonModule, RouterLink, RouterLinkActive],
  template: `
    <nav class="sidebar">
      <ng-container *ngFor="let group of visibleGroups; trackBy: trackGroup">
        <div class="sidebar-section-title">{{ group.title }}</div>
        <a *ngFor="let link of group.links; trackBy: trackLink"
           [routerLink]="link.route"
           routerLinkActive="active">{{ link.label }}</a>
      </ng-container>
    </nav>
  `,
})
export class SidebarNavComponent implements OnInit, OnDestroy {
  visibleGroups: NavGroup[] = [];
  private sub?: Subscription;

  constructor(public role: RoleService) {}

  ngOnInit(): void {
    this.recompute(this.role.currentRole);
    this.sub = this.role.profile$.subscribe((p) => this.recompute(p.role));
  }

  ngOnDestroy(): void {
    this.sub?.unsubscribe();
  }

  trackGroup = (_: number, g: NavGroup) => g.title;
  trackLink = (_: number, l: NavLink) => l.route;

  private recompute(current: Role): void {
    this.visibleGroups = NAV
      .map((g) => ({
        ...g,
        links: g.links.filter((l) =>
          l.roles.length === 0 || l.roles.includes(current) || current === 'sys_admin',
        ),
      }))
      .filter((g) => g.links.length > 0);
  }
}
