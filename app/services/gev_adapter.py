"""Phase 2 GEV adapter — arch §19.

God's Eye View / Cesium stays the visualization foundation; ResQra owns
the data. This adapter merges file-based district GIS + live world state
into one Cesium-ready payload so the frontend never improvises geometry:

  { base: {...geojson...}, operational: {...}, routes: [...] }

CRS rule: GeoJSON is [lng,lat]; Leaflet props are [lat,lng]. Convert at
the edge, never in agents.
"""

from __future__ import annotations


def _safe(fn, default):
    try:
        return fn()
    except Exception:
        return default


def get_gev(bbox: dict | None = None, area: str = "rautahat") -> dict:
    from app.db.repos import areas, incidents, shelters, simulation_events, teams
    from app.services import rautahat_digital_twin, road_data

    twin = {
        "boundary": _safe(rautahat_digital_twin.get_district_boundary, {}),
        "municipalities": _safe(rautahat_digital_twin.get_municipalities_geojson, {}),
        "rivers": _safe(rautahat_digital_twin.get_rivers_geojson, {}),
        "embankments": _safe(rautahat_digital_twin.get_embankments_geojson, {}),
        "flood_2024": _safe(rautahat_digital_twin.get_flood_2024_geojson, {}),
        "infrastructure": _safe(rautahat_digital_twin.get_infrastructure_geojson, {}),
        "rescue_fleet": _safe(rautahat_digital_twin.get_rescue_fleet_geojson, {}),
    }

    roads = {"roads": [], "bridges": []}
    if bbox:
        roads = _safe(
            lambda: road_data.get_roads(
                bbox["sw_lat"], bbox["sw_lng"], bbox["ne_lat"], bbox["ne_lng"]), roads)

    sensor = []
    for kind in ["WATER_LEVEL", "ROAD_BLOCKED", "BRIDGE_BLOCKED", "PEOPLE_DENSITY", "FLOOD_AREA"]:
        sensor.extend(_safe(lambda k=kind: simulation_events.list_by_type(k, limit=10), []))

    return {
        "area": area,
        "crs": "EPSG:4326",
        "base": twin,
        "operational": {
            "incidents": _safe(incidents.list_open_incidents, []),
            "teams": _safe(teams.list_teams, []),
            "shelters": _safe(shelters.list_shelters, []),
            "areas": _safe(areas.list_areas, []),
            "sensor_events": sensor,
            "roads": roads.get("roads", []),
            "bridges": roads.get("bridges", []),
        },
        "routes": [],
    }
