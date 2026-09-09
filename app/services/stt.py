"""Speech-to-text router — fast primary, grounded fallback.

Primary: Groq whisper-large-v3-turbo (~1 s, benchmarked 0.9–1.6 s vs
Gemini 3.9 s on the same clip) with a Rautahat domain-vocabulary prompt
so place names (Gaur, Bagmati, Lalbakaiya, Tikuliya…) transcribe
correctly — the prompt alone fixed "Gar Ward" -> "Gaur Ward" in testing.
Fallback: Gemini generative transcription when Groq is down/unkeyed.

Returns (transcript, engine, elapsed_ms) so callers can log real latency.
"""

from __future__ import annotations

import time

# Domain bias for Whisper: disaster + Rautahat vocabulary. Short on
# purpose — the prompt is a hint, not a transcript.
_DOMAIN_PROMPT = (
    "Gaur Ward, Rautahat district Nepal, Bagmati river, Lalbakaiya, "
    "Tikuliya Ghat, Garuda, Chandrapur, rescue boat dispatch, incident, "
    "trapped, water rising, shelter, team Bravo"
)

_MAX_AUDIO_BYTES = 8 * 1024 * 1024


def _groq_key() -> str:
    from app.config import settings

    return (settings.groq_api_key or "").strip()


async def _groq_transcribe(audio: bytes, filename: str) -> tuple[str, float]:
    from groq import AsyncGroq

    client = AsyncGroq(api_key=_groq_key(), timeout=60.0)
    t0 = time.time()
    out = await client.audio.transcriptions.create(
        file=(filename or "voice.webm", audio),
        model="whisper-large-v3-turbo",
        prompt=_DOMAIN_PROMPT,
        response_format="text",
        temperature=0.0,
    )
    text = out if isinstance(out, str) else (getattr(out, "text", "") or "")
    return text.strip(), (time.time() - t0) * 1000


async def transcribe(audio: bytes, mime: str, filename: str = "voice.webm") -> tuple[str, str, float]:
    """(transcript, engine, elapsed_ms). Raises on empty audio / no keys."""
    if not audio or len(audio) < 1024:
        raise ValueError("No audio captured — hold the mic longer")
    if len(audio) > _MAX_AUDIO_BYTES:
        raise ValueError("Audio too long (8 MB max)")

    errors: list[str] = []
    if _groq_key():
        try:
            text, ms = await _groq_transcribe(audio, filename)
            if text:
                return text, "groq-whisper", ms
            errors.append("groq: empty transcript")
        except Exception as exc:
            errors.append(f"groq: {exc!r}"[:160])

    # Fallback: Gemini generative transcription (slower, unhinted).
    import asyncio as _asyncio

    from app.services import gemini as _gemini

    try:
        t0 = time.time()
        text = await _asyncio.to_thread(
            _gemini.transcribe_audio, audio, mime or "audio/webm")
        if text:
            return text, "gemini", (time.time() - t0) * 1000
        errors.append("gemini: empty transcript")
    except Exception as exc:
        errors.append(f"gemini: {exc!r}"[:160])

    if not _groq_key():
        try:
            from app.services.gemini import GeminiNotConfiguredError

            raise GeminiNotConfiguredError(
                "Neither GROQ_API_KEY nor GEMINI_API_KEY set — voice disabled")
        except ImportError:
            pass
    raise RuntimeError("Transcription failed (" + " | ".join(errors) + ")")
