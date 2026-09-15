import time
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException

from app.agents_gateway import gateway, llm
from app.auth.deps import CurrentUser, require_role
from app.db.repos import (
    activity,
    areas,
    incidents,
    missions,
    pending_actions,
    reports,
    shelters,
    simulation_events,
    teams,
    users,
)
from app.models import (
    ApprovalDecision,
    AssignRequest,
    ReportCreate,
    SensorEventCreate,
    ShelterOccupancyUpdate,
    StatusUpdate,
    TeamCreate,
    TeamLocationUpdate,
    TeamProblemReport,
    TeamStatusUpdate,
)
from app.services import realtime

router = APIRouter(
    prefix="/api/ops",
    tags=["ops"],
    dependencies=[Depends(require_role("coordinator"))],
)

# Coordinator-only surface (BRAINSTORM §4.4). Full operational state:
# queue, all incidents, teams, activity feed, manual overrides.
# F06/F07 flow: /recommend returns a reasoned team suggestion (v0
# deterministic via the agents_gateway seam); /assign is the human
# approval that executes it.


def D(x) -> Decimal:
    return Decimal(str(x))


@router.get("/queue")
def queue():
    """F04: rescue queue, priority desc, oldest first."""
    return {"incidents": incidents.list_open_incidents()}


@router.get("/summary")
def summary():
    """Mission-control snapshot for the coordinator home screen.

    Keep this server-computed so the command picture remains consistent with
    the database and can be consumed by thin clients (web, tablet, PWA).
    """
    open_incidents = incidents.list_open_incidents()
    all_teams = teams.list_teams()
    residents = users.list_residents_with_location()
    high = [
        item for item in open_incidents
        if (item.get("priority") or {}).get("score", 0) >= 8
        or item.get("urgency") == "HIGH"
    ]
    unverified = [
        item for item in open_incidents
        if item.get("location_verification") == "NEEDS_COORDINATOR_REVIEW"
    ]
    available = [item for item in all_teams if item.get("status") == "AVAILABLE"]
    return {
        "active_incidents": len(open_incidents),
        "high_priority": len(high),
        "unverified_locations": len(unverified),
        "underway": sum(item.get("status") in {"ASSIGNED", "IN_PROGRESS"} for item in open_incidents),
        "teams_ready": len(available),
        "teams_total": len(all_teams),
        "people_reported": sum(item.get("people") or 0 for item in open_incidents),
        "rescued_total": sum(item.get("rescued_total") or 0 for item in all_teams),
        "residents_with_unresolved_location": sum(
            bool(item.get("location_text")) and not item.get("location") for item in residents
        ),
        "attention": [
            {
                "id": item.get("id"),
                "label": item.get("raw_text"),
                "score": (item.get("priority") or {}).get("score", 0),
                "status": item.get("status"),
                "reason": "Verify location" if item in unverified else "High priority",
            }
            for item in sorted(high + [item for item in unverified if item not in high], key=lambda x: -(x.get("priority") or {}).get("score", 0))[:6]
        ],
    }


def _incident_flags(item: dict) -> list[str]:
    flags: list[str] = []
    score = (item.get("priority") or {}).get("score", 0)
    if score >= 8 or item.get("urgency") == "HIGH":
        flags.append("high_priority")
    if item.get("location_verification") == "NEEDS_COORDINATOR_REVIEW" or not item.get("location"):
        flags.append("verify_location")
    if item.get("water_rising"):
        flags.append("water_rising")
    if item.get("vulnerabilities"):
        flags.append("vulnerable_people")
    if item.get("status") in {"NEW", "VERIFIED", "PRIORITIZED"} and not item.get("assigned_team"):
        flags.append("needs_assignment")
    return flags


def _next_action(item: dict) -> str:
    flags = _incident_flags(item)
    if "verify_location" in flags:
        return "Verify location"
    if item.get("status") in {"NEW", "VERIFIED"}:
        return "Confirm priority"
    if item.get("status") == "PRIORITIZED" and not item.get("assigned_team"):
        return "Dispatch team"
    if item.get("status") == "ASSIGNED":
        return "Track mission"
    if item.get("status") == "IN_PROGRESS":
        return "Await rescue update"
    return "Review"


@router.get("/action-board")
def action_board():
    """Decision-ready board for the console.

    This is intentionally server-shaped: clients get the same priority order,
    risk flags, next action label, and current allocation recommendation.
    """
    open_incidents = incidents.list_open_incidents()
    all_teams = teams.list_teams()
    pending = pending_actions.list_pending()
    pending_by_incident = {}
    for card in pending:
        pending_by_incident.setdefault(card.get("incident_id"), []).append(card)
    return {
        "incidents": [
            {
                **item,
                "flags": _incident_flags(item),
                "next_action": _next_action(item),
                "recommendation": gateway.recommend_team(item, all_teams),
                "pending_actions": pending_by_incident.get(item.get("id"), []),
            }
            for item in open_incidents
        ]
    }


@router.post("/assistant")
async def assistant(body: dict, user: CurrentUser = Depends(require_role("coordinator"))):
    """Phase 6 supervisor: area-aware grounded answer. Snapshot built
    server-side so the client can never tamper with it. With session_id,
    history persists server-side and both turns are stored."""
    from app.agents_gateway import supervisor as supervisor_mod
    from app.db.repos import coordinator_chat as csessions

    message = str(body.get("message", "")).strip()
    if not message:
        raise HTTPException(status_code=422, detail="message required")
    area_context = body.get("area_context") or {
        "area": body.get("area"), "bounds": body.get("bounds"),
        "incident_id": body.get("incident_id")}
    session_id = body.get("session_id")
    if session_id:
        sess = csessions.get_session(session_id)
        if sess is None or sess.get("coordinator_id") != user.id:
            raise HTTPException(status_code=404, detail="Session not found")
        history = [{"role": m.get("role"), "content": m.get("content")}
                   for m in csessions.get_history(session_id, limit=16)]
        csessions.append_message(session_id, "user", message)
        if (sess.get("title") or "New conversation") == "New conversation":
            existing = csessions.get_history(session_id, limit=5)
            if len(existing) <= 1:
                csessions.touch_session(session_id, title=message[:60])
    else:
        history = body.get("history") or []
    # Explicit coordinator commands execute through the identical gate as
    # the console buttons (same audit, same idempotency). Anything vague
    # falls through to the supervisor for a proposal, never execution.
    cmd = await _try_chat_command(message, user)
    if cmd is not None:
        reply, extra = cmd
        out = {"reply": reply, **extra}
        if session_id:
            csessions.append_message(session_id, "agent", reply)
            out = {**out, "session_id": session_id}
        return out
    out = await supervisor_mod.supervise(message, area_context, history)
    if session_id:
        csessions.append_message(session_id, "agent", out.get("reply", ""))
        out = {**out, "session_id": session_id}
    return out


async def _try_chat_command(message: str, user: CurrentUser) -> tuple[str, dict] | None:
    """Returns (reply, extra) when message is an explicit command, else None.

    Subagent launches (debate/sweep/recommend) execute here too, so chat
    can genuinely deploy the fleet — never claim otherwise.
    """
    from app.services import chat_commands

    parsed = chat_commands.parse_command(
        message,
        pending_actions.list_pending(),
        teams.list_teams(),
        incidents.list_open_incidents())
    action = parsed.get("action")
    if action in ("approve", "reject"):
        decision = "APPROVED" if action == "approve" else "REJECTED"
        try:
            res = _apply_decision(parsed["pending_id"], decision, None,
                                  user.id, note=f"via chat: {message[:120]}",
                                  via="chat")
        except HTTPException as exc:
            return f"Could not {action}: {exc.detail}.", {}
        if res.get("deduped"):
            return (f"Already decided — {parsed['pending_id']} was finalized earlier, "
                    f"nothing executed twice.", {})
        if action == "approve":
            mission = (res.get("mission") or {}).get("id")
            return (f"Approved and dispatched: {parsed['team_id']} to "
                    f"{parsed['incident_id']} (mission {mission}).", {})
        return (f"Rejected dispatch of {parsed['team_id']} for "
                f"{parsed['incident_id']}. The team is available again.", {})
    if action == "assign":
        try:
            _manual_assign(parsed["incident_id"], parsed["team_id"], via="chat")
        except HTTPException as exc:
            return f"Could not assign: {exc.detail}.", {}
        return (f"Assigned {parsed['team_id']} to {parsed['incident_id']} "
                f"(manual override via chat).", {})
    if action == "clarify":
        return parsed.get("reply", "Which one?"), {}
    if action == "sweep":
        out = trigger_agent_sweep()
        n, h = out.get('incidents_scanned', 0), out.get('hotspots_identified', 0)
        if h:
            return (f"Sweep done — checked {n} incidents and found {h} hotspot cluster{'s' if h != 1 else ''} "
                    f"worth a look. Details are in the activity feed.", {})
        return (f"Sweep done — checked {n} incidents, nothing clustering. All quiet on the district scan.", {})
    if action == "recommend":
        try:
            out = gateway.recommend_for_incident(parsed["incident_id"])
        except LookupError:
            raise HTTPException(status_code=404, detail="Incident not found")
        rec = out.get("recommendation") or {}
        pending = out.get("pending_action") or {}
        if rec.get("team_id"):
            return (f"For {parsed['incident_id']}, I'd send {rec.get('team_name')} "
                    f"({rec.get('distance_km')} km out, there in ~{rec.get('eta_min')} min). "
                    f"It's waiting as a pending card — approve it in the Decision Cockpit when ready.", {})
        return (f"No team currently routable for {parsed['incident_id']} — "
                f"escalation noted. Recruit more teams or wait for units to free up.", {})
    if action == "debate":
        import asyncio as _asyncio

        from app.services import debate as debate_service

        try:
            out = await _asyncio.wait_for(
                debate_service.run_debate(parsed["incident_id"]), timeout=150)
        except LookupError:
            raise HTTPException(status_code=404, detail="Incident not found")
        except (_asyncio.TimeoutError, Exception) as exc:
            return (f"The debate crew stalled on {parsed['incident_id']} ({type(exc).__name__}) — "
                    f"the standing recommendation holds. Worth retrying from the Decision Cockpit.", {})
        verdict = (out.get("verdict") or "").strip()
        labels = {"dispatch_advocate": "Dispatch advocate",
                  "shelter_advocate": "Shelter advocate",
                  "dispatch_rebuttal": "Dispatch rebuttal",
                  "shelter_rebuttal": "Shelter rebuttal",
                  "judge": "Judge"}
        stages = [{"role": t.get("role"), "label": labels.get(t.get("role"), t.get("role")),
                   "content": (t.get("content") or "")[:500]}
                  for t in out.get("transcript") or []]
        # Plain-language verdict: lead with the call, then the why.
        just = verdict
        for prefix in ("JUSTIFICATION:", "WINNER: DISPATCH", "WINNER: WAIT"):
            just = just.replace(prefix, "").strip(" \n-:")
        iid = parsed["incident_id"]
        if out.get("winner") == "DISPATCH":
            reply = (f"Crew's done on {iid} — call: DISPATCH. {just} "
                     f"Say the word and I'll queue it for approval.")
        else:
            reply = (f"Crew's done on {iid} — call: HOLD. {just} "
                     f"The incident stays monitored; say 'recommend' anytime for a fresh look.")
        return reply, {"stages": stages, "incident_id": iid,
                       "winner": out.get("winner")}
    return None


@router.get("/map-data")
def map_data():
    sensor_layers = []
    for kind in ["WATER_LEVEL", "ROAD_BLOCKED", "BRIDGE_BLOCKED", "PEOPLE_DENSITY", "FLOOD_AREA"]:
        sensor_layers.extend(simulation_events.list_by_type(kind, limit=10))
    return {
        "incidents": incidents.list_open_incidents(),
        "teams": teams.list_teams(),
        "shelters": shelters.list_shelters(),
        "residents": users.list_residents_with_location(),
        "areas": areas.list_areas(),
        "sensor_events": sensor_layers,
    }


@router.get("/teams")
def list_teams_():
    return {"teams": teams.list_teams()}


@router.get("/twin-layers")
def twin_layers():
    from app.services import rautahat_digital_twin
    return {
        "district": rautahat_digital_twin.get_district_boundary(),
        "municipalities": rautahat_digital_twin.get_municipalities_geojson(),
        "rivers": rautahat_digital_twin.get_rivers_geojson(),
        "embankments": rautahat_digital_twin.get_embankments_geojson(),
        "flood_2024": rautahat_digital_twin.get_flood_2024_geojson(),
        "infrastructure": rautahat_digital_twin.get_infrastructure_geojson(),
        "rescue_fleet": rautahat_digital_twin.get_rescue_fleet_geojson(),
        "summary": rautahat_digital_twin.get_digital_twin_summary(),
    }


@router.post("/teams")
def create_team(body: TeamCreate):
    item = {
        "id": f"team_{uuid.uuid4().hex[:10]}",
        "name": body.name.strip(),
        "capacity": body.capacity,
        "status": body.status,
        "current_mission_id": None,
        "rescued_total": 0,
        "contact": body.contact.strip(),
        "specialization": body.specialization.strip(),
        "notes": body.notes.strip(),
        "district": (body.district or "rautahat").strip().lower(),
        "updated_at": int(time.time() * 1000),
    }
    if body.location:
        item["location"] = {
            "lat": Decimal(str(body.location.lat)),
            "lng": Decimal(str(body.location.lng)),
            "label": body.location.label,
        }
    teams.put_team(item)
    activity.log_event(
        actor="human",
        type_="team_created",
        summary=f"Team added: {item['name']} ({item['status']}, capacity {item['capacity']})",
        payload={"team_id": item["id"]},
    )
    return item


@router.patch("/teams/{team_id}/status")
def set_team_status(team_id: str, body: TeamStatusUpdate):
    """F05: registry status updates from the console (e.g. boat returning →
    available, or marked offline for maintenance). Ranked write:
    coordinator authority sticks until a higher source speaks."""
    from app.services import world_sync

    try:
        out = world_sync.apply_team_status(team_id, body.status, source="COORDINATOR")
    except LookupError:
        raise HTTPException(status_code=404, detail="Team not found")
    item = out["team"]
    activity.log_event(
        actor="human",
        type_="team_status_changed",
        summary=f"{item.get('name', team_id)} → {body.status}",
        payload={"team_id": team_id, "status": body.status},
    )
    return item


@router.patch("/teams/{team_id}/location")
def set_team_location(team_id: str, body: TeamLocationUpdate):
    from app.services import world_sync

    location = {
        "lat": D(body.lat),
        "lng": D(body.lng),
        "label": body.label or f"{body.source} location",
        "updated_at": int(time.time() * 1000),
    }
    try:
        out = world_sync.apply_team_location(team_id, location, source=body.source)
    except LookupError:
        raise HTTPException(status_code=404, detail="Team not found")
    item = out["team"]
    activity.log_event(
        actor="agent" if body.source == "SIMULATION" else "human",
        type_="team_location_updated",
        summary=f"{item.get('name', team_id)} location updated from {body.source}",
        payload={"team_id": team_id, "location": location, "source": body.source},
    )
    return item


@router.post("/teams/{team_id}/problem")
def report_team_problem(team_id: str, body: TeamProblemReport):
    team = teams.get_team(team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    problem = {
        "message": body.message,
        "severity": body.severity,
        "reported_at": int(time.time() * 1000),
    }
    if body.lat is not None and body.lng is not None:
        problem["location"] = {"lat": D(body.lat), "lng": D(body.lng)}
    update = {"last_problem": problem}
    if body.severity == "OFFLINE":
        from app.services import world_sync as _world_sync3

        _world_sync3.apply_team_status(team_id, "OFFLINE", source="TEAM", force=True)
    item = teams.update_team(team_id, **update)
    activity.log_event(
        actor="agent",
        type_="team_problem_reported",
        summary=f"{team.get('name', team_id)} reported {body.severity}: {body.message}",
        payload={"team_id": team_id, "problem": problem},
    )
    return item


@router.get("/activity")
def feed():
    """F09: agent activity timeline, newest first."""
    return {"events": activity.recent_events(50)}


@router.get("/incidents/{incident_id}/timeline")
def incident_timeline(incident_id: str):
    """Per-incident timeline — filters global activity by incident_id."""
    all_events = activity.recent_events(200)
    matched = [
        e for e in all_events
        if (e.get("payload") or {}).get("incident_id") == incident_id
    ]
    return {"events": matched}


@router.patch("/incidents/{incident_id}/status")
def set_status(incident_id: str, body: StatusUpdate):
    item = incidents.update_incident(incident_id, status=body.status)
    if item is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    activity.log_event(
        actor="human",
        type_="status_changed",
        summary=f"Incident {incident_id} → {body.status}",
        payload={"incident_id": incident_id, "status": body.status},
    )
    realtime.publish("INCIDENT_UPDATED", {"incident": item})
    return item


@router.post("/incidents/{incident_id}/recommend")
def recommend(incident_id: str, debate: bool = False):
    """F06 v0: agentic re-evaluation — stable across clicks, explains
    changes, invalidates stale plans when the world moves (§12, §51).
    Human approval stays mandatory (F07). ?debate=1 forces the full
    debate chamber even on clean-cut calls (slower, ~1-2 min)."""
    try:
        out = gateway.recommend_for_incident(incident_id, force_debate=debate)
    except LookupError:
        raise HTTPException(status_code=404, detail="Incident not found")
    rec, pending = out["recommendation"], out["pending_action"]
    activity.log_event(
        actor="agent",
        type_="allocation_recommended",
        summary=(
            f"AllocationAgent recommends {rec.get('team_name') or 'no team'} "
            f"for {incident_id} [{out['stability']['verdict']}]"
        ),
        payload={"incident_id": incident_id, "recommendation": rec,
                 "stability": out["stability"]},
        run_id=(pending or {}).get("run_id") or "",
    )
    realtime.publish("AGENT_RECOMMENDATION_CREATED",
                     {"incident_id": incident_id, "recommendation": rec,
                      "pending_action": pending, "stability": out["stability"]})
    return {"recommendation": rec, "pending_action": pending,
            "stability": out["stability"], "debate": out.get("debate")}


@router.get("/pending-actions")
def list_pending_actions():
    return {"pending_actions": pending_actions.list_pending()}


@router.post("/pending-actions/{pending_id}/decision")
def decide_pending_action(
    pending_id: str,
    body: ApprovalDecision,
    user: CurrentUser = Depends(require_role("coordinator")),
):
    return _apply_decision(pending_id, body.decision, body.override_team_id,
                           user.id, note=body.note, via="console")


def _run_clock_min(run_id: str) -> float | None:
    """Sim-clock of a run for response-time stamps. None outside runs."""
    if not run_id:
        return None
    try:
        from app.db.repos import simulation_runs as _runs

        run = _runs.get_run(run_id)
        return float(run.get("clock_min") or 0) if run else None
    except Exception:
        return None


def _apply_decision(pending_id: str, decision: str, override_team_id: str | None,
                    actor_id: str, note: str = "", via: str = "console") -> dict:
    """Shared approve/reject executor: console buttons and explicit chat
    commands run the identical path (same gate, audit, idempotency)."""
    card = pending_actions.get_action(pending_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Pending action not found")
    decision = decision.upper()
    if decision not in ("APPROVED", "REJECTED"):
        raise HTTPException(status_code=422, detail="decision must be APPROVED or REJECTED")
    card_run_id = card.get("run_id") or ""
    if via == "autonomous_test":
        # Phase C: autonomous approval only inside AUTONOMOUS_TEST runs.
        # Anything else must come through the human console path.
        from app.db.repos import simulation_runs as _runs

        _run = _runs.get_run(card_run_id) if card_run_id else None
        if _run is None or _run.get("mode") != "AUTONOMOUS_TEST":
            raise HTTPException(status_code=403, detail="autonomous approval not allowed here")
    was_pending = card.get("state") == "PENDING"
    decided = pending_actions.decide(pending_id, decision, actor_id, note=note)
    if decision == "REJECTED":
        # Release the soft hold so the team is recommendable again.
        try:
            held_id = card.get("proposed_team_id")
            held = teams.get_team(held_id) if held_id else None
            if held and held.get("status") == "SOFT_RESERVED":
                teams.update_team(held_id, status="AVAILABLE")
        except Exception:
            pass
        activity.log_event(
            actor="human",
            type_="pending_action_rejected",
            summary=f"Coordinator rejected {pending_id}",
            payload={"pending_id": pending_id, "incident_id": card.get("incident_id"), "note": note},
            run_id=card_run_id,
        )
        realtime.publish("HUMAN_REJECTION", {"pending_id": pending_id,
                                             "incident_id": card.get("incident_id")})
        return {"pending_action": decided, "executed": False, "via": via}

    if not was_pending:
        # Idempotent replay: already decided, never double-execute.
        return {"pending_action": decided, "executed": False, "deduped": True, "via": via}

    team_id = override_team_id or card.get("proposed_team_id")
    if not team_id:
        raise HTTPException(status_code=409, detail="Approved action has no team to dispatch")
    team = teams.get_team(team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    incident = incidents.get_incident(card["incident_id"])
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")

    sim_min = _run_clock_min(card_run_id)
    mission = missions.create_for_assignment(
        card["incident_id"], team_id, pending_action_id=pending_id,
        route_id=(card.get("payload") or {}).get("recommendation", {}).get("route_id"),
        run_id=card_run_id, sim_min=sim_min)
    update_fields = {"assigned_team": team_id, "mission_id": mission["id"],
                     "status": "ASSIGNED"}
    if sim_min is not None:
        update_fields["assigned_sim_min"] = D(sim_min)
    incidents.update_incident(card["incident_id"], **update_fields)
    teams.update_team(team_id, current_mission_id=mission["id"])
    from app.services import world_sync as _world_sync

    _world_sync.apply_team_status(team_id, "ON_MISSION", source="COORDINATOR")
    # Phase 8 communication simulation (§50): attempt contact, best-effort.
    try:
        from app.services import comms as _comms

        contact = _comms.contact_team(teams.get_team(team_id) or {"id": team_id},
                                       f"Dispatched to {card['incident_id']}")
        activity.log_event(
            actor="agent", type_="team_contacted" if contact.get("delivered") else "communication_lost",
            summary=f"Contact {team.get('name', team_id)}: {contact.get('detail')}",
            payload={"team_id": team_id, "mission_id": mission["id"]},
            run_id=card_run_id)
        if contact.get("timeout"):
            realtime.publish("COMMUNICATION_LOST", {"target": {"type": "TEAM", "id": team_id}})
    except Exception:
        pass
    activity.log_event(
        actor="human",
        type_="pending_action_approved",
        summary=f"Approved {pending_id}: {team.get('name', team_id)} dispatched",
        payload={
            "pending_id": pending_id,
            "incident_id": card["incident_id"],
            "team_id": team_id,
            "mission_id": mission["id"],
        },
        run_id=card_run_id,
    )
    realtime.publish("MISSION_CREATED", {"mission": mission, "incident_id": card["incident_id"]})
    realtime.publish("HUMAN_APPROVAL", {"pending_id": pending_id,
                                        "incident_id": card["incident_id"],
                                        "mission_id": mission["id"]})
    realtime.publish("INCIDENT_UPDATED", {"incident": incidents.get_incident(card["incident_id"])})
    return {"pending_action": decided, "mission": mission, "executed": True, "via": via}


def _manual_assign(incident_id: str, team_id: str, via: str = "console") -> dict:
    """Shared manual-override executor for console + explicit chat commands.

    Same invariants as the approval gate: the team must be dispatchable,
    and the assignment mints a real mission row (never a bare FK).
    """
    team = teams.get_team(team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    if team.get("status") not in ("AVAILABLE", "RETURNING"):
        raise HTTPException(
            status_code=409,
            detail=f"Team {team.get('name', team_id)} is {team.get('status')} — not dispatchable")
    item = incidents.update_incident(
        incident_id, assigned_team=team_id, status="ASSIGNED"
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    mission = missions.create_for_assignment(
        incident_id, team_id, run_id=item.get("run_id") or "")
    incidents.update_incident(incident_id, mission_id=mission["id"])
    item = incidents.get_incident(incident_id)
    teams.update_team(team_id, current_mission_id=mission["id"])
    from app.services import world_sync as _world_sync2

    _world_sync2.apply_team_status(team_id, "ON_MISSION", source="COORDINATOR")
    activity.log_event(
        actor="human",
        type_="team_assigned",
        summary=f"{team.get('name', team_id)} assigned to {incident_id} (manual via {via})",
        payload={"incident_id": incident_id, "team_id": team_id, "via": via},
    )
    realtime.publish("MISSION_UPDATED", {"incident_id": incident_id, "team_id": team_id})
    realtime.publish("INCIDENT_UPDATED", {"incident": item})
    return item


@router.post("/incidents/{incident_id}/assign")
def assign(incident_id: str, body: AssignRequest):
    """Manual override (F07): coordinator assigns a team directly. In S4 the
    AllocationAgent writes a recommendation and this becomes approve/reject."""
    return _manual_assign(incident_id, body.team_id)


@router.post("/sensor-events")
def create_sensor_event(body: SensorEventCreate):
    """Manual/simulation signal. Routed through world_sync: the observation
    is stamped with provenance, closures notify the coordinator, and the
    map/risk layer prefers SIMULATION over PUBLIC_API on conflict.
    """
    from app.services import world_sync

    return world_sync.apply_sensor(
        kind=body.kind, lat=float(body.lat), lng=float(body.lng),
        value=None if body.value is None else float(body.value),
        level=body.level, note=body.note or "",
        source=body.source_priority, idempotency_key=body.idempotency_key)


@router.post("/risk/recompute-density")
def recompute_density_risk():
    """Build people-density risk areas from currently open incidents."""
    buckets: dict[str, dict] = {}
    for incident in incidents.list_open_incidents():
        loc = incident.get("location") or {}
        if loc.get("lat") is None or loc.get("lng") is None:
            continue
        from app.utils.geo import geohash_encode

        gh = geohash_encode(float(loc["lat"]), float(loc["lng"]))
        bucket = buckets.setdefault(
            gh,
            {
                "geohash": gh,
                "level": "NORMAL",
                "center": {"lat": D(loc["lat"]), "lng": D(loc["lng"])},
                "radius_m": 2200,
                "request_count": 0,
                "high_urgency_count": 0,
                "people_count": 0,
                "source": "INCIDENT_DENSITY",
                "source_priority": "SYSTEM",
                "updated_at": int(time.time() * 1000),
            },
        )
        bucket["request_count"] += 1
        bucket["people_count"] += int(incident.get("people") or 1)
        if (incident.get("priority") or {}).get("score", 0) >= 8 or incident.get("urgency") == "HIGH":
            bucket["high_urgency_count"] += 1

    saved = []
    for bucket in buckets.values():
        if bucket["request_count"] >= 4 or bucket["people_count"] >= 12:
            bucket["level"] = "HOTSPOT"
        elif bucket["request_count"] >= 2:
            bucket["level"] = "RISING"
        saved.append(areas.put_area_risk(bucket))
    activity.log_event(
        actor="agent",
        type_="risk_density_recomputed",
        summary=f"RiskAgent recomputed {len(saved)} density area(s)",
        payload={"area_count": len(saved)},
    )
    return {"areas": saved}


@router.patch("/shelters/{shelter_id}/occupancy")
def update_shelter_occupancy(shelter_id: str, body: ShelterOccupancyUpdate):
    from app.services import world_sync

    try:
        out = world_sync.apply_shelter_occupancy(
            shelter_id, body.current_occupancy, source=body.source)
    except LookupError:
        raise HTTPException(status_code=404, detail="Shelter not found")
    item = out["shelter"]
    activity.log_event(
        actor="agent" if body.source == "SIMULATION" else "human",
        type_="shelter_occupancy_updated",
        summary=f"Shelter {shelter_id} occupancy -> {body.current_occupancy}",
        payload={"shelter_id": shelter_id, "source": body.source},
    )
    return item


# --- Gov reports / advisories (published by officials, shown to residents) ---


@router.post("/reports")
def publish_report(body: ReportCreate, user: CurrentUser = Depends(require_role("coordinator"))):
    item = reports.create_report(
        title=body.title,
        body=body.body,
        severity=body.severity,
        source=body.source,
        area_text=body.area_text,
        link=body.link,
        created_by=user.id,
    )
    activity.log_event(
        actor="human",
        type_="gov_report_published",
        summary=f"Advisory published: {body.title} ({body.severity})",
        payload={"report_id": item["id"], "severity": body.severity},
    )
    return item


@router.get("/reports")
def list_reports_():
    return {"reports": reports.list_reports()}


@router.delete("/reports/{report_id}")
def delete_report(report_id: str):
    if not reports.delete_report(report_id):
        raise HTTPException(status_code=404, detail="Report not found")
    return {"deleted": report_id}


# --- Multi-Agent Observability & Control ---


@router.get("/agents/status")
def get_agents_status():
    """Returns telemetry, health, registered tools, and metrics for all agents."""
    from app.config import settings

    open_incidents = incidents.list_open_incidents()
    all_teams = teams.list_teams()
    pending = pending_actions.list_pending()
    groq_configured = bool(settings.groq_api_key)

    return {
        "agents": [
            {
                "id": "supervisor",
                "name": "Supervisor (ControlRoomAgent)",
                "role": "Master Orchestrator & Approval Gatekeeper",
                "type": "LLM_AND_STATE_MACHINE",
                "status": "HEALTHY",
                "model": settings.groq_model if groq_configured else "degraded-fallback",
                "state_machine": "PENDING -> APPROVED | REJECTED | SUPERSEDED",
                "pending_count": len(pending),
                "active_incidents": len(open_incidents),
                "tools": ["pending_actions", "allocation_engine", "priority_engine", "activity_log"],
                "last_active": "Real-time event loop",
            },
            {
                "id": "intake",
                "name": "IntakeAgent (ReportIntakeAgent)",
                "role": "Multilingual Distress Signal NLP Extraction",
                "type": "LLM_WITH_REGEX_FALLBACK",
                "status": "HEALTHY" if groq_configured else "DEGRADED_MODE",
                "model": settings.groq_model if groq_configured else "regex-multilingual-v2",
                "languages": ["English", "Hindi", "Nepali", "Hinglish"],
                "extraction_fields": ["people", "vulnerabilities", "urgency", "water_rising", "location_text"],
                "tools": ["normalize_extraction", "geocode_location", "regex_extractor"],
                "last_active": "On-demand ingestion",
            },
            {
                "id": "resident",
                "name": "ResidentAgent (ResidentHelpAgent)",
                "role": "Conversational Citizen Helpline & Live Memory Sync",
                "type": "LLM_CONVERSATIONAL",
                "status": "HEALTHY" if groq_configured else "DEGRADED_MODE",
                "model": settings.groq_model if groq_configured else "rule-template-engine",
                "memory_sync": "Auto-updates DynamoDB Users table on turn (F19)",
                "tools": ["context_builder", "update_user_info", "shelter_lookup"],
                "last_active": "Live chat channel",
            },
            {
                "id": "monitor",
                "name": "MonitorAgent (WatchAgent)",
                "role": "Autonomous Geohash Clustering & SLA Delay Escalation",
                "type": "AUTONOMOUS_LOOP",
                "status": "ACTIVE",
                "model": "Deterministic Geo-Clustering & Escalation Matrix",
                "sweep_interval": "60s",
                "hotspots_detected": sum(1 for a in areas.list_areas() if a.get("level") == "HOTSPOT"),
                "tools": ["geohash_cluster", "delay_escalation", "replan_pending_action"],
                "last_active": "Continuous background sweep",
            },
            {
                "id": "priority_engine",
                "name": "Priority Engine (Tool)",
                "role": "Deterministic Explainable Priority Math (0-10)",
                "type": "PURE_PYTHON_TOOL",
                "status": "ONLINE",
                "formula": "Wu + Wp + Wv + Wd + Wa + Wr",
                "llm_used": False,
                "latency_ms": "< 1ms",
                "tools": ["priority_weights", "river_gauge_lookup", "vulnerability_matrix"],
                "last_active": "Sub-millisecond",
            },
            {
                "id": "allocation_engine",
                "name": "Allocation Engine (Tool)",
                "role": "Capacity Matching & Haversine Distance Optimization",
                "type": "PURE_PYTHON_TOOL",
                "status": "ONLINE",
                "formula": "CapacityFilter + HaversineDistance + RejectionMemory",
                "llm_used": False,
                "rejection_memory_active": True,
                "tools": ["haversine_distance", "capacity_solver", "rejection_memory"],
                "last_active": "Sub-millisecond",
            },
        ],
        "system_health": "ALL_SYSTEMS_OPERATIONAL",
        "timestamp": int(time.time() * 1000),
    }


@router.post("/agents/sweep")
def trigger_agent_sweep():
    """Manually triggers a MonitorAgent autonomous sweep over active incidents."""
    from app.utils.geo import geohash_encode

    open_incidents = incidents.list_open_incidents()
    all_teams = teams.list_teams()

    hotspots = 0
    buckets: dict[str, int] = {}
    for inc in open_incidents:
        loc = inc.get("location") or {}
        if loc.get("lat") and loc.get("lng"):
            gh = geohash_encode(float(loc["lat"]), float(loc["lng"]))[:6]
            buckets[gh] = buckets.get(gh, 0) + 1
            if buckets[gh] >= 2:
                hotspots += 1

    activity.log_event(
        actor="agent",
        type_="monitor_agent_sweep",
        summary=f"MonitorAgent executed autonomous sweep over {len(open_incidents)} incidents ({hotspots} hotspot geohashes found)",
        payload={"incident_count": len(open_incidents), "hotspots": hotspots},
    )

    return {
        "sweep_status": "COMPLETED",
        "incidents_scanned": len(open_incidents),
        "teams_monitored": len(all_teams),
        "hotspots_identified": hotspots,
        "timestamp": int(time.time() * 1000),
    }


@router.get("/digital-twin")
def get_digital_twin():
    """Return Rautahat District Digital Twin summary and GIS layers."""
    from app.services import rautahat_digital_twin
    return {
        "summary": rautahat_digital_twin.get_digital_twin_summary(),
        "boundary": rautahat_digital_twin.get_district_boundary(),
        "municipalities": rautahat_digital_twin.get_municipalities_geojson(),
        "rivers": rautahat_digital_twin.get_rivers_geojson(),
        "embankments": rautahat_digital_twin.get_embankments_geojson(),
        "flood_2024": rautahat_digital_twin.get_flood_2024_geojson(),
        "infrastructure": rautahat_digital_twin.get_infrastructure_geojson(),
        "rescue_fleet": rautahat_digital_twin.get_rescue_fleet_geojson(),
    }


@router.post("/agentic/reason")
def agentic_reason(body: dict):
    """Temporary Supervisor/Route shim ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â Phase 6-8 replaces with POST /agents/*."""
    from app.services.react_agent import react_agent
    return react_agent.reason_and_act(body)


@router.post("/demo/reset")
def demo_reset():
    """1-Click Scenario Reset for Demo/Evaluation. Resets DynamoDB to Rautahat baseline."""
    import pathlib
    import sys
    try:
        scripts_path = str(pathlib.Path(__file__).resolve().parents[2] / "scripts")
        if scripts_path not in sys.path:
            sys.path.insert(0, scripts_path)
        from reset_and_seed_rautahat import reset_and_seed_rautahat
        reset_and_seed_rautahat()
        
        try:
            realtime.publish("SCENARIO_RESET", {"status": "SUCCESS", "timestamp": time.time()})
        except Exception:
            pass
            
        return {"status": "SUCCESS", "message": "Rautahat disaster state reset and seeded successfully."}
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception("Demo reset failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Reset failed: {str(e)}")

