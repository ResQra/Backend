"""Thin Groq client — the only place the backend talks to an LLM.

Swap point for models: GROQ_MODEL env var (Groq is OpenAI-compatible;
moving to Bedrock Nova Lite at deploy time means changing this module only).
"""

from functools import lru_cache

from groq import AsyncGroq

from app.config import settings


class LLMNotConfiguredError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _client() -> AsyncGroq:
    if not settings.groq_api_key:
        raise LLMNotConfiguredError("GROQ_API_KEY not set in backend/.env")
    return AsyncGroq(api_key=settings.groq_api_key)


async def chat_completion(
    messages: list[dict],
    *,
    temperature: float = 0.4,
    json_mode: bool = False,
) -> str:
    """messages: [{"role": "system"|"user"|"assistant", "content": str}]"""
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
