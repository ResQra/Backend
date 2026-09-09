"""Phase 6 Coordinator Supervisor — arch §8.

Central reasoning interface, not a free-form SQL chatbot and not an
autonomous commander (§8). Flow (§8.1):

  question → plan read-only tools → execute → combine grounded evidence →
  present recommendation → human approves → track outcome.

Broad read access via controlled tools only (§8.2). Never silently
executes high-impact actions (§8.1.10). Area geometry comes from the UI
explicitly (§8.4): preset id + bounds + optional incident focus.
"""

from __future__ import annotations

import json

from app.services import ops_tools

TOOL_PLAN_RULES = [
    (("team", "boat", "rescue", "dispatch", "nearby"), ["teams", "nearby", "missions"]),
    (("shelter", "capacity", "evacuat", "safe zone"), ["shelters", "capacity", "forecast"]),
    (("road", "blocked", "bridge", "route", "passab", "compare", "alternative"), ["blocked", "bridges", "routes"]),
    (("water", "flood", "river", "rain"), ["water", "hazards"]),
    (("incident", "sos", "trapped", "victim"), ["incidents"]),
    (("pending", "approv", "recommenda"), ["approvals"]),
    (("history", "changed", "timeline", "audit", "log"), ["incident_history", "recent_events", "history"]),
    (("cluster", "hotspot", "concentration", "gathering"), ["incident_cluster"]),
    (("resource", "readiness", "overall"), ["resource_summary"]),
    (("telemet", "live gps", "where is"), ["telemetry"]),
    (("reassess", "re-evaluat"), ["reassessment"]),
    (("forecast", "overflow", "beds left"), ["forecast"]),
    (("lives saved", "run score", "how did"), ["runscore"]),
    (("summar", "happening", "situation", "overview", "picture"), ["picture"]),
]


def plan(question: str) -> list[str]:
    """Deterministic tool plan from keywords (no LLM needed)."""
    q = (question or "").lower()
    picked: list[str] = []
    for keywords, tools in TOOL_PLAN_RULES:
        if any(k in q for k in keywords):
            picked.extend(tools)
    if "picture" not in picked:
        picked.append("picture")
    seen, out = set(), []
    for t in picked:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _bbox_from_context(area_context: dict | None):
    if not area_context:
        return None
    bounds = area_context.get("bounds")
    if isinstance(bounds, (list, tuple)) and len(bounds) == 2:
        return bounds
    return None


def _safe(ev: dict, key: str, fn) -> None:
    """One tool's failure degrades to an error note, never kills evidence."""
    try:
        ev[key] = fn()
    except Exception as exc:
        ev[key + "_error"] = str(exc)[:160]


def execute(plan_names: list[str], area_context: dict | None = None) -> dict:
    """Run read-only tools, return JSON-serializable evidence."""
    bbox = _bbox_from_context(area_context or {})
    focus = (area_context or {}).get("incident_id")
    ev: dict = {"tools_called": plan_names, "area": (area_context or {}).get("area")}
    if "incidents" in plan_names or "picture" in plan_names:
        _safe(ev, "incidents", lambda: [
            {"id": i.get("id"), "status": i.get("status"),
             "score": (i.get("priority") or {}).get("score", 0),
             "people": i.get("people"), "team": i.get("assigned_team")}
            for i in ops_tools.get_active_incidents(bbox)[:10]
        ])
    if "teams" in plan_names or "picture" in plan_names:
        _safe(ev, "teams", lambda: [
            {"id": t.get("id"), "name": t.get("name"), "status": t.get("status"),
             "capacity": t.get("capacity")}
            for t in ops_tools.get_teams(bbox)[:10]
        ])
    if "nearby" in plan_names and focus:
        def _nearby():
            inc = ops_tools.get_incident(focus) or {}
            loc = inc.get("location")
            return ops_tools.get_nearby_teams(loc) if loc else []
        _safe(ev, "nearby_teams", _nearby)
    if "shelters" in plan_names or "capacity" in plan_names:
        _safe(ev, "shelters",
              lambda: ops_tools.get_available_shelter_capacity(bbox)[:10])
    if "blocked" in plan_names or "bridges" in plan_names:
        _safe(ev, "blocked", lambda: [
            {"type": e.get("event_type"), "payload": e.get("payload")}
            for e in ops_tools.get_blocked_roads(bbox)[:10]
        ])
    if "water" in plan_names or "hazards" in plan_names:
        _safe(ev, "hazards", lambda: [
            {"geohash": h.get("geohash"), "level": h.get("level")}
            for h in ops_tools.get_hazard_zones(bbox)[:10]
        ])
    if "missions" in plan_names:
        _safe(ev, "missions", lambda: ops_tools.get_active_missions()[:5])
    if "approvals" in plan_names or "picture" in plan_names:
        _safe(ev, "pending_approvals", lambda: [
            {"id": p.get("id"), "incident_id": p.get("incident_id"),
             "team": p.get("proposed_team_id")}
            for p in ops_tools.get_pending_approvals()[:5]
        ])
    if "incident_history" in plan_names and focus:
        _safe(ev, "incident_history",
              lambda: ops_tools.get_incident_history(focus)[:10])
    if "recent_events" in plan_names:
        _safe(ev, "recent_events", lambda: [
            {"type": e.get("event_type") or e.get("type"),
             "summary": e.get("summary"), "ts": e.get("ts") or e.get("created_at")}
            for e in ops_tools.get_recent_disaster_events(bbox, limit=10)
        ])
    if "incident_cluster" in plan_names:
        _safe(ev, "incident_cluster",
              lambda: ops_tools.get_incident_cluster(bbox))
    if "resource_summary" in plan_names:
        _safe(ev, "resource_summary",
              lambda: ops_tools.get_resource_summary(bbox))
    # Phase G run-operations tools (read-only; reassessment is a preview).
    if "history" in plan_names and focus:
        _safe(ev, "timeline", lambda: [
            {"type": e.get("type"), "summary": e.get("summary"),
             "actor": e.get("actor"), "ts": e.get("ts")}
            for e in ops_tools.get_incident_timeline(focus, limit=20)
        ])
    if "routes" in plan_names and focus:
        def _routes():
            _inc = ops_tools.get_incident(focus) or {}
            _tid = (area_context or {}).get("team_id") or _inc.get("assigned_team")
            return (ops_tools.compare_route_candidates(_tid, focus)
                    if _tid else {"error": "no team in focus"})
        _safe(ev, "route_comparison", _routes)
    if "telemetry" in plan_names:
        def _telemetry():
            _inc = ops_tools.get_incident(focus) if focus else {}
            _tid = (area_context or {}).get("team_id") or (_inc or {}).get("assigned_team")
            return (ops_tools.get_team_telemetry(_tid)
                    if _tid else {"error": "no team in focus"})
        _safe(ev, "team_telemetry", _telemetry)
    if "reassessment" in plan_names and focus:
        _safe(ev, "reassessment", lambda: ops_tools.request_reassessment(focus))
    if "forecast" in plan_names:
        _safe(ev, "shelter_forecast",
              lambda: ops_tools.get_shelter_forecast(bbox))
    if "runscore" in plan_names and (area_context or {}).get("run_id"):
        _safe(ev, "run_score",
              lambda: ops_tools.get_run_score((area_context or {})["run_id"]))
    _safe(ev, "picture",
          lambda: ops_tools.get_current_operational_picture(bbox))
    return json.loads(json.dumps(ev, default=str))


def compose_template(question: str, evidence: dict) -> str:
    """Deterministic grounded reply (no LLM) citing real IDs."""
    pic = evidence.get("picture", {})
    lines = [
        f"Operational picture: {pic.get('active_incidents', 0)} active incidents, "
        f"{pic.get('critical', 0)} critical, {pic.get('teams_available', 0)}/"
        f"{pic.get('teams_total', 0)} teams available, "
        f"{pic.get('pending_approvals', 0)} pending approvals."
    ]
    if evidence.get("incidents"):
        top = [i for i in evidence["incidents"][:3] if isinstance(i, dict)]
        lines.append("Top incidents: " + ", ".join(
            f"{i.get('id')} (score {i.get('score', 0)}, {i.get('status')})" for i in top))
    if evidence.get("teams"):
        avail = [t for t in evidence["teams"]
                 if isinstance(t, dict) and t.get("status") == "AVAILABLE"][:3]
        if avail:
            lines.append("Available teams: " + ", ".join(
                f"{t.get('name') or t.get('id')} (cap {t.get('capacity')})" for t in avail))
    if evidence.get("shelters"):
        top = [s for s in evidence["shelters"][:3] if isinstance(s, dict)]
        lines.append("Shelter space: " + ", ".join(
            f"{s.get('name') or s.get('id')} ({s.get('free', 0)} free)" for s in top))
    if evidence.get("blocked"):
        lines.append(f"Blockages on record: {len(evidence['blocked'])}.")
    if evidence.get("incident_cluster"):
        top = evidence["incident_cluster"][:3]
        lines.append("Clusters: " + ", ".join(
            f"{c['geohash']} ({c['count']} SOS: {', '.join(c['ids'][:3])})" for c in top))
    if evidence.get("recent_events"):
        lines.append(f"Latest change: {evidence['recent_events'][0].get('summary') or evidence['recent_events'][0].get('type')}.")
    if evidence.get("incident_history"):
        lines.append(f"Incident timeline: {len(evidence['incident_history'])} recorded events.")
    if evidence.get("timeline"):
        lines.append(f"Incident timeline: {len(evidence['timeline'])} recorded events.")
    if evidence.get("route_comparison", {}).get("recommended_id"):
        lines.append(f"Best route: {evidence['route_comparison']['recommended_id']}.")
    if evidence.get("team_telemetry", {}).get("location"):
        _t = evidence["team_telemetry"]
        lines.append(f"Team {_t.get('name') or _t.get('team_id')} is {_t.get('status')}"
                     + (" (GPS stale)" if _t.get("stale") else " (GPS live)") + ".")
    if evidence.get("shelter_forecast") is not None:
        _full = sum(1 for s in evidence["shelter_forecast"] if s.get("pressure") == "FULL")
        lines.append(f"Shelters: {len(evidence['shelter_forecast'])} open, {_full} full.")
    if evidence.get("run_score", {}).get("run_id"):
        _rs = evidence["run_score"]
        lines.append(f"Run score: {_rs.get('lives_saved', 0)} saved, "
                     f"{_rs.get('lives_at_risk', 0)} at risk.")
    if evidence.get("resource_summary"):
        rs = evidence["resource_summary"]
        lines.append("Readiness: " + ", ".join(
            f"{k} {v}" for k, v in (rs.get("teams_by_status") or {}).items())
            + f" · {rs.get('missions_active', 0)} missions · {rs.get('shelter_beds_free', 0)} beds free.")
    if evidence.get("pending_approvals"):
        lines.append("Pending approvals: " + ", ".join(
            p["id"] for p in evidence["pending_approvals"][:3])
            + " — review in the Decision Cockpit.")
    lines.append("Recommendations need human approval before execution.")
    return "\n".join(f"• {l}" for l in lines)


async def supervise(question: str, area_context: dict | None = None,
                    history: list | None = None) -> dict:
    """Full supervisor pass → {reply, evidence, tools_called}."""
    names = plan(question)
    evidence = execute(names, area_context)

    try:
        from app.agents_gateway import gateway
        from app.config import settings

        if settings.groq_api_key:
            snapshot = {
                "question": question, "area": (area_context or {}).get("area"),
                "evidence": evidence,
                "policy": ("Cite incident/team/shelter IDs exactly. "
                           "Recommend; never claim execution. If evidence is thin, say so."),
            }
            reply = await gateway.coordinator_assistant(
                question, snapshot, history or [])
            return {"reply": reply, "evidence": evidence, "tools_called": names}
    except Exception:
        pass

    try:
        from app.db.repos import activity

        activity.log_event(
            actor="agent", type_="supervisor_query",
            summary=f"Supervisor answered with tools {','.join(names)}",
            payload={"question": question[:200], "tools": names,
                     "area": (area_context or {}).get("area")})
    except Exception:
        pass
    return {"reply": compose_template(question, evidence),
            "evidence": evidence, "tools_called": names}
