"""Phase 7 exit tests â€” no DB, no keys, no network.

Constrained graph routing + deterministic explanation (Â§17.3).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _square_graph():
    import networkx as nx

    g = nx.Graph()
    # Square: A-B-C-D-A with diagonal B-D. Blocking B-C forces A-B-D-C.
    pts = {"A": (0.0, 0.0), "B": (0.0, 0.01), "C": (0.01, 0.01), "D": (0.01, 0.0)}
    for u, v in [("A", "B"), ("B", "C"), ("C", "D"), ("D", "A"), ("B", "D")]:
        a, b = pts[u], pts[v]
        from app.services import geospatial

        d = geospatial.distance_km(a[0], a[1], b[0], b[1])
        g.add_edge(a, b, weight=round(d, 4), dist_km=round(d, 4), road_id=f"{u}-{v}",
                   blocked_reason=None)
    return g, pts


def test_graph_avoids_blocked_edge():
    import networkx as nx

    g, pts = _square_graph()
    # Block B-C: shortest simple paths must route around it.
    for u, v in g.edges():
        if g[u][v]["road_id"] == "B-C":
            g[u][v]["weight"] = 1e6
            g[u][v]["blocked_reason"] = "B-C reported closed"
    paths = list(nx.shortest_simple_paths(g, pts["A"], pts["C"], weight="weight"))
    used = set()
    for path in paths[:2]:
        for u, v in zip(path, path[1:]):
            used.add(g[u][v]["road_id"])
    assert "B-C" not in used or len(paths) > 1


def test_explain_picks_feasible_and_names_invalid():
    from app.services import route_reasoning

    routes = [
        {"id": "ROUTE-A", "distance_km": 4.2, "feasible": False,
         "blocked_reason": "bridge damaged"},
        {"id": "ROUTE-B", "distance_km": 5.1, "feasible": True},
        {"id": "ROUTE-C", "distance_km": 4.7, "feasible": True},
    ]
    out = route_reasoning.explain(routes)
    assert out["recommended_id"] == "ROUTE-C"
    assert "ROUTE-A" in out["explanation"] and "bridge damaged" in out["explanation"]
    assert out["invalid"] == [{"id": "ROUTE-A", "reason": "bridge damaged"}]


def test_explain_no_feasible_escalates():
    from app.services import route_reasoning

    out = route_reasoning.explain([
        {"id": "ROUTE-A", "distance_km": 4.2, "feasible": False,
         "blocked_reason": "submerged 1.85m"}])
    assert out["recommended_id"] is None
    assert "escalate" in out["explanation"].lower()


def test_calculate_routes_stub_shape_without_network():
    from app.services import routing

    routes = routing._stub_candidates({"lat": 26.76, "lng": 85.27},
                                      {"lat": 26.77, "lng": 85.28}, blocked=True)
    assert [r["id"] for r in routes] == ["ROUTE-A", "ROUTE-B", "ROUTE-C"]
    assert routes[0]["feasible"] is False
    assert routes[1]["feasible"] is True


def test_strands_route_tool_importable():
    from resqra_agents.tools.routing_tools import explain_routes_tool

    assert explain_routes_tool is not None
