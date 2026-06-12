"""
nodes_retrieval.py — Person B: Block 14 grounded sub-pipeline (m3.md Steps 2.2-2.4,
ADR-0005 §4 — task B2).

retrieve_node wraps the ADR-0005 /retrieve read path (via retrieve_client);
confidence_check_node is an LLM-as-judge over the retrieved chunks (ADR-0005 §4
and task-split finding #7 — NOT a mean of retrieval scores); draft_node generates
the Block 14 rationale grounded ONLY in the retrieved clauses;
faithfulness_gate_node is a RAGAS-style LLM faithfulness judge (ADR-0005 §7).

Both judges gate at config.CONFIDENCE_THRESHOLD (0.85); below threshold — or on
any judge/retrieval failure — the run fails SOFT to the CO gate with the
matching *_AWAITING_CO_REVIEW status (never an uncaught exception; the graph
stays total, G2 grounded-or-withheld).

Model note: ADR-0004/0005 name Haiku for drafting/judging with Sonnet only on
confidence-fail rerank. The frozen bedrock_client exposes a single
BEDROCK_MODEL_ID (no per-call model selection), so model tiering is deferred to
a joint contract change; calls below use the configured model.
"""
from __future__ import annotations

import logging

from langgraph.graph import StateGraph
from pydantic import BaseModel, Field

from app import bedrock_client, config
from app.workflow import llm, retrieve_client
from app.workflow.state import WorkflowState

log = logging.getLogger("ai-orchestrator.workflow.retrieval")


class ChunkScores(BaseModel):
    """Per-chunk LLM-as-judge relevance scores, index-aligned with the input."""

    scores: list[float] = Field(description="One 0-1 score per chunk, in order")


class FaithfulnessVerdict(BaseModel):
    """RAGAS-style faithfulness score: are the draft's claims supported?"""

    score: float = Field(ge=0.0, le=1.0)
    unsupported_claims: list[str] = Field(default_factory=list)


_JUDGE_SYSTEM = (
    "You are a retrieval-relevance judge (ADR-0005 §4). Score EACH provided "
    "chunk 0-1 for how well it grounds the stated change request. Return ONLY "
    'a JSON object: {"scores": [..]} with exactly one score per chunk, in order.'
)

_DRAFT_SYSTEM = (
    "You draft FAR Part 43-compliant SF-30 Block 14 modification rationale, "
    "grounded ONLY in the provided clauses. If the clauses do not support the "
    "change, say so rather than inventing support."
)

_FAITHFULNESS_SYSTEM = (
    "You are a faithfulness judge (RAGAS-style, ADR-0005 §7). Score 0-1 how "
    "fully every claim in the draft is supported by the provided clauses; list "
    "unsupported claims. Return ONLY a JSON object: "
    '{"score": <0-1>, "unsupported_claims": [..]}.'
)


def retrieve_node(state: WorkflowState) -> dict:
    """Hybrid retrieval for the Block 14 rationale (ADR-0005 /retrieve).

    Failure -> empty chunks + RAG_FAILED_AWAITING_CO_REVIEW (fail soft to gate).
    """
    change = state.get("change_request") or {}
    agency_id, user_id, role = retrieve_client.identity_for(state)

    try:
        chunks = retrieve_client.retrieve(
            str(change.get("scope", "")),
            sf30_block="14",
            agency_id=agency_id,
            user_id=user_id,
            role=role,
            correlation_id=state.get("correlation_id"),
            contract_id=state.get("contract_number"),
        )
    except (retrieve_client.RetrievalUnavailable, ValueError) as exc:
        log.warning("Block 14 retrieval unavailable — failing to CO review: %s", exc)
        return {
            "retrieved_chunks": [],
            "confidence": 0.0,
            "gate_status": "RAG_FAILED_AWAITING_CO_REVIEW",
        }

    return {"retrieved_chunks": chunks}


def confidence_check_node(state: WorkflowState) -> dict:
    """LLM-as-judge retrieval confidence (ADR-0005 §4; finding #7 — NOT a mean).

    Scores each chunk 0-1, aggregates, and gates at CONFIDENCE_THRESHOLD.
    Fewer than MIN_RETRIEVED_CHUNKS (§10), a judge failure, or a malformed
    judge response all count as confidence failures (fail closed to the gate).
    """
    if state.get("gate_status") == "RAG_FAILED_AWAITING_CO_REVIEW":
        return {}  # retrieval already failed soft — keep the status

    chunks = state.get("retrieved_chunks") or []
    if len(chunks) < config.MIN_RETRIEVED_CHUNKS:
        log.warning(
            "partial retrieval — %d < MIN_RETRIEVED_CHUNKS=%d",
            len(chunks), config.MIN_RETRIEVED_CHUNKS,
        )
        return {"confidence": 0.0, "gate_status": "RAG_FAILED_AWAITING_CO_REVIEW"}

    change = state.get("change_request") or {}
    numbered = "\n\n".join(
        f"[chunk {i}] {c.get('chunk_text', '')}" for i, c in enumerate(chunks)
    )
    prompt = (
        f"Change request: {change.get('scope', '')}\n\n"
        f"Chunks ({len(chunks)}):\n{numbered}"
    )

    try:
        result = llm.call_json(prompt, schema=ChunkScores, system=_JUDGE_SYSTEM)
        scores = result.data.scores
        if len(scores) != len(chunks) or not all(0.0 <= s <= 1.0 for s in scores):
            raise llm.LLMOutputError(
                f"judge returned {len(scores)} scores for {len(chunks)} chunks"
            )
    except llm.LLMOutputError as exc:
        log.warning("confidence judge failed — failing to CO review: %s", exc)
        return {"confidence": 0.0, "gate_status": "RAG_FAILED_AWAITING_CO_REVIEW"}

    confidence = sum(scores) / len(scores)
    if confidence >= config.CONFIDENCE_THRESHOLD:
        return {"confidence": confidence, "gate_status": "OK"}
    return {"confidence": confidence, "gate_status": "RAG_FAILED_AWAITING_CO_REVIEW"}


def route_after_confidence(state: WorkflowState) -> str:
    """Pass -> draft the rationale. Fail -> jump to the CO gate."""
    if state.get("gate_status") == "OK":
        return "draft"
    return "co_gate"


def draft_node(state: WorkflowState) -> dict:
    """Block 14: draft the rationale, grounded in the retrieved clauses."""
    chunks = state.get("retrieved_chunks") or []
    grounding = "\n\n".join(c.get("chunk_text", "") for c in chunks)
    answer = bedrock_client.invoke_model(
        f"Change: {state.get('change_request')}\n"
        f"Grounding clauses:\n{grounding}\n\n"
        f"Draft the SF-30 Block 14 modification rationale.",
        system=_DRAFT_SYSTEM,
    )
    return {"block_14_draft": answer["body"]}


def faithfulness_gate_node(state: WorkflowState) -> dict:
    """RAGAS-style faithfulness judge (ADR-0005 §7); < threshold -> CO review.

    A judge failure (stub Bedrock, malformed output) is a faithfulness failure —
    an unverifiable draft is never submitted onward (fail closed to the gate).
    """
    chunks = state.get("retrieved_chunks") or []
    grounding = "\n\n".join(c.get("chunk_text", "") for c in chunks)
    prompt = (
        f"Draft:\n{state.get('block_14_draft', '')}\n\n"
        f"Clauses:\n{grounding}"
    )

    try:
        result = llm.call_json(
            prompt, schema=FaithfulnessVerdict, system=_FAITHFULNESS_SYSTEM
        )
    except llm.LLMOutputError as exc:
        log.warning("faithfulness judge failed — failing to CO review: %s", exc)
        return {"gate_status": "FAITHFULNESS_FAILED_AWAITING_CO_REVIEW"}

    if result.data.score >= config.CONFIDENCE_THRESHOLD:
        return {"gate_status": "OK"}
    log.info(
        "faithfulness %0.2f below threshold; unsupported: %s",
        result.data.score, result.data.unsupported_claims,
    )
    return {"gate_status": "FAITHFULNESS_FAILED_AWAITING_CO_REVIEW"}


def route_after_faithfulness(state: WorkflowState) -> str:
    """Pass -> assemble the form. Fail -> jump to the CO gate."""
    if state.get("gate_status") == "OK":
        return "assemble"
    return "co_gate"


def register(builder: StateGraph) -> None:
    """Add the Block 14 nodes + conditional routes + the bridge to form-fill.

    Replaces the Foundation's linear confidence -> draft and faithfulness ->
    assemble stub edges with the m3.md Step 2.3/2.4 conditional routes (B2 owns
    these edges; "co_gate" and "assemble" are referenced by name — Person A owns
    those nodes).
    """
    builder.add_node("retrieve", retrieve_node)
    builder.add_node("confidence", confidence_check_node)
    builder.add_node("draft", draft_node)
    builder.add_node("faithfulness", faithfulness_gate_node)

    builder.add_edge("retrieve", "confidence")
    builder.add_conditional_edges(
        "confidence", route_after_confidence, {"draft": "draft", "co_gate": "co_gate"}
    )
    builder.add_edge("draft", "faithfulness")
    builder.add_conditional_edges(
        "faithfulness",
        route_after_faithfulness,
        {"assemble": "assemble", "co_gate": "co_gate"},
    )
