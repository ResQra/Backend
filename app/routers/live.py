"""Live duplex voice endpoint — browser <-> Gemini Live proxy.

WS /api/ops/assistant/live?token=<jwt>&session_id=<sid>

Browser protocol (JSON text):
  -> {"type": "audio", "data": "<b64 PCM16k mono>"}   mic chunks, 16kHz 16-bit
  -> {"type": "text", "text": "..."}                  realtime text injection
  <- {"type": "ready", "model": ...}                  Live session established
  <- {"type": "audio", "data": "<b64 PCM24k>", "rate": 24000}
  <- {"type": "interrupted"}                          stop playback NOW
  <- {"type": "input_transcript"|"output_transcript", "text": ...}
  <- {"type": "turn_complete"}
  <- {"type": "world_update"}                         fresh snapshot injected
  <- {"type": "warning"|"error", "message": ...}

Coordinator-only. Transcripts persist into the chat session so the voice
conversation is replayable/auditable like typed turns. Spoken advice only —
dispatch still goes through the human approval gate.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time

import jwt as pyjwt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.auth.deps import CurrentUser
from app.auth.jwt_utils import decode_token
from app.db.repos import coordinator_chat as csessions
from app.db.repos import incidents, shelters, teams
from app.services import live_voice as live

logger = logging.getLogger("resqra.live")

router = APIRouter(prefix="/api/ops/assistant", tags=["assistant-live"])

_MAX_SESSION_S = 10 * 60
_WARN_AT_S = 9 * 60
_CONTEXT_EVERY_S = 60


def _world_snapshot() -> str:
    try:
        open_inc = incidents.list_open_incidents()[:8]
    except Exception:
        open_inc = []
    try:
        all_teams = teams.list_teams()
    except Exception:
        all_teams = []
    try:
        all_shelters = shelters.list_shelters()
    except Exception:
        all_shelters = []
    lines = []
    for i in open_inc:
        pr = i.get("priority") or {}
        loc = i.get("location") or {}
        lines.append(
            f"- {i.get('id')} [{i.get('status')}] pri={pr.get('score')}/10 "
            f"people={i.get('people')} @({loc.get('lat')},{loc.get('lng')}) "
            f"{(i.get('location_text') or '')[:60]}")
    free_teams = [t for t in all_teams if (t.get("status") or "") != "ON_MISSION"]
    team_line = (f"{len(free_teams)}/{len(all_teams)} teams free: "
                 + ", ".join(f"{t.get('id')}({t.get('status')})"
                             for t in all_teams[:10]))
    shelter_bits = []
    for s in all_shelters[:8]:
        try:
            free = int(s.get("capacity") or 0) - int(s.get("current_occupancy") or 0)
        except Exception:
            free = "?"
        shelter_bits.append(f"{s.get('name') or s.get('id')}:{free} free")
    return ("LIVE WORLD STATE (Rautahat flood response):\n"
            f"Open incidents ({len(open_inc)}):\n" + "\n".join(lines) +
            f"\n{team_line}\nShelters: " + "; ".join(shelter_bits))


def _system_text(snapshot: str) -> str:
    return (
        "You are the ResQra ops voice assistant, speaking live with an "
        "emergency coordinator during flood response in Rautahat, Nepal. "
        "Talk like a sharp radio operator: very short spoken replies (1-3 "
        "sentences), concrete, cite real incident/team/shelter IDs. "
        "Recommend, never execute: dispatch needs the human approval gate, "
        "so propose actions ('say approve and I'll queue it') instead of "
        "claiming anything is done. If asked about something outside the "
        "snapshot below, say what you can see and what you can't.\n\n"
        + snapshot)


def _auth_ws(token: str | None) -> CurrentUser | None:
    if not token:
        return None
    try:
        payload = decode_token(token)
    except pyjwt.PyJWTError:
        return None
    if payload.get("role") != "coordinator":
        return None
    return CurrentUser(id=payload["sub"], phone=payload.get("phone") or "",
                       name=payload.get("name") or "", role="coordinator")


@router.websocket("/live")
async def live_conversation(websocket: WebSocket):
    await websocket.accept()
    qp = websocket.query_params
    user = _auth_ws(qp.get("token"))
    if user is None:
        await websocket.send_json({"type": "error",
                                   "message": "Not authorized (coordinator login required)"})
        await websocket.close(code=4401)
        return
    session_id = qp.get("session_id") or ""
    sess = csessions.get_session(session_id) if session_id else None
    if sess is None or sess.get("coordinator_id") != user.id:
        await websocket.send_json({"type": "error",
                                   "message": "Session not found"})
        await websocket.close(code=4404)
        return

    snapshot = _world_snapshot()
    try:
        gws, model = await live.open_session(_system_text(snapshot))
    except live.LiveNotConfiguredError as exc:
        await websocket.send_json({"type": "error", "message": str(exc)})
        await websocket.close(code=4503)
        return
    except live.LiveSetupError as exc:
        await websocket.send_json({"type": "error", "message": str(exc)})
        await websocket.close(code=4502)
        return

    await websocket.send_json({"type": "ready", "model": model})
    stop = asyncio.Event()
    started = time.time()
    warned = False
    last_context = time.time()
    acc = {"user": "", "agent": ""}

    async def persist_turn():
        if acc["user"].strip():
            csessions.append_message(session_id, "user",
                                     f"[live voice] {acc['user'].strip()}")
        if acc["agent"].strip():
            csessions.append_message(session_id, "agent", acc["agent"].strip())
        acc["user"] = ""
        acc["agent"] = ""

    async def browser_to_gemini():
        try:
            while not stop.is_set():
                raw = await websocket.receive_text()
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                kind = msg.get("type")
                if kind == "audio" and msg.get("data"):
                    try:
                        pcm = base64.b64decode(msg["data"])
                    except Exception:
                        continue
                    if 0 < len(pcm) <= 96_000:  # <=3s per frame, sanity cap
                        await gws.send(live.audio_message(pcm))
                elif kind == "text" and msg.get("text"):
                    await gws.send(json.dumps(
                        {"realtimeInput": {"text": str(msg["text"])[:500]}}))
                elif kind == "end":
                    break
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            logger.warning("live browser loop ended: %s", exc)
        finally:
            stop.set()

    async def gemini_to_browser():
        nonlocal warned, last_context
        try:
            async for raw in gws:
                if stop.is_set():
                    break
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                parsed = live.parse_server_message(msg)
                if parsed["audio"]:
                    await websocket.send_json({
                        "type": "audio",
                        "data": base64.b64encode(parsed["audio"]).decode(),
                        "rate": 24000})
                for ev in parsed["events"]:
                    if ev["type"] == "input_transcript":
                        acc["user"] += (" " + ev["text"])
                    elif ev["type"] == "output_transcript":
                        acc["agent"] += (" " + ev["text"])
                    if ev["type"] in ("input_transcript", "output_transcript",
                                      "interrupted", "turn_complete"):
                        await websocket.send_json(ev)
                    if ev["type"] == "turn_complete":
                        await persist_turn()
                now = time.time()
                if not warned and now - started > _WARN_AT_S:
                    warned = True
                    await websocket.send_json({
                        "type": "warning",
                        "message": "Live session ends in 1 minute — reconnect to continue."})
                if now - started > _MAX_SESSION_S:
                    await websocket.send_json({
                        "type": "warning",
                        "message": "Live session ended (10 min limit) — reconnect to continue."})
                    break
                if now - last_context > _CONTEXT_EVERY_S:
                    last_context = now
                    try:
                        await gws.send(live.context_update(
                            "WORLD UPDATE (fresh, supersedes older numbers):\n"
                            + _world_snapshot()))
                        await websocket.send_json({"type": "world_update"})
                    except Exception as exc:
                        logger.warning("live context refresh failed: %s", exc)
        except Exception as exc:
            logger.warning("live gemini loop ended: %s", exc)
        finally:
            stop.set()

    t1 = asyncio.create_task(browser_to_gemini())
    t2 = asyncio.create_task(gemini_to_browser())
    try:
        await stop.wait()
    finally:
        t1.cancel()
        t2.cancel()
        try:
            await persist_turn()
        except Exception:
            pass
        try:
            await gws.close()
        except Exception:
            pass
        try:
            await websocket.close()
        except Exception:
            pass
