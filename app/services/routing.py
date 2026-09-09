"""Phase 7 routing engine — arch §17, §30.

Interface (stable since Phase 1): calculate_routes(origin, destination,
constraints) → candidates [{id, distance_km, feasible, blocked_reason,
coords, risk_penalty}]. Agent contract never changes (§17.2).

Engines, in order:
1. Valhalla service when VALHALLA_URL is set (same envelope back).
2. NetworkX constrained shortest paths over Overpass geometry.
3. Deterministic haversine stub (Overpass down / empty graph).

Constraints: closed roads + damaged bridges (ids + proximity), optional
risk-weighted cost from hazard circles. No LLM here — the Route Reasoning
Agent interprets these candidates (route_reasoning.py).
"""

from __future__ import annotations

import logging
import os

from app.db.repos import simulation_events
from app.services import geospatial, road_data

logger = logging.getLogger(__name__)

RISK_PENALTY_PER_KM = 0.5
PROXIMITY_BLOCK_M = 60

# Built-graph cache: key includes closure fingerprint so stale blocks
# can never leak into a new recommendation.
_GRAPH_CACHE: dict = {}

# District-wide graph per closure fingerprint: one build serves a whole
# board sweep. Warmed in the background at startup (see app.main).
_DISTRICT_CACHE: dict = {}


def _district_graph(blocked_ids: set[str], points: list[dict], circles: list[dict]):
    """Clean local-file graph per fingerprint (blocked edges omitted, so
    feasibility search never explores penalty dead-ends). Display paths
    keep their own small slice builds with blocked reasons intact."""
    fp = (tuple(sorted(blocked_ids)), _places_fp(points), _circles_fp(circles))
    clean = _DISTRICT_CACHE.get(fp)
    if clean is None:
        data = road_data.get_local_roads(26.5, 85.0, 27.3, 85.6)
        if not data.get("roads"):
            return None
        clean = _build_graph(data["roads"], data.get("bridges", []),
                             blocked_ids, points, circles, skip_blocked=True)
        _DISTRICT_CACHE.clear()
        _DISTRICT_CACHE[fp] = clean
    return clean


def prewarm_district_graph() -> None:
    """Background startup warming: first board sweep stays fast."""
    try:
        blocked_ids, points, circles = _closure_context()
        _district_graph(blocked_ids, points, circles)
    except Exception as exc:
        logger.warning("district prewarm skipped: %r", exc)


_PAIR_CACHE: dict = {}
_PAIR_TTL_S = 180


def _places_fp(points) -> tuple:
    """Content fingerprint for closure points (a moved closure must not
    collide with an old one just because the COUNT matches)."""
    try:
        return tuple(sorted(
            (round(float(p.get("lat", 0)), 5), round(float(p.get("lng", 0)), 5),
             str(p.get("kind", "")))
            for p in (points or [])))
    except Exception:
        return ()


def _circles_fp(circles) -> tuple:
    try:
        return tuple(sorted(
            (round(float(c.get("lat", 0)), 5), round(float(c.get("lng", 0)), 5),
             float(c.get("radius_m") or 0))
            for c in (circles or [])))
    except Exception:
        return ()


def pair_feasible(origin: dict, destination: dict) -> tuple[bool, str]:
    """Fast feasibility only: small local slice, one A* run. Results
    memoize per pair + closures (60s). Used by the allocation fan-out
    (dozens of pairs per board)."""
    import time as _time

    import networkx as nx

    try:
        o = (float(origin["lat"]), float(origin["lng"]))
        d = (float(destination["lat"]), float(destination["lng"]))
        blocked_ids, points, circles = _closure_context()
        key = ((round(o[0], 4), round(o[1], 4)), (round(d[0], 4), round(d[1], 4)),
               tuple(sorted(blocked_ids)), _places_fp(points), _circles_fp(circles))
        hit = _PAIR_CACHE.get(key)
        now = _time.time()
        if hit and now - hit[0] < _PAIR_TTL_S:
            return hit[1]
        if len(_PAIR_CACHE) >= 512:
            _PAIR_CACHE.pop(next(iter(_PAIR_CACHE)))

        g_pair = _district_graph(blocked_ids, points, circles)
        if g_pair is None:
            return True, ""
        clean = g_pair
        if clean.number_of_nodes() < 2:
            return True, ""
        src, dst = _nearest_node(clean, o), _nearest_node(clean, d)
        if src is None or dst is None or src == dst:
            return True, ""
        # Bidirectional Dijkstra on the CLEAN graph (blocked edges absent):
        # fast meet-in-the-middle instead of penalty dead-ends.
        try:
            _cost, path = nx.bidirectional_dijkstra(clean, src, dst, weight="weight")
        except nx.NetworkXNoPath:
            # No clean path: only call it blocked when a reported closure
            # sits on the corridor — otherwise it's an OSM data gap and
            # boat units stay routable (fail open).
            hits = _corridor_hits([o, d], points, o, d)
            if not hits:
                return True, ""
            out = (False, "; ".join(hits))
            _PAIR_CACHE[key] = (now, out)
            return out
        hits = _corridor_hits(path, points, o, d)
        out = (False, "; ".join(hits)) if hits else (True, "")
        _PAIR_CACHE[key] = (now, out)
        return out
    except Exception as exc:
        logger.warning("pair_feasible fallback (fail-open): %r", exc)
        return True, ""


_CLOSURE_CACHE: dict = {}


def _closure_context() -> tuple[set[str], list[dict], list[dict]]:
    import time as _time

    now = _time.time()
    cached = _CLOSURE_CACHE.get("ctx")
    if cached and now - cached[0] < 10:
        return cached[1]
    blocked_roads, damaged_bridges, points = _blocked_sets()
    ctx = (blocked_roads | damaged_bridges, points, _hazard_circles())
    _CLOSURE_CACHE["ctx"] = (now, ctx)
    return ctx


def _blocked_sets() -> tuple[set[str], set[str], list[dict]]:
    blocked_roads: set[str] = set()
    damaged_bridges: set[str] = set()
    points: list[dict] = []
    for ev in simulation_events.list_by_type("ROAD_BLOCKED", limit=50):
        payload = ev.get("payload") or {}
        rid = payload.get("road_id") or ev.get("entity_id")
        if rid:
            blocked_roads.add(str(rid))
        if payload.get("lat") is not None:
            points.append({"lat": float(payload["lat"]), "lng": float(payload["lng"]),
                           "kind": "ROAD_BLOCKED"})
    for ev in simulation_events.list_by_type("BRIDGE_BLOCKED", limit=50):
        payload = ev.get("payload") or {}
        bid = payload.get("bridge_id") or ev.get("entity_id")
        if bid:
            damaged_bridges.add(str(bid))
        if payload.get("lat") is not None:
            points.append({"lat": float(payload["lat"]), "lng": float(payload["lng"]),
                           "kind": "BRIDGE_DAMAGED"})
    return blocked_roads, damaged_bridges, points


def _hazard_circles() -> list[dict]:
    try:
        from app.db.repos import areas

        circles = []
        for a in areas.list_areas():
            c = a.get("center")
            if c and (a.get("level") in ("UNSAFE", "HOTSPOT", "RISING", "HIGH")):
                circles.append({"lat": float(c["lat"]), "lng": float(c["lng"]),
                                "radius_m": float(a.get("radius_m") or 2000)})
        return circles
    except Exception:
        return []


def _edge_blocked(road_id: str | None, blocked_ids: set[str]) -> str | None:
    if road_id and road_id in blocked_ids:
        return f"{road_id} reported closed"
    return None


def _proximity_penalty(mid: tuple[float, float], points: list[dict]) -> float:
    """Soft cost (not a verdict) so detours curve around closures."""
    for p in points:
        # Cheap bbox reject before the haversine.
        if abs(mid[0] - p["lat"]) > 0.002 or abs(mid[1] - p["lng"]) > 0.0025:
            continue
        d_km = geospatial.distance_km(mid[0], mid[1], p["lat"], p["lng"])
        if d_km * 1000 <= PROXIMITY_BLOCK_M:
            return 2.0
    return 0.0


def _corridor_hits(path: list, points: list[dict],
                   o: tuple[float, float], d: tuple[float, float],
                   end_tol_m: float = 120) -> list[str]:
    """Closure kinds the path genuinely threads (float display: closures
    within end_tol_m of either endpoint don't count — crews cover the
    last meters on foot). Ordered, unique."""
    hits, seen = [], set()
    for lat, lng in path:
        if (geospatial.distance_km(lat, lng, o[0], o[1]) * 1000 <= end_tol_m
                or geospatial.distance_km(lat, lng, d[0], d[1]) * 1000 <= end_tol_m):
            continue
        for p in points:
            if abs(lat - p["lat"]) > 0.001 or abs(lng - p["lng"]) > 0.0012:
                continue
            if geospatial.distance_km(lat, lng, p["lat"], p["lng"]) * 1000 <= PROXIMITY_BLOCK_M:
                kind = p["kind"].lower().replace("_", " ")
                if kind not in seen:
                    seen.add(kind)
                    hits.append(kind)
    return hits


def _circle_bounds(circles: list[dict]) -> list[dict]:
    out = []
    for c in circles:
        r_lat = c["radius_m"] / 111000
        r_lng = c["radius_m"] / 99000
        out.append({**c, "lat_min": c["lat"] - r_lat, "lat_max": c["lat"] + r_lat,
                    "lng_min": c["lng"] - r_lng, "lng_max": c["lng"] + r_lng})
    return out


def _edge_risk_penalty(mid: tuple[float, float], circles: list[dict]) -> float:
    penalty = 0.0
    for c in circles:
        lat_min = c.get("lat_min")
        if lat_min is None:  # raw circle without precomputed bounds
            d_km = geospatial.distance_km(mid[0], mid[1], c["lat"], c["lng"])
        elif not (c["lat_min"] <= mid[0] <= c["lat_max"]
                  and c["lng_min"] <= mid[1] <= c["lng_max"]):
            continue
        else:
            d_km = geospatial.distance_km(mid[0], mid[1], c["lat"], c["lng"])
        if d_km * 1000 <= c["radius_m"]:
            penalty += RISK_PENALTY_PER_KM * max(0.2, 1 - (d_km * 1000) / c["radius_m"])
    return round(penalty, 3)


def _build_graph(roads: list[dict], bridges: list[dict],
                 blocked_ids: set[str], points: list[dict],
                 circles: list[dict], skip_blocked: bool = False):
    import networkx as nx

    g = nx.Graph()
    bounded = _circle_bounds(circles)
    for feat in list(roads) + list(bridges):
        coords = feat.get("coords") or []
        for a, b in zip(coords, coords[1:]):
            mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            reason = _edge_blocked(feat.get("id"), blocked_ids)
            dist = geospatial.distance_km(a[0], a[1], b[0], b[1])
            risk = 0.0 if reason else _edge_risk_penalty(mid, bounded)
            detour = 0.0 if reason else _proximity_penalty(mid, points)
            g.add_edge(tuple(a), tuple(b),
                       weight=round(dist * (1 + risk) + detour + (1e6 if reason else 0), 4),
                       dist_km=round(dist, 4), road_id=feat.get("id"),
                       blocked_reason=reason)
    return g


def _nearest_node(g, pt: tuple[float, float]):
    key = id(g)
    idx = _NODE_INDEX.get(key)
    if idx is None:
        idx = _build_node_index(g)
        if len(_NODE_INDEX) >= 4:
            _NODE_INDEX.pop(next(iter(_NODE_INDEX)))
        _NODE_INDEX[key] = idx
    best, best_d = _nearest_indexed(idx, pt)
    if best is not None:
        return best
    for n in g.nodes:  # fallback: full scan (tiny graphs)
        d = geospatial.distance_km(pt[0], pt[1], n[0], n[1])
        if d < best_d:
            best, best_d = n, d
    return best


_NODE_INDEX: dict = {}


def _build_node_index(g) -> dict:
    cells: dict = {}
    for n in g.nodes:
        key = (round(n[0] * 200), round(n[1] * 200))
        cells.setdefault(key, []).append(n)
    return cells


def _nearest_indexed(idx: dict, pt: tuple[float, float]):
    cx, cy = round(pt[0] * 200), round(pt[1] * 200)
    best, best_d = None, float("inf")
    found_ever = False
    for ring in range(0, 45):
        improved = False
        for dx in range(-ring, ring + 1):
            for dy in (-ring, ring):
                for n in idx.get((cx + dx, cy + dy), ()):
                    d = geospatial.distance_km(pt[0], pt[1], n[0], n[1])
                    if d < best_d:
                        best, best_d = n, d
                        improved = True
            for dy in range(-ring + 1, ring):
                for dx in (-ring, ring):
                    for n in idx.get((cx + dx, cy + dy), ()):
                        d = geospatial.distance_km(pt[0], pt[1], n[0], n[1])
                        if d < best_d:
                            best, best_d = n, d
                            improved = True
        # Stop one quiet ring after the last improvement: anything farther
        # out cannot beat the best already found (previously the flag
        # reset every ring, so the search ran all 45 rings every call).
        if improved:
            found_ever = True
        elif found_ever and ring >= 1:
            return best, best_d
    return best, best_d


def _graph_candidates(origin: dict, destination: dict,
                      blocked_ids: set[str], points: list[dict],
                      circles: list[dict]) -> list[dict] | None:
    """Constrained k-shortest paths over live Overpass geometry."""
    import networkx as nx

    o = (float(origin["lat"]), float(origin["lng"]))
    d = (float(destination["lat"]), float(destination["lng"]))
    pad = 0.05
    lo_lat = min(o[0], d[0]) - pad
    lo_lng = min(o[1], d[1]) - pad
    hi_lat = max(o[0], d[0]) + pad
    hi_lng = max(o[1], d[1]) + pad
    # Local disk graph first (instant); live Overpass only as fallback.
    data = road_data.get_local_roads(lo_lat, lo_lng, hi_lat, hi_lng)
    if not data.get("roads"):
        try:
            import math

            data = road_data.get_roads(
                math.floor(lo_lat * 10) / 10, math.floor(lo_lng * 10) / 10,
                math.ceil(hi_lat * 10) / 10, math.ceil(hi_lng * 10) / 10,
                timeout=6)
        except Exception:
            return None
    fingerprint = (round(lo_lat, 2), round(lo_lng, 2), round(hi_lat, 2), round(hi_lng, 2),
                   tuple(sorted(blocked_ids)), _places_fp(points), _circles_fp(circles))
    g = _GRAPH_CACHE.get(fingerprint)
    if g is None:
        g = _build_graph(data.get("roads", []), data.get("bridges", []),
                         blocked_ids, points, circles)
        if len(_GRAPH_CACHE) >= 4:
            _GRAPH_CACHE.pop(next(iter(_GRAPH_CACHE)))
        _GRAPH_CACHE[fingerprint] = g
    if g.number_of_nodes() < 2:
        return None
    if g.number_of_edges() > 60000:
        # Slice too large for street-level paths (e.g. inter-city hops) —
        # callers fall back to stub candidates, which are honest at that scale.
        return None
    src, dst = _nearest_node(g, o), _nearest_node(g, d)
    if src is None or dst is None or src == dst:
        return None
    cands: list[dict] = []
    seen: set = set()
    try:
        # Bounded alternates: one Dijkstra plus two re-runs with used-edge
        # penalties. Predictable and fast, unlike Yen's enumeration which
        # explodes on large graphs.
        penalties: dict = {}
        for i in range(3):
            def _w(u, v, d, _pen=penalties):
                return d.get("weight", 1) * _pen.get((u, v), 1)

            try:
                path = nx.shortest_path(g, src, dst, weight=_w, method="dijkstra")
            except Exception:
                break
            sig = tuple(path)
            if sig in seen:
                break
            seen.add(sig)
            for u, v in zip(path, path[1:]):
                penalties[(u, v)] = penalties.get((u, v), 1) * 4
                penalties[(v, u)] = penalties.get((v, u), 1) * 4
            dist = sum(g[u][v].get("dist_km", 0) for u, v in zip(path, path[1:]))
            hard = [g[u][v].get("blocked_reason")
                    for u, v in zip(path, path[1:]) if g[u][v].get("blocked_reason")]
            # Collapse repeats: one closed street taints many edges.
            seen_reasons, deduped = set(), []
            for b in hard + _corridor_hits(path, points, o, d):
                for part in [p.strip() for p in b.split(";")]:
                    if part and part not in seen_reasons:
                        seen_reasons.add(part)
                        deduped.append(part)
            risk = sum(_edge_risk_penalty(
                ((u[0] + v[0]) / 2, (u[1] + v[1]) / 2), circles)
                for u, v in zip(path, path[1:]))
            cands.append({
                "id": f"ROUTE-GRAPH-{i + 1}",
                "distance_km": round(dist, 2),
                "feasible": not deduped,
                "blocked_reason": "; ".join(deduped) if deduped else None,
                "risk_penalty": round(risk, 2),
                "coords": [[round(lat, 6), round(lng, 6)] for lat, lng in path],
            })
    except Exception:
        return None
    # Feasible first, then shortest.
    cands.sort(key=lambda c: (not c["feasible"], c["distance_km"]))
    return cands or None


def _valhalla_candidates(origin: dict, destination: dict) -> list[dict] | None:
    url = os.environ.get("VALHALLA_URL")
    if not url:
        return None
    try:
        import httpx

        resp = httpx.post(url.rstrip("/") + "/route", json={
            "locations": [
                {"lat": float(origin["lat"]), "lon": float(origin["lng"])},
                {"lat": float(destination["lat"]), "lon": float(destination["lng"])},
            ],
            "costing": "auto",
        }, timeout=8)
        resp.raise_for_status()
        data = resp.json()
        leg = (data.get("trip") or {}).get("legs", [{}])[0]
        shape = leg.get("shape") or []
        dist = float((data.get("trip") or {}).get("summary", {}).get("length", 0))
        return [{"id": "ROUTE-VALHALLA-1", "distance_km": round(dist, 2),
                 "feasible": True, "blocked_reason": None,
                 "risk_penalty": 0.0, "coords": shape}]
    except Exception:
        return None


def _stub_candidates(origin: dict, destination: dict,
                     blocked: bool) -> list[dict]:
    dist = geospatial.distance_km(
        float(origin["lat"]), float(origin["lng"]),
        float(destination["lat"]), float(destination["lng"]))
    return [
        {"id": "ROUTE-A", "distance_km": round(dist, 2),
         "feasible": not blocked,
         "blocked_reason": "blocked corridor reported" if blocked else None,
         "risk_penalty": 0.0, "coords": []},
        {"id": "ROUTE-B", "distance_km": round(dist * 1.2 + 0.4, 2),
         "feasible": True, "blocked_reason": None,
         "risk_penalty": 0.0, "coords": []},
        {"id": "ROUTE-C", "distance_km": round(dist * 1.35 + 0.6, 2),
         "feasible": True, "blocked_reason": None,
         "risk_penalty": 0.0, "coords": []},
    ]


def calculate_routes(
    origin: dict, destination: dict, constraints: dict | None = None
) -> list[dict]:
    """Deterministic candidates honoring closures + risk weights."""
    constraints = constraints or {}
    valhalla = _valhalla_candidates(origin, destination)
    if valhalla:
        return valhalla

    blocked_roads, damaged_bridges, points = _blocked_sets()
    blocked_ids = set(blocked_roads) | set(damaged_bridges)
    circles = [] if constraints.get("ignore_risk") else _hazard_circles()

    try:
        graph = _graph_candidates(origin, destination, blocked_ids, points, circles)
        if graph:
            return graph
    except Exception:
        pass

    dist_blocked = bool(blocked_ids or points)
    return _stub_candidates(origin, destination, dist_blocked)
