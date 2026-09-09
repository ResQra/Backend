"""Phase A: run_id provenance stamping (TDD — RED first).

Every record produced during a simulation run must carry its run_id as a
top-level field so timeline/score/replay can filter by run:
activity events, incidents, pending actions, missions.

HTTP-supplied run tags validate: only live runs are honored.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db.client import table  # noqa: E402
from app.db.repos import activity as activity_repo  # noqa: E402
from tests.run_test_utils import (  # noqa: E402
    ah as login_admin,
    client,
    make_resident,
    wipe_run_everything,
)


def new_run(h, seed=101):
    return client.post("/api/simulation/runs", headers=h, json={
        "scenario_id": "flood-48h-01", "mode": "AUTONOMOUS_TEST", "seed": seed,
        "beats_override": []}).json()["run_id"]


def test_activity_log_stamps_run_id():
    ev = activity_repo.log_event(actor="system", type_="prov_ping",
                                 summary="prov", payload={}, run_id="run_x")
    try:
        got = table("ActivityEvent").get_item(Key={"id": ev["id"]}).get("Item")
        assert got.get("run_id") == "run_x"

        plain = activity_repo.log_event(actor="system", type_="prov_ping",
                                        summary="prov", payload={})
        try:
            got2 = table("ActivityEvent").get_item(Key={"id": plain["id"]}).get("Item")
            assert "run_id" not in got2
        finally:
            try:
                table("ActivityEvent").delete_item(Key={"id": plain["id"]})
            except Exception:
                pass
    finally:
        try:
            table("ActivityEvent").delete_item(Key={"id": ev["id"]})
        except Exception:
            pass


def test_incident_create_stamps_run_id():
    ah = login_admin()
    run_id = new_run(ah)
    try:
        rh = make_resident("+9779801000091")
        r = client.post("/api/incidents", headers=rh, json={
            "raw_text": "Water rising near Gaur Ward 4, 2 people on roof",
            "people": 2, "urgency": "LOW",
            "location": {"lat": 26.7660, "lng": 85.2770, "label": "Gaur Ward 4"},
            "run_id": run_id,
        })
        assert r.status_code == 200, r.text
        inc = r.json()
        assert inc.get("run_id") == run_id
        evs = [e for e in activity_repo.recent_events(30)
               if (e.get("payload") or {}).get("incident_id") == inc["id"]]
        assert evs, "expected activity for the incident"
        assert all(e.get("run_id") == run_id for e in evs), \
            f"missing run_id on {[e.get('type') for e in evs]}"
        assert len(ah) == 1  # silence linters about unused login
    finally:
        wipe_run_everything(run_id, extra_phones=["+9779801000091"])


def test_incident_create_rejects_dead_run_id():
    """Forged/finished run tags are dropped, never ledgered."""
    ah = login_admin()
    rh = make_resident("+9779801000093")
    iid = None
    try:
        r = client.post("/api/incidents", headers=rh, json={
            "raw_text": "Water near Gaur, 1 person waiting",
            "people": 1, "urgency": "LOW",
            "location": {"lat": 26.7660, "lng": 85.2770, "label": "Gaur Ward 4"},
            "run_id": "run_does_not_exist_zzz",
        })
        assert r.status_code == 200, r.text
        inc = r.json()
        iid = inc["id"]
        assert inc.get("run_id", "") == "", inc.get("run_id")
    finally:
        if iid:
            try:
                table("Incidents").delete_item(Key={"id": iid})
            except Exception:
                pass
            for e in activity_repo.recent_events(30):
                if (e.get("payload") or {}).get("incident_id") == iid:
                    try:
                        table("ActivityEvent").delete_item(Key={"id": e["id"]})
                    except Exception:
                        pass
        try:
            from app.db.repos import users as users_repo
            u = users_repo.find_by_phone("+9779801000093")
            if u:
                table("Users").delete_item(Key={"id": u["id"]})
        except Exception:
            pass


def test_recommend_approve_threads_run_id():
    ah = login_admin()
    run_id = new_run(ah, seed=102)
    team_id = None
    try:
        rh = make_resident("+9779801000092")
        t = client.post("/api/ops/teams", headers=ah, json={
            "name": "Prov Boat", "capacity": 8, "status": "AVAILABLE",
            "location": {"lat": 26.7665, "lng": 85.2775, "label": "nearby"},
            "contact": "test", "specialization": "test", "notes": "",
        })
        assert t.status_code == 200, t.text
        team_id = t.json()["id"]

        r = client.post("/api/incidents", headers=rh, json={
            "raw_text": "Need boat near Gaur Ward 4, 2 people waiting",
            "people": 2, "urgency": "LOW",
            "location": {"lat": 26.7660, "lng": 85.2770, "label": "Gaur Ward 4"},
            "run_id": run_id,
        })
        assert r.status_code == 200, r.text
        inc = r.json()

        rec = client.post(f"/api/ops/incidents/{inc['id']}/recommend", headers=ah)
        assert rec.status_code == 200, rec.text
        body = rec.json()
        card = body.get("pending_action")
        assert card, f"expected a pending card, got stability={body.get('stability')}"
        assert card.get("run_id") == run_id, f"card missing run_id: {card.get('id')}"

        d = client.post(f"/api/ops/pending-actions/{card['id']}/decision",
                        headers=ah, json={"decision": "APPROVED", "note": "prov"})
        assert d.status_code == 200, d.text
        mission = (d.json() or {}).get("mission") or {}
        assert mission.get("id"), "expected mission on approve"
        got_m = table("Missions").get_item(Key={"id": mission["id"]}).get("Item")
        assert got_m.get("run_id") == run_id, "mission missing run_id"
    finally:
        wipe_run_everything(run_id, extra_teams=[team_id] if team_id else [],
                            extra_phones=["+9779801000092"])
