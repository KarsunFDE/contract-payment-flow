"""
llm_chain.py — LangChain Runnable drafting path for the UI AI-draft buttons.

Unlike app/bedrock_client.py (raw boto3 InvokeModel, not a Runnable), this builds a
`prompt | ChatBedrock | StrOutputParser` LCEL chain and invokes it. A LangChain
Runnable invocation is traced by LangSmith automatically when LANGSMITH_TRACING +
LANGSMITH_API_KEY are set in the environment — no decorator needed.

Fail-safe: if Bedrock credentials don't resolve, ChatBedrock.invoke raises; the caller
catches LLMUnavailable and falls back to a deterministic stub so the UI still works on
a credential-less laptop.
"""
from __future__ import annotations

import logging
import os

from langchain_aws import ChatBedrock
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from app.bedrock_client import AWS_REGION, BEDROCK_MODEL_ID

log = logging.getLogger("ai-orchestrator.llm_chain")


class LLMUnavailable(RuntimeError):
    """Raised when the real Bedrock model can't be reached (no creds / API error)."""


_llm = None


def _get_llm() -> ChatBedrock:
    global _llm
    if _llm is None:
        _llm = ChatBedrock(
            model_id=BEDROCK_MODEL_ID,
            region_name=AWS_REGION,
            model_kwargs={"temperature": 0.2, "max_tokens": 1024},
        )
    return _llm


def tracing_active() -> bool:
    """True when LangSmith tracing is both requested and credentialed."""
    flag = os.environ.get("LANGSMITH_TRACING") or os.environ.get("LANGCHAIN_TRACING_V2")
    has_key = bool(os.environ.get("LANGSMITH_API_KEY") or os.environ.get("LANGCHAIN_API_KEY"))
    return str(flag).lower() == "true" and has_key


def draft(system: str, human: str, variables: dict) -> str:
    """Invoke `prompt | ChatBedrock | parser` and return the model text.

    The invocation is a LangChain Runnable, so LangSmith traces it automatically
    when tracing is enabled. Raises LLMUnavailable on any model/credential error.
    """
    prompt = ChatPromptTemplate.from_messages([("system", system), ("human", human)])
    chain = prompt | _get_llm() | StrOutputParser()
    try:
        return chain.invoke(variables)
    except Exception as exc:  # boto/cred/model errors — fail to stub at the caller
        raise LLMUnavailable(str(exc)) from exc
