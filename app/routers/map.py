"""Phase 1 map/GIS API ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â arch Ãƒâ€šÃ‚Â§20, Ãƒâ€šÃ‚Â§65. Read-only views of world state."""

from fastapi import APIRouter, Depends

from app.auth.deps import get_current_user
from app.db.repos import areas, incidents, shelters, simulation_events, teams, users

router = APIRouter(prefix="/api/map", tags=["map"])


@router.get("/layers")
def layers(_=Depends(get_current_user)):
    sensor = []
    for kind in ["WATER_LEVEL", "ROAD_BLOCKED", "BRIDGE_BLOCKED", "PEOPLE_DENSITY", "FLOOD_AREA"]:
        sensor.extend(simulation_events.list_by_type(kind, limit=10))
    return {
        "incidents": incidents.list_open_incidents(),
        "teams": teams.list_teams(),
        "shelters": shelters.list_shelters(),
        "residents": users.list_residents_with_location(),
        "areas": areas.list_areas(),
        "sensor_events": sensor,
    }


@router.get("/roads")
def roads(sw_lat: float = 0, sw_lng: float = 0, ne_lat: float = 0, ne_lng: float = 0,
          _=Depends(get_current_user)):
    from app.services import road_data

    if not all([sw_lat, sw_lng, ne_lat, ne_lng]):
        return {"roads": [], "bridges": []}
    return road_data.get_roads(sw_lat, sw_lng, ne_lat, ne_lng)


@router.get("/bridges")
def bridges(sw_lat: float = 0, sw_lng: float = 0, ne_lat: float = 0, ne_lng: float = 0,
            _=Depends(get_current_user)):
    from app.services import road_data

    if not all([sw_lat, sw_lng, ne_lat, ne_lng]):
        return {"bridges": []}
    data = road_data.get_roads(sw_lat, sw_lng, ne_lat, ne_lng)
    return {"bridges": data.get("bridges", [])}


@router.get("/hazards")
def hazards(_=Depends(get_current_user)):
    return {"hazards": areas.list_areas()}


@router.get("/elevation")
def elevation(_=Depends(get_current_user)):
    # Phase 2 wires DEM/terrain; Phase 1 returns contract-stable null.
    return {"elevation": None, "source": "dem-pending-phase-2"}


@router.get("/gev")
def gev(sw_lat: float | None = None, sw_lng: float | None = None,
        ne_lat: float | None = None, ne_lng: float | None = None,
        area: str = "rautahat", _=Depends(get_current_user)):
    """Phase 2 adapter — one Cesium-ready payload (arch §19)."""
    from app.services import gev_adapter

    bbox = None
    if None not in (sw_lat, sw_lng, ne_lat, ne_lng):
        bbox = {"sw_lat": sw_lat, "sw_lng": sw_lng, "ne_lat": ne_lat, "ne_lng": ne_lng}
    return gev_adapter.get_gev(bbox, area)
