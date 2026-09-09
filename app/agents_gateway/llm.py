"""Thin LLM client — the only place the backend talks to a text LLM.

Default: Groq (fast, cheap). Optional: Amazon Bedrock Converse when
BEDROCK_TEXT_MODEL + real AWS creds are set (hackathon-aligned fallback).
Voice always stays on Gemini Live (duplex audio); the text provider does
not change voice latency. Callers keep one contract: messages in, text out.
"""

import asyncio
from functools import lru_cache

from groq import AsyncGroq

from app.config import settings


class LLMNotConfiguredError(RuntimeError):
    pass


_PLACEHOLDER_CREDS = {"", "test", "undefined", "changeme", "xxx"}


def _bedrock_active() -> bool:
    """True only when a model id AND plausible-real creds are configured."""
    if not (settings.bedrock_text_model or "").strip():
        return False
    key = (settings.aws_access_key_id or "").strip().lower()
    secret = (settings.aws_secret_access_key or "").strip().lower()
    return key not in _PLACEHOLDER_CREDS and secret not in _PLACEHOLDER_CREDS


def _bedrock_complete(messages: list[dict], temperature: float,
                      json_mode: bool) -> str:
    """Synchronous Bedrock Converse call (runs in a worker thread)."""
    import boto3

    client = boto3.client(
        "bedrock-runtime",
        region_name=settings.bedrock_region or "us-east-1",
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )
    system, convo = [], []
    for m in messages:
        role, content = m.get("role"), str(m.get("content", ""))
        if role == "system":
            system.append({"text": content})
        else:
            convo.append({"role": "assistant" if role == "assistant" else "user",
                          "content": [{"text": content}]})
    kwargs: dict = {"temperature": temperature}
    if json_mode:
        kwargs["responseFormat"] = {"json": {}}
    resp = client.converse(
        modelId=settings.bedrock_text_model.strip(),
        messages=convo,
        system=system or None,
        inferenceConfig=kwargs,
    )
    return "".join(
        b.get("text", "") for b in (resp.get("output") or {}).get("message", {}).get("content", [])
    ).strip()


@lru_cache(maxsize=1)
def _client() -> AsyncGroq:
    if not settings.groq_api_key:
        raise LLMNotConfiguredError("GROQ_API_KEY not set in backend/.env")
    # Tight transport budget: the chamber makes many calls and carries its
    # own deadline — a single stalled call must never wedge a worker.
    return AsyncGroq(api_key=settings.groq_api_key, timeout=25.0, max_retries=1)


async def chat_completion(
    messages: list[dict],
    *,
    temperature: float = 0.4,
    json_mode: bool = False,
) -> str:
    """messages: [{"role": "system"|"user"|"assistant", "content": str}]"""
    if _bedrock_active():
        return await asyncio.to_thread(
            _bedrock_complete, messages, temperature, json_mode)
    kwargs = {}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = await _client().chat.completions.create(
        model=settings.groq_model,
        messages=messages,
        temperature=temperature,
        **kwargs,
    )
    return resp.choices[0].message.content or ""


async def chat_with_tools(messages: list[dict], tools: list[dict],
                          *, temperature: float = 0.5):
    """Function-calling loop primitive. Returns the raw assistant message
    (has .content and possibly .tool_calls). Tools use OpenAI schema.
    Always Groq: the debate chamber needs OpenAI-style tool_calls, which
    the Bedrock text path does not emulate."""
    resp = await _client().chat.completions.create(
        model=settings.groq_model,
        messages=messages,
        temperature=temperature,
        tools=tools,
        tool_choice="auto",
    )
    return resp.choices[0].message
