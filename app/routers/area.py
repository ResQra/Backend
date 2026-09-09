"""Area / District selection presets for Rautahat District, Nepal.

Laser-focused on Rautahat District (Gaur - Bagmati & Lalbakaiya Basins)
with designated operational flood sectors aligned with HDX 'hot_flood_npl'.
"""

from __future__ import annotations
from fastapi import APIRouter, Query
from pydantic import BaseModel

router = APIRouter(prefix="/api/area", tags=["area"])

# ---------------------------------------------------------------------------
# Preset sectors within Rautahat District
# ---------------------------------------------------------------------------

PRESETS: dict[str, dict] = {
    "rautahat": {
        "name": "Rautahat District (All Sectors)",
        "center": [26.7640, 85.2780],
        "zoom": 12,
        "bounds": {"sw": [26.65, 85.18], "ne": [27.15, 85.42]},
        "country": "NP",
    },
    "gaur_urban": {
        "name": "Gaur Municipality (Bagmati Breach)",
        "center": [26.7620, 85.2760],
        "zoom": 14,
        "bounds": {"sw": [26.74, 85.25], "ne": [26.78, 85.30]},
        "country": "NP",
    },
    "lalbakaiya_tikuliya": {
        "name": "Tikuliya Ghat (Lalbakaiya Basin)",
        "center": [26.7850, 85.2420],
        "zoom": 14,
        "bounds": {"sw": [26.76, 85.22], "ne": [26.81, 85.27]},
        "country": "NP",
    },
    "garuda": {
        "name": "Garuda Municipality (Central Lowland)",
        "center": [26.9250, 85.3120],
        "zoom": 13,
        "bounds": {"sw": [26.89, 85.28], "ne": [26.96, 85.35]},
        "country": "NP",
    },
    "chandrapur": {
        "name": "Chandranigahapur (Highway Evac Base)",
        "center": [27.1250, 85.3400],
        "zoom": 13,
        "bounds": {"sw": [27.08, 85.30], "ne": [27.18, 85.38]},
        "country": "NP",
    },
}


class CustomBounds(BaseModel):
    sw_lat: float
    sw_lng: float
    ne_lat: float
    ne_lng: float


@router.get("/presets")
def list_presets():
    """Return all demo-ready sectors."""
    return {
        "presets": [
            {"id": k, "name": v["name"], "center": v["center"], "zoom": v["zoom"]}
            for k, v in PRESETS.items()
        ]
    }


@router.get("/config")
def area_config(area: str = Query("rautahat")):
    """Return center, zoom, bounds for a named area or custom bbox."""
    if area in PRESETS:
        return PRESETS[area]
    return PRESETS.get("rautahat", {
        "name": "Rautahat District",
        "center": [26.7640, 85.2780],
        "zoom": 12,
        "bounds": {"sw": [26.65, 85.18], "ne": [27.15, 85.42]},
    })


@router.get("/roads")
def area_roads(sw_lat: float = 0, sw_lng: float = 0, ne_lat: float = 0, ne_lng: float = 0):
    """Road + bridge geometry for a bbox with live closure markers.

    Merges Overpass geometry (services.road_data, cached 30 min) with
    blockade events from the world state so closed corridors render.
    Always returns blocked_events even when Overpass is unreachable.
    """
    from app.db.repos import simulation_events
    from app.services import road_data

    blocked = []
    for kind in ("ROAD_BLOCKED", "BRIDGE_BLOCKED"):
        try:
            for ev in simulation_events.list_by_type(kind, limit=20):
                payload = ev.get("payload") or {}
                if payload.get("lat") is None or payload.get("lng") is None:
                    continue
                blocked.append({
                    "lat": float(payload["lat"]),
                    "lng": float(payload["lng"]),
                    "kind": kind,
                    "level": payload.get("level", "BLOCKED"),
                })
        except Exception:
            continue

    if not all([sw_lat, sw_lng, ne_lat, ne_lng]):
        return {"roads": [], "bridges": [], "blocked_events": blocked}
    # Local disk graph first (instant); live Overpass only as fallback.
    local = road_data.get_local_roads(sw_lat, sw_lng, ne_lat, ne_lng)
    if local.get("roads"):
        local["blocked_events"] = blocked
        return _capped(local)
    try:
        data = road_data.get_roads(sw_lat, sw_lng, ne_lat, ne_lng)
    except Exception:
        data = {"roads": [], "bridges": [], "error": "overpass_unavailable"}
    return _capped({**data, "blocked_events": blocked})


def _capped(data: dict) -> dict:
    """Cap render load: major corridors first. Full graph stays
    available to the routing engine server-side."""
    priority = {"motorway": 0, "trunk": 1, "primary": 2, "secondary": 3,
                "tertiary": 4, "unclassified": 5, "residential": 6}
    roads = sorted(data.get("roads", []),
                   key=lambda r: priority.get(str(r.get("type", "")).lower(), 9))[:1200]
    data["roads"] = roads
    data["bridges"] = data.get("bridges", [])[:400]
    data["truncated"] = True
    return data
