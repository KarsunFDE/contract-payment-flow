"""
llm.py — structured-output wrapper over bedrock_client.invoke_model.

bedrock_client returns raw text with no JSON parsing and no model-version field;
this wrapper adds Pydantic-validated JSON parsing for the workflow's classifier /
adjudicator nodes (m3.md Steps 2.1, 7.2) and exposes the model version for
provenance (Issue 4).

NOTE: this is ADDITIVE workflow code. It does NOT modify the debt-locked endpoints
in main.py (Item 4 — missing structured-output validation stays as the cohort's
W1 exercise). The new agent graph simply does its own validation in this module.

Stub-safe: when AWS credentials are absent, bedrock_client returns a non-JSON stub
({"stub": True, "body": "[stub] ..."}). `call_json` surfaces that as a typed
`LLMOutputError` the caller handles (e.g. route to CO review) rather than crashing
the graph in local dev.
"""
from __future__ import annotations

import json
import re
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app import bedrock_client

T = TypeVar("T", bound=BaseModel)

# Bedrock model ids look like "anthropic.claude-3-7-sonnet-20250219-v1:0".
# The trailing "-vN[:N]" is the model version we record for provenance.
_VERSION_RE = re.compile(r"-(v\d+(?::\d+)?)$")


class LLMOutputError(ValueError):
    """Raised when the model response is not valid JSON for the target schema
    (or is a credentials-absent stub). Callers fail closed -> CO review."""


class JsonResult:
    """A validated JSON result plus provenance (model id + version) for the audit
    trail. `data` is an instance of the schema passed to `call_json`.

    `stub` records whether the underlying Bedrock response was a credentials-absent
    stub. `call_json` fails closed on a stub, so a real result carries stub=False;
    the flag is provenance callers and tests can inspect."""

    def __init__(self, data: BaseModel, model: str, model_version: str,
                 stub: bool = False):
        self.data = data
        self.model = model
        self.model_version = model_version
        self.stub = stub


def _strip_fences(text: str) -> str:
    """Strip a markdown code fence (``` or ```json) wrapping the model output.

    Claude often fences its JSON; json.loads chokes on the backticks. Unfenced
    text is returned unchanged."""
    stripped = text.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        first_newline = stripped.find("\n")
        if first_newline != -1:
            return stripped[first_newline + 1 : -3].strip()
    return text


def model_version(model_id: str) -> str:
    """Extract the version tag from a Bedrock model id, for provenance.

    "anthropic.claude-3-7-sonnet-20250219-v1:0" -> "v1:0".
    An unrecognized shape -> "unknown" (never guess a version into the audit log).
    """
    match = _VERSION_RE.search(model_id)
    return match.group(1) if match else "unknown"


def call_json(
    prompt: str,
    *,
    schema: type[T],
    system: str | None = None,
    max_tokens: int = 1024,
    temperature: float = 0.2,
) -> JsonResult:
    """Invoke Claude via Bedrock, parse the body as JSON, validate against `schema`.

    Returns a JsonResult(data=<schema instance>, model, model_version).
    Raises LLMOutputError if the response is a stub or not schema-valid JSON.
    """
    answer = bedrock_client.invoke_model(
        prompt, system=system, max_tokens=max_tokens, temperature=temperature,
    )

    # Credentials-absent stub returns "[stub] ..." text — not JSON. Fail closed.
    if answer.get("stub"):
        raise LLMOutputError(
            "bedrock stub response (no AWS credentials) — cannot parse structured output"
        )

    try:
        payload = json.loads(_strip_fences(answer["body"]))
        data = schema.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise LLMOutputError(
            f"model output failed {schema.__name__} validation: {exc}"
        ) from exc

    model = answer.get("model", "")
    return JsonResult(data=data, model=model, model_version=model_version(model),
                      stub=bool(answer.get("stub", False)))
