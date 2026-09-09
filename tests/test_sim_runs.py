"""Phase B: simulation runs + sim clock + story beats (TDD — RED first).

Covers: prepare, create run, sync tick (clock + beat firing with run_id),
pause/resume/speed/stop, SOS_BURST honest DEFERRED status (Phase D executes).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402

import app.main as app_main  # noqa: E402
from app.db.client import table  # noqa: E402
from app.db.repos import activity as activity_repo  # noqa: E402

client = TestClient(app_main.app)


def ensure_admin():
    from app.auth.security import hash_password
    from app.db.repos import users as users_repo
    if users_repo.find_by_username("resqra-admin") is None:
        users_repo.create_user(name="Control Room", role="coordinator",
                               username="resqra-admin",
                               password_hash=hash_password("resqra-admin-123"))


ensure_admin()


def ah():
    from tests.run_test_utils import resilient_login
    return resilient_login(client)


def wipe_run(run_id):
    for evt in activity_repo.recent_events(200):
        if evt.get("run_id") == run_id or (evt.get("payload") or {}).get("run_id") == run_id:
            try:
                table("ActivityEvent").delete_item(Key={"id": evt["id"]})
            except Exception:
                pass
    try:
        table("SimulationRuns").delete_item(Key={"id": run_id})
    except Exception:
        pass


WIPED_TABLES = ["Incidents", "Teams", "Shelters", "PendingActions", "Missions",
                "ActivityEvent", "SimulationEvents", "GovReports", "Users"]


def snapshot_tables():
    return {t: table(t).scan().get("Items", []) for t in WIPED_TABLES}


def restore_tables(snap):
    for t in WIPED_TABLES:
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


def test_prepare_returns_baseline():
    h = ah()
    snap = snapshot_tables()
    try:
        r = client.post("/api/simulation/scenarios/flood-48h-01/prepare", headers=h)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("scenario_id") == "flood-48h-01"
        assert body.get("teams", 0) >= 6, body
    finally:
        restore_tables(snap)


def test_create_tick_pause_stop():
    h = ah()
    beats = [
        {"id": "t-beat-1", "at_min": 5, "kind": "SIM_EVENT",
         "event": {"type": "COMMUNICATION_LOST",
                   "target": {"type": "TEAM", "id": "team_probe"},
                   "parameters": {}}},
        {"id": "t-burst-1", "at_min": 10, "kind": "SOS_BURST",
         "note": "Phase D executes this"},
    ]
    r = client.post("/api/simulation/runs", headers=h, json={
        "scenario_id": "flood-48h-01", "mode": "AUTONOMOUS_TEST",
        "seed": 7, "beats_override": beats})
    assert r.status_code == 200, r.text
    run = r.json()
    run_id = run["run_id"]
    try:
        assert run["clock_label"] == "Day 1 06:00", run
        assert run["status"] == "RUNNING", run

        t = client.post(f"/api/simulation/runs/{run_id}/tick", headers=h,
                        json={"minutes": 6})
        assert t.status_code == 200, t.text
        tb = t.json()
        assert tb["clock_label"] == "Day 1 06:06", tb
        fired = {b["id"]: b["status"] for b in tb["fired"]}
        assert fired.get("t-beat-1") == "FIRED", tb

        hits = [e for e in activity_repo.recent_events(50)
                if e.get("type") == "communication_lost"
                and e.get("run_id") == run_id]
        assert hits, "beat event missing run_id-stamped activity"

        t2 = client.post(f"/api/simulation/runs/{run_id}/tick", headers=h,
                         json={"minutes": 5})
        assert t2.status_code == 200, t2.text
        fired2 = {b["id"]: b["status"] for b in t2.json()["fired"]}
        # unknown burst id → honest ERROR (real bursts execute via the pack)
        assert fired2.get("t-burst-1") == "ERROR", t2.json()

        p = client.post(f"/api/simulation/runs/{run_id}/pause", headers=h)
        assert p.status_code == 200, p.text
        assert p.json()["status"] == "PAUSED"
        t3 = client.post(f"/api/simulation/runs/{run_id}/tick", headers=h,
                         json={"minutes": 5})
        assert t3.status_code == 409, t3.text

        s = client.post(f"/api/simulation/runs/{run_id}/speed", headers=h,
                        json={"speed": 6.0})
        assert s.status_code == 200 and s.json()["speed"] == 6.0, s.text
        rs = client.post(f"/api/simulation/runs/{run_id}/resume", headers=h)
        assert rs.json()["status"] == "RUNNING"

        st = client.post(f"/api/simulation/runs/{run_id}/stop", headers=h)
        assert st.json()["status"] == "STOPPED"
        t4 = client.post(f"/api/simulation/runs/{run_id}/tick", headers=h,
                         json={"minutes": 5})
        assert t4.status_code == 409, t4.text
    finally:
        wipe_run(run_id)


def test_get_run_and_clock_labels():
    h = ah()
    r = client.post("/api/simulation/runs", headers=h, json={
        "scenario_id": "flood-48h-01", "mode": "AUTONOMOUS_TEST", "seed": 1,
        "beats_override": []})
    assert r.status_code == 200, r.text
    run_id = r.json()["run_id"]
    try:
        g = client.get(f"/api/simulation/runs/{run_id}", headers=h)
        assert g.status_code == 200, g.text
        assert g.json()["clock_label"] == "Day 1 06:00"
        t = client.post(f"/api/simulation/runs/{run_id}/tick", headers=h,
                        json={"minutes": 1440})
        assert t.json()["clock_label"] == "Day 2 06:00", t.json()
    finally:
        wipe_run(run_id)


def test_ticker_advances_clock():
    import time as _time

    h = ah()
    r = client.post("/api/simulation/runs", headers=h, json={
        "scenario_id": "flood-48h-01", "mode": "HUMAN_GATED", "seed": 5,
        "beats_override": []}).json()
    run_id = r["run_id"]
    try:
        client.post(f"/api/simulation/runs/{run_id}/speed", headers=h,
                    json={"speed": 120})
        t = client.post(f"/api/simulation/runs/{run_id}/ticker", headers=h,
                        json={"on": True})
        assert t.json()["ticker_on"] is True
        deadline = _time.time() + 20
        clock = 0.0
        while _time.time() < deadline:
            _time.sleep(1)
            g = client.get(f"/api/simulation/runs/{run_id}", headers=h).json()
            clock = float(g.get("clock_min") or 0)
            if clock > 0:
                break
        assert clock > 0, "ticker did not advance the clock"
    finally:
        try:
            client.post(f"/api/simulation/runs/{run_id}/ticker", headers=h,
                        json={"on": False})
            client.post(f"/api/simulation/runs/{run_id}/stop", headers=h)
        except Exception:
            pass
        wipe_run(run_id)
