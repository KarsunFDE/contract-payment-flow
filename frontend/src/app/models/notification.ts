/**
 * In-app notification (bell + drawer surface).
 *
 * Source events mapped in feature-inventory-target.md notification
 * surfaces table. Item 6 (inconsistent correlation IDs) bites because
 * the notification log uses a different correlation ID than the
 * originating service request.
 */
export type NotificationKind =
  // — Post-award contract administration / payment (FAR Parts 32 / 42 / 43) —
  | 'SF30_ISSUED'              // SF-30 modification signed (FAR 43)
  | 'INVOICE_RECEIVED'        // proper-invoice check on receipt (FAR 32.905)
  | 'PAYMENT_CERTIFIED'       // CO certifies payment (Prompt Payment, FAR 32.9)
  | 'INVOICE_RETURNED'        // improper invoice returned within 7 days (FAR 32.905(b))
  | 'DCAA_FLAG_RAISED'        // DCAA cost-type audit flag (FAR 42.1)
  | 'CLOSEOUT_INITIATED'      // contract closeout started (FAR 4.804)
  | 'CPAR_WINDOW_OPEN'        // CPAR rebuttal window (FAR 42.1503(d))
  | 'QASP_FINDING'
  | 'OIG_FINDING_OPENED'
  // — Legacy pre-award kinds (inherited; W3 may repurpose) —
  | 'CONTRACT_MODIFICATION_PUBLISHED'
  | 'AMENDMENT_ISSUED'
  | 'PROPOSAL_RECEIVED'
  | 'INVOICE_REVIEW_DUE'
  | 'AWARD_DECISION'
  | 'DEBRIEF_REQUESTED';

export interface Notification {
  id: string;
  kind: NotificationKind;
  title: string;
  body: string;
  recipientRole: string;
  link: string;                    // router link
  createdAt: string;               // ISO
  readAt: string | null;
}
