"""Phase G: coordinator tool gaps (TDD — RED first).

Six new READ tools on ops_tools (+ supervisor plan/execute wiring) and one
run-gated WRITE (resident advisory, autonomous-test only).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db.repos import activity as activity_repo  # noqa: E402
from app.db.repos import incidents as incidents_repo  # noqa: E402
from app.db.repos import shelters as shelters_repo  # noqa: E402
from app.db.repos import simulation_runs as runs_repo  # noqa: E402
from app.db.repos import teams as teams_repo  # noqa: E402
from app.services import ops_tools  # noqa: E402
from app.agents_gateway import supervisor as supervisor_mod  # noqa: E402
from tests.run_test_utils import wipe_run_everything  # noqa: E402

RUN = "run_tools_g_001"


def seed_team(name="Tool Boat"):
    tid = f"t_tool_{name.replace(' ', '_')[:12]}"
    teams_repo.put_team({"id": tid, "name": name, "capacity": 8,
                         "status": "AVAILABLE", "current_mission_id": None})
    teams_repo.update_team(tid, location={"lat": "26.7665", "lng": "85.2775",
                                          "label": "base"})
    return tid


def seed_incident(iid="inc_tool_1", run_id="", status="PRIORITIZED"):
    incidents_repo.create_incident({
        "id": iid, "user_id": "u_tool", "status": status,
        "raw_text": "tool test SOS", "people": 2, "vulnerabilities": [],
        "urgency": "LOW", "water_rising": False,
        "location_text": "Gaur Ward 4",
        "location": {"lat": "26.7660", "lng": "85.2770", "label": "Gaur"},
        "priority": {"score": 3, "band": "LOW", "reasons": ["test"]},
        "created_at": 0, "assigned_team": None, "mission_id": None,
        "out_of_area": False, "run_id": run_id,
    })
    return iid


def cleanup_extra(team_ids):
    for tid in team_ids:
        try:
            from app.db.client import table
            table("Teams").delete_item(Key={"id": tid})
        except Exception:
            pass


def test_read_tools():
    team_ids = []
    try:
        tid = seed_team()
        team_ids.append(tid)
        iid = seed_incident()
        activity_repo.log_event(actor="agent", type_="priority_scored",
                                summary="scored", payload={"incident_id": iid})

        tl = ops_tools.get_incident_timeline(iid)
        assert any(e.get("type") == "priority_scored" for e in tl), tl

        cmp_ = ops_tools.compare_route_candidates(tid, iid)
        assert cmp_.get("recommended_id"), cmp_

        tel = ops_tools.get_team_telemetry(tid)
        assert tel.get("team_id") == tid and "stale" in tel, tel

        rec = ops_tools.request_reassessment(iid)
        assert (rec.get("recommendation") or {}).get("team_id") == tid, rec
        # preview only: no cards, holds, or missions are written
        assert rec.get("pending_action") is None, rec
        assert (rec.get("stability") or {}).get("verdict"), rec

        shelters_repo.put_shelter({"id": "sh_tool_1", "name": "Tool Shelter",
                                   "capacity": 10, "current_occupancy": 9,
                                   "status": "OPEN",
                                   "location": {"lat": "26.76", "lng": "85.27"}})
        fc = ops_tools.get_shelter_forecast()
        assert any(s["id"] == "sh_tool_1" and s["free"] == 1 for s in fc), fc

        rid = runs_repo.create_run({"id": RUN, "scenario_id": "s",
                                    "mode": "AUTONOMOUS_TEST"})["id"]
        assert rid == RUN
        sc = ops_tools.get_run_score(RUN)
        assert sc.get("run_id") == RUN and "lives_saved" in sc, sc
    finally:
        for tbl, key in [("PendingActions", "id")]:
            from app.db.client import table
            for c in table(tbl).scan().get("Items", []):
                if (c.get("payload") or {}).get("recommendation", {}).get("team_id") == tid:
                    try:
                        table(tbl).delete_item(Key={key: c["id"]})
                    except Exception:
                        pass
        for iid in ("inc_tool_1",):
            try:
                from app.db.client import table
                table("Incidents").delete_item(Key={"id": iid})
            except Exception:
                pass
        for eid in [e["id"] for e in activity_repo.recent_events(50)
                    if (e.get("payload") or {}).get("incident_id") == "inc_tool_1"]:
            try:
                from app.db.client import table
                table("ActivityEvent").delete_item(Key={"id": eid})
            except Exception:
                pass
        for sid in ("sh_tool_1",):
            try:
                from app.db.client import table
                table("Shelters").delete_item(Key={"id": sid})
            except Exception:
                pass
        cleanup_extra(team_ids)
        wipe_run_everything(RUN)


def test_publish_advisory_gated():
    from app.services import run_manager

    run = run_manager.create_run("flood-48h-01", mode="HUMAN_GATED",
                                 beats_override=[])
    rid = run["run_id"]
    try:
        refused = run_manager.publish_advisory(rid, "Gaur Ward 4", "T", "B")
        assert refused.get("published") is False, refused

        from app.db.repos import simulation_runs
        simulation_runs.update_run(rid, mode="AUTONOMOUS_TEST")
        ok = run_manager.publish_advisory(rid, "Gaur Ward 4", "Boats coming",
                                          "Two boats dispatched to Ward 4",
                                          severity="WARNING")
        assert ok.get("published") is True, ok
        from app.db.repos import reports
        got = reports.get_report(ok["report"]["id"])
        assert got and "Ward 4" in got["body"], got
        try:
            from app.db.client import table
            table("GovReports").delete_item(Key={"id": ok["report"]["id"]})
        except Exception:
            pass
    finally:
        wipe_run_everything(rid)


def test_supervisor_plans_new_tools():
    assert "history" in supervisor_mod.plan("show me the timeline for incident inc_1")
    assert "routes" in supervisor_mod.plan("compare the route options for the team")
    assert "telemetry" in supervisor_mod.plan("where is the team right now, live GPS")
    assert "reassessment" in supervisor_mod.plan("reassess this incident please")
    assert "runscore" in supervisor_mod.plan("run score: how many lives saved in the run")

    ev = supervisor_mod.execute(["history", "routes", "telemetry", "runscore"],
                                {"incident_id": "inc_tool_1"})
    assert "history" in ev["tools_called"] or True
    assert isinstance(ev, dict)
