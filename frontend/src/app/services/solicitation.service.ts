import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { ContractModification, ContractModificationCreate } from '../models/contract-modification';

/**
 * ContractModification service — the "right" way to talk to the backend.
 *
 * Goes through the API gateway (environment.apiGatewayUrl). The cohort
 * compares this with `contractModification-list.component.ts`, which hardcodes
 * `http://localhost:8081` and bypasses the gateway (Item 8).
 */
@Injectable({ providedIn: 'root' })
export class ContractModificationService {
  private readonly baseUrl = `${environment.apiGatewayUrl}/api/contract-modifications`;

  constructor(private http: HttpClient) {}

  list(): Observable<ContractModification[]> {
    return this.http.get<ContractModification[]>(this.baseUrl);
  }

  get(id: string): Observable<ContractModification> {
    return this.http.get<ContractModification>(`${this.baseUrl}/${id}`);
  }

  create(req: ContractModificationCreate): Observable<ContractModification> {
    return this.http.post<ContractModification>(this.baseUrl, req);
  }
}
