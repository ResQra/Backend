"""INTEGRATION SEAM — this is where the Strands agents plug in.

Runtime resolution order for agent work (triage, allocation):
1. Deployed agent: settings.resqra_agent_url -> POST {url}/tasks
2. Local dev: import the standalone agents/ project in-process
3. Nothing configured: AgentNotConnectedError (routers degrade gracefully)

resident_chat / coordinator_assistant currently call Groq directly so chat
works before the Strands ResidentAgent exists. When it's ready, replace the
body of those functions with the agent call — the router, persistence and
extraction contract stay the same.

Contract for every seam function:
- raise AgentNotConnectedError if nothing is wired yet
- return plain text for chat seams, dicts for structured seams
- routers own persistence; agent tools use app.db.repos.* directly
  (e.g. update_user_info for F19)
"""

import json
import os
import sys
from pathlib import Path

from app.agents_gateway import llm, memory
from app.config import settings
from app.db.repos import users
from app.utils.geo import haversine_km

RESIDENT_SYSTEM_PROMPT = """You are ResQra, the dedicated Emergency Flood Rescue Copilot for Rautahat District, Nepal (Madhesh Province).
You assist citizens in distress during the Bagmati and Lalbakaiya monsoon flood surge.

YOU HAVE DEEP LOCAL GEOGRAPHIC & RESCUE KNOWLEDGE OF RAUTAHAT DISTRICT:
- District Headquarters: Gaur Municipality (Ward 1 to 4, Court Road, Customs Road, Hospital Chowk, Gaur Ring Road, Sluice Gate).
- Other Municipalities: Garuda, Chandrapur (Chandranigahapur), Ishnath, Tikuliya Ghat, Rajpur, Katahariya, Durga Bhagawati, Baudhimai, Rajdevi, Brindaban, Gadhimai, Madhav Narayan, Phatuwa Bijaypur, Gujara, Maulapur, Dewahi Gonahi, Paroha.
- Rivers & Flood Basins: Bagmati River (Eastern embankment breach zone) and Lalbakaiya River (Tikuliya breach zone).
- Designated Open Evacuation Shelters & Hospitals:
  * Gaur District Hospital & Trauma Center (Gaur Ward 3, 160 beds, boat dock)
  * Rautahat District Sports Stadium Evacuation Camp (Gaur High Ground, 3000 capacity)
  * Juddha Higher Secondary School Relief Camp (Gaur Ward 2, 1800 capacity)
  * Tikuliya Ghat Community Relief Point (Lalbakaiya Bank, 950 capacity)
  * Garuda Municipal Evacuation Complex (Central Hub, 2200 capacity)
  * Chandranigahapur Community Hospital (East-West Highway, 300 beds)
- Active Rescue Fleet:
  * GAUR BAGMATI WATER RESCUE UNIT (Lead Motorboat Squadron, Contact: +977-55-520100, Radio: 144.2 MHz)
  * APF No. 11 Battalion Rautahat (Radio: 142.8 MHz)
  * Nepal Army Gaur Contingent (Radio: 148.6 MHz)
  * Nepal Red Cross Rautahat Chapter (+977-55-520250)

CORE RULES:
1. Always recognize local towns instantly: When someone mentions "Gaur", "Tikuliya", "Garuda", "Chandrapur", "Ward 1-4", or landmarks like "hospital", "stadium", "juddha school", or "bagmati", you IMMEDIATELY know they are in Rautahat District, Nepal. NEVER say "I don't know where Gaur is".
2. Language: Reply warmly in whichever language the citizen speaks — Nepali, Maithili, Bhojpuri, Hindi, or English (including Romanized forms like "gaur ma chu", "fasal chi", "pani badh raha hai").
3. Brevity & Empathy: Keep responses calm, reassuring, and concise (2-4 sentences max). Give immediate safety advice: stay on the highest floor/rooftop, keep away from fast-moving Bagmati/Lalbakaiya floodwaters, and keep your phone dry.
4. Memory First: Before replying, check the conversation history and WHAT YOU ALREADY KNOW. NEVER re-ask for details the resident already provided.
5. If the resident gives their location (e.g. "Gaur"), acknowledge it, suggest the nearest known shelter (like Juddha School or Gaur Hospital/Stadium), and ask for specific details like Ward number or landmark if needed.
"""


def _known_profile_section(user_id: str) -> str:
    profile = memory.get_profile(user_id)
    if not profile:
        return "WHAT YOU ALREADY KNOW: (nothing yet)"
    parts = []
    for k, v in profile.items():
        text = ", ".join(v) if isinstance(v, list) else str(v)
        parts.append(f"{k.replace('_', ' ')}: {text}")
    return (
        "WHAT YOU ALREADY KNOW about this resident (do NOT ask for these again): "
        + "; ".join(parts)
    )

EXTRACTION_PROMPT = """Extract resident profile updates from this flood-emergency \
chat. Return STRICT JSON only, no markdown:
{"location": <nearest landmark/address string or null>,
 "people_with": <integer of people together or null>,
 "vulnerabilities": <list from: children, elderly, pregnant, disabled, ill, injured; or null>,
 "status": <one of: SAFE, NEEDS_HELP, TRAPPED, EVACUATED; or null>}
Use null for anything not clearly stated in the conversation. Do not guess.

Conversation:
"""


class AgentNotConnectedError(RuntimeError):
    """Raised when a seam has no real agent behind it yet."""


async def resident_chat(user_id: str, message: str, history: list[dict]) -> str:
    """F18/F19: reply to a resident + keep their profile current.

    Two calls: (1) empathetic reply, (2) strict-JSON extraction written to
    the Users table via update_user_info — F19 behavior. Extraction and DB
    are best-effort: chat still works when either fails.
    """
    msgs = [
        {"role": "system", "content": RESIDENT_SYSTEM_PROMPT},
        {"role": "system", "content": _known_profile_section(user_id)},
    ]
    for m in history[-20:]:
        role = "assistant" if m.get("role") == "agent" else "user"
        msgs.append({"role": role, "content": str(m.get("content", ""))})
    msgs.append({"role": "user", "content": message})
    reply = await llm.chat_completion(msgs)

    # F19: extract what changed and persist (best-effort, non-blocking on failure)
    try:
        await _extract_and_save(user_id, message, reply)
    except Exception:
        pass
    return reply


RAUTAHAT_LANDMARKS = {
    "gaur ward 4": (26.7660, 85.2770, "Gaur Ward 4 (Bagmati Breach Corridor), Rautahat"),
    "gaur ward 3": (26.7640, 85.2780, "Gaur Ward 3 (Hospital Chowk), Rautahat"),
    "gaur ward 2": (26.7600, 85.2750, "Gaur Ward 2 (Court Road), Rautahat"),
    "gaur ward 1": (26.7580, 85.2740, "Gaur Ward 1 (Customs Area), Rautahat"),
    "ward 4": (26.7660, 85.2770, "Gaur Ward 4, Rautahat"),
    "ward 3": (26.7640, 85.2780, "Gaur Ward 3, Rautahat"),
    "ward 2": (26.7600, 85.2750, "Gaur Ward 2, Rautahat"),
    "ward 1": (26.7580, 85.2740, "Gaur Ward 1, Rautahat"),
    "juddha secondary school": (26.7590, 85.2720, "Juddha Higher Secondary School Relief Camp, Gaur"),
    "juddha school": (26.7590, 85.2720, "Juddha Higher Secondary School, Gaur"),
    "gaur hospital": (26.7640, 85.2780, "Gaur District Hospital & Trauma Center, Rautahat"),
    "hospital": (26.7640, 85.2780, "Gaur District Hospital, Rautahat"),
    "rautahat stadium": (26.7680, 85.2810, "Rautahat District Sports Stadium Shelter, Gaur"),
    "stadium": (26.7680, 85.2810, "Rautahat District Sports Stadium Shelter, Gaur"),
    "tikuliya ghat": (26.7820, 85.2420, "Tikuliya Ghat, Lalbakaiya River, Rautahat"),
    "tikuliya": (26.7820, 85.2420, "Tikuliya Ghat (Lalbakaiya Basin), Rautahat"),
    "garuda bazaar": (26.9250, 85.3120, "Garuda Municipal Complex, Rautahat"),
    "garuda": (26.9250, 85.3120, "Garuda Municipal Center, Rautahat"),
    "chandranigahapur": (27.1250, 85.3400, "Chandranigahapur Highway Hub, Rautahat"),
    "chandrapur": (27.1250, 85.3400, "Chandranigahapur Highway Base, Rautahat"),
    "bagmati river": (26.7700, 85.2950, "Bagmati River Embankment, Rautahat"),
    "bagmati": (26.7700, 85.2950, "Bagmati River Corridor, Rautahat"),
    "lalbakaiya": (26.7800, 85.2400, "Lalbakaiya River Corridor, Rautahat"),
    "gaur": (26.7620, 85.2760, "Gaur Municipality, Rautahat"),
}


async def _extract_and_save(user_id: str, user_msg: str, agent_reply: str) -> None:
    convo = f'user: "{user_msg}"\nassistant: "{agent_reply}"'
    raw = await llm.chat_completion(
        [{"role": "user", "content": EXTRACTION_PROMPT + convo}],
        temperature=0.0,
        json_mode=True,
    )
    data = json.loads(raw)
    updates = fields_to_dict(
        {
            "people_with": data.get("people_with"),
            "vulnerabilities": data.get("vulnerabilities"),
            "status": data.get("status"),
        }
    )

    # Stated location: geocode it so it can be plotted. This is the
    # person's CLAIMED location (F19) — deliberately separate from
    # device_location (GPS heartbeat), which never overwrites it.
    stated = data.get("location")
    if stated:
        from decimal import Decimal

        from app.utils.geocode import geocode

        updates["location_text"] = str(stated)
        stated_lower = str(stated).lower()

        # Check local Rautahat landmark dictionary first for instant, accurate coordinates
        matched_landmark = None
        for lm_key, (lat, lng, label) in RAUTAHAT_LANDMARKS.items():
            if lm_key in stated_lower:
                matched_landmark = {"lat": lat, "lng": lng, "label": label, "confidence": 0.98}
                break

        if matched_landmark:
            geo = matched_landmark
        else:
            geo = await geocode(f"{stated}, Rautahat, Nepal") or await geocode(str(stated))

        if geo:
            # DynamoDB rejects floats — store coordinates as Decimal
            updates["location"] = {
                "lat": Decimal(str(round(geo["lat"], 6))),
                "lng": Decimal(str(round(geo["lng"], 6))),
                "label": geo["label"],
                "confidence": Decimal(str(geo["confidence"])),
            }
            updates["location_verification"] = "STATED_GEOCODED"
            print(f"[F19] geocoded '{stated}' -> {geo['lat']:.4f},{geo['lng']:.4f} ({geo['label'][:50]})")
        else:
            # Fallback default to Gaur center if stated was clearly in Rautahat/Gaur
            if "gaur" in stated_lower or "rautahat" in stated_lower:
                updates["location"] = {
                    "lat": Decimal("26.762000"),
                    "lng": Decimal("85.276000"),
                    "label": f"{stated}, Gaur, Rautahat",
                    "confidence": Decimal("0.90"),
                }
                updates["location_verification"] = "STATED_GEOCODED"
            else:
                updates["location_verification"] = "NEEDS_COORDINATOR_REVIEW"
                users.clear_resolved_location(user_id)
                print(f"[F19] could not geocode '{stated}' — cleared stale pin, flagged for review")

    if not updates:
        return
    print(f"[F19] extracted for {user_id}: {[k for k in updates]}")
    memory.update_profile(
        user_id, **{k: v for k, v in updates.items() if k != "location"},
        **({"location": stated} if stated else {}),
    )
    try:
        users.update_user_info(user_id, **updates)
    except Exception:
        pass

    # Real-time WebSocket Broadcast: send updated resident beacon to War Room map
    try:
        from app.services.broadcast import manager as broadcast
        user_record = users.find_by_id(user_id)
        if user_record and user_record.get("location"):
            broadcast.send_to_all({
                "event": "resident_updated",
                "resident": {
                    "id": user_id,
                    "name": user_record.get("name", "Citizen Distress Beacon"),
                    "phone": user_record.get("phone", ""),
                    "location": user_record.get("location"),
                    "location_text": user_record.get("location_text", stated),
                    "people_with": user_record.get("people_with", 1),
                    "vulnerabilities": user_record.get("vulnerabilities", []),
                    "status": user_record.get("status", "NEEDS_HELP"),
                    "updated_at": int(time.time() * 1000),
                }
            })
    except Exception as e:
        print(f"[F19] Broadcast error: {e}")

    # F09: make the profile update visible on the coordinator feed
    try:
        from app.db.repos import activity

        summary = ", ".join(
            f"{k}={v if not isinstance(v, list) else '+'.join(v)}"
            for k, v in {**updates, **({"location": stated} if stated else {})}.items()
        )
        activity.log_event(
            actor="agent",
            type_="user_info_updated",
            summary=f"ResidentAgent updated {user_id}: {summary}",
            payload={"user_id": user_id, "updates": {k: str(v) for k, v in updates.items()}},
        )
    except Exception:
        pass


def fields_to_dict(fields: dict) -> dict:
    """None values (including empty lists) shouldn't overwrite stored data."""
    return {k: v for k, v in fields.items() if v not in (None, [])}


async def intake_extract(raw_text: str) -> dict:
    """F01: IntakeAgent turns free text into a structured incident dict.

    Expected keys: people, vulnerabilities[], urgency, water_rising,
    location_text (geocoding handled separately via geocode_location).
    """
    raise AgentNotConnectedError(
        "IntakeAgent not connected yet — implement intake_extract() "
        "in app/agents_gateway/gateway.py"
    )


# --- Agent runtime: deployed agent first, local agents/ project second ---

_local_agent_cache = None
_local_agent_failed = False


def _agents_path() -> str:
    if settings.resqra_agents_path:
        return settings.resqra_agents_path
    env_path = os.environ.get("RESQRA_AGENTS_PATH")
    if env_path:
        return env_path
    # backend/app/agents_gateway/gateway.py -> repo root -> agents/
    return str(Path(__file__).resolve().parents[3] / "agents")


def _get_local_agent():
    """Import the standalone resqra_agents package for dev-mode integration."""
    global _local_agent_cache, _local_agent_failed
    if _local_agent_cache is not None or _local_agent_failed:
        return _local_agent_cache
    path = _agents_path()
    if not os.path.isdir(path):
        _local_agent_failed = True
        return None
    try:
        if path not in sys.path:
            sys.path.insert(0, path)
        from resqra_agents.main_agent import main_agent as agent

        _local_agent_cache = agent
    except Exception:
        _local_agent_failed = True
        _local_agent_cache = None
    return _local_agent_cache


async def _agent_dispatch(task: dict) -> dict | None:
    """Send a task envelope to the configured runtime. None = no runtime."""
    if settings.resqra_agent_url:
        import httpx

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                settings.resqra_agent_url.rstrip("/") + "/tasks",
                json=task,
            )
            resp.raise_for_status()
            return resp.json()
    agent = _get_local_agent()
    if agent is not None:
        return agent.dispatch(task)
    return None


async def triage_score(incident: dict) -> dict:
    """F03: PriorityAgent returns {"score", "band", "factors", "reasons"}.

    Always deterministic — the formula lives in the agent's
    priority_engine tool; the LLM never computes this number.
    """
    out = await _agent_dispatch({"type": "score_incident", "incident": incident})
    if out is None:
        raise AgentNotConnectedError(
            "PriorityAgent not connected — set RESQRA_AGENT_URL to the "
            "deployed agent, or keep the agents/ folder next to backend/ "
            "for local dev integration"
        )
    return out["result"]


OPS_SYSTEM_PROMPT = """You are ResQra Ops Assistant — an intelligence assistant for a flood \
rescue coordinator. You are given a LIVE SNAPSHOT of the operations database \
before each message.

Rules:
- Be concise, structured and operational. Use short paragraphs or tight bullet lines.
- Cite incidents/teams by their exact IDs when referring to them.
- For allocation advice, reason from availability, capacity, distance and current missions — \
and say your reasoning in one line each. Never invent teams or statuses not in the snapshot.
- Recommend actions as recommendations: the coordinator approves everything in the console — \
you never claim to have executed anything.
- If asked for a situation summary: lead with the highest-priority unresolved items, then \
resource pressure, then anything flagged NEEDS_COORDINATOR_REVIEW.
- Reply in the language the coordinator writes in.
"""


async def coordinator_assistant(message: str, snapshot: dict, history: list[dict]) -> str:
    """Coordinator console AI panel. v0: direct Groq call with a live ops
    snapshot. When the Strands ops agent is deployed, replace this body —
    the router contract (message + snapshot + history → text) stays."""
    msgs = [{"role": "system", "content": OPS_SYSTEM_PROMPT}]
    for m in history[-16:]:
        role = "assistant" if m.get("role") == "agent" else "user"
        msgs.append({"role": role, "content": str(m.get("content", ""))})
    msgs.append(
        {
            "role": "system",
            "content": "LIVE SNAPSHOT:\n"
            + json.dumps(snapshot, indent=1, default=str)[:6000],
        }
    )
    msgs.append({"role": "user", "content": message})
    return await llm.chat_completion(msgs, temperature=0.3)


BOAT_SPEED_KMH = 20.0


def recommend_team(incident: dict, teams: list[dict], rejected_pairs: set | None = None) -> dict:
    """F06: allocation recommendation with reasons (deterministic).

    Delegates to the agent runtime when available (deployed URL or local
    agents/ project) so TeamDispatchAgent is the single source of truth.
    Falls back to this embedded v0 copy if no runtime can be loaded.

    Returns {"team_id", "team_name", "distance_km", "eta_min", "reasons",
    "considered": [{"team_id", "team_name", "ok", "reason"}]} or
    {"team_id": None, "reasons": [...]} when no team is eligible.
    """
    agent = _get_local_agent()
    if agent is not None:
        try:
            # Pure deterministic recommendation; the backend owns card
            # persistence, so bypass the agent's local approval store.
            return agent.control_room.dispatch_agent.recommend(
                incident, teams, rejected_pairs=rejected_pairs
            )
        except Exception:
            pass  # fall through to embedded v0 below

    need = incident.get("people") or 1
    loc = incident.get("location") or None
    considered: list[dict] = []
    eligible: list[tuple[dict, float | None]] = []

    for t in teams:
        name = t.get("name") or t.get("id", "?")
        if (t.get("id"), incident.get("id")) in (rejected_pairs or set()):
            considered.append(
                {"team_id": t.get("id"), "team_name": name, "ok": False,
                 "reason": f"{name} was already rejected for this incident"}
            )
            continue
        status = t.get("status", "UNKNOWN")
        if status not in ("AVAILABLE", "RETURNING"):
            considered.append(
                {"team_id": t.get("id"), "team_name": name, "ok": False,
                 "reason": f"{name} is {status} - not dispatchable"}
            )
            continue
        capacity = t.get("capacity") or 0
        if capacity < need:
            considered.append(
                {"team_id": t.get("id"), "team_name": name, "ok": False,
                 "reason": f"{name} capacity {capacity} < {need} people"}
            )
            continue
        dist = None
        if loc and t.get("location"):
            dist = haversine_km(
                float(loc["lat"]), float(loc["lng"]),
                float(t["location"]["lat"]), float(t["location"]["lng"]),
            )
        eligible.append((t, dist))
        considered.append(
            {"team_id": t.get("id"), "team_name": name, "ok": True,
             "reason": f"{name} {status.lower()}, capacity {capacity} >= {need} people"
                       + (f", {dist:.1f} km away" if dist is not None else "")}
        )

    if not eligible:
        return {
            "team_id": None,
            "team_name": None,
            "distance_km": None,
            "eta_min": None,
            "reasons": ["No eligible team: " + "; ".join(
                c["reason"] for c in considered if not c["ok"]
            )],
            "considered": considered,
        }

    best, dist = min(eligible, key=lambda pair: pair[1] if pair[1] is not None else 1e9)
    name = best.get("name") or best.get("id", "?")
    reasons = [
        f"{name} is {str(best.get('status', '')).lower()} now",
        f"capacity {best.get('capacity')} >= {need} people",
    ]
    if dist is not None:
        eta = dist / BOAT_SPEED_KMH * 60
        reasons.append(f"nearest eligible team: {dist:.1f} km away, ETA about {eta:.0f} min")
    else:
        reasons.append("incident location unverified - pick by availability/capacity only")
    for c in considered:
        if not c["ok"]:
            reasons.append(c["reason"])
    return {
        "team_id": best.get("id"),
        "team_name": name,
        "distance_km": round(dist, 1) if dist is not None else None,
        "eta_min": round(dist / BOAT_SPEED_KMH * 60) if dist is not None else None,
        "reasons": reasons,
        "considered": considered,
    }
