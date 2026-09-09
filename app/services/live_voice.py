"""Gemini Live bidirectional voice client — the duplex engine behind the
coordinator's live conversation (Gemini-Live / Advanced-Voice grade:
simultaneous listen+talk, server-side interruption).

Browser --PCM16k--> backend WS --Live API--> Gemini --PCM24k--> backend WS
--> browser. The API key never leaves the server; the browser only ever
talks to us. No new dependencies: `websockets` ships with uvicorn[standard].

Wire format is JSON text throughout; audio payloads are base64 PCM.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging

import websockets

from app.config import settings

logger = logging.getLogger("resqra.live")

_LIVE_WS = ("wss://generativelanguage.googleapis.com/ws/google.ai."
            "generativelanguage.v1beta.GenerativeService.BidiGenerateContent")

# Preferred model first, then known-good fallbacks. Google retires preview
# model IDs without ceremony; a sunset must degrade, never 500 the orb.
_FALLBACK_MODELS = [
    "gemini-2.5-flash-native-audio-preview-12-2025",
    "gemini-3.1-flash-live-preview",
]

_SETUP_TIMEOUT_S = 25.0


class LiveNotConfiguredError(RuntimeError):
    pass


class LiveSetupError(RuntimeError):
    pass


def candidate_models() -> list[str]:
    models = [settings.gemini_live_model, *_FALLBACK_MODELS]
    seen: list[str] = []
    for m in models:
        m = (m or "").strip()
        if m and m not in seen:
            seen.append(m)
    return seen


def _setup_payload(model: str, system_text: str) -> dict:
    return {
        "setup": {
            "model": f"models/{model}",
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {
                            "voiceName": settings.gemini_tts_voice or "Kore"
                        }
                    }
                },
            },
            "systemInstruction": {"parts": [{"text": system_text}]},
            "inputAudioTranscription": {},
            "outputAudioTranscription": {},
        }
    }


async def open_session(system_text: str):
    """Connect to Gemini Live, trying each candidate model in order.

    Returns (websocket, model_used). Raises LiveNotConfiguredError when no
    key, LiveSetupError when every model refuses setup (message included).
    """
    if not settings.gemini_api_key:
        raise LiveNotConfiguredError(
            "GEMINI_API_KEY not set in backend/.env — live voice disabled")
    attempts: list[str] = []
    for model in candidate_models():
        url = f"{_LIVE_WS}?key={settings.gemini_api_key}"
        try:
            ws = await websockets.connect(url, max_size=8 * 1024 * 1024)
        except Exception as exc:
            attempts.append(f"{model}: connect failed: {exc}")
            logger.warning("live %s", attempts[-1])
            continue
        try:
            await ws.send(json.dumps(_setup_payload(model, system_text)))
            raw = await asyncio.wait_for(ws.recv(), timeout=_SETUP_TIMEOUT_S)
            msg = json.loads(raw)
            if "setupComplete" in msg:
                logger.info("live session up on %s", model)
                return ws, model
            attempts.append(f"{model}: setup refused: {str(msg)[:220]}")
            logger.warning("live %s", attempts[-1])
        except Exception as exc:  # timeout / reset / bad JSON
            attempts.append(f"{model}: setup failed: {exc}")
            logger.warning("live %s", attempts[-1])
        try:
            await ws.close()
        except Exception:
            pass
    raise LiveSetupError("Gemini Live unavailable — "
                         + " | ".join(attempts or ["no candidate models"]))


def audio_message(pcm16k: bytes) -> str:
    """Browser PCM16k chunk -> Live realtimeInput frame."""
    return json.dumps({
        "realtimeInput": {
            "audio": {
                "mimeType": "audio/pcm;rate=16000",
                "data": base64.b64encode(pcm16k).decode(),
            }
        }
    })


def context_update(text: str) -> str:
    """Fresh world-state text injected mid-conversation (never interrupts)."""
    return json.dumps({
        "clientContent": {
            "turns": [{"role": "user",
                       "parts": [{"text": text}]}],
            "turnComplete": True,
        }
    })


def parse_server_message(msg: dict) -> dict:
    """Normalize one Live server message into our browser protocol events.

    Returns {"events": [...], "audio": bytes|None}. Events: ready (never
    here), interrupted, turn_complete, input_transcript, output_transcript.
    """
    events: list[dict] = []
    audio: bytes | None = None
    sc = msg.get("serverContent") or {}
    if sc.get("interrupted"):
        events.append({"type": "interrupted"})
    for key, etype in (("inputTranscription", "input_transcript"),
                       ("outputTranscription", "output_transcript")):
        tr = sc.get(key) or {}
        if tr.get("text"):
            events.append({"type": etype, "text": tr["text"]})
    turn = sc.get("modelTurn") or {}
    for part in turn.get("parts") or []:
        blob = part.get("inlineData") or {}
        if blob.get("data"):
            try:
                audio = (audio or b"") + base64.b64decode(blob["data"])
            except Exception:
                pass
    if sc.get("turnComplete"):
        events.append({"type": "turn_complete"})
    if msg.get("toolCall"):
        # No tools declared; acknowledge to keep the session alive.
        events.append({"type": "tool_call_ignored"})
    return {"events": events, "audio": audio}
