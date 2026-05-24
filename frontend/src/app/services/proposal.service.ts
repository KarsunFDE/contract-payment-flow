import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { Proposal } from '../models/proposal';

@Injectable({ providedIn: 'root' })
export class ProposalService {
  constructor(private http: HttpClient) {}

  listForContractModification(contract_modificationId: string): Observable<Proposal[]> {
    return this.http.get<Proposal[]>(
      `${environment.apiGatewayUrl}/api/contract-modifications/${contract_modificationId}/proposals`,
    );
  }

  vendorOwn(): Observable<Proposal[]> {
    return this.http.get<Proposal[]>(
      `${environment.apiGatewayUrl}/api/vendor/proposals`,
    );
  }

  acknowledgeAmendment(
    contract_modificationId: string,
    proposalId: string,
    amendmentNumber: number,
  ): Observable<void> {
    return this.http.post<void>(
      `${environment.apiGatewayUrl}/api/contract-modifications/${contract_modificationId}/proposals/${proposalId}/acknowledge-amendment`,
      { amendmentNumber },
    );
  }
}
