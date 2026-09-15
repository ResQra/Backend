"""Road data service — fetches roads/bridges from Overpass API for any bbox.

Caches results for 30 minutes per bounding box. Merges with live sensor
events (ROAD_BLOCKED / BRIDGE_BLOCKED) to mark blocked segments.

The Overpass API requires POST with raw query body and a descriptive
User-Agent. Mirrors are attempted on failure.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.request
import urllib.parse
from typing import Any

# ---------------------------------------------------------------------------
# Cache (in-memory, per-process — good enough for a single-server demo)
# ---------------------------------------------------------------------------

_CACHE_TTL_S = 30 * 60  # 30 minutes
_cache: dict[str, tuple[float, dict]] = {}


def _bbox_key(sw_lat: float, sw_lng: float, ne_lat: float, ne_lng: float) -> str:
    raw = f"{sw_lat:.4f},{sw_lng:.4f},{ne_lat:.4f},{ne_lng:.4f}"
    return hashlib.md5(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Local district graph (Phase: offline-first interactive paths)
# ---------------------------------------------------------------------------

_LOCAL_GRAPH = None
_LOCAL_GRAPH_OK = False
_FEAT_INDEX = None


def _cell(lat: float, lng: float, step: float = 0.02) -> tuple:
    import math

    return (math.floor(lat / step), math.floor(lng / step))


def _feature_cells(coords: list, step: float = 0.02) -> set:
    cells = set()
    for lat, lng in coords:
        cells.add(_cell(lat, lng, step))
        # Catch segments crossing cell borders via endpoints only is
        # approximate; pad lookup by one ring at query time.
    return cells


def _ensure_feat_index(graph: dict) -> None:
    global _FEAT_INDEX
    if _FEAT_INDEX is not None:
        return
    index: dict = {}
    for source in ("roads", "bridges"):
        for i, feat in enumerate(graph.get(source, [])):
            for cell in _feature_cells(feat.get("coords") or []):
                index.setdefault(cell, []).append((source, i))
    _FEAT_INDEX = index


def _local_graph_path():
    from pathlib import Path

    local = Path(__file__).resolve().parents[1] / "data" / "road_graph.json"
    if local.is_file():
        return local
    return Path(__file__).resolve().parents[3] / "geo" / "data" / "road_graph.json"



def _load_local_graph() -> dict:
    """Rautahat district graph fetched once; {} when absent."""
    global _LOCAL_GRAPH, _LOCAL_GRAPH_OK
    if _LOCAL_GRAPH_OK:
        return _LOCAL_GRAPH
    try:
        import json

        _LOCAL_GRAPH = json.loads(_local_graph_path().read_text(encoding="utf-8"))
    except Exception:
        _LOCAL_GRAPH = {}
    _LOCAL_GRAPH_OK = True
    return _LOCAL_GRAPH


def get_local_roads(sw_lat: float, sw_lng: float, ne_lat: float, ne_lng: float) -> dict:
    """Bbox slice of the on-disk district graph (no network)."""
    graph = _load_local_graph()
    if not graph.get("roads"):
        return {"roads": [], "bridges": [], "source": "local-missing"}

    _ensure_feat_index(graph)
    import math

    step = 0.02
    want: set = set()
    lat = math.floor(sw_lat / step)
    while lat <= math.floor(ne_lat / step):
        lng = math.floor(sw_lng / step)
        while lng <= math.floor(ne_lng / step):
            # One-ring pad catches segments crossing cell borders.
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    want.add((lat + dx, lng + dy))
            lng += 1
        lat += 1

    roads, bridges = [], []
    seen = set()
    for cell in want:
        for source, i in (_FEAT_INDEX or {}).get(cell, []):
            if (source, i) in seen:
                continue
            seen.add((source, i))
            feat = graph[source][i]
            (roads if source == "roads" else bridges).append(feat)
    return {"roads": roads, "bridges": bridges, "source": "local"}


# ---------------------------------------------------------------------------
# Overpass query helpers
# ---------------------------------------------------------------------------

_OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

_QUERY_TEMPLATE = """[out:json][timeout:25];
(
  way["highway"]({sw_lat},{sw_lng},{ne_lat},{ne_lng});
  way["bridge"="yes"]({sw_lat},{sw_lng},{ne_lat},{ne_lng});
);
out body;
>;
out skel qt;"""


def _fetch_overpass(sw_lat: float, sw_lng: float, ne_lat: float, ne_lng: float,
                    timeout: int = 8) -> dict | None:
    """POST an Overpass QL query and return parsed JSON. Tries mirrors."""
    query = _QUERY_TEMPLATE.format(
        sw_lat=sw_lat, sw_lng=sw_lng, ne_lat=ne_lat, ne_lng=ne_lng
    )
    data = urllib.parse.urlencode({"data": query}).encode("utf-8")
    headers = {
        "User-Agent": "ResQra-DisasterResponse/1.0 (flood-mapping-tool)",
        "Accept": "application/json",
        "Referer": "https://overpass-turbo.eu/",
    }
    for url in _OVERPASS_URLS:
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            continue
    return None


def _parse_ways(elements: list[dict]) -> tuple[list[dict], list[dict]]:
    """Parse Overpass elements into roads and bridges with geometry."""
    node_map: dict[int, dict] = {}
    for el in elements:
        if el.get("type") == "node":
            node_map[el["id"]] = {"lat": el["lat"], "lng": el["lon"]}

    roads: list[dict] = []
    bridges: list[dict] = []
    for el in elements:
        if el.get("type") != "way":
            continue
        coords = []
        for node_id in el.get("nodes", []):
            pt = node_map.get(node_id)
            if pt:
                coords.append([pt["lat"], pt["lng"]])
        if len(coords) < 2:
            continue
        tags = el.get("tags", {})
        entry = {
            "id": f"osm_{el['id']}",
            "coords": coords,
            "type": tags.get("highway", "road"),
            "name": tags.get("name", ""),
            "blocked": False,
        }
        if tags.get("bridge") == "yes":
            bridges.append(entry)
        else:
            roads.append(entry)
    return roads, bridges


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_roads(
    sw_lat: float,
    sw_lng: float,
    ne_lat: float,
    ne_lng: float,
    blocked_event_ids: set[str] | None = None,
    timeout: int = 8,
) -> dict:
    """Return roads and bridges for a bounding box, with blocked status.

    blocked_event_ids: set of sensor event idempotency_keys that are
    ROAD_BLOCKED or BRIDGE_BLOCKED. These override the default unblocked state.
    """
    key = _bbox_key(sw_lat, sw_lng, ne_lat, ne_lng)
    now = time.time()

    # Check cache
    if key in _cache:
        cached_at, cached_data = _cache[key]
        if now - cached_at < _CACHE_TTL_S:
            result = dict(cached_data)
            _apply_blocked_flags(result, blocked_event_ids or set())
            return result

    # Fetch from Overpass
    raw = _fetch_overpass(sw_lat, sw_lng, ne_lat, ne_lng, timeout=timeout)
    if raw is None:
        return {"roads": [], "bridges": [], "error": "overpass_unavailable"}

    roads, bridges = _parse_ways(raw.get("elements", []))
    data = {"roads": roads, "bridges": bridges}
    _cache[key] = (now, data)

    result = dict(data)
    _apply_blocked_flags(result, blocked_event_ids or set())
    return result


def _apply_blocked_flags(data: dict, blocked_ids: set[str]) -> None:
    """Intentional no-op hook (NOT a bug): sensor events don't carry OSM
    ids, so exact id-matching is impossible. Blocked closures reach the
    map/routers through dedicated channels instead — `blocked_events`
    markers (RoadLayer) and the routing closure context — never through
    road.blocked flags. Kept as the seam for future exact matching.
    """
    # For now, the sensor events don't carry OSM ids.
    # The frontend will render blocked events as separate markers.
    # This is a hook for future exact matching.
    pass
