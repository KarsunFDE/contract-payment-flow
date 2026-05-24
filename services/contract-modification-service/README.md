# contract-modification-service

Spring Boot 3.2 + Spring Data MongoDB. FAR/DFARS contract_modification CRUD.

## Endpoints

| Method | Path | Notes |
|--------|------|-------|
| GET    | `/api/contract-modifications` | List all (⚠ no tenant filter — Item 10) |
| GET    | `/api/contract-modifications/{id}` | |
| POST   | `/api/contract-modifications` | Create (⚠ no input sanitization — Item 9) |
| PUT    | `/api/contract-modifications/{id}` | |
| DELETE | `/api/contract-modifications/{id}` | |

## Build + run

```bash
mvn -B -DskipTests package
java -jar target/contract-modification-service-*.jar
```

## Brownfield-debt items present in this service

- **Item 2** — Audit row written async, after HTTP response is flushed (race).
- **Item 6 (partial)** — Logs `correlationId` (not `X-Request-ID` like the gateway).
- **Item 9** — `description` accepts arbitrary HTML.
- **Item 10** — `agency_id` in schema but no query filter.
- **Item 11** — `Dockerfile` uses `:latest`.

See `docs/brownfield-debt.md` for the full inventory.
