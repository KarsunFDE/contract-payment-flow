import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../environments/environment';
import { Qna } from '../models/qna';

@Injectable({ providedIn: 'root' })
export class QnaService {
  constructor(private http: HttpClient) {}

  list(contract_modificationId: string): Observable<Qna[]> {
    return this.http.get<Qna[]>(
      `${environment.apiGatewayUrl}/api/contract-modifications/${contract_modificationId}/qa`,
    );
  }

  answer(contract_modificationId: string, qaId: string, answer: string): Observable<Qna> {
    return this.http.put<Qna>(
      `${environment.apiGatewayUrl}/api/contract-modifications/${contract_modificationId}/qa/${qaId}/answer`,
      { answer },
    );
  }

  submitQuestion(contract_modificationId: string, question: string): Observable<Qna> {
    return this.http.post<Qna>(
      `${environment.apiGatewayUrl}/api/contract-modifications/${contract_modificationId}/qa`,
      { question },
    );
  }
}
