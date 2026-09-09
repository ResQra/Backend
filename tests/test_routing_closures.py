"""Closure reaction regression test (scenario 7 mechanism).

A ROAD_BLOCKED write at the best route's midpoint must observably change
the plan on the very next calculation — no TTL staleness. In a dense
street graph the engine reroutes by design (soft detour cost, not a
verdict), so the assertion is on the RECOMMENDED PATH changing (or a
candidate flipping infeasible where no detour exists).
"""

import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db.client import table  # noqa: E402
from app.services import routing, world_sync  # noqa: E402

ORIGIN = {"lat": 26.7670, "lng": 85.2920}
DEST = {"lat": 26.7650, "lng": 85.2790}

# Closure/area rows are GLOBAL state (no run scope): snapshot + restore so
# dry-run residue can never fake or mask the flip under test.
WIPED = ["SimulationEvents", "AreaRisk"]


def _snapshot():
    return {t: table(t).scan().get("Items", []) for t in WIPED}


def _restore(snap):
    for t in WIPED:
        tbl = table(t)
        keys = [k["AttributeName"] for k in tbl.key_schema]
        for it in tbl.scan().get("Items", []):
            try:
                tbl.delete_item(Key={k: it[k] for k in keys})
            except Exception:
                pass
        for it in snap.get(t, []):
            try:
                tbl.put_item(Item=it)
            except Exception:
                pass
        if t == "SimulationEvents":
            routing._CLOSURE_CACHE.pop("ctx", None)


def _clear():
    for t in WIPED:
        tbl = table(t)
        keys = [k["AttributeName"] for k in tbl.key_schema]
        for it in tbl.scan().get("Items", []):
            try:
                tbl.delete_item(Key={k: it[k] for k in keys})
            except Exception:
                pass
    routing._CLOSURE_CACHE.pop("ctx", None)


def test_closure_flips_route_immediately():
    snap = _snapshot()
    _clear()
    try:
        routes = routing.calculate_routes(ORIGIN, DEST)
        assert routes, "no routes computed"
        old_best = next((r for r in routes if r.get("feasible")), routes[0])
        old_coords = old_best["coords"]
        mid = old_coords[len(old_coords) // 2]
        key = f"probe-{uuid.uuid4().hex[:8]}"
        world_sync.apply_sensor(
            kind="ROAD_BLOCKED", lat=float(mid[0]), lng=float(mid[1]),
            value=None, level="UNSAFE", note="closure probe",
            source="SIMULATION", idempotency_key=key)
        after = routing.calculate_routes(ORIGIN, DEST)
        assert after, "no routes after closure"
        new_best = next((r for r in after if r.get("feasible")), after[0])
        changed = new_best["coords"] != old_coords
        flipped = any(not r.get("feasible") for r in after)
        cites = any("block" in str(r.get("blocked_reason", "")).lower()
                    or "clos" in str(r.get("blocked_reason", "")).lower()
                    for r in after)
        assert changed or flipped, (
            "closure changed nothing: same best path, all feasible")
    finally:
        _restore(snap)
