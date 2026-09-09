"""Phase C: autonomous approval gate — test runs only (TDD — RED first).

AUTONOMOUS_TEST runs may auto-approve their own pending cards as
actor "coordinator-agent" (via="autonomous_test"). Anything else —
no run_id, HUMAN_GATED, normal console path — is untouched.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402

import app.main as app_main  # noqa: E402
from app.db.client import table  # noqa: E402
from app.db.repos import activity as activity_repo  # noqa: E402
from app.db.repos import pending_actions as pending_repo  # noqa: E402
from tests.run_test_utils import wipe_run_everything  # noqa: E402

client = TestClient(app_main.app)
RUN_SEED = 0


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


def make_resident(phone):
    r = client.post("/api/auth/otp/request", json={"phone": phone, "name": "Auto Resident"})
    assert r.status_code == 200, r.text
    code = r.json()["dev_code"]
    r = client.post("/api/auth/otp/verify",
                    json={"phone": phone, "code": code, "name": "Auto Resident"})
    assert r.status_code == 200, r.text
    return ({"Authorization": f"Bearer {r.json()['token']}"}, phone)


def cleanup(ids, phones, run_id=""):
    # Hermetic wipe: every row carrying run_id, across all run tables.
    wipe_run_everything(run_id, extra_teams=ids.get("Teams", []),
                        extra_phones=phones)


def seed_card(h, rh, run_id):
    t = client.post("/api/ops/teams", headers=h, json={
        "name": "Auto Boat", "capacity": 8, "status": "AVAILABLE",
        "location": {"lat": 26.7665, "lng": 85.2775, "label": "nearby"},
        "contact": "t", "specialization": "t", "notes": ""})
    assert t.status_code == 200, t.text
    inc = client.post("/api/incidents", headers=rh, json={
        "raw_text": "Need boat near Gaur Ward 4, 2 people waiting",
        "people": 2, "urgency": "LOW",
        "location": {"lat": 26.7660, "lng": 85.2770, "label": "Gaur Ward 4"},
        "run_id": run_id}).json()
    rec = client.post(f"/api/ops/incidents/{inc['id']}/recommend", headers=h)
    assert rec.status_code == 200, rec.text
    card = rec.json().get("pending_action")
    assert card, rec.json().get("stability")
    return t.json()["id"], inc["id"], card["id"]


def collect_run_events(run_id):
    return [e for e in activity_repo.recent_events(100)
            if e.get("run_id") == run_id]


def test_autonomous_run_autodecides():
    h = ah()
    rh, phone = make_resident("+9779801000101")
    ids = {"Teams": [], "Incidents": [], "PendingActions": [], "Missions": [], "ActivityEvent": []}
    try:
        run = client.post("/api/simulation/runs", headers=h, json={
            "scenario_id": "flood-48h-01", "mode": "AUTONOMOUS_TEST", "seed": 3,
            "beats_override": []}).json()
        run_id = run["run_id"]
        try:
            tid, iid, cid = seed_card(h, rh, run_id)
            ids["Teams"].append(tid)
            ids["Incidents"].append(iid)
            ids["PendingActions"].append(cid)

            d = client.post(f"/api/simulation/runs/{run_id}/autodecide", headers=h)
            assert d.status_code == 200, d.text
            body = d.json()
            assert body["decided"] == [cid], body
            assert body["skipped"] == []

            card = pending_repo.get_action(cid)
            assert card["state"] == "APPROVED"
            assert card["decided_by"] == "coordinator-agent"
            assert card.get("run_id") == run_id
            for m in table("Missions").scan().get("Items", []):
                if m.get("pending_action_id") == cid:
                    ids["Missions"].append(m["id"])
                    assert m.get("run_id") == run_id
            for e in collect_run_events(run_id):
                ids["ActivityEvent"].append(e["id"])
        finally:
            try:
                table("SimulationRuns").delete_item(Key={"id": run_id})
            except Exception:
                pass
    finally:
        cleanup(ids, [phone], locals().get("run_id", ""))


def test_human_gated_run_refuses_autodecide():
    h = ah()
    rh, phone = make_resident("+9779801000102")
    ids = {"Teams": [], "Incidents": [], "PendingActions": [], "Missions": [], "ActivityEvent": []}
    try:
        run = client.post("/api/simulation/runs", headers=h, json={
            "scenario_id": "flood-48h-01", "mode": "HUMAN_GATED", "seed": 3,
            "beats_override": []}).json()
        run_id = run["run_id"]
        try:
            tid, iid, cid = seed_card(h, rh, run_id)
            ids["Teams"].append(tid)
            ids["Incidents"].append(iid)
            ids["PendingActions"].append(cid)

            d = client.post(f"/api/simulation/runs/{run_id}/autodecide", headers=h)
            assert d.status_code == 200, d.text
            assert d.json()["decided"] == []
            assert pending_repo.get_action(cid)["state"] == "PENDING"

            # normal human path still works on the same card
            ok = client.post(f"/api/ops/pending-actions/{cid}/decision", headers=h,
                             json={"decision": "APPROVED", "note": "human"})
            assert ok.status_code == 200, ok.text
            for m in table("Missions").scan().get("Items", []):
                if m.get("pending_action_id") == cid:
                    ids["Missions"].append(m["id"])
            for e in collect_run_events(run_id):
                ids["ActivityEvent"].append(e["id"])
        finally:
            try:
                table("SimulationRuns").delete_item(Key={"id": run_id})
            except Exception:
                pass
    finally:
        cleanup(ids, [phone], locals().get("run_id", ""))


def test_fresh_cards_wait_out_deliberation():
    """Debate costs sim time: a card born at clock T is not approvable
    until T + DEBATE_DELAY_MIN, so triage order matters under load."""
    h = ah()
    run = client.post("/api/simulation/runs", headers=h, json={
        "scenario_id": "flood-48h-01", "mode": "AUTONOMOUS_TEST", "seed": 31,
        "beats_override": []}).json()
    run_id = run["run_id"]
    team_id = None
    try:
        t = client.post("/api/ops/teams", headers=h, json={
            "name": "Deliberation Boat", "capacity": 8, "status": "AVAILABLE",
            "location": {"lat": 26.7665, "lng": 85.2775, "label": "base"},
            "contact": "t", "specialization": "t", "notes": ""}).json()
        team_id = t["id"]
        inj = client.post(f"/api/simulation/runs/{run_id}/inject", headers=h,
                          json={"sos_items": [{
                              "raw_text": "Deliberation test SOS, 2 waiting",
                              "people": 2, "vulnerabilities": [], "urgency": "LOW",
                              "water_rising": False, "location_text": "Gaur Ward 4",
                              "lat": 26.7660, "lng": 85.2770,
                              "reporter_name": "Delib", "reporter_phone": "+9779801000103"}]})
        assert inj.status_code == 200, inj.text

        tick = client.post(f"/api/simulation/runs/{run_id}/tick", headers=h,
                           json={"minutes": 10})
        assert tick.status_code == 200, tick.text
        assert tick.json()["recommended"], tick.json()
        assert tick.json()["autodecided"] == [], tick.json()

        # clock is now 10; +30 crosses the 30-min deliberation line.
        tick2 = client.post(f"/api/simulation/runs/{run_id}/tick", headers=h,
                            json={"minutes": 30})
        assert tick2.status_code == 200, tick2.text
        assert len(tick2.json()["autodecided"]) == 1, tick2.json()
    finally:
        cleanup({}, ["+9779801000103"], run_id)
        if team_id:
            try:
                table("Teams").delete_item(Key={"id": team_id})
            except Exception:
                pass
        try:
            table("SimulationRuns").delete_item(Key={"id": run_id})
        except Exception:
            pass
