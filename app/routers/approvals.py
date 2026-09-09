"""Phase 1 approvals API ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¢ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡Ãƒâ€šÃ‚Â¬ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬Ãƒâ€šÃ‚Â arch ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â§12, ÃƒÆ’Ã†â€™ÃƒÂ¢Ã¢â€šÂ¬Ã…Â¡ÃƒÆ’Ã¢â‚¬Å¡Ãƒâ€šÃ‚Â§65. Human gate for high-impact acts."""

from fastapi import APIRouter, Depends, HTTPException

from app.auth.deps import CurrentUser, require_role
from app.db.repos import activity, incidents, missions, pending_actions, teams
from app.models import ApprovalDecision
from app.services import realtime

router = APIRouter(prefix="/api/approvals", tags=["approvals"],
                   dependencies=[Depends(require_role("coordinator"))])


@router.get("")
def list_approvals():
    return {"pending_actions": pending_actions.list_pending()}


def _run_clock_min(run_id: str) -> float | None:
    if not run_id:
        return None
    try:
        from app.db.repos import simulation_runs as _runs

        run = _runs.get_run(run_id)
        return float(run.get("clock_min") or 0) if run else None
    except Exception:
        return None


def _execute(card: dict, team_id: str, coordinator_id: str) -> dict:
    team = teams.get_team(team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    incident = incidents.get_incident(card["incident_id"])
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    card_run_id = card.get("run_id") or ""
    sim_min = _run_clock_min(card_run_id)
    mission = missions.create_for_assignment(
        card["incident_id"], team_id, pending_action_id=card["id"],
        route_id=(card.get("payload") or {}).get("recommendation", {}).get("route_id"),
        run_id=card_run_id, sim_min=sim_min)
    update_fields = {"assigned_team": team_id, "mission_id": mission["id"],
                     "status": "ASSIGNED"}
    if sim_min is not None:
        from decimal import Decimal

        update_fields["assigned_sim_min"] = Decimal(str(sim_min))
    incidents.update_incident(card["incident_id"], **update_fields)
    teams.update_team(team_id, current_mission_id=mission["id"])
    from app.services import world_sync as _world_sync

    _world_sync.apply_team_status(team_id, "ON_MISSION", source="COORDINATOR")
    realtime.publish("MISSION_CREATED", {"mission": mission, "incident_id": card["incident_id"]})
    try:
        from app.services import comms as _comms

        contact = _comms.contact_team(teams.get_team(team_id) or {"id": team_id},
                                      f"Dispatched to {card['incident_id']}")
        activity.log_event(
            actor="agent", type_="team_contacted" if contact.get("delivered") else "communication_lost",
            summary=f"Contact {team.get('name', team_id)}: {contact.get('detail')}",
            payload={"team_id": team_id, "mission_id": mission["id"]},
            run_id=card.get("run_id") or "")
        if contact.get("timeout"):
            realtime.publish("COMMUNICATION_LOST", {"target": {"type": "TEAM", "id": team_id}})
    except Exception:
        pass
    return mission


def _release_hold(card: dict) -> None:
    try:
        held_id = card.get("proposed_team_id")
        held = teams.get_team(held_id) if held_id else None
        if held and held.get("status") == "SOFT_RESERVED":
            teams.update_team(held_id, status="AVAILABLE")
    except Exception:
        pass


@router.post("/{approval_id}/approve")
def approve(approval_id: str, body: dict | None = None,
            user: CurrentUser = Depends(require_role("coordinator"))):
    card = pending_actions.get_action(approval_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Pending action not found")
    was_pending = card.get("state") == "PENDING"
    decided = pending_actions.decide(approval_id, "APPROVED", user.id,
                                     note=(body or {}).get("note", ""))
    if not was_pending:
        return {"pending_action": decided, "executed": False, "deduped": True}
    team_id = (body or {}).get("override_team_id") or card.get("proposed_team_id")
    mission = _execute(card, team_id, user.id)
    activity.log_event(actor="human", type_="pending_action_approved",
                       summary=f"Approved {approval_id}",
                       payload={"pending_id": approval_id, "mission_id": mission["id"]},
                       run_id=card.get("run_id") or "")
    realtime.publish("HUMAN_APPROVAL", {"pending_id": approval_id,
                                        "incident_id": card["incident_id"],
                                        "mission_id": mission["id"]})
    realtime.publish("INCIDENT_UPDATED",
                     {"incident": incidents.get_incident(card["incident_id"])})
    return {"pending_action": decided, "mission": mission, "executed": True}


@router.post("/{approval_id}/reject")
def reject(approval_id: str, body: ApprovalDecision,
           user: CurrentUser = Depends(require_role("coordinator"))):
    card = pending_actions.get_action(approval_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Pending action not found")
    decided = pending_actions.decide(approval_id, "REJECTED", user.id, note=body.note)
    _release_hold(card)
    activity.log_event(actor="human", type_="pending_action_rejected",
                       summary=f"Coordinator rejected {approval_id}: {body.note}",
                       payload={"pending_id": approval_id})
    realtime.publish("HUMAN_REJECTION", {"pending_id": approval_id,
                                         "incident_id": card.get("incident_id")})
    return {"pending_action": decided, "executed": False}


@router.post("/{approval_id}/modify")
def modify(approval_id: str, body: dict,
           user: CurrentUser = Depends(require_role("coordinator"))):
    card = pending_actions.get_action(approval_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Pending action not found")
    # Modify = approve with override team (§12 modify path).
    override = body.get("override_team_id")
    if not override:
        raise HTTPException(status_code=422, detail="override_team_id required")
    was_pending = card.get("state") == "PENDING"
    decided = pending_actions.decide(approval_id, "APPROVED", user.id,
                                     note=body.get("note", "modified"))
    if not was_pending:
        return {"pending_action": decided, "executed": False, "deduped": True}
    mission = _execute(card, override, user.id)
    activity.log_event(actor="human", type_="pending_action_approved",
                       summary=f"Modified {approval_id} -> {override}",
                       payload={"pending_id": approval_id, "mission_id": mission["id"]},
                       run_id=card.get("run_id") or "")
    realtime.publish("HUMAN_APPROVAL", {"pending_id": approval_id,
                                        "incident_id": card["incident_id"],
                                        "mission_id": mission["id"]})
    realtime.publish("INCIDENT_UPDATED",
                     {"incident": incidents.get_incident(card["incident_id"])})
    return {"pending_action": decided, "mission": mission, "executed": True}
