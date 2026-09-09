"""Coordinator session API — Phase 2 of the coordinator AI program.

Sessions give the ChatGPT-like tab persistent conversations: list, open,
rename, delete, and per-session history. The assistant endpoint binds a
session id so history lives server-side instead of vanishing on reload.
"""

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app.auth.deps import CurrentUser, require_role
from app.db.repos import coordinator_chat as sessions

router = APIRouter(prefix="/api/ops/assistant", tags=["assistant"],
                   dependencies=[Depends(require_role("coordinator"))])


def _owned(session_id: str, user: CurrentUser) -> dict:
    item = sessions.get_session(session_id)
    if item is None or item.get("coordinator_id") != user.id:
        raise HTTPException(status_code=404, detail="Session not found")
    return item


@router.get("/sessions")
def list_sessions(user: CurrentUser = Depends(require_role("coordinator"))):
    return {"sessions": sessions.list_sessions(user.id)}


@router.post("/sessions")
def create_session(body: dict | None = None,
                   user: CurrentUser = Depends(require_role("coordinator"))):
    body = body or {}
    item = sessions.create_session(
        user.id, title=str(body.get("title") or "New conversation")[:80],
        area=body.get("area"), incident_id=body.get("incident_id"))
    return {"session": item}


@router.get("/sessions/{session_id}/history")
def session_history(session_id: str,
                    user: CurrentUser = Depends(require_role("coordinator"))):
    _owned(session_id, user)
    return {"session_id": session_id,
            "messages": sessions.get_history(session_id)}


@router.patch("/sessions/{session_id}")
def rename_session(session_id: str, body: dict,
                   user: CurrentUser = Depends(require_role("coordinator"))):
    _owned(session_id, user)
    title = str(body.get("title") or "").strip()[:80]
    if not title:
        raise HTTPException(status_code=422, detail="title required")
    sessions.touch_session(session_id, title=title)
    return {"session": sessions.get_session(session_id)}


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str,
                   user: CurrentUser = Depends(require_role("coordinator"))):
    _owned(session_id, user)
    sessions.delete_session(session_id)
    return {"deleted": session_id}


async def _answer(user: CurrentUser, message: str, area_context: dict,
                   session_id: str | None, user_persist: str | None = None) -> dict:
    """Shared supervisor call + session persistence (mirrors ops assistant).

    user_persist overrides what is stored as the user's turn: image/voice
    routes pass the RAW turn so replay shows "(photo) …" instead of the
    LLM-augmented prompt, while the supervisor still reasons over `message`.
    """
    from app.agents_gateway import supervisor as supervisor_mod

    history: list = []
    if session_id:
        sess = sessions.get_session(session_id)
        if sess is None or sess.get("coordinator_id") != user.id:
            raise HTTPException(status_code=404, detail="Session not found")
        history = [{"role": m.get("role"), "content": m.get("content")}
                   for m in sessions.get_history(session_id, limit=16)]
        sessions.append_message(session_id, "user", user_persist if user_persist is not None else message)
        if (sess.get("title") or "New conversation") == "New conversation":
            sessions.touch_session(session_id, title=message[:60])
    out = await supervisor_mod.supervise(message, area_context, history)
    if session_id:
        sessions.append_message(session_id, "agent", out.get("reply", ""))
        out = {**out, "session_id": session_id}
    return out


@router.post("/image")
async def image_message(file: UploadFile = File(...),
                        message: str = Form(""),
                        session_id: str | None = Form(None),
                        area: str | None = Form(None),
                        user: CurrentUser = Depends(require_role("coordinator"))):
    """Photo + optional question. Gemini describes; supervisor reasons
    over the description + live world state. Needs GEMINI_API_KEY."""
    import asyncio as _asyncio

    from app.services import gemini as gemini_mod

    try:
        raw = await file.read()
        observation = await _asyncio.to_thread(
            gemini_mod.describe_image,
            raw, file.content_type or "image/jpeg", hint=message)
    except gemini_mod.GeminiNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Image analysis failed: {exc}")
    question = (message.strip() + "\n\n[Attached photo observation: " + observation + "]"
                if message.strip() else
                "What does this attached photo show for flood operations, and what should change?\n\n"
                "[Attached photo observation: " + observation + "]")
    # The full grounded question is what the supervisor reasons over, but
    # only the RAW user turn persists — replay stays readable, audit clean.
    raw_turn = (message.strip() + " [photo attached]" if message.strip()
                else "[photo attached]")
    out = await _answer(user, question, {"area": area,
                                         "image_observation": observation}, session_id,
                        user_persist=raw_turn)
    out["image_observation"] = observation
    return out


@router.post("/voice")
async def voice_message(file: UploadFile = File(...),
                        session_id: str | None = Form(None),
                        area: str | None = Form(None),
                        tts: bool = Form(True),
                        user: CurrentUser = Depends(require_role("coordinator"))):
    """Voice note: transcribe (Groq Whisper, Gemini fallback) ->
    supervisor -> optional spoken reply. Needs GROQ_API_KEY and/or
    GEMINI_API_KEY. Blocking work runs in threads; per-stage timings
    ride along so latency is measurable, not vibes."""
    import asyncio as _asyncio
    import logging as _logging
    import time as _time

    from app.services import stt as stt_mod
    from app.services.gemini import GeminiNotConfiguredError as _NotConfigured

    raw = await file.read()
    timings: dict = {}
    try:
        transcript, engine, stt_ms = await stt_mod.transcribe(
            raw, file.content_type or "audio/webm",
            filename=getattr(file, "filename", None) or "voice.webm")
        timings = {"transcribe_ms": round(stt_ms), "stt_engine": engine}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except _NotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Transcription failed: {exc}")
    t_reason = _time.time()
    out = await _answer(user, transcript, {"area": area}, session_id)
    timings["reason_ms"] = round((_time.time() - t_reason) * 1000)
    result = {"transcript": transcript, **out, "timings": timings}
    if tts:
        try:
            spoken = _spoken_summary(out.get("reply", ""))
            t_tts = _time.time()
            wav, mime = await _asyncio.to_thread(
                _gemini_synthesize, spoken)
            import base64 as _b64

            result["audio_b64"] = _b64.b64encode(wav).decode()
            result["audio_mime"] = mime
            timings["tts_ms"] = round((_time.time() - t_tts) * 1000)
            timings["tts_chars"] = len(spoken)
        except Exception as exc:  # spoken reply is best-effort; text stands
            _logging.getLogger("resqra.coordinator").warning(
                "TTS failed, text reply only: %s", exc)
            result["audio_b64"] = None
            result["audio_error"] = str(exc)[:200]
    _logging.getLogger("resqra.voice").info(
        "voice turn timings ms: %s", timings)
    return result


def _spoken_summary(reply: str, limit: int = 400) -> str:
    """First whole sentences up to ~limit chars — TTS cost scales with
    text length, so speak the point, not the whole report."""
    import re as _re

    text = (reply or "").replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    parts = _re.split(r"(?<=[.!?])\s+", text)
    out = ""
    for p in parts:
        if out and len(out) + len(p) + 1 > limit:
            break
        out = (out + " " + p).strip()
    return out or text[:limit]


def _gemini_synthesize(text: str):
    from app.services import gemini as _gemini

    return _gemini.synthesize_speech(text)
