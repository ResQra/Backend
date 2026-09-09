"""Explicit coordinator commands from chat — Phase 3.

Rule (from the program plan): an explicit instruction in an authenticated
coordinator session IS the human deciding, so the agent may execute it
through the same approval endpoints + audit as the buttons. Anything
vague yields a proposal, never execution.

Deterministic parsing (no LLM): approve / reject pending cards by team
reference, manual assign team -> incident, launch subagent work
(debate chamber, monitor sweep, dispatch recommendation).
Ambiguity (several cards match, none match) returns a clarification
question, never a guess.
"""

from __future__ import annotations

import re

_SUBAGENT_WORDS = ("subagent", "sub-agent", "sub agent", "debate",
                   "advocate", "deliberat")

_CAPABILITIES = (
    "Here's the crew I can put to work: a district sweep for hotspots, "
    "a full debate on one incident (dispatch and shelter advocates argue "
    "it out, judge calls it), or a dispatch recommendation with a pending "
    "card for your approval. I also take direct orders: approve, reject, "
    "or assign a team to an incident."
)


def _open_list(incidents: list[dict]) -> str:
    return ", ".join(i.get("id", "?") for i in incidents) or "none"


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def _squash(s: str) -> str:
    return _norm(s).replace(" ", "")


def _team_matches(team: dict, ref: str) -> bool:
    ref_n = _norm(ref)
    if not ref_n:
        return False
    if _squash(team.get("id")) == _squash(ref):
        return True
    name_n = _norm(team.get("name"))
    return bool(ref_n) and (ref_n in name_n or all(w in name_n for w in ref_n.split()))


def _incident_matches(incident: dict, ref: str) -> bool:
    ref_n = _norm(ref)
    if not ref_n:
        return False
    if _squash(incident.get("id")) == _squash(ref):
        return True
    return bool(ref_n) and ref_n in _norm(incident.get("location_text") or "")


def _resolve_incident(text: str, low: str,
                      incidents: list[dict]) -> tuple[dict | None, str | None]:
    """Pin an incident by explicit id or unambiguous location reference.

    Returns (incident, None) or (None, clarify_reply). Never guesses.
    """
    m = re.search(r"\b(inc_[a-z0-9_-]+)\b", low)
    if m:
        hit = next((i for i in incidents if i.get("id") == m.group(1)), None)
        if hit is not None:
            return hit, None
        return None, f"There's no open incident called {m.group(1)}. Open right now: {_open_list(incidents)}."
    cands = [i for i in incidents if _incident_matches(i, text)]
    if not cands:
        # Fallback: a distinctive location word from the incident appearing
        # anywhere in the message ("the Gaur incident" -> Gaur Ward 4).
        for i in incidents:
            loc = _norm(i.get("location_text") or "")
            words = [w for w in loc.split() if len(w) >= 4]
            if any(w in low for w in words):
                cands.append(i)
    # A bare district word matches everything — that is not a reference.
    if len(cands) == len(incidents) and len(incidents) > 1:
        cands = []
    if len(cands) == 1:
        return cands[0], None
    if len(cands) > 1:
        return None, ("A few match that — which one? " +
                      ", ".join(i.get("id", "?") for i in cands) + ".")
    return None, ("Which incident should the crew dig into? Open right now: " +
                  _open_list(incidents) + ".")


def parse_command(message: str, pending: list[dict], teams: list[dict],
                  incidents: list[dict]) -> dict:
    """Returns {action, ...} with action in approve/reject/assign/debate/sweep/recommend/clarify/none."""
    text = (message or "").strip()
    low = text.lower()

    m = re.match(r"^(approve|reject|deny|decline)\b(.+)?$", low, re.DOTALL)
    if m:
        verb, rest = m.group(1), (m.group(2) or "").strip()
        action = "approve" if verb == "approve" else "reject"
        if not rest:
            return {"action": "clarify",
                    "reply": f"Which dispatch should I {action}? Name a team or incident."}
        scored = []
        for card in pending:
            team = next((t for t in teams if t.get("id") == card.get("proposed_team_id")), {})
            inc = next((i for i in incidents if i.get("id") == card.get("incident_id")), {})
            hits = 0
            if _team_matches(team, rest):
                hits += 2
            if _incident_matches(inc, rest):
                hits += 1
            if re.search(r"\b" + re.escape(card.get("id", "")) + r"\b", low):
                hits += 3
            if hits:
                scored.append((hits, card))
        if not scored:
            return {"action": "clarify",
                    "reply": "No pending dispatch matches that. Pending cards: " +
                             (", ".join(f"{c.get('proposed_team_id')} for {c.get('incident_id')}"
                                        for c in pending) or "none") + "."}
        scored.sort(key=lambda x: -x[0])
        top = [c for h, c in scored if h == scored[0][0]]
        if len(top) > 1:
            return {"action": "clarify",
                    "reply": "Several pending dispatches match — which incident? " +
                             ", ".join(c.get("incident_id") for c in top) + "."}
        return {"action": action, "pending_id": top[0]["id"],
                "team_id": top[0].get("proposed_team_id"),
                "incident_id": top[0].get("incident_id")}

    m = re.match(r"^assign\s+(.+?)\s+to\s+(.+)$", low, re.DOTALL)
    if m:
        team_ref, inc_ref = m.group(1).strip(), m.group(2).strip()
        team = next((t for t in teams if _team_matches(t, team_ref)), None)
        inc = next((i for i in incidents if _incident_matches(i, inc_ref)), None)
        if team is None:
            return {"action": "clarify",
                    "reply": f"No team matches '{team_ref}'. Name a team from the fleet list."}
        if inc is None:
            cands = [i for i in incidents
                     if i.get("status") in ("NEW", "VERIFIED", "PRIORITIZED",
                                            "UNVERIFIED", "AWAITING_ASSIGNMENT")]
            if len(cands) == 1:
                inc = cands[0]
            else:
                return {"action": "clarify",
                        "reply": f"No incident matches '{inc_ref}'. Give an incident id."}
        return {"action": "assign", "team_id": team["id"], "incident_id": inc["id"]}

    # Monitor sweep — no incident needed.
    if re.search(r"\b(sweep|rescan|monitor sweep)\b", low):
        return {"action": "sweep"}

    # Dispatch recommendation for an incident.
    if re.match(r"^(recommend|suggest|propose)\b", low):
        inc, clarify = _resolve_incident(text, low, incidents)
        if inc is None:
            return {"action": "clarify", "reply": clarify}
        return {"action": "recommend", "incident_id": inc["id"]}

    # Subagent debate chamber for an incident ("launch subagents…").
    if any(w in low for w in _SUBAGENT_WORDS):
        inc, clarify = _resolve_incident(text, low, incidents)
        if inc is None:
            return {"action": "clarify",
                    "reply": clarify + " " + _CAPABILITIES}
        return {"action": "debate", "incident_id": inc["id"]}

    return {"action": "none"}
