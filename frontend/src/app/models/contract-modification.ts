/**
 * ContractModification — a post-award SF-30 (Standard Form 30,
 * "Amendment of Solicitation / Modification of Contract").
 *
 * Domain (post-award contract administration, anchor: WAWF): a modification
 * changes an awarded contract — adds/removes funds, shifts the period of
 * performance, or revises scope under a FAR Part 43 Changes authority.
 * Unilateral mods (change order / administrative) are signed by the CO alone;
 * bilateral supplemental agreements require contractor consent. See FAR 43.103
 * (definitions) and FAR 43.301 (use of SF-30).
 */

/** SF-30 modification type (FAR Part 43). */
export type ModType =
  | 'unilateral_change_order'
  | 'unilateral_admin'
  | 'bilateral_supplemental';

export interface ContractModification {
  id: string;
  agencyId: string;
  title: string;
  /** Doubles as the SF-30 change rationale. */
  description: string;
  status: string;
  createdAt?: string;
  updatedAt?: string;

  // — SF-30 post-award fields (FAR Part 43) —
  /** Base contract being modified, e.g. GS-35F-0001V. */
  contractNumber?: string;
  /** SF-30 mod number, e.g. P00001 (supplemental) / A00001 (admin). */
  modificationNumber?: string;
  modType?: ModType;
  /** FAR authority cite for the change, e.g. FAR 52.243-1 (Changes — FFP). */
  farAuthority?: string;
  /** Net funding change (USD); positive = add funds, negative = deobligate. */
  fundingDelta?: number;
  /** Revised period-of-performance start (ISO), if PoP changes. */
  popStart?: string;
  /** Revised period-of-performance end (ISO), if PoP changes. */
  popEnd?: string;
  /** Issue date (unilateral) / mutually agreed effective date (bilateral). */
  effectiveDate?: string;
  /** True for bilateral supplemental agreements. */
  contractorConsentRequired?: boolean;

  // — Free-form sub-sections (changeNarrative, priceCostImpact, fundingCitation) —
  sections?: ContractModificationSections;

  // — Legacy pre-award fields (inherited; retained for repurposable components) —
  /** @deprecated pre-award NAICS — retained for inherited components. */
  naics?: string;
  /** @deprecated pre-award set-aside — retained for inherited components. */
  setAside?: '' | 'SDVOSB' | 'WOSB' | 'HUBZONE' | '8A' | 'SMALL_BUSINESS' | 'FULL_AND_OPEN';
  /** @deprecated pre-award contract type — retained for inherited components. */
  contractType?: 'FFP' | 'CPFF' | 'T_AND_M' | 'IDIQ' | 'BPA';
  /** @deprecated pre-award ceiling — retained for inherited components. */
  ceilingValue?: number;
  /** @deprecated pre-award notice type — retained for inherited components. */
  noticeType?: 'RFI' | 'SOURCES_SOUGHT' | 'RFP' | 'RFQ' | 'COMBINED_SYNOPSIS';
  /** @deprecated pre-award proposal deadline — retained for inherited components. */
  proposalsDueAt?: string;
}

/**
 * Free-form modification sub-sections (post-award). Keys are open so the
 * cohort can extend without schema changes; legacy sectionC/L/M keys remain
 * available for inherited pre-award components.
 */
export interface ContractModificationSections {
  /** Scope-change narrative (replaces the pre-award SOW). */
  changeNarrative?: string;
  /** Price / cost-impact analysis (FAR 43.204). */
  priceCostImpact?: string;
  /** Funding citation / line-of-accounting. */
  fundingCitation?: string;

  // — Legacy pre-award section keys (inherited) —
  sectionA?: string;
  sectionB?: string;
  sectionC?: string;
  sectionD?: string;
  sectionE?: string;
  sectionF?: string;
  sectionG?: string;
  sectionH?: string;
  sectionJ?: string;
  sectionK?: string;
  sectionL?: string;
  sectionM?: string;
}

export interface ContractModificationCreate {
  agencyId: string;
  title: string;
  description: string;
  status?: string;
  contractNumber?: string;
  modificationNumber?: string;
  modType?: ModType;
  farAuthority?: string;
  fundingDelta?: number;
  popStart?: string;
  popEnd?: string;
  effectiveDate?: string;
  contractorConsentRequired?: boolean;
  sections?: ContractModificationSections;

  // legacy pre-award (inherited)
  naics?: string;
  setAside?: string;
  contractType?: string;
  ceilingValue?: number;
  noticeType?: string;
  proposalsDueAt?: string;
}

/**
 * Post-award modification lifecycle.
 * Legacy pre-award states (DRAFT/INTERNAL_REVIEW/PUBLISHED/AMENDED) retained
 * so inherited fixtures/components keep type-checking.
 */
export type ContractModificationState =
  | 'MODIFICATION_REQUEST'
  | 'PERFORMANCE_MONITORING'
  | 'INVOICE_PROCESSING'
  | 'CLOSEOUT'
  | 'CANCELLED'
  // legacy pre-award states (inherited)
  | 'DRAFT'
  | 'INTERNAL_REVIEW'
  | 'READY_TO_PUBLISH'
  | 'PUBLISHED'
  | 'AMENDED'
  | 'CLOSED';
