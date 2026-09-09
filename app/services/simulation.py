"""Phase 1 simulation mutation layer — arch §23-25, §63-64.

Single place where DEMO_SIMULATOR writes become canonical world state.
All writes go through world_sync (rank + provenance + coordinator
notice); simulation source SIMULATION outranks team/public feeds.
"""

from __future__ import annotations

import time
import uuid
from decimal import Decimal

from app.db.repos import activity, areas, shelters, simulation_events, teams
from app.services import realtime


def _now_ms() -> int:
    return int(time.time() * 1000)


def apply_event(event: dict) -> dict:
    """Apply a unified §24 SimulationEvent dict to world state.

    Expected keys: type, target {type,id}, parameters, scenario_id, run_id.
    Returns the stored operational record.
    """
    etype = event.get("type")
    target = event.get("target") or {}
    params = event.get("parameters") or {}
    scenario_id = event.get("scenario_id", "flood-escalation-01")
    run_id = event.get("run_id", "")

    key = event.get("event_id") or f"sim_{uuid.uuid4().hex[:12]}"
    record: dict = {"key": key, "type": etype, "scenario_id": scenario_id, "run_id": run_id}

    if etype in ("TEAM_LOCATION_UPDATED", "TEAM_MOVED"):
        team_id = target.get("id")
        lat, lng = params.get("lat"), params.get("lng")
        if not team_id or lat is None or lng is None:
            record["applied"] = False
            record["error"] = "team_id/lat/lng required"
        else:
            from app.services import world_sync

            loc = {"lat": Decimal(str(lat)), "lng": Decimal(str(lng)),
                   "label": params.get("label", "simulation update"),
                   "updated_at": _now_ms()}
            out = world_sync.apply_team_location(team_id, loc, source="SIMULATION",
                                                 run_id=run_id)
            record["team"] = out["team"]
            record["sync"] = {k: v for k, v in out.items() if k != "team"}
    elif etype in ("TEAM_STATUS_CHANGED", "TEAM_UNAVAILABLE", "TEAM_DAMAGED"):
        team_id = target.get("id")
        status = params.get("status", "UNAVAILABLE")
        if not team_id:
            record["applied"] = False
            record["error"] = "team_id required"
        else:
            from app.services import world_sync

            out = world_sync.apply_team_status(team_id, status, source="SIMULATION",
                                               run_id=run_id)
            record["team"] = out["team"]
            record["sync"] = {k: v for k, v in out.items() if k != "team"}
    elif etype in ("ROAD_BLOCKED", "BRIDGE_DAMAGED", "WATER_LEVEL_UPDATED", "FLASH_FLOOD"):
        from app.services import world_sync

        kind_map = {"ROAD_BLOCKED": "ROAD_BLOCKED", "BRIDGE_DAMAGED": "BRIDGE_BLOCKED",
                    "WATER_LEVEL_UPDATED": "WATER_LEVEL", "FLASH_FLOOD": "FLOOD_AREA"}
        geo = params.get("lat"), params.get("lng")
        if geo[0] is None or geo[1] is None:
            activity.log_event(actor="system", type_="simulation_event_rejected",
                               summary=f"SIMULATION {etype} missing lat/lng [{scenario_id}]",
                               payload={"key": key, "type": etype},
                               run_id=run_id)
            return {**record, "error": "lat/lng required", "applied": False}
        try:
            lat_f, lng_f = float(geo[0]), float(geo[1])
        except (TypeError, ValueError):
            return {**record, "error": "invalid lat/lng", "applied": False}
        if not (-90 <= lat_f <= 90 and -180 <= lng_f <= 180):
            return {**record, "error": "lat/lng out of range", "applied": False}
        out = world_sync.apply_sensor(
            kind=kind_map.get(etype, "FLOOD_AREA"),
            lat=lat_f, lng=lng_f,
            value=params.get("water_level_change") or params.get("value"),
            level=params.get("severity", "UNSAFE"),
            note=f"{etype} {target} [{scenario_id}/{run_id or 'manual'}]",
            source="SIMULATION", idempotency_key=key, run_id=run_id)
        record["event"] = out["event"]
    elif etype in ("SHELTER_STATUS_CHANGED", "SHELTER_FULL"):
        shelter_id = target.get("id")
        occ = params.get("current_occupancy")
        if not shelter_id or occ is None:
            record["applied"] = False
            record["error"] = "shelter id/current_occupancy required"
        else:
            from app.services import world_sync

            out = world_sync.apply_shelter_occupancy(shelter_id, int(occ),
                                                     source="SIMULATION",
                                                     run_id=run_id)
            record["shelter"] = out["shelter"]
            record["sync"] = {k: v for k, v in out.items() if k != "shelter"}
    elif etype == "NEW_INCIDENT":
        record["note"] = "incidents are created via POST /incidents (intake owns it)"
        record["applied"] = False
    elif etype == "MISSION_UPDATED":
        record["note"] = "missions mutate via approvals/dispatch gate, not simulation"
        record["applied"] = False
    elif etype == "COMMUNICATION_LOST":
        activity.log_event(actor="agent", type_="communication_lost",
                           summary=f"COMMUNICATION_LOST {target} [{scenario_id}/{run_id or 'manual'}]",
                           payload={"target": target, "scenario_id": scenario_id, "run_id": run_id, "event_id": key},
                           run_id=run_id)
        realtime.publish("COMMUNICATION_LOST", {"target": target})
        record["logged"] = True

    activity.log_event(actor="system", type_="simulation_event_applied",
                       summary=f"SIMULATION {etype} {target} [{scenario_id}]",
                       payload={"key": key, "type": etype},
                       run_id=run_id)
    return record


def current_state() -> dict:
    from app.db.repos import incidents

    return {
        "incidents": incidents.list_open_incidents(),
        "teams": teams.list_teams(),
        "shelters": shelters.list_shelters(),
        "areas": areas.list_areas(),
    }
