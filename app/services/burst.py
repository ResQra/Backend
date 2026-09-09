"""Phase D burst injection + team telemetry (arch §22, §44).

SOS bursts run the REAL intake path (routers.incidents.create_incident),
so priority/intake behavior under load is genuine, not stubbed. Team
telemetry advances ON_MISSION teams along straight-line legs toward their
incident and walks the mission lifecycle to completion.
"""

from __future__ import annotations

import json
import pathlib
import time
from decimal import Decimal

from app.auth.deps import CurrentUser
from app.db.repos import activity, incidents, missions, teams, users
from app.models import IncidentCreate
from app.utils.geo import haversine_km

PACK_PATH = pathlib.Path(__file__).resolve().parents[3] / "simulation" / "seed" / "sos_pack_48h.json"

BOAT_SPEED_KMH = 20.0
ARRIVAL_KM = 0.15
# Rescue work is real work: 20 sim-min on scene + 15 per boat trip.
# Trips = ceil(people / team capacity). A 7-person rooftop with an
# 8-boat takes 35 sim-min; the same rooftop with a 4-raft takes 50.
BASE_RESCUE_MIN = 20.0
MIN_PER_TRIP = 15.0


def rescue_required_min(people: int, capacity: int) -> float:
    import math

    trips = max(1, math.ceil(max(1, int(people or 1)) / max(1, int(capacity or 1))))
    return BASE_RESCUE_MIN + MIN_PER_TRIP * trips


def _now_ms() -> int:
    return int(time.time() * 1000)


def D(x) -> Decimal:
    return Decimal(str(x))


def load_pack() -> list[dict]:
    return json.loads(PACK_PATH.read_text(encoding="utf-8"))


def _beacon(user_id: str, item: dict) -> None:
    """Resident map beacon: stated location + live status, broadcast live."""
    from app.services import realtime

    loc = {"lat": D(item["lat"]), "lng": D(item["lng"]),
           "label": item.get("location_text", "simulation report"),
           "confidence": D(0.95)}
    users.update_user_info(
        user_id,
        location=loc,
        location_text=item.get("location_text"),
        people_with=item.get("people", 1),
        vulnerabilities=item.get("vulnerabilities") or [],
        status="TRAPPED" if item.get("water_rising") else "NEEDS_HELP",
    )
    user = users.get_user(user_id) or {}
    realtime.publish("RESIDENT_UPDATED", {"resident": {
        "id": user_id,
        "name": user.get("name", "Sim Resident"),
        "phone": user.get("phone", ""),
        "location": loc,
        "location_text": item.get("location_text"),
        "people_with": item.get("people", 1),
        "vulnerabilities": item.get("vulnerabilities") or [],
        "status": "TRAPPED" if item.get("water_rising") else "NEEDS_HELP",
        "updated_at": _now_ms(),
    }})


async def inject_sos_items(run_id: str, items: list[dict],
                         sim_min: float | None = None) -> dict:
    """Push SOS items through real intake. Returns ids + counts."""
    from app.routers import incidents as incidents_router

    incident_ids: list[str] = []
    reporter_ids: list[str] = []
    for idx, it in enumerate(items):
        phone = it.get("reporter_phone") or f"+977SIM{(run_id[-6:] if len(run_id) >= 6 else run_id):s}{idx % 20:02d}"
        user = users.find_by_phone(phone)
        if user is None:
            user = users.create_user(phone=phone,
                                     name=it.get("reporter_name", f"Sim Resident {idx}"),
                                     role="resident")
        try:
            users.update_user_info(user["id"], run_id=run_id)
        except Exception:
            pass
        cu = CurrentUser(id=user["id"], phone=phone,
                         name=user.get("name", ""), role="resident")
        loc = None
        if it.get("lat") is not None and it.get("lng") is not None:
            loc = {"lat": float(it["lat"]), "lng": float(it["lng"]),
                   "label": it.get("location_text", "simulation report")}
        body = IncidentCreate(
            raw_text=it.get("raw_text", ""),
            people=it.get("people", 1),
            vulnerabilities=it.get("vulnerabilities") or [],
            urgency=it.get("urgency"),
            water_rising=bool(it.get("water_rising")),
            location=loc,
            location_text=it.get("location_text"),
            run_id=run_id,
        )
        created = await incidents_router.create_incident(body, cu)
        incident_ids.append(created["id"])
        reporter_ids.append(user["id"])
        if sim_min is not None:
            try:
                incidents.update_incident(created["id"], sim_min=D(sim_min))
            except Exception:
                pass
        if loc is not None:
            try:
                _beacon(user["id"], it)
            except Exception:
                pass
    activity.log_event(actor="system", type_="sos_burst_injected",
                       summary=f"SOS burst: {len(incident_ids)} incidents ingested [{run_id}]",
                       payload={"run_id": run_id, "incident_ids": incident_ids,
                                "count": len(incident_ids)},
                       run_id=run_id)
    return {"run_id": run_id, "incidents_created": len(incident_ids),
            "incident_ids": incident_ids, "reporter_ids": reporter_ids}


async def inject_sos_burst(run_id: str, burst_id: str, sim_min: float | None = None) -> dict:
    items = [it for it in load_pack() if it.get("burst") == burst_id]
    if not items:
        raise LookupError(f"unknown burst {burst_id!r}")
    return await inject_sos_items(run_id, items, sim_min=sim_min)


def advance_teams(run_id: str, sim_minutes: float, clock_min: float | None = None) -> dict:
    """Move the run's ON_MISSION teams toward their incidents; walk arrivals
    DISPATCHED/EN_ROUTE → ON_SCENE → COMPLETED (+RESCUED) and recycle
    RETURNING teams to AVAILABLE.

    Rescue work consumes sim time: a mission completes only after its
    required on-scene minutes elapse, so big tick jumps still honor the
    clock instead of teleporting rescues.
    """
    from app.services import world_sync

    if clock_min is None:
        try:
            from app.db.repos import simulation_runs as _runs

            _r = _runs.get_run(run_id)
            clock_min = float((_r or {}).get("clock_min") or 0)
        except Exception:
            clock_min = 0.0
    advanced = 0
    transitions: list[dict] = []
    step_km = BOAT_SPEED_KMH * float(sim_minutes) / 60.0
    for m in missions.list_missions():
        if m.get("run_id") != run_id:
            continue
        st = m.get("status")
        team = teams.get_team(m.get("team_id") or "")
        inc = incidents.get_incident(m.get("incident_id") or "")
        if team is None or inc is None:
            continue
        if st in ("DISPATCHED", "EN_ROUTE"):
            tloc, iloc = team.get("location"), inc.get("location")
            if not tloc or not iloc:
                continue
            dist = haversine_km(float(tloc["lat"]), float(tloc["lng"]),
                                float(iloc["lat"]), float(iloc["lng"]))
            if dist <= max(step_km, ARRIVAL_KM):
                world_sync.apply_team_location(
                    team["id"],
                    {"lat": D(iloc["lat"]), "lng": D(iloc["lng"]),
                     "label": f"on scene {inc['id']}", "updated_at": _now_ms()},
                    source="SIMULATION", run_id=run_id)
                missions.update_mission(m["id"], status="ON_SCENE",
                                        on_scene_sim_min=D(clock_min))
                incidents.update_incident(inc["id"], status="IN_PROGRESS")
                activity.log_event(actor="agent", type_="team_on_scene",
                                   summary=f"{team.get('name', team['id'])} on scene at {inc['id']}",
                                   payload={"run_id": run_id, "team_id": team["id"],
                                            "incident_id": inc["id"],
                                            "mission_id": m["id"]},
                                   run_id=run_id)
                transitions.append({"mission_id": m["id"], "to": "ON_SCENE"})
            else:
                frac = step_km / dist if dist else 1.0
                new = {"lat": D(float(tloc["lat"]) + (float(iloc["lat"]) - float(tloc["lat"])) * frac),
                       "lng": D(float(tloc["lng"]) + (float(iloc["lng"]) - float(tloc["lng"])) * frac),
                       "label": f"en route {inc['id']}", "updated_at": _now_ms()}
                world_sync.apply_team_location(team["id"], new,
                                               source="SIMULATION", run_id=run_id)
                if st == "DISPATCHED":
                    missions.update_mission(m["id"], status="EN_ROUTE")
                advanced += 1
        elif st == "ON_SCENE":
            started = m.get("on_scene_sim_min")
            if started is None:
                missions.update_mission(m["id"], on_scene_sim_min=D(clock_min))
                continue
            required = rescue_required_min(inc.get("people"), team.get("capacity"))
            if float(clock_min) - float(started) < required:
                continue
            missions.update_mission(m["id"], status="COMPLETED")
            incidents.update_incident(inc["id"], status="RESCUED")
            world_sync.apply_team_status(team["id"], "RETURNING",
                                         source="SIMULATION", run_id=run_id)
            activity.log_event(actor="agent", type_="rescue_completed",
                               summary=f"Rescued {inc.get('people') or 1} at {inc['id']} "
                                       f"({team.get('name', team['id'])})",
                               payload={"run_id": run_id, "team_id": team["id"],
                                        "incident_id": inc["id"], "mission_id": m["id"],
                                        "people": inc.get("people") or 1},
                               run_id=run_id)
            transitions.append({"mission_id": m["id"], "to": "COMPLETED"})
        elif st == "COMPLETED" and team.get("status") == "RETURNING":
            world_sync.apply_team_status(team["id"], "AVAILABLE",
                                         source="SIMULATION", run_id=run_id)
            activity.log_event(actor="agent", type_="team_available",
                               summary=f"{team.get('name', team['id'])} available again",
                               payload={"run_id": run_id, "team_id": team["id"]},
                               run_id=run_id)
            transitions.append({"mission_id": m["id"], "to": "TEAM_AVAILABLE"})
    return {"run_id": run_id, "teams_advanced": advanced, "transitions": transitions}
