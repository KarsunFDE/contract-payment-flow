/**
 * InvoiceReview — post-award invoice / payment review (FAR Part 32,
 * anchor: WAWF). Replaces the pre-award TEP source-selection panel.
 *
 * A contractor submits a payment request (invoice) against an awarded
 * contract's CLINs. The COR matches it to the WAWF receiving report, runs
 * the proper-invoice checklist (FAR 32.905 required elements), and either
 * certifies it for payment or returns it as improper (must return within
 * 7 days per FAR 32.905(b)). Prompt-Payment due date = receipt + 30 days
 * (5 CFR 1315). Cost-type invoices may carry DCAA audit flags.
 */

/** A single CLIN line on the invoice. */
export interface InvoiceLineItem {
  clin: string;            // Contract Line Item Number, e.g. "0001"
  description: string;
  quantity: number;
  unitPrice: number;
  amount: number;          // quantity * unitPrice
}

/** received → proper → certified → paid, or improper_returned. */
export type PaymentStatus =
  | 'received'
  | 'proper'
  | 'improper_returned'
  | 'certified'
  | 'paid';

/** FAR 32.905 proper-invoice required elements (present/absent). */
export interface ProperInvoiceChecks {
  contractorNameAddress: boolean;
  invoiceDate: boolean;
  contractNumber: boolean;
  descriptionOfSuppliesServices: boolean;
  quantitiesUnitPrices: boolean;
  shippingPaymentTerms: boolean;
  payeeNameAddress: boolean;
}

/** Invoice-processing workflow state. */
export type InvoiceReviewState =
  | 'RECEIVED'
  | 'PROPER_INVOICE_CHECK'
  | 'RECEIVING_REPORT_MATCH'
  | 'CERTIFICATION'
  | 'PAID'
  | 'RETURNED';

export interface InvoiceReview {
  id: string;
  contractNumber: string;
  invoiceNumber: string;
  invoiceDate: string;
  /** WAWF receiving-report reference matched against the invoice. */
  receivingReportRef: string | null;
  lineItems: InvoiceLineItem[];
  /** Total invoiced amount across all CLIN line items (USD). */
  invoiceAmount: number;
  properInvoiceChecks: ProperInvoiceChecks;
  paymentStatus: PaymentStatus;
  /** Prompt-Payment due date = invoice receipt + 30 days (5 CFR 1315). */
  promptPayDueDate: string | null;
  /** If returned improper, the reason (FAR 32.905(b)); return within 7 days. */
  returnReason: string | null;
  /** DCAA cost-type audit flags (FAR 31.205 unallowable, defective pricing). */
  dcaaFlags: string[];
  state: InvoiceReviewState;
}

// ---------------------------------------------------------------------------
// Legacy source-selection types — retained as raw material the W3 cohort may
// repurpose for a multi-agent review surface. NOT part of the FAR 32 payment
// spine; the primary InvoiceReview interface above is the post-award shape.
// ---------------------------------------------------------------------------

/** @deprecated pre-award TEP factor — kept for consensus-ssdd / evaluator-workspace. */
export interface InvoiceReviewFactor {
  id: string;
  name: string;
  weight: number;
  sectionM: string;
}

/** @deprecated pre-award TEP score — kept for consensus-ssdd / evaluator-workspace. */
export interface InvoiceReviewScore {
  evaluatorId: string;
  evaluatorName: string;
  proposalId: string;
  factorId: string;
  score: number;
  narrative: string;
  submittedAt: string;
}
