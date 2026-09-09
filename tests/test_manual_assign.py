"""Manual-assign invariants: dispatchable-only, real mission rows."""

from app.db.repos import incidents as incidents_repo  # noqa: E402
from app.db.repos import missions as missions_repo  # noqa: E402
from app.db.repos import teams as teams_repo  # noqa: E402
from tests.run_test_utils import ah, client, make_resident, wipe_run_everything  # noqa: E402


def _team(h, name, status="AVAILABLE"):
    t = client.post("/api/ops/teams", headers=h, json={
        "name": name, "capacity": 8, "status": status,
        "location": {"lat": 26.7665, "lng": 85.2775, "label": "base"},
        "contact": "t", "specialization": "t", "notes": ""}).json()
    return t["id"]


def _incident(rh):
    return client.post("/api/incidents", headers=rh, json={
        "raw_text": "Manual assign test SOS, 2 waiting",
        "people": 2, "urgency": "LOW",
        "location": {"lat": 26.7660, "lng": 85.2770, "label": "Gaur Ward 4"},
    }).json()["id"]


def test_manual_assign_rejects_busy_team():
    from app.db.client import table

    h = ah()
    rh = make_resident("+9779801000501")
    team_id = _team(h, "Busy Boat")
    try:
        teams_repo.update_team(team_id, status="ON_MISSION")
        iid = _incident(rh)
        try:
            r = client.post(f"/api/ops/incidents/{iid}/assign", headers=h,
                            json={"team_id": team_id})
            assert r.status_code == 409, r.text
        finally:
            try:
                table("Incidents").delete_item(Key={"id": iid})
            except Exception:
                pass
    finally:
        try:
            table("Teams").delete_item(Key={"id": team_id})
        except Exception:
            pass
        try:
            from app.db.repos import users as users_repo
            u = users_repo.find_by_phone("+9779801000501")
            if u:
                table("Users").delete_item(Key={"id": u["id"]})
        except Exception:
            pass


def test_manual_assign_mints_mission():
    h = ah()
    rh = make_resident("+9779801000502")
    team_id = None
    iid = None
    try:
        team_id = _team(h, "Free Boat")
        iid = _incident(rh)
        r = client.post(f"/api/ops/incidents/{iid}/assign", headers=h,
                        json={"team_id": team_id})
        assert r.status_code == 200, r.text
        inc = incidents_repo.get_incident(iid)
        assert (inc.get("mission_id") or "").startswith("mis_"), inc
        mission = missions_repo.get_mission(inc["mission_id"])
        assert mission and mission["team_id"] == team_id, mission
        assert teams_repo.get_team(team_id)["current_mission_id"] == mission["id"]
    finally:
        if iid:
            from app.db.client import table
            for m in missions_repo.list_missions():
                if m.get("incident_id") == iid:
                    try:
                        table("Missions").delete_item(Key={"id": m["id"]})
                    except Exception:
                        pass
            try:
                table("Incidents").delete_item(Key={"id": iid})
            except Exception:
                pass
        if team_id:
            try:
                from app.db.client import table
                table("Teams").delete_item(Key={"id": team_id})
            except Exception:
                pass
        try:
            from app.db.repos import users as users_repo
            from app.db.client import table
            u = users_repo.find_by_phone("+9779801000502")
            if u:
                table("Users").delete_item(Key={"id": u["id"]})
        except Exception:
            pass
