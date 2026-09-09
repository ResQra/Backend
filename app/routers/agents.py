"""Phase 1 agents API — arch §65. Thin HTTP over agents_gateway.

No LLM math here: query/analyze delegate to gateway + deterministic
services; recommend/replan create pending cards gated by approvals API.
"""

from fastapi import APIRouter, Depends, HTTPException

from app.agents_gateway import gateway
from app.auth.deps import require_role
from app.db.repos import activity, incidents, teams
from app.services import geospatial

router = APIRouter(prefix="/api/agents", tags=["agents"],
                   dependencies=[Depends(require_role("coordinator"))])


@router.post("/query")
async def query(body: dict):
    """Phase 6 supervisor: area-aware grounded answer + evidence."""
    from app.agents_gateway import supervisor as supervisor_mod

    message = str(body.get("message", "")).strip()
    if not message:
        raise HTTPException(status_code=422, detail="message required")
    area_context = body.get("area_context") or {
        "area": body.get("area"), "bounds": body.get("bounds"),
        "incident_id": body.get("incident_id")}
    return await supervisor_mod.supervise(message, area_context, body.get("history") or [])


@router.post("/analyze-area")
def analyze_area(body: dict):
    area = str(body.get("area", ""))
    open_inc = incidents.list_open_incidents()
    clusters = geospatial.cluster_incidents(open_inc)
    return {"area": area, "open_incidents": len(open_inc),
            "clusters": {k: len(v) for k, v in clusters.items()},
            "risk_areas": geospatial.list_risk_areas()}


@router.post("/recommend-dispatch")
def recommend_dispatch(body: dict):
    incident_id = body.get("incident_id")
    try:
        out = gateway.recommend_for_incident(
            incident_id, force_debate=bool((body or {}).get("force_debate")))
    except LookupError:
        raise HTTPException(status_code=404, detail="Incident not found")
    return out


@router.get("/route-preview")
def route_preview(incident_id: str, team_id: str | None = None):
    """Side-effect-free best-route detail for map display: candidates,
    recommended id, explanation, plus an evacuation leg to the nearest
    open shelter. Nothing is held, carded, or dispatched."""
    from app.db.repos import incidents, shelters, teams

    item = incidents.get_incident(incident_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    loc = item.get("location")
    if not loc:
        raise HTTPException(status_code=422, detail="Incident has no mappable location")
    tid = team_id
    if not tid:
        try:
            tid = gateway.recommend_for_incident(incident_id, persist=False)["recommendation"].get("team_id")
        except Exception:
            tid = None
    team = teams.get_team(tid) if tid else None
    routes, explanation = [], {"recommended_id": None,
                               "explanation": "No team currently available for routing.",
                               "invalid": []}
    if team is not None and team.get("location"):
        from app.services import route_reasoning, routing as _routing

        tloc = team["location"]
        routes = _routing.calculate_routes(
            {"lat": float(tloc["lat"]), "lng": float(tloc["lng"])},
            {"lat": float(loc["lat"]), "lng": float(loc["lng"])})
        explanation = route_reasoning.explain(routes)
    # Evacuation leg: incident -> nearest open shelter.
    shelter_leg = None
    try:
        open_shelters = [s for s in shelters.list_shelters()
                         if s.get("location")
                         and (s.get("capacity") or 0) - (s.get("current_occupancy") or 0) > 0]
        if open_shelters:
            from app.services import geospatial as _geo

            best_s = min(open_shelters, key=lambda s: _geo.distance_km(
                float(loc["lat"]), float(loc["lng"]),
                float(s["location"]["lat"]), float(s["location"]["lng"])))
            sloc = best_s["location"]
            sroutes = _routing.calculate_routes(
                {"lat": float(loc["lat"]), "lng": float(loc["lng"])},
                {"lat": float(sloc["lat"]), "lng": float(sloc["lng"])})
            shelter_leg = {"shelter": {"id": best_s.get("id"), "name": best_s.get("name")},
                           "routes": sroutes,
                           "explanation": route_reasoning.explain(sroutes)}
    except Exception:
        pass
    return {"incident_id": incident_id,
            "team": {"id": team.get("id"), "name": team.get("name")} if team else None,
            "routes": routes, "explanation": explanation,
            "shelter_leg": shelter_leg}


@router.post("/replan")
def replan(body: dict):
    from app.services.react_agent import react_agent

    return react_agent.reason_and_act(body)


@router.post("/debate")
async def debate(body: dict):
    """LLM debate loop over the LIVE snapshot: dispatch vs shelter
    advocates argue with cited facts, a judge picks a winner. Read-only
    (no cards, holds, or dispatches) — the transcript lands in activity."""
    from app.agents_gateway import llm
    from app.services import debate as debate_service

    incident_id = (body or {}).get("incident_id")
    if not incident_id:
        raise HTTPException(status_code=422, detail="incident_id required")
    try:
        return await debate_service.run_debate(incident_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Incident not found")
    except llm.LLMNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        # LLM transport flakes (timeout/reset) must fail CLOSED with a clean
        # 503 — never a raw traceback 500. Deterministic path is unaffected.
        raise HTTPException(status_code=503, detail=f"debate engine unavailable: {type(exc).__name__}")


@router.get("/activity")
def activity_feed():
    return {"events": activity.recent_events(50)}
