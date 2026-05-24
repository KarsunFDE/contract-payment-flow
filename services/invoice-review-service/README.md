# invoice-review-service

Spring Boot 3.2. InvoiceReview panel coordination. Calls contract-modification-service over sync REST.

## Endpoints

| Method | Path | Notes |
|--------|------|-------|
| GET    | `/api/invoice-reviews/{invoice_reviewId}/contract_modification/{contract_modificationId}` | Fetches contract_modification via contract-modification-service |
| POST   | `/api/invoice-reviews` | Create panel (⚠ no idempotency key — Item 3) |

## Brownfield-debt items present in this service

- **Item 3** — No Resilience4j circuit breaker / timeout / fallback on `ContractModificationClient`; no idempotency key on `POST /api/invoice-reviews`.
- **Item 6 (partial)** — Logs `traceId` (third correlation-ID convention).
- **Item 11** — `Dockerfile` uses `:latest`.

See `docs/brownfield-debt.md` for the full inventory.
