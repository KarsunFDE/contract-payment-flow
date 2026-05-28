# FAR Part 42 / 43 / 32 — post-award corpus (STARTER STUBS)

Thin seed corpus for the contract-payment-flow RAG surface
(`far_post_award` vector index, collection `COLLECTION_FAR_POST_AWARD`).

> **These are STARTER STUBS, not the production corpus.** Each file holds a
> short (1–2 paragraph) excerpt of a real FAR / CFR cite so the cohort has
> something to retrieve against on W1 Thu. The full ingest + Atlas hybrid
> retrieval wiring is the **W2 RAG cohort task** — do not treat this as
> complete. Expand it then.

## Domain

Post-award contract administration + payment (anchor: WAWF — Wide Area
Workflow). The three FAR parts that govern this lifecycle:

| Part | Topic |
|------|-------|
| FAR Part 42 | Contract administration + audit services |
| FAR Part 43 | Contract modifications (SF-30) |
| FAR Part 32 | Contract financing + payment (proper invoice, prompt payment) |

## Files

| File | Cite | Topic |
|------|------|-------|
| `far-43-101-definitions.md` | FAR 43.101 | Modification types (unilateral / bilateral) |
| `far-43-103-types.md` | FAR 43.103 | Change order vs supplemental agreement |
| `far-43-301-sf30.md` | FAR 43.301 | Use of the SF-30 |
| `far-32-905-proper-invoice.md` | FAR 32.905 | Proper-invoice required elements |
| `far-32-9-prompt-payment.md` | FAR 32.9 | Prompt Payment Act framework |
| `cfr-5-1315-prompt-payment.md` | 5 CFR 1315 | 30-day pay / 7-day return clock |
| `far-42-overview.md` | FAR Part 42 | Contract administration overview (COR/DCAA) |
| `dfars-252-232-7003-wawf.md` | DFARS 252.232-7003 | Electronic submission via WAWF |

## Sources

All excerpts paraphrase / quote from public federal sources, retrieved
2026-05-28 via /web-research:
- Acquisition.gov FAR Parts 42 / 43 / 32 (https://www.acquisition.gov/far)
- eCFR Title 5 Part 1315 (https://www.ecfr.gov/current/title-5/.../part-1315)
- DFARS 252.232-7003 (https://www.acquisition.gov/dfars)

> Verify cite text against the live FAR before relying on it for a deliverable —
> these stubs are trimmed for retrieval, not for legal accuracy.
