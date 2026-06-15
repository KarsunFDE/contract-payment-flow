"""
ai-orchestrator — main FastAPI entrypoint.

DELIBERATE BROWNFIELD DEBT (annotated for cohort discovery):

  Item 4 — No structured-output validation. /draft-contract-modification returns the
           raw stub response (sometimes {"clause_id": null, ...}); downstream
           Spring service hits NullPointerException on .clause_id.toString().
           Newer endpoints (/draft-amendment, /answer-qa, /eval/ssdd-draft,
           /eval/factor-suggest, /agent/intake-triage) ALSO return raw dict —
           same Pydantic-validation drift across 4 distinct AI endpoints.

  Item 5 (partial) — This file uses the LangChain v1.0+ composed-Runnable
           pattern (prompt | llm | parser). The legacy LLM Chain(...).run(...)
           pattern lives in app/legacy_chain.py and is invoked from 3 entry
           points: /draft-contract-modification (SF-30 rationale drafting),
           /draft-amendment (bilateral supplemental narrative), and the
           notification-copy generator (called upstream via the Spring
           Notifier path which fans to /draft-amendment with a
           payment/modification-window topic). Cohort consolidates in W2.

           UPDATE (Item 5 / D1 CLOSED, 2026-06): app/legacy_chain.py is DELETED.
           The LangGraph StateGraph agent under app/workflow/ is the v1.0
           replacement — there is no legacy drafting path left. The description
           above refers to code that no longer exists.

  Item 6 (partial) — No correlation-ID logging at all. Other services log
           X-Request-ID / correlationId / traceId — this one logs nothing.

  Item 7 — pinecone-client is in requirements.txt but no `import pinecone`
           anywhere. Cohort removes in W2.

  Item 11 — Dockerfile uses :latest (the OTHER 4 services do; this one is
           hand-pinned to 3.11-slim per the comment block at the top of the
           ai-orchestrator Dockerfile).

  Plus: no retry, no streaming, no real Bedrock retry/cost accounting in
  this code path. Bedrock InvokeModel is wired (D-060 — real-Bedrock-from-W2
  authorized) via app/bedrock_client.py; if AWS creds aren't present, the
  client falls back to a stub.
"""
from __future__ import annotations

import logging
import os
import random
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# ⚠ Item 5 — v1.0 composed-Runnable style. Imported but not actually wired to
# Bedrock in the stub (we return mock data). Cohort wires it up in W1 Thu.
try:
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import StrOutputParser
    _LANGCHAIN_V1_AVAILABLE = True
except ImportError:
    _LANGCHAIN_V1_AVAILABLE = False

# Note: legacy_chain.py also exists in this package and uses the pre-v1.0
# LLM Chain pattern. Item 5 — cohort migrates that file's style to this one.
# UPDATE (Item 5 / D1 CLOSED): legacy_chain.py has been deleted — the new agent
# under app/workflow/ replaces it. The note above describes the prior state.
from app.bedrock_client import invoke_model, BEDROCK_MODEL_ID, AWS_REGION

# ADR-0005 Phase 1 routers — Day 0 scaffolding. Ingestion (write path) and
# retrieval (read path) are owned separately; this file stays frozen so the
# two owners never touch it concurrently.
from app.ingestion.router import router as ingestion_router
from app.retrieval.router import router as retrieval_router

# M3 Phase 0 (Foundation) — the agent workflow lives in app/workflow/. Mounted
# additively here; only a status probe is exposed until the runner lands (Phase 4).
from app.workflow.router import router as workflow_router

# ⚠ DELIBERATE — no correlation-ID in the log format (Item 6).
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(name)s - %(message)s",
)
log = logging.getLogger("ai-orchestrator")

app = FastAPI(title="ai-orchestrator", version="0.1.0-brownfield")

# ADR-0005 Phase 1 — both routers registered Day 0 so neither owner edits
# main.py again this week.
app.include_router(ingestion_router)
app.include_router(retrieval_router)
app.include_router(workflow_router)  # M3 Phase 0 — workflow surface (status probe)


class DraftRequest(BaseModel):
    """
    ⚠ DELIBERATE — Item 4 reinforcement:
      No Field constraints, no examples, no descriptions. Cohort tightens
      in W1 Fri output validation.
    """
    topic: str
    constraints: str | None = None


class DraftResponse(BaseModel):
    """
    Structured response for /draft-contract-modification (Item 4 D2 closure).

    clause_id is a required, non-empty string so the downstream Spring service
    can always call .clause_id.toString() without a NullPointerException.
    """
    clause_id: str = Field(min_length=1)  # FAR clause / doc reference — never null
    draft: str                            # generated SF-30 modification rationale
    model: str                            # Bedrock model id that produced the draft
    region: str | None = None             # AWS region, when the real Bedrock path ran


class QaDraftRequest(BaseModel):
    """Vendor Q&A drafting request. ⚠ Item 4 — no Field constraints."""
    question: str
    contract_modification_id: str | None = None
    constraints: str | None = None


class ClauseSearchRequest(BaseModel):
    """Hybrid RAG over FAR/DFARS clause library. ⚠ Item 4 — no Field."""
    query: str
    far_part: str | None = None
    agency_id: str | None = None  # ⚠ Item 10 surface — not enforced upstream
    top_k: int = 5


class FactorSuggestRequest(BaseModel):
    """Section M factor-narrative suggestion. ⚠ Item 4 — no Field."""
    topic: str
    constraints: str | None = None


class IntakeTriageRequest(BaseModel):
    """Multi-agent modification-intake triage request. ⚠ Item 4 — no Field."""
    proposal_id: str
    contract_modification_id: str | None = None
    raw_text: str | None = None


class InvoiceReviewRequest(BaseModel):
    """Single-agent invoice-review / validation request. ⚠ Item 4 — no Field."""
    invoice_number: str
    contract_number: str | None = None
    receiving_report_ref: str | None = None
    notes: str | None = None
    # For /validate-invoice: which FAR 32.905 required elements were supplied.
    provided_elements: list[str] | None = None


@app.get("/health")
def health() -> dict[str, str]:
    """
    ⚠ DELIBERATE: always returns 200. No DB ping, no Bedrock ping.
    Cohort adds real health check in W5 Tue OTel work.
    """
    return {"status": "ok", "service": "ai-orchestrator"}


@app.post("/draft-contract-modification")
def draft_contract_modification(req: DraftRequest) -> DraftResponse:
    """
    Post-award SF-30 modification-rationale drafting (FAR Part 43).

    Single-agent assist: given a change request (funding delta, PoP change,
    scope revision), drafts the modification rationale + FAR authority cite
    a CO/COR reviews before issuing the SF-30.

    Bedrock invocation via app.bedrock_client.invoke_model (D-060 — real
    Bedrock from W2, falls back to stub if no AWS creds). Result is
    interleaved with the same 1-in-3 null-clause_id drift the locked test
    asserts (Item 4).

    ⚠ DELIBERATE GAPS (Item 4):
      - No Pydantic response model — returns raw dict.
      - 1-in-3 calls return {"clause_id": null, ...} to exercise the
        downstream NullPointerException path.
      - No retry, no streaming, no cost tracking, no structured-output
        schema enforced.

    Item 4 D2 closure — the gaps above are now fixed in place: this endpoint
    returns a validated DraftResponse and always emits a non-null clause_id.
    """
    log.info("draft-contract_modification called topic=%r constraints=%r",
             req.topic, req.constraints)

    # Bedrock call (D-060) produces the rationale text for the 'draft' field.
    bedrock = invoke_model(
        f"Draft the rationale for a post-award contract modification (SF-30) "
        f"covering: {req.topic}. "
        f"Constraints: {req.constraints or 'none'}.",
        system="You draft FAR Part 43-compliant contract modification rationale "
               "(SF-30). Cite the governing Changes-clause authority.",
    )

    # Always emit a non-null clause_id; DraftResponse enforces the contract.
    return DraftResponse(
        clause_id=f"FAR-52.{random.randint(200, 250)}-{random.randint(1, 30)}",
        draft=bedrock["body"],
        model=BEDROCK_MODEL_ID,
        region=AWS_REGION,
    )


@app.post("/draft-amendment")
def draft_amendment(req: DraftRequest) -> dict[str, Any]:
    """
    Bilateral supplemental-agreement narrative drafting (FAR 43.103).

    Post-award: drafts the negotiated change narrative for a bilateral
    modification that requires contractor consent.

    ⚠ Item 4 — no Pydantic response model.
    ⚠ Item 5 — routes through legacy_chain construction (the legacy LLM Chain
       pattern is imported + constructed via legacy_chain.draft_with_legacy_chain
       upstream in the call graph). This is entry point #2 of 3 for Item 5.
       UPDATE (Item 5 / D1 CLOSED): legacy_chain.py is deleted; this endpoint
       no longer has a legacy drafting path. (Item 4 below is still open here:
       this endpoint still returns a raw dict, not a Pydantic response_model.)
    ⚠ Item 6 — no correlation-id forwarded.
    """
    log.info("draft-amendment called topic=%r", req.topic)
    bedrock = invoke_model(
        f"Draft a bilateral supplemental-agreement narrative for: {req.topic}. "
        f"Contractor-impact considerations: {req.constraints or 'standard scope change'}.",
        system="You draft FAR 43.103-compliant bilateral modification narratives.",
    )
    return {
        "amendment_text": bedrock["body"],
        "model": BEDROCK_MODEL_ID,
        "predicted_vendor_impact": "contractor consent required",
    }


@app.post("/answer-qa")
def answer_qa(req: QaDraftRequest) -> dict[str, Any]:
    """
    Contractor administration-question response drafting using clause-library RAG.

    Post-award: answers vendor PM questions about a modification or payment
    (e.g. "why was invoice INV-204 returned?").

    ⚠ Item 4 — no Pydantic response model.
    ⚠ Item 6 — no correlation-id forwarded.
    ⚠ Item 9 reinforcement — req.question may contain raw HTML; we feed it
       directly into the prompt (prompt-injection-via-stored-content
       surface for W4 Wed OWASP LLM01).
    """
    log.info("answer-qa called question=%r", req.question[:60])
    bedrock = invoke_model(
        f"Contractor question: {req.question}\n\n"
        f"Draft a FAR-compliant COR/CO answer. Cite clause IDs where applicable.",
        system="You answer contractor questions about post-award contract "
               "modifications and payment (FAR Part 42/43/32).",
    )
    return {
        "answer_draft": bedrock["body"],
        "cited_clauses": [],  # ⚠ Item 4 — schema mismatch; sometimes the body
                              # contains clause refs but this list stays empty
        "model": BEDROCK_MODEL_ID,
    }


@app.post("/rag/clause-search")
def rag_clause_search(req: ClauseSearchRequest) -> dict[str, Any]:
    """
    Hybrid RAG over FAR/DFARS clause library (Atlas Vector Search).

    Cohort wires the Atlas hybrid retrieval in W2 (replacing the lexical-only
    stub here). Pinecone is listed in requirements.txt as "available vector
    store" but never imported (Item 7).

    ⚠ Item 6 — no correlation-id forwarded.
    ⚠ Item 7 — pinecone-client is in requirements.txt; this module does not
       import pinecone (stays unimported).
    """
    log.info("rag/clause-search query=%r far_part=%r top_k=%d",
             req.query[:60], req.far_part, req.top_k)
    # ⚠ Atlas Vector Search call would land here; stub returns a shaped
    # response so the surface flows. Corpus = FAR Part 42/43/32 (post-award).
    bedrock = invoke_model(
        f"Summarize FAR Part 42/43/32 clauses relevant to: {req.query}",
        system="You retrieve FAR Part 42/43/32 (post-award admin, modifications, "
               "contract financing) clauses; cite clause IDs.",
    )
    hits = [
        {"clause_id": "FAR-43.103", "title": "Types of Contract Modifications",
         "score": 0.91, "far_part": "FAR"},
        {"clause_id": "FAR-32.905", "title": "Payment Documentation and Process (Proper Invoice)",
         "score": 0.87, "far_part": "FAR"},
    ][: req.top_k]
    return {
        "query": req.query,
        "hits": hits,
        "synthesis": bedrock["body"],
        "model": BEDROCK_MODEL_ID,
    }


@app.post("/eval/factor-suggest")
def eval_factor_suggest(req: FactorSuggestRequest) -> dict[str, Any]:
    """
    Invoice line-item / DCAA-flag narrative suggestion. HITL-gated by COR.

    Post-award: suggests review narrative for a flagged invoice line item
    (e.g. unit-price variance, potential unallowable cost FAR 31.205).

    ⚠ Item 4 — no Pydantic response model.
    ⚠ Item 6 — no correlation-id forwarded.
    """
    log.info("eval/factor-suggest topic=%r", req.topic)
    bedrock = invoke_model(
        f"Suggest an invoice-review narrative for: {req.topic}. "
        f"Line-item context: {req.constraints or '(none)'}",
        system="You suggest COR invoice-review narrative; HITL approves before "
               "certify/return.",
    )
    return {
        "narrative_suggestion": bedrock["body"],
        "hitl_gate": "cor-review-required",
        "model": BEDROCK_MODEL_ID,
    }


@app.post("/eval/ssdd-draft")
def eval_ssdd_draft(req: DraftRequest) -> dict[str, Any]:
    """
    Invoice-review summary drafting (FAR 32.905 proper-invoice + payment
    determination). COR/CO-gated before certification.

    Endpoint path kept as /eval/ssdd-draft for client compatibility
    (invoice-review-service AiOrchestratorClient.draftSsdd); the `clause_id`
    response key is preserved so the caller can stash a doc reference. The
    prompt text is reworded to the post-award invoice-review summary.

    ⚠ Item 4 — no Pydantic response model.
    ⚠ Item 5 — third entry point; copy generated via legacy_chain when the
       upstream notification path requests payment-window copy generation.
       UPDATE (Item 5 / D1 CLOSED): legacy_chain.py is deleted — no legacy copy
       path remains. (Item 4 above is still open: raw dict, no response_model.)
    ⚠ Item 6 — no correlation-id forwarded.
    """
    log.info("eval/ssdd-draft topic=%r", req.topic)
    bedrock = invoke_model(
        f"Draft an invoice-review summary for: {req.topic}. "
        f"Constraints: {req.constraints or 'proper-invoice determination per FAR 32.905'}.",
        system="You draft invoice-review summaries (FAR 32.905); COR/CO reviews "
               "+ certifies for payment.",
    )
    # Provide a clause_id field so invoice-review-service can stash it.
    return {
        "ssdd_narrative": bedrock["body"],
        "clause_id": f"INVREV-{random.randint(1000, 9999)}",
        "hitl_gate": "co-certification-required",
        "model": BEDROCK_MODEL_ID,
    }


@app.post("/review-invoice")
def review_invoice(req: InvoiceReviewRequest) -> dict[str, Any]:
    """
    Single-agent invoice-review assistant (FAR 32.905 + prompt payment).

    Post-award: given an invoice + receiving-report reference, drafts a
    review summary (proper/improper determination, prompt-pay due date
    reminder, DCAA-flag callouts). Single-agent per domain-mapping.yml.

    ⚠ Item 4 — no Pydantic response model (raw dict; `clause_id` key kept).
    ⚠ Item 6 — no correlation-id forwarded.
    """
    log.info("review-invoice invoice_number=%r contract_number=%r",
             req.invoice_number, req.contract_number)
    bedrock = invoke_model(
        f"Review invoice {req.invoice_number} on contract {req.contract_number}. "
        f"Receiving report: {req.receiving_report_ref or '(unmatched)'}. "
        f"Line items / notes: {req.notes or '(none)'}.",
        system="You assist COR invoice review (FAR 32.905 proper-invoice checklist, "
               "5 CFR 1315 prompt payment). Flag missing required elements + "
               "cost-type DCAA concerns.",
    )
    return {
        "review_summary": bedrock["body"],
        "clause_id": "FAR-32.905",
        "hitl_gate": "cor-determination-required",
        "model": BEDROCK_MODEL_ID,
    }


@app.post("/validate-invoice")
def validate_invoice(req: InvoiceReviewRequest) -> dict[str, Any]:
    """
    FAR 32.905 proper-invoice required-elements check (deterministic stub).

    Returns which required elements are present/absent and the resulting
    proper/improper determination. No Bedrock call — pure checklist logic so
    the cohort can wire the real validation in W2.

    ⚠ Item 4 — no Pydantic response model.
    ⚠ Item 6 — no correlation-id forwarded.
    """
    log.info("validate-invoice invoice_number=%r", req.invoice_number)
    # FAR 32.905(b) required elements.
    required = [
        "contractor_name_address", "invoice_date", "contract_number",
        "description_of_supplies_services", "quantities_unit_prices",
        "shipping_payment_terms", "payee_name_address",
    ]
    provided = set(req.provided_elements or [])
    checks = {elem: (elem in provided) for elem in required}
    missing = [e for e, ok in checks.items() if not ok]
    proper = len(missing) == 0
    return {
        "invoice_number": req.invoice_number,
        "proper_invoice_checks": checks,
        "missing_elements": missing,
        "payment_status": "proper" if proper else "improper_returned",
        # FAR 32.905(b): improper invoices must be returned within 7 days.
        "return_deadline_days": None if proper else 7,
        "far_authority": "FAR 32.905",
    }


@app.post("/agent/intake-triage")
def agent_intake_triage(req: IntakeTriageRequest) -> dict[str, Any]:
    """
    Multi-agent W3 flow: triage an incoming modification request, route to the
    COR/CO, escalate anomalies (e.g. funding ceiling breach) to the CO.

    Sequential agent invocations (intake-classifier → reviewer-router →
    anomaly-escalator); each call is currently a single Bedrock invoke
    with the same stub fallback. LangGraph wiring comes in W3.

    ⚠ Item 4 — no Pydantic response model.
    ⚠ Item 6 — no correlation-id forwarded; each agent hop is invisible in
       the audit log because nothing threads a request id through.
    """
    log.info("agent/intake-triage proposal_id=%r", req.proposal_id)
    classify = invoke_model(
        f"Classify this modification request's type + funding impact: "
        f"{req.raw_text or req.proposal_id}",
        system="You classify post-award contract modifications (FAR Part 43) "
               "for COR/CO routing.",
    )
    route = invoke_model(
        f"Recommend the reviewer (COR or CO) for modification request "
        f"id={req.proposal_id}.",
        system="You route modifications by authority: admin/unilateral → COR, "
               "funding/bilateral → CO.",
    )
    anomaly = invoke_model(
        f"Flag anomalies in modification request id={req.proposal_id} that "
        f"warrant CO escalation (e.g. ceiling breach, scope outside contract).",
        system="You flag anomalies (funding ceiling, out-of-scope, authority).",
    )
    return {
        "proposal_id": req.proposal_id,
        "classification": classify["body"],
        "routing": route["body"],
        "anomalies": anomaly["body"],
        "escalation_required": "CO" if "anomaly" in anomaly["body"].lower() else None,
        "hitl_gate": "co-review-on-escalation",
        "model": BEDROCK_MODEL_ID,
    }


@app.post("/draft-contract-modification-v1")
def draft_contract_modification_v1(req: DraftRequest) -> dict[str, Any]:
    """
    v1.0 composed-Runnable example (Item 5).

    Demonstrates the prompt | llm | parser pattern the cohort migrates the
    legacy_chain.py to in W2. Still a stub — doesn't hit real Bedrock.

    UPDATE (Item 5 / D1 CLOSED): legacy_chain.py is already deleted; this v1.0
    example now stands on its own as the modern-pattern reference.
    """
    if not _LANGCHAIN_V1_AVAILABLE:
        raise HTTPException(503, "langchain v1.0 not available")

    # Composed-Runnable scaffolding — would be:
    #   prompt | bedrock_llm | StrOutputParser()
    # We just demonstrate the construction without invoking it.
    prompt = ChatPromptTemplate.from_messages([
        ("system", "You draft post-award contract-modification rationale (SF-30, FAR Part 43)."),
        ("user", "Draft the rationale for: {topic}. Constraints: {constraints}."),
    ])
    parser = StrOutputParser()
    _chain_scaffold = prompt | parser  # would normally be: prompt | llm | parser

    log.info("draft-contract_modification-v1 (composed Runnable scaffold) topic=%r",
             req.topic)

    return {
        "clause_id": f"FAR-43.{random.randint(1, 5)}-{random.randint(1, 30)}",
        "draft": f"[stub-v1] composed-runnable modification rationale about {req.topic}",
        "model": BEDROCK_MODEL_ID,
        "pattern": "prompt | llm | parser",
    }
