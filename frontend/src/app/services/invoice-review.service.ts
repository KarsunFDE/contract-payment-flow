import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { InvoiceReview, InvoiceReviewScore } from '../models/invoice-review';

@Injectable({ providedIn: 'root' })
export class InvoiceReviewService {
  constructor(private http: HttpClient) {}

  get(id: string): Observable<InvoiceReview> {
    return this.http.get<InvoiceReview>(
      `${environment.apiGatewayUrl}/api/invoice-reviews/${id}`,
    );
  }

  scores(id: string): Observable<InvoiceReviewScore[]> {
    return this.http.get<InvoiceReviewScore[]>(
      `${environment.apiGatewayUrl}/api/invoice-reviews/${id}/scores`,
    );
  }

  submitScore(id: string, score: Partial<InvoiceReviewScore>): Observable<InvoiceReviewScore> {
    return this.http.post<InvoiceReviewScore>(
      `${environment.apiGatewayUrl}/api/invoice-reviews/${id}/scores`,
      score,
    );
  }

  consensus(id: string): Observable<InvoiceReviewScore[]> {
    return this.http.get<InvoiceReviewScore[]>(
      `${environment.apiGatewayUrl}/api/invoice-reviews/${id}/consensus`,
    );
  }

  /** AI-drafted Source Selection Decision Document narrative (FAR 15.308). */
  draftSsdd(id: string): Observable<{ narrative: string; correlationId: string }> {
    return this.http.post<{ narrative: string; correlationId: string }>(
      `${environment.apiGatewayUrl}/api/ai/eval/ssdd-draft`,
      { invoiceReviewId: id },
    );
  }
}
