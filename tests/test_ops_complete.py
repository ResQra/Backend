import os
import sys

# Ensure backend directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient
import app.main as app_main

client = TestClient(app_main.app)

def run_ops_suite():
    def p(msg):
        print(msg, flush=True)

    p("--- 1. Admin Authentication ---")
    r_login = client.post("/api/auth/admin/login", json={"username": "resqra-admin", "password": "ResQra123"})
    assert r_login.status_code == 200, f"Login failed: {r_login.text}"
    tok = r_login.json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    p(f"  [PASS] Logged in as: {r_login.json().get('role')}")

    p("--- 2. Auth Identity ---")
    r_me = client.get("/api/auth/me", headers=h)
    assert r_me.status_code == 200, f"/auth/me failed: {r_me.text}"
    p(f"  [PASS] User name: {r_me.json().get('name')}")

    p("--- 3. Area Configuration ---")
    r_area = client.get("/api/area/config?area=rautahat")
    assert r_area.status_code == 200, f"Area config failed: {r_area.text}"
    p(f"  [PASS] Area loaded: {r_area.json().get('name')}")

    p("--- 4. Ops Operational Summary ---")
    r_sum = client.get("/api/ops/summary", headers=h)
    assert r_sum.status_code == 200, f"Summary failed: {r_sum.text}"
    sum_data = r_sum.json()
    p(f"  [PASS] Active incidents: {sum_data.get('active_incidents')}, Teams ready: {sum_data.get('teams_ready')}")

    p("--- 5. Action Board ---")
    r_board = client.get("/api/ops/action-board", headers=h)
    assert r_board.status_code == 200, f"Action board failed: {r_board.text}"
    incidents_list = r_board.json().get("incidents", [])
    pending_actions = r_board.json().get("pending_actions", [])
    p(f"  [PASS] Board incidents: {len(incidents_list)}, Pending actions: {len(pending_actions)}")
    assert len(incidents_list) > 0, "No incidents loaded on Action Board!"

    p("--- 6. Tactical Map Data ---")
    r_map = client.get("/api/ops/map-data", headers=h)
    assert r_map.status_code == 200, f"Map data failed: {r_map.text}"
    shelters = r_map.json().get("shelters", [])
    sensors = r_map.json().get("sensor_events", [])
    p(f"  [PASS] Shelters: {len(shelters)}, Sensors: {len(sensors)}")

    p("--- 7. Response Fleet ---")
    r_teams = client.get("/api/ops/teams", headers=h)
    assert r_teams.status_code == 200, f"Teams failed: {r_teams.text}"
    teams_list = r_teams.json().get("teams", [])
    p(f"  [PASS] Teams count: {len(teams_list)}")

    inc_id = incidents_list[0]["id"]

    p(f"--- 8. Route Preview for {inc_id} ---")
    r_rp = client.get(f"/api/agents/route-preview?incident_id={inc_id}", headers=h)
    assert r_rp.status_code == 200, f"Route preview failed: {r_rp.text}"
    rp_team = r_rp.json().get("team") or {}
    p(f"  [PASS] Route preview for {inc_id}: assigned team={rp_team.get('id')} ({rp_team.get('name')})")

    p("--- 9. Team Recommendation ---")
    r_rec = client.post(f"/api/ops/incidents/{inc_id}/recommend", headers=h)
    assert r_rec.status_code == 200, f"Recommend failed: {r_rec.text}"
    rec_obj = r_rec.json().get("recommendation") or {}
    p(f"  [PASS] Recommended team: {rec_obj.get('team_id')} ({rec_obj.get('team_name')})")

    p("--- 10. Pending Actions Decision Gate ---")
    if pending_actions:
        p_id = pending_actions[0]["id"]
        r_dec = client.post(f"/api/ops/pending-actions/{p_id}/decision", json={"decision": "APPROVED"}, headers=h)
        assert r_dec.status_code == 200, f"Decision failed: {r_dec.text}"
        p(f"  [PASS] Decision on {p_id}: {r_dec.json().get('status')}")

    p("--- 11. Ops AI Assistant Sessions & History ---")
    r_sess = client.post("/api/ops/assistant/sessions", json={"area": "rautahat", "title": "Command Log"}, headers=h)
    assert r_sess.status_code == 200, f"Create session failed: {r_sess.text}"
    sid = r_sess.json()["session"]["session_id"]
    r_hist = client.get(f"/api/ops/assistant/sessions/{sid}/history", headers=h)
    assert r_hist.status_code == 200, f"Session history failed: {r_hist.text}"
    p(f"  [PASS] Chat session {sid} created and history verified")

    print("\n=======================================================")
    print("ALL OPS COORDINATOR ENDPOINTS & WORKFLOWS VERIFIED 100%")
    print("=======================================================")

if __name__ == "__main__":
    run_ops_suite()
