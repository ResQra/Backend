"""World-state synchronization — one front door for all map writes.

Rule (user-confirmed): live ingestion AUTO-APPLIES by source rank, and the
coordinator is ALWAYS notified on conflicts, overrides, and closures.

    COORDINATOR (100) > SIMULATION (80) > TEAM (60) > PUBLIC_API (40) > SYSTEM (10)

- Unknown/missing incumbent source ranks as SYSTEM (seed baseline yields
  to any live source, coordinator edits always stick).
- Equal rank: newer write wins.
- Every applied write stamps provenance {source, fetched_at, confidence}.
- STALENESS_TTL_S marks aging data; readers (not writers) decide display.
- Sensor facts are append-only (idempotency-keyed); closures always notify.

Routers and simulation.apply_event must route their writes through here
instead of touching repos directly, so rank + provenance + notify hold
for every dot on the map.
"""

from __future__ import annotations

import time
from decimal import Decimal

SOURCE_RANK = {
    "COORDINATOR": 100,
    "SIMULATION": 80,
    "TEAM": 60,
    "PUBLIC_API": 40,
    "SYSTEM": 10,
}

STALENESS_TTL_S = {
    "team_location": 120,
    "team_status": 300,
    "shelter_occupancy": 600,
    "sensor": 3600,
    "road": 86400,
}

CLOSURE_KINDS = {"ROAD_BLOCKED", "BRIDGE_BLOCKED", "BRIDGE_DAMAGED"}


def _now_ms() -> int:
    return int(time.time() * 1000)


def rank_of(source: str | None) -> int:
    """Missing/unknown sources rank as SYSTEM (seed baseline yields)."""
    return SOURCE_RANK.get(str(source or "").upper(), SOURCE_RANK["SYSTEM"])


def provenance(source: str, confidence: float | None = None) -> dict:
    return {"source": str(source or "SYSTEM").upper(),
            "fetched_at": _now_ms(),
            "confidence": confidence}


def is_stale(domain: str, prov: dict | None, now_ms: int | None = None) -> bool:
    """True when provenance is missing or older than the domain TTL."""
    if not isinstance(prov, dict) or prov.get("fetched_at") is None:
        return True
    ttl = STALENESS_TTL_S.get(domain, 600)
    return (_now_ms() if now_ms is None else now_ms) - int(prov["fetched_at"]) > ttl * 1000


def resolve(current_source: str | None, incoming_source: str) -> tuple[bool, str]:
    """Rank duel. Returns (apply, outcome). Equal rank: newer wins."""
    cur, inc = rank_of(current_source), rank_of(incoming_source)
    if inc >= cur:
        return True, "applied"
    return False, f"rejected: {incoming_source} rank {inc} < {current_source} rank {cur}"


def _run_owns_team(team_id: str, run_id: str) -> bool:
    """True when the team's active mission belongs to this run — the run's
    own lifecycle writes (advance/return) then outrank a stale same-run
    coordinator pin. Human edits outside the run still win."""
    if not run_id:
        return False
    try:
        from app.db.repos import missions, teams

        team = teams.get_team(team_id)
        mid = (team or {}).get("current_mission_id")
        if not mid:
            return False
        m = missions.get_mission(mid)
        return bool(m) and m.get("run_id") == run_id
    except Exception:
        return False


def notify(summary: str, payload: dict | None = None,
           event: str = "WORLD_SYNC_NOTICE", level: str = "info",
           run_id: str = "") -> None:
    """Coordinator notification: persistent ledger entry + realtime push
    (the coordinator console toasts ws events carrying a summary)."""
    from app.db.repos import activity
    from app.services import realtime

    payload = {"level": level, **(payload or {})}
    try:
        activity.log_event(actor="system", type_="world_sync_notice",
                           summary=summary, payload=payload, run_id=run_id)
    except Exception:
        pass
    try:
        realtime.publish(event, {"summary": summary, **payload})
        if event != "WORLD_SYNC_NOTICE":
            realtime.publish("WORLD_SYNC_NOTICE", {"summary": summary, **payload})
    except Exception:
        pass


def _conflict_note(domain: str, entity: str, old_source: str | None,
                   new_source: str, applied: bool) -> str:
    verb = "overrode" if applied else "held against"
    return (f"{domain} {entity}: {new_source} {verb} "
            f"{old_source or 'unranked baseline'}")


def apply_team_location(team_id: str, location: dict, source: str,
                        run_id: str = "") -> dict:
    """Ranked team-position write. Returns {team, applied, outcome}."""
    from app.db.repos import teams
    from app.services import realtime

    team = teams.get_team(team_id)
    if team is None:
        raise LookupError("Team not found")
    current_source = team.get("location_source")
    applied, outcome = resolve(current_source, source)
    if not applied and _run_owns_team(team_id, run_id):
        applied, outcome = True, "applied: run owns team mission"
    if not applied:
        notify(f"Ignored stale-ranked position for {team.get('name', team_id)}",
               {"team_id": team_id, "outcome": outcome,
                "current_source": current_source, "incoming_source": source},
               level="warning", run_id=run_id)
        return {"team": team, "applied": False, "outcome": outcome}
    item = teams.update_location(team_id, location, source=source)
    realtime.publish("TEAM_LOCATION_UPDATED", {"team": item})
    if (current_source or "").upper() != str(source).upper():
        notify(_conflict_note("position", team.get('name', team_id),
                              current_source, source, True),
               {"team_id": team_id, "outcome": outcome,
                "current_source": current_source, "incoming_source": source},
               run_id=run_id)
    return {"team": item, "applied": True, "outcome": outcome}


def apply_team_status(team_id: str, status: str, source: str,
                      force: bool = False, run_id: str = "") -> dict:
    """Ranked team-status write. Returns {team, applied, outcome}.

    force=True is the safety override: a crew reporting its own breakdown
    (OFFLINE) always lands, whatever the ledger says — stamped + notified
    loudly so the coordinator sees why.
    """
    from app.db.repos import teams
    from app.services import realtime

    team = teams.get_team(team_id)
    if team is None:
        raise LookupError("Team not found")
    current_source = team.get("status_source")
    if force:
        item = teams.update_team(team_id, status=status, status_source=source)
        realtime.publish("TEAM_STATUS_CHANGED", {"team": item})
        notify(f"SAFETY OVERRIDE: {team.get('name', team_id)} reported {status} "
               f"(over {current_source or 'unranked baseline'})",
               {"team_id": team_id, "status": status,
                "current_source": current_source, "incoming_source": source},
               level="warning", run_id=run_id)
        return {"team": item, "applied": True, "outcome": "applied: safety override"}
    applied, outcome = resolve(current_source, source)
    if not applied and _run_owns_team(team_id, run_id):
        applied, outcome = True, "applied: run owns team mission"
    if not applied:
        notify(f"Ignored stale-ranked status for {team.get('name', team_id)}",
               {"team_id": team_id, "status": status, "outcome": outcome,
                "current_source": current_source, "incoming_source": source},
               level="warning", run_id=run_id)
        return {"team": team, "applied": False, "outcome": outcome}
    item = teams.update_team(team_id, status=status, status_source=source)
    realtime.publish("TEAM_STATUS_CHANGED", {"team": item})
    if (current_source or "").upper() != str(source).upper():
        notify(_conflict_note("status", team.get('name', team_id),
                              current_source, source, True),
               {"team_id": team_id, "status": status, "outcome": outcome,
                "current_source": current_source, "incoming_source": source},
               run_id=run_id)
    return {"team": item, "applied": True, "outcome": outcome}


def apply_shelter_occupancy(shelter_id: str, occupancy: int, source: str,
                            run_id: str = "") -> dict:
    """Ranked shelter-occupancy write. Returns {shelter, applied, outcome}."""
    from app.db.repos import shelters
    from app.services import realtime

    shelter = shelters.get_shelter(shelter_id)
    if shelter is None:
        raise LookupError("Shelter not found")
    current_source = shelter.get("occupancy_source")
    applied, outcome = resolve(current_source, source)
    if not applied:
        notify(f"Ignored stale-ranked occupancy for {shelter.get('name', shelter_id)}",
               {"shelter_id": shelter_id, "outcome": outcome,
                "current_source": current_source, "incoming_source": source},
               level="warning", run_id=run_id)
        return {"shelter": shelter, "applied": False, "outcome": outcome}
    item = shelters.update_occupancy(shelter_id, int(occupancy), source=source)
    realtime.publish("SHELTER_CAPACITY_CHANGED", {"shelter": item})
    if (current_source or "").upper() != str(source).upper():
        notify(_conflict_note("occupancy", shelter.get('name', shelter_id),
                              current_source, source, True),
               {"shelter_id": shelter_id, "occupancy": int(occupancy),
                "outcome": outcome, "current_source": current_source,
                "incoming_source": source},
               run_id=run_id)
    return {"shelter": item, "applied": True, "outcome": outcome}


def apply_sensor(kind: str, lat: float, lng: float, value, level: str,
                 note: str, source: str, idempotency_key: str | None = None,
                 run_id: str = "") -> dict:
    """Sensor observation write (append-only, idempotency-keyed).

    Facts are never rank-rejected — but closures always notify, and the
    risk layer prefers SIMULATION over PUBLIC_API on conflict (existing
    behavior, preserved here).
    """
    import uuid

    from app.db.repos import activity, areas, simulation_events, users
    from app.services import realtime
    from app.utils.geo import geohash_encode

    def D(x):
        return Decimal(str(x))

    key = idempotency_key or f"manual_{uuid.uuid4().hex[:12]}"
    payload = {"kind": kind, "lat": D(lat), "lng": D(lng),
               "value": D(value) if value is not None else None,
               "level": level, "note": note or "",
               "source_priority": source}
    if run_id:
        payload["run_id"] = run_id
    event = simulation_events.put_event(key, kind, payload)
    if kind in CLOSURE_KINDS:
        # Closures must flip routes instantly: drop the router's TTL cache
        # so the next calculation sees this write (judge fires flood →
        # coordinator map + replans react now, not after cache expiry).
        try:
            from app.services import routing as _routing

            _routing._CLOSURE_CACHE.pop("ctx", None)
        except Exception:
            pass

    kind_to_event = {
        "WATER_LEVEL": "WATER_LEVEL_CHANGED",
        "FLOOD_AREA": "FLOOD_ZONE_CHANGED",
        "ROAD_BLOCKED": "ROAD_BLOCKED",
        "BRIDGE_BLOCKED": "BRIDGE_DAMAGED",
        "PEOPLE_DENSITY": "FLOOD_ZONE_CHANGED",
    }
    realtime.publish(kind_to_event.get(kind, "FLOOD_ZONE_CHANGED"), {"event": event})

    try:
        gh = users.geohash_encode(float(lat), float(lng)) \
            if hasattr(users, "geohash_encode") else geohash_encode(float(lat), float(lng))
    except Exception:
        gh = geohash_encode(float(lat), float(lng))
    risk_level = "HOTSPOT" if level in {"HOTSPOT", "UNSAFE"} else level
    areas.put_area_risk({
        "geohash": gh, "level": risk_level,
        "center": {"lat": D(lat), "lng": D(lng)}, "radius_m": 1800,
        "request_count": 0, "high_urgency_count": 0,
        "source": source, "source_priority": source,
        "sensor_kind": kind, "sensor_value": D(value) if value is not None else None,
        "note": note or "", "updated_at": _now_ms(),
    })
    activity.log_event(
        actor="agent" if source == "SIMULATION" else "system",
        type_="sensor_event_received",
        summary=f"{source} {kind}: {level} near {float(lat):.4f},{float(lng):.4f}",
        payload={"idempotency_key": key, "event": payload},
        run_id=run_id)
    if kind in CLOSURE_KINDS:
        notify(f"{kind.replace('_', ' ').title()} reported near "
               f"{float(lat):.4f},{float(lng):.4f} ({source})",
               {"kind": kind, "lat": float(lat), "lng": float(lng),
                "level": level, "source": source},
               event=kind_to_event.get(kind, "FLOOD_ZONE_CHANGED"),
               level="warning", run_id=run_id)
    return {"event": event, "applied": True, "outcome": "applied"}
