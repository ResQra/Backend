"""INTEGRATION SEAM — this is where the Strands agents plug in.

v0 note: resident_chat currently calls Groq directly so the chat flow
works before the Strands ResidentAgent exists. When it's ready, replace
the body of resident_chat with the agent call — the router, persistence
and extraction contract stay the same.

Contract for every seam function:
- raise AgentNotConnectedError if nothing is wired yet
- return plain text for chat seams, dicts for structured seams
- routers own persistence; agent tools use app.db.repos.* directly
  (e.g. update_user_info for F19)
"""

import json

from app.agents_gateway import llm, memory
from app.db.repos import users
from app.utils.geo import haversine_km

RESIDENT_SYSTEM_PROMPT = """You are ResQra, a flood emergency response assistant \
for residents of Patna, India. You chat with people affected by flooding.

Core rules:
- Be calm, warm and BRIEF (2-4 sentences max). Reply in the language the user \
writes in (Hindi, English, or Hinglish).
- MEMORY FIRST: before saying anything, check the conversation history and the \
"WHAT YOU ALREADY KNOW" section below. NEVER ask again for information the \
resident already gave or that is listed there — repeating questions angers \
people in emergencies. Acknowledge new info in one short clause instead.
- Ask at most ONE new question per reply (a second only if critical). Pick the \
single most important missing detail: people count → location → water level → \
special vulnerabilities.
- If a stated location is clearly not a real place (e.g. "moon", jokes), say \
kindly that you couldn't recognize it and ask for a nearby landmark — do not \
pretend it was accepted.
- If the user is frustrated or says you are repeating, apologize in one short \
sentence and move forward — never re-explain.
- If they describe danger, acknowledge urgency without panic and give one \
piece of immediate safety advice (highest floor/rooftop, avoid moving water, \
keep phone dry).
- NEVER invent rescue team names, ETAs, or promise specific rescue times. Say \
help coordination is underway when an incident exists.
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
        geo = await geocode(str(stated))
        if geo:
            # DynamoDB rejects floats — store coordinates as Decimal
            updates["location"] = {
                "lat": Decimal(str(geo["lat"])),
                "lng": Decimal(str(geo["lng"])),
                "label": geo["label"],
                "confidence": Decimal(str(geo["confidence"])),
            }
            updates["location_verification"] = "STATED_GEOCODED"
            print(f"[F19] geocoded '{stated}' -> {geo['lat']:.4f},{geo['lng']:.4f} ({geo['label'][:50]})")
        else:
            # New stated place unresolved: the old resolved pin is now
            # WRONG — clear it rather than leave a misleading marker. The
            # person still plots via device-GPS fallback (ops map layer).
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
            payload={"user_id": user_id, **{k: str(v) for k, v in updates.items()}},
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


async def triage_score(incident: dict) -> dict:
    """F03: TriageAgent returns {"score": int, "reasons": [str, ...]}.

    The LLM supplies factors; the deterministic formula lives in the
    agent's score_priority tool. This seam returns its result.
    """
    raise AgentNotConnectedError(
        "TriageAgent not connected yet — implement triage_score() "
        "in app/agents_gateway/gateway.py"
    )


OPS_SYSTEM_PROMPT = """You are ResQra Ops Assistant — an intelligence assistant for a flood \
rescue coordinator in Patna, India. You are given a LIVE SNAPSHOT of the operations database \
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


BOAT_SPEED_KMH = 20.0  # planning figure for ETA estimates


def recommend_team(incident: dict, teams: list[dict]) -> dict:
    """F06 v0: deterministic AllocationAgent — availability + capacity +
    haversine distance, every verdict explained. The Strands AllocationAgent
    replaces this body later; the router/console contract stays the same.

    Returns {"team_id", "team_name", "distance_km", "eta_min", "reasons",
    "considered": [{"team_id", "team_name", "ok", "reason"}]} or
    {"team_id": None, "reasons": [...]} when no team is eligible.
    """
    need = incident.get("people") or 1
    loc = incident.get("location") or None
    considered: list[dict] = []
    eligible: list[tuple[dict, float | None]] = []

    for t in teams:
        name = t.get("name") or t.get("id", "?")
        status = t.get("status", "UNKNOWN")
        if status not in ("AVAILABLE", "RETURNING"):
            considered.append(
                {"team_id": t.get("id"), "team_name": name, "ok": False,
                 "reason": f"{name} is {status} — not dispatchable"}
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
             "reason": f"{name} {status.lower()}, capacity {capacity} ≥ {need} people"
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

    # Nearest eligible team wins; without a verified incident location,
    # fall back to the first eligible team and say so.
    best, dist = min(eligible, key=lambda pair: pair[1] if pair[1] is not None else 1e9)
    name = best.get("name") or best.get("id", "?")
    reasons = [
        f"{name} is {str(best.get('status', '')).lower()} now",
        f"capacity {best.get('capacity')} ≥ {need} people",
    ]
    if dist is not None:
        eta = dist / BOAT_SPEED_KMH * 60
        reasons.append(f"nearest eligible team — {dist:.1f} km away, ETA ~{eta:.0f} min")
    else:
        reasons.append("incident location unverified — pick by availability/capacity only")
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
