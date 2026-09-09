"""Phase 6 read-only operational tools — arch §9.

Typed, permissioned (coordinator-only via routers), logged by callers.
No writes, no dispatch, no DB mutation. Agents reason over results;
deterministic math stays here (§81).
"""

from __future__ import annotations


def _in_bbox(lat, lng, bbox) -> bool:
    try:
        sw, ne = bbox
        return sw[0] <= float(lat) <= ne[0] and sw[1] <= float(lng) <= ne[1]
    except Exception:
        return True


def _loc(item: dict) -> dict | None:
    return item.get("location") or None


# --- Incidents ---

def get_active_incidents(area_bbox=None, status=None, priority=None, limit=50) -> list[dict]:
    from app.db.repos import incidents

    items = incidents.list_open_incidents()
    if status:
        items = [i for i in items if i.get("status") == status]
    if priority:
        items = [i for i in items if (i.get("priority") or {}).get("band") == priority]
    if area_bbox:
        items = [i for i in items
                 if _loc(i) and _in_bbox(_loc(i)["lat"], _loc(i)["lng"], area_bbox)]
    return items[:limit]


def get_incident(incident_id: str) -> dict | None:
    from app.db.repos import incidents

    return incidents.get_incident(incident_id)


def get_incident_history(incident_id: str, limit=50) -> list[dict]:
    from app.db.repos import activity

    return [e for e in activity.recent_events(200)
            if (e.get("payload") or {}).get("incident_id") == incident_id][:limit]


# --- Teams ---

def get_teams(area_bbox=None, status=None, limit=100) -> list[dict]:
    from app.db.repos import teams

    items = teams.list_teams()
    if status:
        items = [t for t in items if t.get("status") == status]
    if area_bbox:
        items = [t for t in items
                 if _loc(t) and _in_bbox(_loc(t)["lat"], _loc(t)["lng"], area_bbox)]
    return items[:limit]


def get_team(team_id: str) -> dict | None:
    from app.db.repos import teams

    return teams.get_team(team_id)


def get_nearby_teams(location: dict, radius_km: float = 10, limit=10) -> list[dict]:
    from app.services import geospatial

    out = []
    for t in get_teams():
        tl = _loc(t)
        if not tl:
            continue
        d = geospatial.distance_km(float(location["lat"]), float(location["lng"]),
                                   float(tl["lat"]), float(tl["lng"]))
        if d <= radius_km:
            out.append({**t, "distance_km": round(d, 2)})
    return sorted(out, key=lambda x: x["distance_km"])[:limit]


# --- Shelters ---

def get_shelters(area_bbox=None) -> list[dict]:
    from app.db.repos import shelters

    items = shelters.list_shelters()
    if area_bbox:
        items = [s for s in items
                 if _loc(s) and _in_bbox(_loc(s)["lat"], _loc(s)["lng"], area_bbox)]
    return items


def get_available_shelter_capacity(area_bbox=None) -> list[dict]:
    rows = []
    for s in get_shelters(area_bbox):
        free = max(0, int(s.get("capacity") or 0) - int(s.get("current_occupancy") or 0))
        rows.append({"id": s.get("id"), "name": s.get("name"), "free": free,
                     "status": s.get("status", "OPEN")})
    return sorted(rows, key=lambda r: r["free"], reverse=True)


def get_shelter(shelter_id: str) -> dict | None:
    from app.db.repos import shelters

    return shelters.get_shelter(shelter_id)


def get_shelter_capacity(shelter_id: str) -> dict | None:
    s = get_shelter(shelter_id)
    if s is None:
        return None
    capacity = int(s.get("capacity") or 0)
    occupied = int(s.get("current_occupancy") or 0)
    return {"id": s.get("id"), "name": s.get("name"),
            "capacity": capacity, "occupied": occupied,
            "free": max(0, capacity - occupied),
            "status": s.get("status", "OPEN")}


# --- Geography / disaster state ---

def get_blocked_roads(area_bbox=None, limit=50) -> list[dict]:
    from app.db.repos import simulation_events

    evs = (simulation_events.list_by_type("ROAD_BLOCKED", limit=limit)
           + simulation_events.list_by_type("BRIDGE_BLOCKED", limit=limit))
    return evs[:limit]


def get_water_levels(area_bbox=None, limit=20) -> list[dict]:
    from app.db.repos import simulation_events

    return simulation_events.list_by_type("WATER_LEVEL", limit=limit)[:limit]


def get_hazard_zones(area_bbox=None) -> list[dict]:
    from app.db.repos import areas

    return areas.list_areas()


# --- Operations ---

def get_active_missions(limit=50) -> list[dict]:
    from app.db.repos import missions

    try:
        return missions.list_missions()[:limit]
    except Exception:
        return []


def get_team_mission(team_id: str) -> dict | None:
    """Latest mission carrying this team (missions store team_id)."""
    try:
        cands = [m for m in get_active_missions(limit=200)
                 if m.get("team_id") == team_id]
    except Exception:
        return None
    if not cands:
        return None
    cands.sort(key=lambda m: float(m.get("created_at") or 0), reverse=True)
    return cands[0]


def get_team_history(team_id: str, limit=50) -> list[dict]:
    from app.db.repos import activity

    return [e for e in activity.recent_events(200)
            if (e.get("payload") or {}).get("team_id") == team_id][:limit]


def get_recent_disaster_events(area_bbox=None, limit=20) -> list[dict]:
    """Newest sensor/closure observations across kinds, tagged by kind."""
    from app.db.repos import simulation_events

    out = []
    for kind in ("ROAD_BLOCKED", "BRIDGE_BLOCKED", "WATER_LEVEL",
                 "FLOOD_AREA", "PEOPLE_DENSITY"):
        try:
            for e in simulation_events.list_by_type(kind, limit=limit):
                out.append({"kind": kind, **e})
        except Exception:
            continue
    out.sort(key=lambda e: float(e.get("created_at") or e.get("timestamp") or 0),
             reverse=True)
    return out[:limit]


def get_incident_cluster(area_bbox=None) -> list[dict]:
    """Geohash clusters of open incidents: [{geohash, count, ids}]."""
    from app.services import geospatial

    from app.db.repos import incidents

    items = incidents.list_open_incidents()
    if area_bbox:
        items = [i for i in items
                 if _loc(i) and _in_bbox(_loc(i)["lat"], _loc(i)["lng"], area_bbox)]
    try:
        groups = geospatial.cluster_incidents(items)
    except Exception:
        return []
    rows = [{"geohash": gh, "count": len(v),
             "ids": [i.get("id") for i in v]} for gh, v in groups.items()]
    return sorted(rows, key=lambda r: r["count"], reverse=True)


def get_resource_summary(area_bbox=None) -> dict:
    """Fleet readiness roll-up: teams by status, missions, approvals, beds."""
    teams = get_teams(area_bbox)
    by_status: dict = {}
    for t in teams:
        by_status[t.get("status", "UNKNOWN")] = by_status.get(t.get("status", "UNKNOWN"), 0) + 1
    try:
        missions_active = len(get_active_missions(limit=200))
    except Exception:
        missions_active = 0
    try:
        pending = len(get_pending_approvals())
    except Exception:
        pending = 0
    try:
        beds_free = sum(r["free"] for r in get_available_shelter_capacity(area_bbox))
    except Exception:
        beds_free = 0
    return {"teams_by_status": by_status, "teams_total": len(teams),
            "missions_active": missions_active,
            "pending_approvals": pending, "shelter_beds_free": beds_free}


def get_damaged_bridges(area_bbox=None, limit=50) -> list[dict]:
    from app.db.repos import simulation_events

    try:
        return simulation_events.list_by_type("BRIDGE_BLOCKED", limit=limit)[:limit]
    except Exception:
        return []


def get_area_weather(area_bbox=None) -> dict:
    """Live weather sampled at the bbox center (keyless Open-Meteo).

    Honest sampling: one center point, labeled as such — not a district
    forecast grid.
    """
    if area_bbox:
        try:
            (sw, ne) = area_bbox
            lat, lng = (sw[0] + ne[0]) / 2, (sw[1] + ne[1]) / 2
        except Exception:
            return {"sampled": False, "reason": "bad bbox"}
    else:
        lat, lng = 26.7640, 85.2780  # Rautahat district center
    try:
        from app.services import web_tools

        return {"sampled": True, "lat": lat, "lng": lng,
                "weather": web_tools.web_weather(float(lat), float(lng))}
    except Exception as exc:
        return {"sampled": False, "reason": str(exc)[:120]}


def calculate_safe_route(origin: dict, destination: dict,
                         constraints: dict | None = None) -> list[dict]:
    """Arch §10 name for the deterministic routing engine candidates."""
    from app.services import routing

    return routing.calculate_routes(origin, destination, constraints or {})


def compare_route_candidates(routes: list[dict]) -> dict:
    """Arch §10 name for the route-reasoning explainer."""
    from app.services import route_reasoning

    return route_reasoning.explain(routes)


def get_pending_approvals() -> list[dict]:
    from app.db.repos import pending_actions

    return pending_actions.list_pending()


def get_agent_activity(limit=20) -> list[dict]:
    from app.db.repos import activity

    return activity.recent_events(limit)


def get_current_operational_picture(area_bbox=None) -> dict:
    incidents = get_active_incidents(area_bbox)
    teams = get_teams(area_bbox)
    critical = [i for i in incidents if (i.get("priority") or {}).get("score", 0) >= 8]
    return {
        "active_incidents": len(incidents),
        "critical": len(critical),
        "teams_available": sum(1 for t in teams if t.get("status") == "AVAILABLE"),
        "teams_total": len(teams),
        "pending_approvals": len(get_pending_approvals()),
        "top_ids": {
            "incidents": [i.get("id") for i in incidents[:5]],
            "critical": [i.get("id") for i in critical[:5]],
        },
    }


# --- Phase G: run-operations tools (still read-only) ---


def get_incident_timeline(incident_id: str, limit: int = 50) -> list[dict]:
    """Causal chain for one incident (judge drill-down, debate context)."""
    return get_incident_history(incident_id, limit=limit)


def compare_route_candidates(team_id: str, incident_id: str) -> dict:
    """Deterministic route candidates + explanation for a team→incident pair."""
    from app.services import route_reasoning, routing as _routing

    team = get_team(team_id)
    inc = get_incident(incident_id)
    if team is None or inc is None:
        return {"error": "team or incident not found"}
    tloc, iloc = team.get("location"), inc.get("location")
    if not tloc or not iloc:
        return {"error": "missing team or incident location"}
    try:
        routes = _routing.calculate_routes(
            {"lat": float(tloc["lat"]), "lng": float(tloc["lng"])},
            {"lat": float(iloc["lat"]), "lng": float(iloc["lng"])})
    except Exception as exc:
        return {"error": f"routing failed: {exc}"[:160]}
    explained = route_reasoning.explain(routes)
    return {"team_id": team_id, "incident_id": incident_id,
            "routes": routes, "recommended_id": explained.get("recommended_id"),
            "explanation": explained.get("explanation"),
            "invalid": explained.get("invalid", [])}


def get_team_telemetry(team_id: str) -> dict:
    """Live team position + freshness (stale GPS is uncertainty, not fact)."""
    from app.services import world_sync

    team = get_team(team_id)
    if team is None:
        return {"error": "team not found"}
    loc = team.get("location") or {}
    try:
        stale = world_sync.is_stale(
            "team_location", {"fetched_at": loc.get("updated_at")})
    except Exception:
        stale = True
    return {"team_id": team_id, "name": team.get("name"),
            "status": team.get("status"),
            "location": {"lat": str(loc.get("lat")), "lng": str(loc.get("lng")),
                         "label": loc.get("label")},
            "location_source": team.get("location_source"),
            "stale": bool(stale),
            "mission": get_team_mission(team_id)}


def request_reassessment(incident_id: str) -> dict:
    """Side-effect-free re-evaluation preview (persist=False): what the
    pipeline would recommend right now, without cards or holds."""
    from app.agents_gateway import gateway

    return gateway.recommend_for_incident(incident_id, persist=False)


def get_shelter_forecast(area_bbox=None) -> list[dict]:
    """Open shelters by free beds + pressure label (FULL/TIGHT/OK)."""
    rows = []
    for s in get_available_shelter_capacity(area_bbox):
        free = int(s.get("free") or 0)
        pressure = "FULL" if free <= 0 else ("TIGHT" if free <= 2 else "OK")
        rows.append({**s, "pressure": pressure})
    return rows


def get_run_score(run_id: str) -> dict:
    """Run scorecard for the coordinator loop (derived from the ledger)."""
    from app.services import run_score

    return run_score.get_score(run_id)
