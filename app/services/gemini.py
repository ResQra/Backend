"""Gemini ears/mouth/eyes — Phase 6, REST via httpx (zero new deps).

- describe_image: what is visible (flood cues, landmarks, damage).
- transcribe_audio: speech-to-text for voice messages.
- synthesize_speech: agent reply -> WAV audio bytes.
Empty GEMINI_API_KEY -> GeminiNotConfiguredError -> endpoints answer 503
honestly. Text reasoning stays on Groq; nothing here is on that path.
"""

from __future__ import annotations

import base64

import httpx

from app.config import settings

_API = "https://generativelanguage.googleapis.com/v1beta/models"
_TIMEOUT = 30.0
_MAX_IMAGE_BYTES = 4 * 1024 * 1024
_MAX_AUDIO_BYTES = 8 * 1024 * 1024

# Transient transport failures (large audio posts over TLS reset mid-read,
# e.g. SSL UNEXPECTED_EOF_WHILE_READING) are retried, never surfaced raw.
_RETRYABLE = ()
try:
    import ssl as _ssl

    _RETRYABLE = (_ssl.SSLError,)
except Exception:
    pass
_RETRYABLE = _RETRYABLE + (httpx.TransportError,)
_MAX_ATTEMPTS = 3


class GeminiNotConfiguredError(RuntimeError):
    pass


def _key() -> str:
    if not settings.gemini_api_key:
        raise GeminiNotConfiguredError(
            "GEMINI_API_KEY not set in backend/.env — voice/image features disabled")
    return settings.gemini_api_key


def _post(model: str, payload: dict, timeout: float = _TIMEOUT) -> dict:
    """POST with retries on transient transport failures.

    Big audio posts occasionally die mid-TLS-read (SSL
    UNEXPECTED_EOF_WHILE_READING); a fresh connection almost always
    succeeds, so retry before failing the voice turn.
    """
    import logging as _logging
    import time as _time

    last: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            with httpx.Client(timeout=timeout) as client:
                r = client.post(f"{_API}/{model}:generateContent",
                                params={"key": _key()}, json=payload)
                r.raise_for_status()
                return r.json()
        except _RETRYABLE as exc:
            last = exc
            _logging.getLogger("resqra.voice").warning(
                "gemini POST attempt %d/%d transient failure: %r",
                attempt, _MAX_ATTEMPTS, exc)
            _time.sleep(min(2 ** (attempt - 1), 4))
        except httpx.HTTPStatusError:
            raise
    assert last is not None
    raise last


def _text_of(data: dict) -> str:
    try:
        parts = data["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts).strip()
    except (KeyError, IndexError, TypeError):
        return ""


def describe_image(image: bytes, mime: str, hint: str = "") -> str:
    """What is visible, biased to operational detail. Raises on failure."""
    if len(image) > _MAX_IMAGE_BYTES:
        raise ValueError("Image too large (4 MB max)")
    prompt = (
        "Describe this photo for flood-disaster coordination in 4-6 sentences: "
        "visible water (depth cues, flow), damage, people/vehicles needing help, "
        "readable landmarks/signs for location, passable vs blocked paths. "
        "Be concrete, no speculation beyond the pixels."
        + (f" Coordinator note: {hint}" if hint.strip() else ""))
    data = _post(settings.gemini_model, {
        "contents": [{"parts": [
            {"text": prompt},
            {"inline_data": {"mime_type": mime or "image/jpeg",
                             "data": base64.b64encode(image).decode()}}]}]},
        timeout=60.0)
    text = _text_of(data)
    if not text:
        raise RuntimeError("Gemini returned no description")
    return text


def transcribe_audio(audio: bytes, mime: str) -> str:
    """Speech -> text for voice messages. Raises on failure."""
    if len(audio) > _MAX_AUDIO_BYTES:
        raise ValueError("Audio too long (8 MB max)")
    data = _post(settings.gemini_model, {
        "contents": [{"parts": [
            {"text": "Transcribe this speech exactly, in its original language. "
                     "Return only the transcript, no commentary."},
            {"inline_data": {"mime_type": mime or "audio/webm",
                             "data": base64.b64encode(audio).decode()}}]}]},
        timeout=90.0)
    text = _text_of(data)
    if not text:
        raise RuntimeError("Gemini returned no transcript")
    return text


def synthesize_speech(text: str) -> tuple[bytes, str]:
    """Agent reply -> (wav_bytes, mime). Raises on failure."""
    clipped = text.replace("\n", " ").strip()[:800]
    if not clipped:
        raise ValueError("Nothing to speak")
    data = _post(settings.gemini_tts_model, {
        "contents": [{"parts": [{"text": f"Say clearly, calmly: {clipped}"}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {
                "voiceName": settings.gemini_tts_voice}}}}})
    try:
        parts = data["candidates"][0]["content"]["parts"]
        blob = next(p["inlineData"] for p in parts if "inlineData" in p)
        pcm = base64.b64decode(blob["data"])
    except (KeyError, IndexError, TypeError, ValueError):
        raise RuntimeError("Gemini returned no audio")
    # Gemini returns raw 16-bit PCM (no container); browsers/<audio> need
    # WAV, so wrap a header. Rate parsed from the mime, default 24000 Hz.
    import io
    import re
    import wave

    rate = 24000
    m = re.search(r"rate=(\d+)", blob.get("mimeType", ""))
    if m:
        rate = int(m.group(1))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm)
    return buf.getvalue(), "audio/wav"
