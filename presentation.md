# Contract Payment Flow — Demo Runbook

A presenter's script, run **entirely in the Angular web app** (`http://localhost:4200`).
No code on screen; the only terminal use is one-time pre-flight.

This runbook demonstrates the full post-award **SF-30 contract-modification** flow and the
AI/RAG capabilities behind it:

- **Contract-of-record autofill** — type a contract number, the static SF-30 blocks fill
  from the (mock) SAM.gov record, tenant-scoped by agency.
- **Derived FAR authority** — the governing FAR cite follows the modification type.
- **Live, LangSmith-traced AI drafting** — rationale + price/cost language from a real
  Claude model on AWS Bedrock, citing the actual period of performance.
- **Gateway-routed persistence** — the submission saves through the API gateway and the
  saved record is reachable from the modification index.
- **Live FAR/DFARS RAG clause search** — hybrid retrieval (RRF + rerank) over the real corpus.
- **(Optional) contractor consent loop** — the FAR 43.103(a) bilateral signature.

Everything below is one contract: **`GS-35F-0001V`** (agency **`agency-gsa`**). A second
seeded contract (`W912DY-24-C-0042`, agency `agency-usace`) is available to demonstrate
tenant isolation.

---

## How to use this document

- **Section 1** — one-time pre-flight (the only terminal step), done before the audience.
- **Section 2** — the demo, in acts, each a click-path with exact data + what to say.
- **Section 3** — what each act is really doing (architecture talking points).
- **Section 4** — live vs. fixture, presenter notes, recovery.
- **Section 5** — the data reference sheet (every value, copy-paste ready).

Rehearse Acts 1–2 once before presenting (the AI calls take a few seconds).

---

## 1. Pre-flight (before the audience — the only terminal steps)

1. Bring the stack up (off-screen). Confirm services healthy: `api-gateway`,
   `contract-modification-service`, `invoice-review-service`, `ai-orchestrator`,
   `frontend`, `mongodb`.
2. **Seed the contract-of-record** (required for autofill — runs in the container):
   ```
   docker compose -f infra/docker/docker-compose.yml exec ai-orchestrator python -m scripts.seed_contracts
   ```
   Expect `seeded 2 contracts into 'contracts'`. (Synthetic data only — no live PII.)
3. **Confirm the AI is live** (off-screen): open the SF-30 wizard, click **AI-draft
   rationale**, confirm a freshly generated, FAR-cited draft appears (a few seconds of
   "Drafting…") with a provenance line reading `…claude… · traced (LangSmith)`. If it reads
   `stub fallback` / `offline draft`, the AI service or its AWS/LangSmith creds aren't
   reachable — fix before presenting (§4).
4. (Optional but recommended) Open your **LangSmith project** in a browser tab so you can
   show the trace land live during Act 2.
5. Browse to `http://localhost:4200`; confirm the **Dashboard** loads. Set the role dropdown
   (top-right) to **Dana Reeves (CO)**. Zoom to ~110–125% so labels read from the back.

> **Why there's no login screen.** The local stack runs no OIDC/JWT issuer, so the API
> gateway is configured for dev (`GATEWAY_DEV_NO_AUTH=true`) to permit the SPA's data routes
> and allow the browser's CORS pre-flight. **All application traffic still routes through the
> gateway at `:8080`** — the frontend has no hardcoded service URLs. In production the same
> gateway requires a verified JWT (the dev flag defaults off). This is worth saying out loud:
> the architecture is gateway-fronted; only the dev *auth posture* is relaxed.

---

## 2. The demo

**Storyline:** A GSA contractor's contract needs Option Year 2 funded and the period of
performance extended. The Contracting Officer issues a bilateral SF-30 supplemental
agreement under FAR 43.103, assisted by AI that is grounded in the FAR/DFARS corpus. The
contractor then (optionally) signs it.

---

### Act 1 — Issue the SF-30: contract-of-record autofill

**Role:** **Dana Reeves (Contracting Officer)** (top-right dropdown).

**Say:** *"As the Contracting Officer I'm issuing a bilateral SF-30 supplemental agreement to
fund Option Year 2 and extend the period of performance, under FAR 43.103. I'll start by
pulling the contract of record."*

1. From the **Dashboard**, click **`+ New SF-30 modification`**.

2. **Step 1 — Basics.** Enter the title, then the two lookup keys (title + Agency + contract #):
   | Field | Value |
   |---|---|
   | Modification title | `Exercise Option Year 2 — incremental funding & PoP extension` |
   | Agency ID | `agency-gsa`  *(leave the default — must match the seeded contract)* |
   | Base contract # | `GS-35F-0001V` |

3. **Tab out of the contract # field.** The lookup fires and **autofills the static SF-30 blocks**:
   | Field | Autofilled value | SF-30 origin |
   |---|---|---|
   | Modification # | `P00003` | next mod number on the record (block 2) |
   | Effective date | `2026-06-15` | block 3 |
   | Funding citation | `Appropriation 47X0535.202601` | appropriation (block 12; carried to Step 4) |
   | *(captured, used by the AI draft)* | original PoP `2024-01-10 → 2026-06-30` | base period of performance |

   A note reads **"Auto-filled from SAM.gov"**.

   > *Say:* *"Typing the contract number resolved the authoritative contract-of-record from
   > SAM.gov and pre-filled the static blocks — next modification number, effective date,
   > appropriation, and the original period of performance. The officer reviews and adjusts;
   > nothing is invented."*
   >
   > **Tenant-isolation beat (optional, strong):** *"That lookup is scoped to my agency. If I
   > were signed into a different agency, the same contract number would return nothing — a
   > CO can't resolve another agency's contract."* (To show it: change Agency to `GSA-FAS` and
   > re-tab — the fields stay blank / 'no match'. Change it back to `agency-gsa`.)

4. Set **Modification type → Bilateral — supplemental agreement (FAR 43.103)**.
   - **FAR authority** auto-fills to `FAR 43.103(a) — Supplemental Agreement`.
     > *Say:* *"FAR authority isn't a property of the base contract — it follows the kind of
     > action. Choosing bilateral set the governing cite automatically; a unilateral change
     > order would set FAR 52.243 instead."*
   - The **"Contractor consent required"** banner appears. Point at it — it sets up the
     optional Act 5. Click **`Next →`**.

5. **Step 2 — Funding & Period of Performance.** Enter, then **`Next →`**:
   | Field | Value |
   |---|---|
   | Net funding delta ($) | `+2450000` |
   | Revised PoP start | `2026-07-01` |
   | Revised PoP end | `2027-06-30` |

---

### Act 2 — Live, traced AI drafting (the headline)

**Say:** *"Now the AI assists with the narrative — but every word is reviewable before it
becomes part of the record."*

6. **Step 3 — Rationale (LIVE AI).** Click **`▦ AI-draft rationale`**. After a few seconds
   the field fills with a FAR-cited change rationale. Provenance reads
   `…claude-haiku… · traced (LangSmith)`.
   - The **Period of Performance section states the real dates** — original
     `2024-01-10 to 2026-06-30`, revised `2026-07-01 to 2027-06-30` — **not** `[Insert …]`
     placeholders. Those dates flowed from the autofill (original) and Step 2 (revised) into
     the model prompt.

   > **This is the moment to land "real AI."** *Say:* *"That rationale was just generated by a
   > Claude model on AWS Bedrock — a real call, traced end-to-end in LangSmith, citing the
   > actual period of performance from the contract record and this modification."* Switch to
   > your LangSmith tab to show the trace landing. Edit a sentence to prove it's editable
   > (human-in-the-loop). Click **`Next →`**.

7. **Step 4 — Price / Cost Impact (LIVE AI).** Click **`▦ AI-draft price/cost impact`** —
   another live, traced draft (FAR 43.204 equitable-adjustment framing). The funding citation
   was carried from the Step-1 autofill. Click **`Next →`**.

> **If the service is unreachable:** the buttons fall back to a deterministic local draft and
> the provenance line says so — the wizard still works, but it's not a real traced call.

---

### Act 3 — Submit + gateway-routed persistence

8. **Step 5 — Review.** Walk the summary (bilateral, +$2,450,000, consent required), then
   **`Submit modification request`**.
   - The record is **persisted through the API gateway** (`:8080` → `contract-modification-service`)
     and you land on the **modification editor**.

   > *Say:* *"Submitting saved the modification through the gateway and dropped me into the
   > pre-publication editor. It's also now in the modification index — every saved
   > modification is one click away."*

9. **(Show the index, optional)** Navigate to the **modification index** (`/contractModifications`).
   The new modification is listed; **click its title** to reopen the editor. (Previously the
   only way back in was hand-editing the URL — the index rows are now links.)

---

### Act 4 — Live FAR/DFARS RAG clause search

On the **editor** (`/contractModifications/<id>/edit`):

10. In the **right-hand column → "Clause library (RAG)"** card, type:
    `bilateral supplemental agreement contractor consent`
11. Press **Enter** (or click **Search**). Real FAR clauses return from the corpus — e.g.
    **43.103 Types of Contract Modifications**, **43.301 Use of the SF-30**,
    **43.101 Definitions**, **43.204 Administration of Change Orders** — with an info line:
    `N clause(s) · hybrid_rrf_reranked · NNN ms`.
    - Results are **de-duplicated by clause** (a clause split across multiple chunks shows once).

   > *Say:* *"This is hybrid retrieval — lexical plus vector search, fused with reciprocal
   > rank fusion and then reranked — over the actual FAR/DFARS Part 42/43/32 corpus. It's the
   > same grounding the drafting draws on, and it's scoped by agency just like the contract
   > lookup."*

---

### Act 5 — (Optional) Contractor signs the bilateral modification

**Say:** *"A bilateral modification isn't effective until the contractor signs."*

12. Role dropdown → **Acme Federal LLC (contractor)** → **Vendor portal** (`/vendor/proposals`).
13. Find the `GS-35F-0001V` row; **Amendment acks** shows an outstanding item with an
    **`Acknowledge amendment`** button. Click it — the count ticks up and the button clears.
14. Switch back to **CO** → open **Proposal intake** *and* **Amendment editor** for that
    modification. The acknowledgement is reflected in **both** Acks columns (they stay in sync).

    > *Say:* *"That's the contractor's signature on the SF-30 — the full FAR 43.103(a) consent
    > loop, CO to contractor, in one system."*
    > *(Act 5 is in-session demo state and resets on a page refresh.)*

---

## 3. What each act is really doing (architecture talking points)

| Act | Under the hood |
|---|---|
| **1 — Autofill** | Wizard calls `ai-orchestrator` `POST /workflow/contract-lookup` with `{contract_number, agency_id}`. Deterministic lookup (no LLM) against the seeded `contracts` collection; the query is **agency-scoped** (tenant isolation). Returns the SF-30 static-field map + a SAM.gov source citation. |
| **1 — FAR authority** | Pure frontend mapping from modification type → governing FAR cite. Not from the contract record (the authority follows the *action*, not the award). |
| **2 — AI draft** | `POST /draft-section` runs a LangChain Runnable (`prompt | ChatBedrock | parser`) on AWS Bedrock; traced automatically when LangSmith env is set. The prompt now receives the original + revised PoP dates and is instructed to print explicit ranges, never placeholders. Falls back to a deterministic stub if Bedrock is unreachable. |
| **3 — Submit** | `ContractModificationService.create()` → gateway `:8080` → `contract-modification-service`. The gateway permits the route in dev (`GATEWAY_DEV_NO_AUTH`) + serves CORS for `localhost:4200`; prod keeps full JWT auth. No hardcoded service URLs in the SPA. |
| **4 — RAG** | `POST /retrieve/` on `ai-orchestrator`: hybrid lexical + Atlas Vector Search → RRF fusion → cross-encoder rerank → fail-closed audit, scoped by agency. UI de-dupes by clause number. |
| **5 — Consent** | Acknowledgement updates the proposal- and amendment-level state so the vendor portal and both CO views agree (in-session demo state). |

---

## 4. Live vs. fixture, presenter notes, recovery

**Live (real services):**

| Element | Behaviour |
|---|---|
| Contract-of-record autofill | **Live** — deterministic agency-scoped lookup via `ai-orchestrator`. |
| AI-draft rationale / price-cost | **Live** — real AWS Bedrock call, **LangSmith-traced**. |
| Clause-library RAG search | **Live** — real hybrid retrieval (RRF + rerank) over the FAR/DFARS corpus. |
| SF-30 wizard submit | **Persists** through the gateway to `contract-modification-service`. |

**Fixture / in-session:** the editor's section text, the modification index contents beyond
what you just created, and the Act-5 acknowledgement are demo state (reset on refresh).

**Roles:** no login — identity is the top-right dropdown. CO = **Dana Reeves**; contractor =
**Acme Federal LLC**.

**Key gotchas:**
- **Agency must be `agency-gsa`** for autofill — the lookup is tenant-scoped to the seeded
  contract. `GSA-FAS` (or anything else) returns no match and the fields stay blank. (This is
  the same fact you can demo as a *feature* in Act 1.)
- **If a draft button shows `stub fallback` / `offline draft`:** `ai-orchestrator` or its
  AWS/LangSmith creds aren't reachable. Sensible draft still appears, but it isn't a real
  traced call — fix in pre-flight, don't discover it on stage.
- **AI-draft + RAG take a few seconds** (real model / real retrieval) — buttons read
  "Drafting…" / "Searching…"; wait for them.

**Proving the AI is real (the headline):** the `…claude… · traced (LangSmith)` provenance
line plus the live trace in your LangSmith tab. Set up LangSmith in a tab beforehand.

**Do NOT, in front of the audience:** paste HTML/scripts into any text field; wander into
unrelated roles/screens. Keep to the path above.

**Recovery:**
- Blank autofill → confirm Agency is `agency-gsa` and the seed ran (§1.2).
- Wizard won't submit → Steps 3–4 need content first.
- Landed on the index instead of the editor → click the modification's **title** to open it.
- RAG returns "sample results (retrieval service unreachable)" → `ai-orchestrator` `/retrieve`
  isn't reachable on `:8000`; the panel still demonstrates with a small static set.

---

## 5. Data reference sheet (copy-paste ready)

**SF-30 modification (Acts 1–3)**
| Item | Value |
|---|---|
| Agency | `agency-gsa` |
| Base contract # | `GS-35F-0001V` |
| Modification title | `Exercise Option Year 2 — incremental funding & PoP extension` |
| Modification # | `P00003` *(autofilled)* |
| Effective date | `2026-06-15` *(autofilled)* |
| Modification type | Bilateral — supplemental agreement (FAR 43.103) |
| FAR authority | `FAR 43.103(a) — Supplemental Agreement` *(derived from type)* |
| Net funding delta | `+2450000` |
| Revised PoP | `2026-07-01` → `2027-06-30` |
| Original PoP (autofilled, feeds the AI draft) | `2024-01-10` → `2026-06-30` |
| Funding citation | `Appropriation 47X0535.202601` *(autofilled)* |
| Clause-search query | `bilateral supplemental agreement contractor consent` |

**Second seeded contract** (tenant-isolation / alternate demo):
`W912DY-24-C-0042`, agency `agency-usace` (contractor *Beacon Civil Works Inc*).

**Roles (top-right dropdown)**
| Role | Persona | Used in |
|---|---|---|
| Contracting Officer | Dana Reeves (CO) | Acts 1–4 |
| Contractor (vendor) | Acme Federal LLC | Act 5 (optional) |

---

### Elevator pitch (opening line)

> *"Contract Payment Flow runs post-award federal contract administration. Watch a
> Contracting Officer issue a bilateral SF-30 modification — fields auto-filled from the
> agency-scoped contract-of-record, rationale and price/cost language drafted by a real
> Claude model on AWS Bedrock and traced end-to-end in LangSmith, grounded in a live
> FAR/DFARS retrieval corpus with hybrid search and reranking — then the contractor signs
> it, completing the FAR 43.103(a) consent loop. All in the browser, all through the gateway."*
