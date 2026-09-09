"""Phase E: run score + timeline + auto-verdicts (TDD — RED first).

Score is derived from the ledger, never hand-counted. Response times are
measured in SIM-minutes (wall clock is meaningless in a compressed run).
"""

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
from tests.run_test_utils import wipe_run_everything  # noqa: E402

client = TestClient(app_main.app)

ITEMS = [
    {"raw_text": "Roof rescue needed near Gaur Ward 4, 4 people",
     "people": 4, "vulnerabilities": [], "urgency": "LOW",
     "water_rising": True, "location_text": "Gaur Ward 4",
     "lat": 26.7660, "lng": 85.2770,
     "reporter_name": "Score T1", "reporter_phone": "+9779801000301"},
    {"raw_text": "2 people waiting at Juddha School gate",
     "people": 2, "vulnerabilities": [], "urgency": "LOW",
     "water_rising": False, "location_text": "Juddha School",
     "lat": 26.7590, "lng": 85.2720,
     "reporter_name": "Score T2", "reporter_phone": "+9779801000302"},
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


def test_score_timeline_verdicts():
    h = ah()
    run_id = client.post("/api/simulation/runs", headers=h, json={
        "scenario_id": "flood-48h-01", "mode": "AUTONOMOUS_TEST", "seed": 11,
        "beats_override": []}).json()["run_id"]
    team_ids = []
    try:
        for i, (lat, lng) in enumerate([(26.7665, 85.2775), (26.7595, 85.2725)]):
            t = client.post("/api/ops/teams", headers=h, json={
                "name": f"Score Boat {i}", "capacity": 8, "status": "AVAILABLE",
                "location": {"lat": lat, "lng": lng, "label": "base"},
                "contact": "t", "specialization": "t", "notes": ""}).json()
            team_ids.append(t["id"])

        inj = client.post(f"/api/simulation/runs/{run_id}/inject", headers=h,
                          json={"sos_items": ITEMS})
        assert inj.status_code == 200, inj.text

        # recommend + auto-approve both, rescue both
        for iid in inj.json()["incident_ids"]:
            client.post(f"/api/ops/incidents/{iid}/recommend", headers=h)
        client.post(f"/api/simulation/runs/{run_id}/autodecide", headers=h)

        client.post(f"/api/simulation/runs/{run_id}/inject", headers=h,
                    json={"telemetry_minutes": 30})
        client.post(f"/api/simulation/runs/{run_id}/inject", headers=h,
                    json={"telemetry_minutes": 60})

        s = client.get(f"/api/simulation/runs/{run_id}/score", headers=h)
        assert s.status_code == 200, s.text
        score = s.json()
        assert score["run_id"] == run_id
        assert score["lives_saved"] == 6, score
        assert score["lives_at_risk"] == 0, score
        assert score["dispatch_coverage"] == 1.0, score
        assert "response_p50_sim_min" in score and "response_p90_sim_min" in score
        assert isinstance(score["verdicts"], list) and score["verdicts"]
        assert all(set(v) >= {"criterion", "status", "detail"} for v in score["verdicts"])
        assert all(v["status"] in ("PASS", "PARTIAL", "FAIL") for v in score["verdicts"])

        tl = client.get(f"/api/simulation/runs/{run_id}/timeline", headers=h,
                        params={"limit": 200})
        assert tl.status_code == 200, tl.text
        types = [e["type"] for e in tl.json()["events"]]
        assert "sos_burst_injected" in types, types
        assert "rescue_completed" in types, types
        assert all(e.get("run_id") == run_id for e in tl.json()["events"])
    finally:
        cleanup(run_id, extra_teams=tuple(team_ids),
                extra_users=("+9779801000301", "+9779801000302"))
