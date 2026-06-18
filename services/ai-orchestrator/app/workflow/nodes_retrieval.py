"""
nodes_retrieval.py — Block 14 grounded sub-pipeline (m3.md Steps 2.2-2.4,
ADR-0005 §4).

retrieve_node runs the ADR-0005 read path; confidence_check_node is a Haiku
LLM-as-judge (scores each chunk 0-1, aggregates, ADR-0005 §4 — NOT a mean of
similarity scores); draft_node generates the Block 14 rationale grounded in the
retrieved clauses; faithfulness_gate_node runs an LLM faithfulness judge over the
draft. Both quality gates fail closed: below CONFIDENCE_THRESHOLD (or on any
LLM/retrieval error) the package routes to the CO instead of dead-ending.
"""
from __future__ import annotations

import logging

from langgraph.graph import StateGraph
from pydantic import BaseModel, Field

from app import bedrock_client, config
from app.workflow import retrieve_client
from app.workflow.audit_events import record_event
from app.workflow.llm import call_json, LLMOutputError
from app.workflow.nodes_lookup import is_blocking
from app.workflow.state import WorkflowState

log = logging.getLogger("ai-orchestrator.workflow.retrieval")


class ChunkRelevanceScores(BaseModel):
    """Per-chunk relevance scores from the Haiku judge (ADR-0005 §4)."""

    scores: list[float] = Field(description="One 0-1 relevance score per chunk, in order")


class FaithfulnessScore(BaseModel):
    """Single 0-1 faithfulness score: is the draft fully supported by the clauses?"""

    score: float = Field(ge=0.0, le=1.0)


def retrieve_node(state: WorkflowState) -> dict:
    """Hybrid retrieval for the Block 14 rationale (ADR-0005 /retrieve), Step 2.2.

    On a read-path failure, return no chunks and flag CO review — the downstream
    confidence gate then routes to the CO (fail-closed).
    """
    change = state["change_request"]
    try:
        chunks = retrieve_client.retrieve_for_state(state, change["scope"], sf30_block="14")
    except retrieve_client.RetrieveError as exc:
        log.warning("retrieve failed (%s) — flagging CO review. correlation_id=%s",
                    exc, state.get("correlation_id"))
        return {"retrieved_chunks": [], "gate_status": "RAG_FAILED_AWAITING_CO_REVIEW"}

    return {"retrieved_chunks": chunks}


def confidence_check_node(state: WorkflowState) -> dict:
    """Haiku LLM-as-judge scores each retrieved chunk; aggregate < threshold escalates.

    ADR-0005 §4: the judge rates each chunk 0-1 for relevance and we aggregate
    (mean) — this is NOT a mean of retrieval similarity scores.

    Routing (ADR-0006 "Sonnet fallback only on confidence-fail"):
      - aggregate >= threshold       -> draft with Haiku (tier "haiku")
      - chunks present, aggregate <  -> draft with Sonnet (tier "sonnet") — escalate
                                        the MODEL, faithfulness_gate is the arbiter
      - no chunks / judge error      -> CO review (Sonnet cannot fix zero grounding)

    Blocking statuses are sticky: if an earlier node already set a blocking
    gate_status, this node does NOT overwrite it with "OK".
    """
    # Sticky-blocking guard: honour a prior failing gate from retrieve_node.
    if is_blocking(state.get("gate_status")):
        return {}

    chunks = state.get("retrieved_chunks") or []
    if not chunks:
        return {"confidence": 0.0, "gate_status": "RAG_FAILED_AWAITING_CO_REVIEW"}

    # DEV/DEMO: change_request.force_low_confidence forces the Sonnet-escalation path
    # deterministically (skips the judge call), so the fallback can be shown on stage.
    if state.get("change_request", {}).get("force_low_confidence"):
        log.info("force_low_confidence set (dev/demo) — escalating draft to Sonnet. "
                 "correlation_id=%s", state.get("correlation_id"))
        record_event(state, "confidence_escalation",
                     {"confidence": 0.0, "tier": "sonnet", "forced": True})
        return {"confidence": 0.0, "draft_model_tier": "sonnet", "gate_status": "OK"}

    try:
        result = call_json(
            prompt=f"Query: {state['change_request']['scope']}\n"
                   f"Chunks (in order): {[c.get('chunk_text') for c in chunks]}\n"
                   f"Score each chunk 0-1 for how well it supports drafting the "
                   f"SF-30 Block 14 rationale. Return JSON: scores (list of floats).",
            system="You are a retrieval-relevance judge. Score each chunk "
                   "independently 0 (irrelevant) to 1 (directly on point).",
            schema=ChunkRelevanceScores,
        )
    except LLMOutputError as exc:
        log.warning("confidence judge failed (%s) — flagging CO review. correlation_id=%s",
                    exc, state.get("correlation_id"))
        return {"confidence": 0.0, "gate_status": "RAG_FAILED_AWAITING_CO_REVIEW"}

    scores = result.data.scores
    # The judge must return exactly one score per chunk, in the same order. If the
    # counts don't match we can't tell which score belongs to which chunk, so an
    # average would be meaningless — fail closed to CO review instead of trusting a
    # misaligned list (this also covers the judge returning an empty score list).
    if len(scores) != len(chunks):
        log.warning("confidence judge returned %d scores for %d chunks — flagging "
                    "CO review. correlation_id=%s",
                    len(scores), len(chunks), state.get("correlation_id"))
        return {"confidence": 0.0, "gate_status": "RAG_FAILED_AWAITING_CO_REVIEW"}
    aggregate = sum(scores) / len(scores)

    if aggregate >= config.CONFIDENCE_THRESHOLD:
        return {"confidence": aggregate, "draft_model_tier": "haiku", "gate_status": "OK"}

    # Confidence-fail WITH chunks: escalate the draft model to Sonnet rather than
    # routing straight to the CO (ADR-0006). faithfulness_gate still gates the result.
    log.info("confidence %.3f < %.2f — escalating draft to Sonnet. correlation_id=%s",
             aggregate, config.CONFIDENCE_THRESHOLD, state.get("correlation_id"))
    record_event(state, "confidence_escalation",
                 {"confidence": aggregate, "tier": "sonnet", "forced": False})
    return {"confidence": aggregate, "draft_model_tier": "sonnet", "gate_status": "OK"}


def route_after_confidence(state: WorkflowState) -> str:
    """Pass -> draft the rationale. Fail -> jump to the CO gate (Step 2.3)."""
    if state.get("gate_status") == "OK":
        return "draft"
    return "co_gate"


def draft_node(state: WorkflowState) -> dict:
    """Block 14: draft the rationale grounded only in the retrieved clauses (Step 2.4).

    Uses bedrock_client directly (free text, not JSON). The credentials-absent stub
    returns placeholder text, which is acceptable as a dev-mode draft body.

    Model tier comes from confidence_check (ADR-0006): Haiku by default, Sonnet when
    confidence failed. `draft_model` records the id actually used (visible in audit).
    """
    tier = state.get("draft_model_tier", "haiku")
    model_id = (bedrock_client.BEDROCK_FALLBACK_MODEL_ID if tier == "sonnet"
                else bedrock_client.BEDROCK_MODEL_ID)
    answer = bedrock_client.invoke_model(
        prompt=f"Change: {state['change_request']}\n"
               f"Grounding clauses: {state.get('retrieved_chunks')}\n"
               f"Draft the SF-30 Block 14 modification rationale.",
        system="You draft FAR Part 43-compliant SF-30 rationale, grounded ONLY in "
               "the provided clauses. Do not introduce facts absent from them.",
        model_id=model_id,
    )
    return {"block_14_draft": answer["body"], "draft_model": answer["model"]}


def faithfulness_gate_node(state: WorkflowState) -> dict:
    """Faithfulness judge over the draft (Step 2.4). Below threshold -> CO review.

    Checks the draft is fully supported by the retrieved clauses (no fabrication).
    A judge error fails closed to CO review.

    Blocking statuses are sticky: if an earlier node (e.g. retrieve, confidence)
    already set a blocking gate_status, this node does NOT overwrite it with "OK".
    """
    # Sticky-blocking guard: a prior failing gate must not be silently cleared.
    if is_blocking(state.get("gate_status")):
        return {}

    try:
        result = call_json(
            prompt=f"Clauses: {[c.get('chunk_text') for c in state.get('retrieved_chunks') or []]}\n"
                   f"Draft: {state.get('block_14_draft')}\n"
                   f"Return JSON: score (0-1) for how fully the draft is supported "
                   f"by the clauses, with no unsupported claims.",
            system="You are a faithfulness judge. Score 1 only if every claim in the "
                   "draft is grounded in the clauses; lower it for any unsupported claim.",
            schema=FaithfulnessScore,
        )
    except LLMOutputError as exc:
        log.warning("faithfulness judge failed (%s) — flagging CO review. correlation_id=%s",
                    exc, state.get("correlation_id"))
        return {"gate_status": "FAITHFULNESS_FAILED_AWAITING_CO_REVIEW"}

    if result.data.score >= config.CONFIDENCE_THRESHOLD:
        return {"gate_status": "OK"}
    return {"gate_status": "FAITHFULNESS_FAILED_AWAITING_CO_REVIEW"}


def route_after_faithfulness(state: WorkflowState) -> str:
    """Pass -> assemble the form. Fail -> jump to the CO gate (same shape as 2.3)."""
    if state.get("gate_status") == "OK":
        return "assemble"
    return "co_gate"


def register(builder: StateGraph) -> None:
    """Add the Block 14 nodes + conditional routes to the form-fill / CO-gate seams.

    confidence and faithfulness are both fail-closed branch points: a failing gate
    routes to "co_gate" (Person A owns that node) instead of continuing.
    """
    builder.add_node("retrieve", retrieve_node)
    builder.add_node("confidence", confidence_check_node)
    builder.add_node("draft", draft_node)
    builder.add_node("faithfulness", faithfulness_gate_node)

    builder.add_edge("retrieve", "confidence")
    builder.add_conditional_edges("confidence", route_after_confidence,
                                  {"draft": "draft", "co_gate": "co_gate"})
    builder.add_edge("draft", "faithfulness")
    builder.add_conditional_edges("faithfulness", route_after_faithfulness,
                                  {"assemble": "assemble", "co_gate": "co_gate"})
