"""Phase 1 geospatial service — arch §18, §31 (deterministic, no LLM).

Wraps utils.geo + areas repo + road_data. Agents call these helpers;
they never compute geometry themselves (§81).
"""

from __future__ import annotations

from app.db.repos import areas
from app.utils.geo import geohash_encode, haversine_km


def encode_geohash(lat: float, lng: float) -> str:
    return geohash_encode(lat, lng)


def distance_km(a_lat: float, a_lng: float, b_lat: float, b_lng: float) -> float:
    return haversine_km(a_lat, a_lng, b_lat, b_lng)


def list_risk_areas() -> list[dict]:
    return areas.list_areas()


def cluster_incidents(incidents: list[dict]) -> dict[str, list[dict]]:
    """Trivial geohash clustering for Phase 1 (Phase 7 refines)."""
    buckets: dict[str, list[dict]] = {}
    for inc in incidents:
        loc = inc.get("location") or {}
        if loc.get("lat") is None or loc.get("lng") is None:
            buckets.setdefault("unlocated", []).append(inc)
            continue
        gh = geohash_encode(float(loc["lat"]), float(loc["lng"]))[:6]
        buckets.setdefault(gh, []).append(inc)
    return buckets
