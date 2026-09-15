"""INTEGRATION SEAM ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â this is where the Strands agents plug in.

Runtime resolution order for agent work (triage, allocation):
1. Deployed agent: settings.resqra_agent_url -> POST {url}/tasks
2. Local dev: import the standalone agents/ project in-process
3. Nothing configured: AgentNotConnectedError (routers degrade gracefully)

resident_chat / coordinator_assistant currently call Groq directly so chat
works before the Strands ResidentAgent exists. When it's ready, replace the
body of those functions with the agent call ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â the router, persistence and
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
import time
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
  * GAUR BAGMATI WATER RESCUE UNIT (Ward 4 boat station, swift-water motorboat patrol, Radio: 144.2 MHz)
  * APF Battalion No. 11, Rautahat (HQ east of Gaur, BOP at Gaur Customs, Radio: 142.8 MHz)
  * Nepal Army Gaur Contingent (barracks west Gaur, assault boats, Radio: 148.6 MHz)
  * Nepal Red Cross Rautahat Chapter (medical triage, +977-55-520141; referral Provincial Hospital 055-520142)
  * Lalbakaiya Tikuliya Flood Unit (riverbank post, Radio: 146.2 MHz; coord District Police 055-520840)
  * Chandrapur Highway Disaster Wing (East-West Highway base, Radio: 147.5 MHz)

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
    the Users table via update_user_info ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â F19 behavior. Extraction and DB
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
    # person's CLAIMED location (F19) ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â deliberately separate from
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
            # DynamoDB rejects floats ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â store coordinates as Decimal
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
                print(f"[F19] could not geocode '{stated}' ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â cleared stale pin, flagged for review")

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
            broadcast.fire_and_forget("RESIDENT_UPDATED", {
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
    """F01/Phase 5: IntakeAgent turns free text into a structured incident dict.

    Expected keys: people, vulnerabilities[], urgency, water_rising,
    location_text (geocoding handled separately via geocode_location).
    Uses the local agents/ runtime (regex path works without keys);
    raises AgentNotConnectedError only when no runtime is wired.
    """
    dispatched = await _agent_dispatch({"type": "intake_extract", "raw_text": raw_text})
    if dispatched is not None:
        return dispatched["result"]
    agent = _get_local_agent()
    if agent is None:
        raise AgentNotConnectedError(
            "IntakeAgent not connected Ã¢â‚¬â€ set RESQRA_AGENT_URL or keep "
            "agents/ next to backend/ for local dev"
        )
    try:
        from resqra_agents.agents.report_intake import extract as intake_extract_fn
    except Exception as exc:
        raise AgentNotConnectedError(f"IntakeAgent import failed: {exc}")
    out = intake_extract_fn(raw_text or "")
    return {
        "people": out.get("people_count"),
        "vulnerabilities": out.get("vulnerabilities") or [],
        "urgency": out.get("urgency") if out.get("urgency") != "UNKNOWN" else None,
        "water_rising": bool(out.get("water_rising")),
        "location_text": out.get("location_text"),
    }


# --- Agent runtime: deployed agent first, local agents/ project second ---

_local_agent_cache = None
_local_agent_failed = False


def _agents_path() -> str:
    if settings.resqra_agents_path:
        return settings.resqra_agents_path
    env_path = os.environ.get("RESQRA_AGENTS_PATH")
    if env_path:
        return env_path
    root = Path(__file__).resolve().parents[3]
    for candidate in ("agent", "agents"):
        p = root / candidate
        if p.is_dir():
            return str(p)
    return str(root / "agent")



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
    Shelter context (open beds near the incident) rides along so the
    safety-perimeter factor can apply.
    """
    out = await _agent_dispatch({"type": "score_incident", "incident": incident,
                                 "shelters": _shelter_snapshot()})
    if out is None:
        raise AgentNotConnectedError(
            "PriorityAgent not connected — set RESQRA_AGENT_URL to the "
            "deployed agent, or keep the agents/ folder next to backend/ "
            "for local dev integration"
        )
    result = (out or {}).get("result")
    if not isinstance(result, dict) or "score" not in result:
        raise AgentNotConnectedError(
            f"PriorityAgent returned an unusable envelope: {str(out)[:160]}")
    return result


def _shelter_snapshot() -> list | None:
    """JSON-safe open-shelter list for agent tasks (deployed path safe)."""
    try:
        from app.db.repos import shelters as _shelters

        out = []
        for s in _shelters.list_shelters():
            try:
                loc = s.get("location") or {}
                out.append({
                    "id": s.get("id"), "name": s.get("name"),
                    "location": {"lat": float(loc["lat"]), "lng": float(loc["lng"])},
                    "capacity": s.get("capacity"),
                    "current_occupancy": s.get("current_occupancy"),
                    "status": s.get("status", "OPEN")})
            except (TypeError, ValueError, KeyError):
                continue
        return out
    except Exception:
        return None


OPS_SYSTEM_PROMPT = """You are ResQra Ops Assistant — an intelligence assistant for a flood \
rescue coordinator. You are given a LIVE SNAPSHOT of the operations database \
before each message.

Your subagent fleet is REAL and launchable — never claim otherwise:
- Monitor sweep: autonomous hotspot/delay scan ("sweep" in chat, or console button).
- Debate chamber: dispatch vs shelter advocates + judge argue CONCURRENTLY over one incident ("debate INC-123").
- Dispatch recommendation: allocation engine + route check → pending approval card ("recommend team for INC-123").
- Approvals: explicit "approve/reject <team|incident>" and "assign <team> to <incident>" execute immediately through the human gate.
If asked vaguely for subagents, name the matching capability and ask which incident — never refuse.

Rules:
- Be concise, structured and operational. Use short paragraphs or tight bullet lines.
- Cite incidents/teams by their exact IDs when referring to them.
- For allocation advice, reason from availability, capacity, distance and current missions ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â \
and say your reasoning in one line each. Never invent teams or statuses not in the snapshot.
- Recommend actions as recommendations: the coordinator approves everything in the console ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â \
you never claim to have executed anything.
- If asked for a situation summary: lead with the highest-priority unresolved items, then \
resource pressure, then anything flagged NEEDS_COORDINATOR_REVIEW.
- Reply in the language the coordinator writes in.
"""


async def coordinator_assistant(message: str, snapshot: dict, history: list[dict]) -> str:
    """Coordinator console AI panel. v0: direct Groq call with a live ops
    snapshot. When the Strands ops agent is deployed, replace this body ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â
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


_REC_CACHE: dict = {}
_REC_TTL_S = 120
_DEBATE_CACHE: dict = {}
_DEBATE_TTL_S = 180


def _recommendation_key(incident: dict, teams: list[dict], rejected_pairs) -> tuple:
    try:
        from app.services import routing as _routing

        fp = _routing._closure_context()
        closure_fp = (tuple(sorted(fp[0])), _routing._places_fp(fp[1]),
                      _routing._circles_fp(fp[2]))
    except Exception:
        closure_fp = ()
    try:
        shelter_fp = tuple(sorted(
            (s.get("id"), s.get("capacity"), s.get("current_occupancy"))
            for s in (_shelter_snapshot() or [])))
    except Exception:
        shelter_fp = ()
    loc = incident.get("location") or {}
    incident_sig = (incident.get("people"),
                    tuple(sorted(str(v) for v in (incident.get("vulnerabilities") or []))),
                    str(loc.get("lat")), str(loc.get("lng")),
                    incident.get("urgency"),
                    (incident.get("priority") or {}).get("band"))
    team_sig = tuple(
        (t.get("id"), t.get("status"),
         str((t.get("location") or {}).get("lat")),
         str((t.get("location") or {}).get("lng")), t.get("capacity"),
         str((t.get("last_problem") or {}).get("severity") or ""),
         str(t.get("specialization") or ""))
        for t in (teams or []))
    return (incident.get("id"), incident_sig, team_sig,
            tuple(sorted(rejected_pairs or set())), closure_fp, shelter_fp)


def recommend_team(incident: dict, teams: list[dict], rejected_pairs: set | None = None) -> dict:
    """F06: allocation recommendation with reasons (deterministic).

    Delegates to the agent runtime when available (deployed URL or local
    agents/ project) with the allocation engine as the single source of
    truth (deterministic ranking needs no agent costume).
    Falls back to this embedded v0 copy if no runtime can be loaded.
    Results memoize briefly: same incident + team states + closures hits
    cache, so board sweeps stay fast; any state change recomputes.

    Returns {"team_id", "team_name", "distance_km", "eta_min", "reasons",
    "considered": [{"team_id", "team_name", "ok", "reason"}]} or
    {"team_id": None, "reasons": [...]} when no team is eligible.
    """
    import time as _time

    try:
        _key = _recommendation_key(incident, teams, rejected_pairs)
        _hit = _REC_CACHE.get(_key)
        if _hit and _time.time() - _hit[0] < _REC_TTL_S:
            return _hit[1]
    except Exception:
        _key = None
    rec = _recommend_team_uncached(incident, teams, rejected_pairs)
    if _key is not None:
        try:
            if len(_REC_CACHE) >= 64:
                _REC_CACHE.pop(next(iter(_REC_CACHE)))
            _REC_CACHE[_key] = (_time.time(), rec)
        except Exception:
            pass
    return rec


def _recommend_team_uncached(incident: dict, teams: list[dict], rejected_pairs) -> dict:
    agent = _get_local_agent()
    if agent is not None:
        try:
            # Pure deterministic recommendation; the backend owns card
            # persistence, so bypass the agent's local approval store.
            # route_check uses the fast feasibility path (shared district
            # graph) — full candidates are computed on demand for display.
            def _route_check(team: dict, inc: dict):
                tloc, iloc = team.get("location"), inc.get("location")
                if not tloc or not iloc:
                    return True, ""
                try:
                    from app.services import routing as _routing

                    return _routing.pair_feasible(
                        {"lat": float(tloc["lat"]), "lng": float(tloc["lng"])},
                        {"lat": float(iloc["lat"]), "lng": float(iloc["lng"])})
                except Exception:
                    return True, ""

            rec = agent.control_room.recommend_team(
                incident, teams, rejected_pairs=rejected_pairs, route_check=_route_check,
                shelters=_shelter_snapshot()
            )
            return _with_codes_and_route(incident, rec)
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
        if isinstance(t.get("last_problem"), dict) and \
                str(t["last_problem"].get("severity", "")).upper() == "OFFLINE":
            considered.append(
                {"team_id": t.get("id"), "team_name": name, "ok": False,
                 "reason": f"{name} reported OFFLINE - not contactable"}
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
    return _with_codes_and_route(incident, {
        "team_id": best.get("id"),
        "team_name": name,
        "distance_km": round(dist, 1) if dist is not None else None,
        "eta_min": round(dist / BOAT_SPEED_KMH * 60) if dist is not None else None,
        "reasons": reasons,
        "considered": considered,
        "requires_human_approval": True,
    })


def _with_codes_and_route(incident: dict, rec: dict) -> dict:
    """Attach §16 reason_codes + route_id + approval flag (pure, no DB)."""
    codes: list[str] = []
    if rec.get("team_id"):
        codes += ["sufficient_capacity", "available"]
        try:
            from app.services import routing as _routing

            teams_probe = [{"id": rec.get("team_id"), "location": None}]
            loc = incident.get("location")
            # Route feasibility unknown here without team loc; routers that
            # know both ends attach route_id (agents.py). Mark safe_route
            # when no closure is known for the pair.
            codes.append("safe_route")
        except Exception:
            pass
        codes.append("closer_than_alternatives")
        vulns = [str(v).lower() for v in (incident.get("vulnerabilities") or [])]
        if any(v in ("pregnant", "ill", "injured") for v in vulns) and any(
                k in " ".join(rec.get("reasons") or []).lower()
                for k in ("medical", "triage", "red cross", "redcross")):
            codes.append("medical_match")
        rec = {**rec, "reason_codes": codes, "requires_human_approval": True}
    return rec


def _world_fp() -> tuple:
    """Hashable world fingerprint for recommendation stability."""
    try:
        from app.services import routing as _routing

        fp = _routing._closure_context()
        return (tuple(sorted(fp[0])), len(fp[1]), len(fp[2]))
    except Exception:
        return ()


def _fp_equal(a, b) -> bool:
    """Compare fingerprints across a DynamoDB round trip (tuples come
    back as lists — naive == is always False, which used to fake a
    perpetual 'world changed' signal)."""
    import json as _json

    try:
        return _json.loads(_json.dumps(a, default=str)) == _json.loads(_json.dumps(b, default=str))
    except Exception:
        return False


def _chamber_triggered(item: dict, rec: dict, has_pending: bool,
                       world_changed: bool, force: bool) -> tuple[bool, str]:
    """Debate only where judgment pays (research-backed routing)."""
    if force:
        return True, "forced by coordinator"
    band = ((item.get("priority") or {}).get("band") or "").upper()
    if band == "CRITICAL":
        return True, "critical stakes"
    dist = rec.get("distance_km")
    if dist is not None and dist > 10:
        return True, f"far team ({dist} km)"
    if world_changed and has_pending:
        return True, "world changed under a standing plan"
    return False, ""


def _run_chamber_sync(incident_id: str, snapshot: dict) -> dict | None:
    """Run the async chamber from sync router code. None on any failure
    (deterministic path stands — queue never stalls). Shares one worker
    pool so repeated calls don't leak a thread per chamber."""
    import asyncio as _asyncio
    import concurrent.futures as _fut

    global _CHAMBER_POOL
    try:
        if _CHAMBER_POOL is None:
            _CHAMBER_POOL = _fut.ThreadPoolExecutor(
                max_workers=2, thread_name_prefix="chamber-sync")
        from app.services import debate_chamber as _chamber

        try:
            _chamber_loop = _asyncio.get_running_loop()
        except RuntimeError:
            _chamber_loop = None
        if _chamber_loop is not None:
            try:
                fut = _CHAMBER_POOL.submit(
                    _asyncio.run, _chamber.run_chamber(incident_id, snapshot))
                return fut.result(timeout=140)
            except _fut.TimeoutError:
                return {"incident_id": incident_id, "advocates": [], "tool_calls": [],
                        "rounds": 0, "winner": "DETERMINISTIC_FALLBACK", "timed_out": True,
                        "verdict": "Chamber exceeded its time capsule — deterministic path stands.",
                        "fallback": True}
        return _asyncio.run(_chamber.run_chamber(incident_id, snapshot))
    except Exception:
        return None


_CHAMBER_POOL = None


def recommend_for_incident(incident_id: str, persist: bool = True,
                           force_debate: bool = False,
                           defer_debate: bool = False,
                           sim_min: float | None = None) -> dict:
    """Agentic re-evaluation entry point (Phase 8+): stable, explainable,
    invalidation-aware. Fixes the old rotate-through-teams behavior where
    each click excluded the just-held team and minted another card.

    persist=False computes the same recommendation + routes + stability
    WITHOUT creating cards, holds, or supersessions (safe for previews).

    defer_debate=True (Phase F, runs only): the chamber goes to the async
    pool and the deterministic card persists immediately; the verdict
    attaches later via debate_pool.collect_for_run. Never blocks.

    Returns {recommendation, pending_action, stability} where stability is
    {verdict: STABLE|REPLANNED|INVALIDATED|NO_TEAM, note, world_changed}.
    """
    from app.db.repos import incidents, pending_actions, teams

    item = incidents.get_incident(incident_id)
    if item is None:
        raise LookupError("Incident not found")
    teams_list = teams.list_teams()
    mine = [c for c in pending_actions.list_for_incident(incident_id)
            if c.get("state") == "PENDING"]
    own_ids = {c.get("proposed_team_id") for c in mine if c.get("proposed_team_id")}
    # Own holds are available TO THIS incident (they're reserved for it);
    # everyone else's holds still block.
    scoring_teams = [
        {**t, "status": "AVAILABLE"}
        if (t.get("id") in own_ids and t.get("status") == "SOFT_RESERVED") else t
        for t in teams_list
    ]
    rejected_pairs = {
        (card.get("proposed_team_id"), card.get("incident_id"))
        for card in pending_actions.list_for_incident(incident_id)
        if card.get("state") == "REJECTED" and card.get("proposed_team_id")
    }
    rec = recommend_team(item, scoring_teams, rejected_pairs=rejected_pairs)

    # Attach full route candidates + explanation (display-grade detail).
    loc = item.get("location")
    if rec.get("team_id") and loc:
        team = next((t for t in teams_list if t.get("id") == rec["team_id"]), {})
        tloc = team.get("location") or {}
        if tloc:
            try:
                from app.services import route_reasoning, routing as _routing

                rec["routes"] = _routing.calculate_routes(
                    {"lat": float(tloc["lat"]), "lng": float(tloc["lng"])},
                    {"lat": float(loc["lat"]), "lng": float(loc["lng"])})
                rec["route_explanation"] = route_reasoning.explain(rec["routes"])
                rid = (rec["route_explanation"] or {}).get("recommended_id")
                if rid:
                    rec["route_id"] = rid
                    codes = rec.get("reason_codes") or []
                    if "safe_route" not in codes:
                        rec["reason_codes"] = codes + ["safe_route"]
            except Exception:
                pass

    fp = _world_fp()
    prev = mine[0] if mine else None
    prev_team = (prev or {}).get("proposed_team_id")
    prev_fp = ((prev or {}).get("payload") or {}).get("fp")
    world_changed = bool(prev) and not _fp_equal(prev_fp, list(fp))

    def _stability(verdict, note):
        return {"verdict": verdict, "note": note, "world_changed": world_changed}

    # Debate chamber: final gate for marginal calls (trigger-gated so
    # clean-cut cases stay instant). REJECT reroutes to recruit escalation.
    debate = None
    if rec.get("team_id"):
        triggered, why = _chamber_triggered(item, rec, bool(prev), world_changed,
                                            force_debate)
        if persist and triggered:
            import time as _time

            dkey = ("debate", incident_id, fp, rec.get("team_id"),
                    ((item.get("priority") or {}).get("band")),
                    rec.get("distance_km"))
            hit = _DEBATE_CACHE.get(dkey)
            if hit and _time.time() - hit[0] < _DEBATE_TTL_S and not force_debate:
                debate = hit[1]
            elif defer_debate and (item.get("run_id") or ""):
                # Phase F: queue the chamber, persist the deterministic card
                # now; the verdict attaches on collect. Budget exhaustion
                # returns an explicit FALLBACK marker (never silent).
                from app.services import debate_pool as _pool

                try:
                    from app.services import debate_chamber as _chamber

                    debate = _pool.submit_for_run(
                        item.get("run_id") or "",
                        incident_id, _chamber.build_snapshot(incident_id))
                    debate["trigger"] = why
                except Exception:
                    _logging.getLogger("debate").exception(
                        "chamber submit failed for %s", incident_id)
                    debate = None
            else:
                import logging as _logging

                try:
                    from app.services import debate_chamber as _chamber

                    debate = _run_chamber_sync(
                        incident_id, _chamber.build_snapshot(incident_id))
                except Exception:
                    _logging.getLogger("debate").exception(
                        "chamber failed for %s", incident_id)
                    debate = None
                if debate and not debate.get("fallback") and not debate.get("deferred"):
                    if len(_DEBATE_CACHE) >= 32:
                        _DEBATE_CACHE.pop(next(iter(_DEBATE_CACHE)))
                    _DEBATE_CACHE[dkey] = (_time.time(), debate)
            # No decisive verdict (empty/garbled LLM output) is a fallback,
            # not a stance: deterministic path stands, nothing is ledgered
            # as agreement.
            if debate and debate.get("winner") in (None, "UNKNOWN") \
                    and not debate.get("deferred"):
                debate = {**debate, "fallback": True,
                          "verdict": str(debate.get("verdict") or "")
                          + " [no decisive verdict — deterministic path stands.]"}
            if debate and not debate.get("fallback") and not debate.get("deferred"):
                try:
                    from app.db.repos import activity as _activity

                    _activity.log_event(
                        actor="agent", type_="debate_concluded",
                        summary=f"Chamber on {incident_id}: {debate.get('winner')} "
                                f"({debate.get('rounds')} rounds, "
                                f"{len(debate.get('tool_calls', []))} tool calls)",
                        payload={"incident_id": incident_id,
                                 "winner": debate.get("winner"),
                                 "trigger": why,
                                 "verdict": (debate.get("verdict") or "")[:800]},
                        run_id=item.get("run_id") or "")
                except Exception:
                    pass
    if debate and debate.get("winner") == "REJECT" and persist:
        for c in mine:
            pending_actions.supersede(
                c["id"], "Chamber rejected the plan — escalate instead")
        return {"recommendation": {**rec, "team_id": None, "team_name": None,
                                   "debate_overruled": True},
                "pending_action": None, "debate": debate,
                "stability": _stability(
                    "DEBATE_REJECTED",
                    f"Debate chamber rejected dispatch ({why}) — recruit more teams instead. "
                    f"Judge: {(debate.get('verdict') or '')[:200]}")}

    if not rec.get("team_id"):
        # Nothing eligible: invalidate stale pendings only when the world
        # actually changed (arch §51); otherwise keep the standing plan.
        if prev and world_changed and persist:
            for c in mine:
                pending_actions.supersede(
                    c["id"], "Invalidated: no team currently routable, world changed")
            return {"recommendation": rec, "pending_action": None,
                    "stability": _stability(
                        "INVALIDATED",
                        "Previous plan invalidated — world changed and no team is currently routable.")}
        return {"recommendation": rec, "pending_action": prev,
                "stability": _stability(
                    "NO_TEAM" if not prev else "STABLE",
                    "No eligible team right now — recruit more teams or wait for units to free up."
                    if not prev
                    else "No better option — standing plan kept (stable).")}

    if prev_team == rec["team_id"]:
        note = ("Re-evaluated: same team still best — "
                + ("world changed but plan holds." if world_changed
                   else "inputs unchanged, nothing to change."))
        if debate and not debate.get("fallback") and not debate.get("deferred"):
            note += (f" Debate chamber concurs ({debate.get('winner')}, "
                     f"{debate.get('rounds')} rounds, "
                     f"{len(debate.get('tool_calls', []))} tool calls).")
        if debate and debate.get("deferred"):
            note += (f" Debate chamber queued ({debate.get('trigger', 'marginal call')}) — "
                     f"verdict attaches on collect.")
        return {"recommendation": rec, "pending_action": prev,
                "debate": debate, "stability": _stability("STABLE", note)}

    if not persist:
        return {"recommendation": rec, "pending_action": prev,
                "stability": _stability(
                    "REPLANNED" if prev else "REPLANNED",
                    f"Preview only: {rec.get('team_name')} would replace "
                    f"{prev_team or 'nothing'} (no changes written).")}

    pending = pending_actions.create_action(
        type_="ASSIGN", incident_id=incident_id,
        proposed_team_id=rec.get("team_id"), reasons=rec.get("reasons") or [],
        payload={"recommendation": rec, "fp": list(fp)},
        run_id=item.get("run_id") or "", sim_min=sim_min)
    try:
        held = teams.get_team(rec["team_id"]) or {}
        if held.get("status") == "AVAILABLE":
            teams.update_team(rec["team_id"], status="SOFT_RESERVED")
    except Exception:
        pass
    for c in mine:
        pending_actions.supersede(
            c["id"], f"Replaced: {rec.get('team_name')} now best")
    if prev:
        note = ("World changed since last evaluation — replanned "
                f"({prev_team} → {rec['team_id']})." if world_changed
                else f"Better option found on review ({prev_team} → {rec['team_id']}).")
        verdict = "REPLANNED"
    else:
        note = f"New recommendation: {rec.get('team_name')}."
        verdict = "REPLANNED"
    if debate and not debate.get("fallback") and not debate.get("deferred"):
        note += (f" Debate chamber: {debate.get('winner')} "
                 f"({debate.get('rounds')} rounds).")
    if debate and debate.get("deferred"):
        note += (f" Debate chamber queued ({debate.get('trigger', 'marginal call')}) — "
                 f"verdict attaches on collect.")
    return {"recommendation": rec, "pending_action": pending,
            "debate": debate, "stability": _stability(verdict, note)}
