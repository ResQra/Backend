import time
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException

from app.agents_gateway import gateway, llm
from app.auth.deps import CurrentUser, require_role
from app.db.repos import activity, areas, incidents, reports, shelters, teams, users
from app.models import AssignRequest, ReportCreate, StatusUpdate, TeamCreate, TeamStatusUpdate

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
    return {
        "incidents": [
            {
                **item,
                "flags": _incident_flags(item),
                "next_action": _next_action(item),
                "recommendation": gateway.recommend_team(item, all_teams),
            }
            for item in open_incidents
        ]
    }


@router.post("/assistant")
async def assistant(body: dict):
    """Coordinator AI panel: message in → agent reply out. The ops snapshot
    (queue + teams + flags) is attached server-side so the client can never
    tamper with it. Seam: gateway.coordinator_assistant (Strands slot)."""
    message = str(body.get("message", "")).strip()
    if not message:
        raise HTTPException(status_code=422, detail="message required")
    snapshot = {
        "open_incidents": incidents.list_open_incidents(),
        "teams": teams.list_teams(),
        "unresolved_locations": [
            {"id": r.get("id"), "name": r.get("name"), "stated": r.get("location_text")}
            for r in users.list_residents_with_location()
            if r.get("location_text") and not r.get("location")
        ],
    }
    history = body.get("history") or []
    try:
        reply = await gateway.coordinator_assistant(message, snapshot, history)
    except llm.LLMNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except gateway.AgentNotConnectedError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"reply": reply}


@router.get("/map-data")
def map_data():
    return {
        "incidents": incidents.list_open_incidents(),
        "teams": teams.list_teams(),
        "shelters": shelters.list_shelters(),
        "residents": users.list_residents_with_location(),
        "areas": areas.list_areas(),
    }


@router.get("/teams")
def list_teams_():
    return {"teams": teams.list_teams()}


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
    available, or marked offline for maintenance)."""
    if teams.get_team(team_id) is None:
        raise HTTPException(status_code=404, detail="Team not found")
    item = teams.update_team(team_id, status=body.status)
    activity.log_event(
        actor="human",
        type_="team_status_changed",
        summary=f"{item.get('name', team_id)} → {body.status}",
        payload={"team_id": team_id, "status": body.status},
    )
    return item


@router.get("/activity")
def feed():
    """F09: agent activity timeline, newest first."""
    return {"events": activity.recent_events(50)}


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
    return item


@router.post("/incidents/{incident_id}/recommend")
async def recommend(incident_id: str):
    """F06 v0: allocation recommendation with reasons (deterministic).
    The coordinator approves by calling /assign — F07 stays human-gated."""
    item = incidents.get_incident(incident_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    rec = gateway.recommend_team(item, teams.list_teams())
    activity.log_event(
        actor="agent",
        type_="allocation_recommended",
        summary=(
            f"AllocationAgent recommends {rec.get('team_name') or 'no team'} "
            f"for {incident_id}"
        ),
        payload={"incident_id": incident_id, "recommendation": rec},
    )
    return {"recommendation": rec}


@router.post("/incidents/{incident_id}/assign")
def assign(incident_id: str, body: AssignRequest):
    """Manual override (F07): coordinator assigns a team directly. In S4 the
    AllocationAgent writes a recommendation and this becomes approve/reject."""
    team = teams.get_team(body.team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    item = incidents.update_incident(
        incident_id, assigned_team=body.team_id, status="ASSIGNED"
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    teams.update_team(
        body.team_id, status="ON_MISSION", current_mission_id=incident_id
    )
    activity.log_event(
        actor="human",
        type_="team_assigned",
        summary=f"{team.get('name', body.team_id)} assigned to {incident_id} (manual)",
        payload={"incident_id": incident_id, "team_id": body.team_id},
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
