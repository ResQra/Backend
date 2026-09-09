"""Phase D: burst inject + telemetry lifecycle + deterministic pack (TDD)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402

import app.main as app_main  # noqa: E402
from app.db.client import table  # noqa: E402
from app.db.repos import activity as activity_repo  # noqa: E402
from app.db.repos import incidents as incidents_repo  # noqa: E402
from app.db.repos import missions as missions_repo  # noqa: E402
from app.db.repos import pending_actions as pending_repo  # noqa: E402
from app.db.repos import teams as teams_repo  # noqa: E402
from tests.run_test_utils import wipe_run_everything  # noqa: E402

client = TestClient(app_main.app)

ITEMS = [
    {"raw_text": "Water rising near Gaur Ward 4, 2 people on roof",
     "people": 2, "vulnerabilities": [], "urgency": "LOW",
     "water_rising": True, "location_text": "Gaur Ward 4",
     "lat": 26.7660, "lng": 85.2770,
     "reporter_name": "Burst Tester", "reporter_phone": "+9779801000201"},
    {"raw_text": "बागमती पानी भरल, ३ आदमी फँसल",
     "people": 3, "vulnerabilities": ["children"], "urgency": "MEDIUM",
     "water_rising": True, "location_text": "Gaur Ward 3",
     "lat": 26.7640, "lng": 85.2780,
     "reporter_name": "Burst Tester 2", "reporter_phone": "+9779801000202"},
]


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


def cleanup(run_id, extra_teams=(), extra_users=()):
    # Hermetic wipe: every row carrying run_id, across all run tables.
    wipe_run_everything(run_id, extra_teams=list(extra_teams),
                        extra_phones=list(extra_users))


def new_run(h, beats=None):
    r = client.post("/api/simulation/runs", headers=h, json={
        "scenario_id": "flood-48h-01", "mode": "AUTONOMOUS_TEST", "seed": 9,
        "beats_override": beats if beats is not None else []}).json()
    return r["run_id"]


def test_inject_sos_items():
    h = ah()
    run_id = new_run(h)
    try:
        r = client.post(f"/api/simulation/runs/{run_id}/inject", headers=h,
                        json={"sos_items": ITEMS})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["incidents_created"] == 2, body
        for iid in body["incident_ids"]:
            inc = incidents_repo.get_incident(iid)
            assert inc and inc.get("run_id") == run_id
            assert inc.get("status") == "PRIORITIZED", inc.get("status")
        from app.db.repos import users as users_repo
        for phone in ("+9779801000201", "+9779801000202"):
            u = users_repo.find_by_phone(phone)
            assert u and (u.get("location") or {}).get("lat"), f"no beacon for {phone}"
        evs = [e for e in activity_repo.recent_events(60) if e.get("run_id") == run_id]
        assert any(e.get("type") == "sos_burst_injected" for e in evs)
    finally:
        cleanup(run_id, extra_users=("+9779801000201", "+9779801000202"))


def test_telemetry_lifecycle():
    h = ah()
    run_id = new_run(h)
    team_id = None
    try:
        t = client.post("/api/ops/teams", headers=h, json={
            "name": "Telem Boat", "capacity": 8, "status": "AVAILABLE",
            "location": {"lat": 26.7665, "lng": 85.2775, "label": "base"},
            "contact": "t", "specialization": "t", "notes": ""}).json()
        team_id = t["id"]
        rh = make_resident_simple()
        inc = client.post("/api/incidents", headers=rh, json={
            "raw_text": "Far rooftop near Tikuliya side road, 2 waiting",
            "people": 2, "urgency": "LOW",
            "location": {"lat": 26.7900, "lng": 85.3000, "label": "far point"},
            "run_id": run_id}).json()
        card = client.post(f"/api/ops/incidents/{inc['id']}/recommend",
                           headers=h).json()["pending_action"]
        client.post(f"/api/ops/pending-actions/{card['id']}/decision", headers=h,
                    json={"decision": "APPROVED", "note": "t"})

        before = teams_repo.get_team(team_id)["location"]
        r1 = client.post(f"/api/simulation/runs/{run_id}/inject", headers=h,
                         json={"telemetry_minutes": 5})
        assert r1.status_code == 200, r1.text
        assert r1.json()["teams_advanced"] == 1
        after = teams_repo.get_team(team_id)["location"]
        d0 = _dist(float(before["lat"]), float(before["lng"]), 26.79, 85.30)
        d1 = _dist(float(after["lat"]), float(after["lng"]), 26.79, 85.30)
        assert d1 < d0, f"team did not advance: {d0} -> {d1}"

        r2 = client.post(f"/api/simulation/runs/{run_id}/inject", headers=h,
                         json={"telemetry_minutes": 30})
        assert r2.status_code == 200, r2.text
        mission = [m for m in missions_repo.list_missions()
                   if m.get("run_id") == run_id][0]
        assert mission["status"] == "ON_SCENE", mission
        assert incidents_repo.get_incident(inc["id"])["status"] == "IN_PROGRESS"

        # +5 sim-min of work is not enough (needs 35) — no teleporting.
        r25 = client.post(f"/api/simulation/runs/{run_id}/inject", headers=h,
                          json={"telemetry_minutes": 5})
        assert r25.status_code == 200, r25.text
        mission = [m for m in missions_repo.list_missions()
                   if m.get("run_id") == run_id][0]
        assert mission["status"] == "ON_SCENE", mission

        # rescue work takes sim time: 2 people, cap-8 boat → 35 sim-min.
        # +40 crosses it; +5 more would not.
        r3 = client.post(f"/api/simulation/runs/{run_id}/inject", headers=h,
                         json={"telemetry_minutes": 40})
        assert r3.status_code == 200, r3.text
        mission = [m for m in missions_repo.list_missions()
                   if m.get("run_id") == run_id][0]
        assert mission["status"] == "COMPLETED", mission
        assert incidents_repo.get_incident(inc["id"])["status"] == "RESCUED"
        assert teams_repo.get_team(team_id)["status"] in ("RETURNING", "AVAILABLE")

        r4 = client.post(f"/api/simulation/runs/{run_id}/inject", headers=h,
                         json={"telemetry_minutes": 5})
        assert teams_repo.get_team(team_id)["status"] == "AVAILABLE"
        assert r4.status_code == 200
    finally:
        cleanup(run_id, extra_teams=(team_id,) if team_id else (),
                extra_users=("+9779801000203",))


def make_resident_simple():
    r = client.post("/api/auth/otp/request",
                    json={"phone": "+9779801000203", "name": "Telem Resident"})
    code = r.json()["dev_code"]
    r = client.post("/api/auth/otp/verify",
                    json={"phone": "+9779801000203", "code": code,
                          "name": "Telem Resident"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _dist(a, b, c, d):
    from app.utils.geo import haversine_km
    return haversine_km(a, b, c, d)


def test_pack_deterministic():
    import json
    import pathlib
    import sys
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "simulation" / "seed"))
    import build_sos_pack
    file_pack = json.loads(pathlib.Path(build_sos_pack.OUT).read_text(encoding="utf-8"))
    assert len(file_pack) == 100
    assert build_sos_pack.build_pack() == build_sos_pack.build_pack() == file_pack
    from collections import Counter
    assert Counter(i["burst"] for i in file_pack) == {"burst-1": 40, "burst-2": 30, "burst-3": 30}
