import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { Amendment, AmendmentCreate } from '../models/amendment';

/**
 * Amendments to a published contract_modification (FAR 15.206).
 *
 * Routes through `environment.apiGatewayUrl` — the right way. Compare
 * with `contract_modification-list.component.ts` which hardcodes :8081 per Item 8.
 */
@Injectable({ providedIn: 'root' })
export class AmendmentService {
  constructor(private http: HttpClient) {}

  list(contract_modificationId: string): Observable<Amendment[]> {
    return this.http.get<Amendment[]>(
      `${environment.apiGatewayUrl}/api/contract-modifications/${contract_modificationId}/amendments`,
    );
  }

  issue(contract_modificationId: string, req: AmendmentCreate): Observable<Amendment> {
    return this.http.post<Amendment>(
      `${environment.apiGatewayUrl}/api/contract-modifications/${contract_modificationId}/amendments`,
      req,
    );
  }
}
