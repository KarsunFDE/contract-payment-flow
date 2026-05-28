import { Injectable } from '@angular/core';
import { BehaviorSubject, Observable } from 'rxjs';
import { Notification } from '../models/notification';

/**
 * In-app notification bus (bell icon + drawer).
 *
 * Per feature-inventory-target.md notification table. Item 6
 * (correlation-ID mismatch) is reinforced by the fact that this
 * client-side mock generates its own UUID independent of the
 * triggering service-side correlation ID.
 */
@Injectable({ providedIn: 'root' })
export class NotificationService {
  private readonly subject = new BehaviorSubject<Notification[]>(this.seed());
  readonly items$: Observable<Notification[]> = this.subject.asObservable();

  markRead(id: string): void {
    this.subject.next(
      this.subject.value.map((n) =>
        n.id === id ? { ...n, readAt: new Date().toISOString() } : n,
      ),
    );
  }

  markAllRead(): void {
    const ts = new Date().toISOString();
    this.subject.next(
      this.subject.value.map((n) => ({ ...n, readAt: n.readAt ?? ts })),
    );
  }

  unreadCount(): number {
    return this.subject.value.filter((n) => !n.readAt).length;
  }

  private seed(): Notification[] {
    return [
      {
        id: 'n-1001',
        kind: 'SF30_ISSUED',
        title: 'SF-30 P00003 issued — Option Year 2 + funds (GS-35F-0001V)',
        body: 'CO Reeves signed bilateral supplemental mod P00003 (exercise OY2, +$18M incremental funding) per FAR 43.103. Contractor acknowledgement required.',
        recipientRole: 'contracting_officer',
        link: '/contractModifications/mod-0142/edit',
        createdAt: new Date(Date.now() - 1000 * 60 * 12).toISOString(),
        readAt: null,
      },
      {
        id: 'n-1002',
        kind: 'INVOICE_RECEIVED',
        title: 'Invoice INV-2026-0412 received — proper-invoice check passed',
        body: 'Acme Federal LLC submitted INV-2026-0412 ($482,350) via WAWF; all FAR 32.905 proper-invoice elements present and receiving report WAWF-RR-88213 matched.',
        recipientRole: 'cor',
        link: '/invoiceReview/workspace',
        createdAt: new Date(Date.now() - 1000 * 60 * 60 * 2).toISOString(),
        readAt: null,
      },
      {
        id: 'n-1003',
        kind: 'PAYMENT_CERTIFIED',
        title: 'Payment certified — $482,350 (INV-2026-0412)',
        body: 'CO certified INV-2026-0412 for payment; Prompt Payment due 2026-06-23 per FAR 32.904. Interest accrues thereafter (FAR 32.907).',
        recipientRole: 'contracting_officer',
        link: '/invoiceReview/workspace',
        createdAt: new Date(Date.now() - 1000 * 60 * 60 * 8).toISOString(),
        readAt: null,
      },
      {
        id: 'n-1004',
        kind: 'INVOICE_RETURNED',
        title: 'Invoice INV-2026-0415 returned as improper',
        body: 'Missing unit prices for CLIN 0002 and unmatched receiving report; returned to contractor within 7 days per FAR 32.905(b). Prompt-payment clock paused.',
        recipientRole: 'cor',
        link: '/invoiceReview/workspace',
        createdAt: new Date(Date.now() - 1000 * 60 * 60 * 14).toISOString(),
        readAt: null,
      },
      {
        id: 'n-1005',
        kind: 'DCAA_FLAG_RAISED',
        title: 'DCAA flag raised on cost-type invoice DLA-INV-7741',
        body: 'Cost-type invoice pending DCAA audit (FAR 42.1); provisional payment subject to later cost-allowability adjustment per FAR 31.205.',
        recipientRole: 'dcaa_auditor',
        link: '/invoiceReview/workspace',
        createdAt: new Date(Date.now() - 1000 * 60 * 60 * 26).toISOString(),
        readAt: null,
      },
      {
        id: 'n-1006',
        kind: 'CLOSEOUT_INITIATED',
        title: 'Closeout initiated — Contract GS-35F-0001V',
        body: 'Draft mod A00003 to deobligate residual FY25 funds; final invoice + release-of-claims pending per FAR 4.804 / 42.708.',
        recipientRole: 'contract_specialist',
        link: '/contractModifications/mod-0418/edit',
        createdAt: new Date(Date.now() - 1000 * 60 * 60 * 30).toISOString(),
        readAt: null,
      },
      {
        id: 'n-1007',
        kind: 'CPAR_WINDOW_OPEN',
        title: 'CPAR rebuttal window open — Contract GS-35F-0001V',
        body: 'Interim CPARS issued; contractor has 60 days to submit rebuttal per FAR 42.1503(d).',
        recipientRole: 'vendor',
        link: '/contracts/ctr-0001/cpars',
        createdAt: new Date(Date.now() - 1000 * 60 * 60 * 40).toISOString(),
        readAt: null,
      },
      {
        id: 'n-1008',
        kind: 'OIG_FINDING_OPENED',
        title: 'OIG Finding F-2026-0007 opened',
        body: 'CA-7 continuous-monitoring finding — evidence requested.',
        recipientRole: 'oig_reviewer',
        link: '/admin/findings',
        createdAt: new Date(Date.now() - 1000 * 60 * 60 * 48).toISOString(),
        readAt: new Date(Date.now() - 1000 * 60 * 60 * 47).toISOString(),
      },
    ];
  }
}
