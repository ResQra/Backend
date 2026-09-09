"""Phase F: async debate pool + budget guard (TDD — RED first).

Runs submit chambers to a bounded worker pool instead of blocking the
recommend path; the deterministic card persists immediately and the
verdict attaches when the chamber lands. Budget exhaustion degrades to
an explicit DETERMINISTIC_FALLBACK — never silent, never blocking.
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402

import app.main as app_main  # noqa: E402
from app.agents_gateway import gateway  # noqa: E402
from app.db.repos import pending_actions as pending_repo  # noqa: E402
from app.services import debate_pool  # noqa: E402
from tests.run_test_utils import ah, make_resident, wipe_run_everything  # noqa: E402

client = TestClient(app_main.app)


def seed_team(h, name="Pool Boat"):
    t = client.post("/api/ops/teams", headers=h, json={
        "name": name, "capacity": 8, "status": "AVAILABLE",
        "location": {"lat": 26.7665, "lng": 85.2775, "label": "base"},
        "contact": "t", "specialization": "t", "notes": ""}).json()
    return t["id"]


def seed_incident(rh, run_id, urgency="LOW"):
    return client.post("/api/incidents", headers=rh, json={
        "raw_text": "Pool test SOS near Gaur Ward 4, 2 people waiting",
        "people": 2, "urgency": urgency,
        "location": {"lat": 26.7660, "lng": 85.2770, "label": "Gaur Ward 4"},
        "run_id": run_id}).json()


def test_deferred_chamber_attaches_verdict():
    h = ah()
    rh = make_resident("+9779801000401")
    run_id = client.post("/api/simulation/runs", headers=h, json={
        "scenario_id": "flood-48h-01", "mode": "AUTONOMOUS_TEST", "seed": 21,
        "beats_override": []}).json()["run_id"]
    team_id = None
    try:
        team_id = seed_team(h)
        inc = seed_incident(rh, run_id)
        out = gateway.recommend_for_incident(inc["id"], force_debate=True,
                                             defer_debate=True)
        card = out.get("pending_action")
        assert card, out.get("stability")
        assert (out.get("debate") or {}).get("deferred") is True, out.get("debate")

        drained = debate_pool.collect_for_run(run_id, wait_s=140)
        assert drained["collected"] >= 1, drained
        verdict = drained["verdicts"][0]
        assert verdict.get("incident_id") == inc["id"]
        # live Groq → real winner; rate-limited/down → honest fallback.
        # Either way a verdict must exist and attach.
        assert verdict.get("winner") in (
            "DISPATCH", "WAIT", "RECRUIT", "DETERMINISTIC_FALLBACK"), verdict

        stored = pending_repo.get_action(card["id"])
        assert (stored.get("payload") or {}).get("debate", {}).get("winner") \
            == verdict.get("winner"), stored.get("payload")
    finally:
        wipe_run_everything(run_id, extra_teams=[team_id] if team_id else [],
                            extra_phones=["+9779801000401"])


def test_budget_exhaustion_falls_back_explicitly():
    h = ah()
    rh = make_resident("+9779801000402")
    run_id = client.post("/api/simulation/runs", headers=h, json={
        "scenario_id": "flood-48h-01", "mode": "AUTONOMOUS_TEST", "seed": 22,
        "beats_override": []}).json()["run_id"]
    team_id = None
    try:
        from app.db.repos import simulation_runs
        simulation_runs.update_run(run_id, max_debates=0)
        team_id = seed_team(h, name="Pool Boat 2")
        inc = seed_incident(rh, run_id)
        out = gateway.recommend_for_incident(inc["id"], force_debate=True,
                                             defer_debate=True)
        debate = out.get("debate") or {}
        assert debate.get("fallback") is True, debate
        assert debate.get("winner") == "DETERMINISTIC_FALLBACK", debate
        assert debate_pool.pending_count(run_id) == 0
    finally:
        wipe_run_everything(run_id, extra_teams=[team_id] if team_id else [],
                            extra_phones=["+9779801000402"])


def test_tick_collects_completed_debates():
    h = ah()
    rh = make_resident("+9779801000403")
    run_id = client.post("/api/simulation/runs", headers=h, json={
        "scenario_id": "flood-48h-01", "mode": "HUMAN_GATED", "seed": 23,
        "beats_override": []}).json()["run_id"]
    team_id = None
    try:
        team_id = seed_team(h, name="Pool Boat 3")
        inc = seed_incident(rh, run_id)
        gateway.recommend_for_incident(inc["id"], force_debate=True,
                                       defer_debate=True)
        assert debate_pool.pending_count(run_id) >= 1
        t = client.post(f"/api/simulation/runs/{run_id}/tick", headers=h,
                        json={"minutes": 5})
        assert t.status_code == 200, t.text
        assert "debates_pending" in t.json(), t.json()
        deadline = time.time() + 140
        while debate_pool.pending_count(run_id) and time.time() < deadline:
            client.post(f"/api/simulation/runs/{run_id}/tick", headers=h,
                        json={"minutes": 1})
            time.sleep(1)
        assert debate_pool.pending_count(run_id) == 0
    finally:
        wipe_run_everything(run_id, extra_teams=[team_id] if team_id else [],
                            extra_phones=["+9779801000403"])


def test_resubmit_reuses_tracked_chamber():
    """Per-tick re-evaluations must not burn budget or spawn duplicate
    chambers for the same incident."""
    from app.db.repos import simulation_runs

    h = ah()
    run_id = client.post("/api/simulation/runs", headers=h, json={
        "scenario_id": "flood-48h-01", "mode": "HUMAN_GATED", "seed": 24,
        "beats_override": []}).json()["run_id"]
    try:
        snap = {"incident": {"id": "inc_probe"}, "teams": [], "shelters": []}
        first = debate_pool.submit_for_run(run_id, "inc_probe", snap)
        second = debate_pool.submit_for_run(run_id, "inc_probe", snap)
        assert first.get("deferred") is True and second.get("deferred") is True
        assert debate_pool.pending_count(run_id) == 1
        run = simulation_runs.get_run(run_id)
        assert int(run.get("debates_used") or 0) == 1, run
        out = debate_pool.collect_for_run(run_id, wait_s=120)
        assert out["collected"] >= 1, out
    finally:
        wipe_run_everything(run_id)
