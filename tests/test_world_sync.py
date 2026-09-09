"""world_sync tests — pure rank/provenance logic plus fake-store apply paths.

Run: backend/.venv/Scripts/python.exe backend/tests/test_world_sync.py
(no pytest in the venv; plain asserts, non-zero exit on failure).
"""

import sys
import time

sys.path.insert(0, "backend")

from app.services import world_sync as ws


def test_rank_order():
    assert ws.rank_of("COORDINATOR") == 100
    assert ws.rank_of("SIMULATION") == 80
    assert ws.rank_of("TEAM") == 60
    assert ws.rank_of("PUBLIC_API") == 40
    assert ws.rank_of("SYSTEM") == 10
    assert ws.rank_of(None) == 10
    assert ws.rank_of("nonsense") == 10
    assert ws.rank_of("coordinator") == 100


def test_resolve_matrix():
    ok, _ = ws.resolve(None, "TEAM")
    assert ok is True  # unknown incumbent always yields
    ok, _ = ws.resolve("TEAM", "SIMULATION")
    assert ok is True
    ok, _ = ws.resolve("SIMULATION", "SIMULATION")
    assert ok is True  # equal rank: newer wins
    ok, outcome = ws.resolve("COORDINATOR", "TEAM")
    assert ok is False and "60 <" in outcome and "100" in outcome
    ok, _ = ws.resolve("SYSTEM", "PUBLIC_API")
    assert ok is True  # seeds yield to any live source


def test_provenance_and_staleness():
    p = ws.provenance("TEAM", confidence=0.9)
    assert p["source"] == "TEAM" and isinstance(p["fetched_at"], int)
    assert ws.is_stale("team_location", None) is True
    assert ws.is_stale("team_location", {"fetched_at": int(time.time() * 1000)}) is False
    old = {"fetched_at": int(time.time() * 1000) - 10_000_000}
    assert ws.is_stale("team_location", old) is True
    assert ws.is_stale("nope", None) is True


def _fake_world():
    store = {"teams": {}, "activity": [], "published": []}

    class Teams:
        def get_team(self, tid):
            return store["teams"].get(tid)

        def update_location(self, tid, location, source="team"):
            store["teams"][tid] = {**(store["teams"].get(tid) or {"id": tid, "name": tid}),
                                   "location": location, "location_source": source}
            return store["teams"][tid]

        def update_team(self, tid, **fields):
            store["teams"][tid] = {**(store["teams"].get(tid) or {"id": tid, "name": tid}),
                                   **fields}
            return store["teams"][tid]

    class Activity:
        def log_event(self, **kw):
            store["activity"].append(kw)

    class Realtime:
        def publish(self, event, payload):
            store["published"].append((event, payload))

    return store, Teams(), Activity(), Realtime()


def _patch(monkey_targets):
    import app.db.repos.teams as teams_mod
    import app.db.repos.activity as activity_mod
    import app.services.realtime as realtime_mod

    saved = {}
    for mod, name, fake in monkey_targets:
        saved[(mod, name)] = getattr(mod, name)
        setattr(mod, name, fake)
    return saved


def _unpatch(saved):
    for (mod, name), fn in saved.items():
        setattr(mod, name, fn)


def test_apply_location_conflict_notifies():
    from app.db.repos import activity as activity_mod
    from app.db.repos import teams as teams_mod
    from app.services import realtime as realtime_mod

    store, teams, activity, realtime = _fake_world()
    saved = _patch([(teams_mod, "get_team", teams.get_team),
                    (teams_mod, "update_location", teams.update_location),
                    (activity_mod, "log_event", activity.log_event),
                    (realtime_mod, "publish", realtime.publish)])
    try:
        teams_mod.get_team("t1") or teams.update_location(
            "t1", {"lat": 1.0, "lng": 1.0}, source="TEAM")
        # TEAM GPS over unranked seed baseline: applies, no conflict note storm
        # (baseline has no source → SYSTEM).
        r1 = ws.apply_team_location("t1", {"lat": 2.0, "lng": 2.0}, source="TEAM")
        assert r1["applied"] is True
        # Coordinator pins it; TEAM heartbeat must not move it.
        teams.update_team("t1", location_source="COORDINATOR")
        r2 = ws.apply_team_location("t1", {"lat": 3.0, "lng": 3.0}, source="TEAM")
        assert r2["applied"] is False
        assert teams.get_team("t1")["location"] == {"lat": 2.0, "lng": 2.0}
        # SIMULATION outranks TEAM and triggers a coordinator notice.
        teams.update_team("t1", location_source="TEAM")
        r3 = ws.apply_team_location("t1", {"lat": 4.0, "lng": 4.0}, source="SIMULATION")
        assert r3["applied"] is True
        notices = [a for a in store["activity"] if a.get("type_") == "world_sync_notice"]
        assert any("overrode" in a.get("summary", "") for a in notices), store["activity"]
        assert any(e == "WORLD_SYNC_NOTICE" for e, _ in store["published"])
    finally:
        _unpatch(saved)


def test_apply_status_safety_override():
    from app.db.repos import teams as teams_mod

    store = {"teams": {"t9": {"id": "t9", "name": "T9", "status": "AVAILABLE",
                              "status_source": "COORDINATOR"}}}

    class Teams:
        def get_team(self, tid):
            return store["teams"].get(tid)

        def update_team(self, tid, **fields):
            store["teams"][tid] = {**store["teams"][tid], **fields}
            return store["teams"][tid]

    class Realtime:
        def publish(self, event, payload):
            pass

    class Activity:
        def log_event(self, **kw):
            pass

    import app.db.repos.activity as activity_mod
    import app.services.realtime as realtime_mod

    saved = _patch([(teams_mod, "get_team", Teams().get_team),
                    (teams_mod, "update_team", Teams().update_team),
                    (activity_mod, "log_event", Activity().log_event),
                    (realtime_mod, "publish", Realtime().publish)])
    try:
        # Self-reported breakdown beats even coordinator state.
        r = ws.apply_team_status("t9", "OFFLINE", source="TEAM", force=True)
        assert r["applied"] is True
        assert store["teams"]["t9"]["status"] == "OFFLINE"
        # ...while a routine TEAM status write does not.
        store["teams"]["t9"]["status_source"] = "COORDINATOR"
        r2 = ws.apply_team_status("t9", "AVAILABLE", source="TEAM")
        assert r2["applied"] is False
    finally:
        _unpatch(saved)


if __name__ == "__main__":
    test_rank_order()
    test_resolve_matrix()
    test_provenance_and_staleness()
    test_apply_location_conflict_notifies()
    test_apply_status_safety_override()
    print("world_sync: all tests passed")
