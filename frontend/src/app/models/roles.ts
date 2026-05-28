/**
 * Federal acquisitions role model.
 *
 * Mirrors the JWT `role` claim defined in feature-inventory-target.md
 * personas table. FedRAMP RBAC AC-2/AC-5 (least-privilege +
 * separation-of-duties).
 *
 * NOTE: this is a mock role-switcher for cohort instructor demos.
 * Production RBAC resolves role from validated JWT in the API gateway
 * (which today has Debt Item 1 — JWT signature-skip on `/api/public/*`).
 */
export type Role =
  | 'contracting_officer'         // CO — signs SF-30 mods, certifies payment
  | 'cor'                         // Contracting Officer's Representative (default)
  | 'contract_specialist'
  | 'program_manager'
  | 'dcaa_auditor'                // DCAA — cost-type invoice audit
  | 'vendor'                      // contractor program manager
  | 'oig_reviewer'
  | 'sys_admin'
  | 'public'
  // — Legacy pre-award source-selection roles (inherited; W3 may repurpose) —
  | 'ssa'
  | 'evaluator';

export interface RoleProfile {
  role: Role;
  displayName: string;
  agencyId: string | null;   // null for sys_admin (cross-tenant) and public
  vendorDuns?: string;       // only present for `vendor`
  /** FAR/FedRAMP authority notes shown in role-switcher tooltip. */
  authorityNote: string;
}

export const ROLE_PROFILES: RoleProfile[] = [
  {
    role: 'contracting_officer',
    displayName: 'Dana Reeves (CO, GSA-FAS)',
    agencyId: 'GSA-FAS',
    authorityNote: 'Sign SF-30 modifications, certify invoices for payment, terminate contract (FAR 1.602-1 / 42.302).',
  },
  {
    role: 'cor',
    displayName: 'Priya Shah (COR, GSA-FAS)',
    agencyId: 'GSA-FAS',
    authorityNote: 'Accept deliverables + receiving reports, review invoices, recommend payment (FAR 42.302 / 46.5). Cannot obligate funds.',
  },
  {
    role: 'contract_specialist',
    displayName: 'Miguel Ortiz (CS, GSA-FAS)',
    agencyId: 'GSA-FAS',
    authorityNote: 'Draft modifications; cannot sign SF-30 (FAR 1.603).',
  },
  {
    role: 'program_manager',
    displayName: 'Jordan Lee (PM, GSA-FAS)',
    agencyId: 'GSA-FAS',
    authorityNote: 'Requirements + CPAR draft (FAR 42.1503).',
  },
  {
    role: 'dcaa_auditor',
    displayName: 'R. Castillo (DCAA auditor)',
    agencyId: 'DCAA',
    authorityNote: 'Audit cost-type invoices; flag unallowable cost (FAR 31.205) + defective pricing (FAR 42.1).',
  },
  {
    role: 'vendor',
    displayName: 'Acme Federal LLC (contractor PM, UEI AB1CDE2FGHI3)',
    agencyId: null,
    vendorDuns: '123456789',
    authorityNote: 'Submit invoices + SF-30 acceptance; rebuttal on CPAR (FAR 42.1503(d)).',
  },
  {
    role: 'ssa',
    displayName: 'Col. Whitfield (SSA — legacy pre-award)',
    agencyId: 'GSA-FAS',
    authorityNote: 'Legacy source-selection authority (FAR 15.303). Pre-award role retained for inherited surfaces.',
  },
  {
    role: 'evaluator',
    displayName: 'Dr. Allen (evaluator — legacy pre-award)',
    agencyId: 'GSA-FAS',
    authorityNote: 'Legacy TEP evaluator (FAR 15.305). Pre-award role retained for inherited surfaces.',
  },
  {
    role: 'oig_reviewer',
    displayName: 'Inspector Park (OIG)',
    agencyId: 'GSA-OIG',
    authorityNote: 'Read-only across tenants; open findings.',
  },
  {
    role: 'sys_admin',
    displayName: 'Root (sys_admin)',
    agencyId: null,
    authorityNote: 'Cross-tenant admin; provisioning + key rotation.',
  },
  {
    role: 'public',
    displayName: 'Unauthenticated visitor',
    agencyId: null,
    authorityNote: 'Read-only on /public/* (Item 1 surface).',
  },
];
