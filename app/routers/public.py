from fastapi import APIRouter, Depends, HTTPException

from app.auth.deps import CurrentUser, get_current_user
from app.db.repos import areas, guides, incidents, reports, shelters

router = APIRouter(prefix="/api/public", tags=["public"])

# Resident-facing projection (BRAINSTORM §4.4): shelters + OWN incident +
# coarse area risk. Teams and other people's incidents are never here Ã¢â‚¬â€
# the split is enforced server-side, not by hiding frontend layers.


@router.get("/map-data")
def map_data(user: CurrentUser = Depends(get_current_user)):
    mine = incidents.list_user_incidents(user.id)
    my_open = next(
        (i for i in mine if i.get("status") in incidents.OPEN_STATUSES), None
    )
    return {
        "shelters": shelters.list_shelters(),
        "my_incident": my_open,
        "areas": areas.list_areas(),
    }


@router.get("/reports")
def gov_reports(user: CurrentUser = Depends(get_current_user)):
    """Official advisories/notices for residents Ã¢â‚¬â€ newest first."""
    return {"reports": reports.list_reports()}


@router.get("/guides")
def list_guides(category: str | None = None, language: str | None = None):
    """Preparedness / survival guides. Optional ?category=before|during|
    after|health|kit and ?language=en|hi filters."""
    items = guides.list_guides(category)
    if language:
        items = [g for g in items if g.get("language") == language]
    return {"guides": items}


@router.get("/guides/{guide_id}")
def get_guide(guide_id: str):
    item = guides.get_guide(guide_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Guide not found")
    return item


@router.post("/safest-route")
def safest_route(body: dict, user: CurrentUser = Depends(get_current_user)):
    """Phase 2 resident hook Ã¢â‚¬â€ safest route to shelter/point (arch Ã‚Â§18/Ã‚Â§41).

    Permission-safe: origin = own GPS / own incident only; destination =
    open shelter or map point. Returns deterministic candidates from
    services/routing (blocked-aware). No teams, no other incidents.
    Full turn-by-turn + live closures arrive in Phase 7.
    """
    from app.services import routing

    origin = body.get("origin") or {}
    dest = body.get("destination") or {}
    try:
        o_lat, o_lng = float(origin["lat"]), float(origin["lng"])
        d_lat, d_lng = float(dest["lat"]), float(dest["lng"])
    except Exception:
        raise HTTPException(status_code=422, detail="origin.lat/lng + destination.lat/lng required")

    shelter_id = body.get("shelter_id")
    shelter = None
    if shelter_id:
        shelter = shelters.get_shelter(shelter_id)
        if shelter is None:
            raise HTTPException(status_code=404, detail="Shelter not found")
        sloc = shelter.get("location") or {}
        d_lat, d_lng = float(sloc["lat"]), float(sloc["lng"])

    routes = routing.calculate_routes(
        {"lat": o_lat, "lng": o_lng}, {"lat": d_lat, "lng": d_lng},
        {"mode": "resident-evacuation"})
    feasible = [r for r in routes if r.get("feasible")]
    best = feasible[0] if feasible else routes[0]
    from app.services import route_reasoning

    return {"routes": routes, "best": best, "shelter": shelter,
            "route_explanation": route_reasoning.explain(routes),
            "disclaimer": "Decision support only Ã¢â‚¬â€ follow official guidance."}
