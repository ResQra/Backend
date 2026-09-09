"""Phase 6 exit tests â€” no DB, no LLM keys, no network.

Supervisor plans read-only tools, executes against stubbed ops_tools,
and composes grounded replies citing real IDs.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _stub_tools(monkey=None):
    from app.services import ops_tools

    ops_tools.get_active_incidents = lambda bbox=None, **k: [
        {"id": "INC-1", "status": "PRIORITIZED",
         "priority": {"score": 9}, "people": 6, "assigned_team": None}]
    ops_tools.get_teams = lambda bbox=None, **k: [
        {"id": "T-A", "name": "Team Alpha", "status": "AVAILABLE", "capacity": 16}]
    ops_tools.get_available_shelter_capacity = lambda bbox=None, **k: [
        {"id": "S-1", "name": "Shelter One", "free": 42, "status": "OPEN"}]
    ops_tools.get_blocked_roads = lambda bbox=None, **k: []
    ops_tools.get_hazard_zones = lambda bbox=None, **k: [
        {"geohash": "abc", "level": "RISING"}]
    ops_tools.get_active_missions = lambda **k: []
    ops_tools.get_pending_approvals = lambda: [
        {"id": "PA-1", "incident_id": "INC-1", "proposed_team_id": "T-A"}]
    ops_tools.get_current_operational_picture = lambda bbox=None: {
        "active_incidents": 1, "critical": 1, "teams_available": 1,
        "teams_total": 1, "pending_approvals": 1,
        "top_ids": {"incidents": ["INC-1"], "critical": ["INC-1"]}}


def test_plan_keywords():
    from app.agents_gateway import supervisor

    assert "shelters" in supervisor.plan("Which shelters have capacity?")
    assert "capacity" in supervisor.plan("Which shelters have capacity?")
    assert "teams" in supervisor.plan("Which boats are available now?")
    assert "blocked" in supervisor.plan("Which roads are blocked?")
    assert "picture" in supervisor.plan("hello")


def test_execute_grounded_ids():
    _stub_tools()
    from app.agents_gateway import supervisor

    ev = supervisor.execute(["incidents", "teams", "shelters", "approvals", "picture"],
                            {"area": "rautahat"})
    assert ev["incidents"][0]["id"] == "INC-1"
    assert ev["teams"][0]["id"] == "T-A"
    assert ev["shelters"][0]["id"] == "S-1"
    assert ev["pending_approvals"][0]["id"] == "PA-1"


def test_compose_cites_ids():
    _stub_tools()
    from app.agents_gateway import supervisor

    ev = supervisor.execute(["incidents", "teams", "shelters", "approvals", "picture"],
                            {"area": "rautahat"})
    reply = supervisor.compose_template("What is happening?", ev)
    for token in ("INC-1", "Team Alpha", "Shelter One", "PA-1"):
        assert token in reply


def test_supervise_without_keys_returns_evidence():
    _stub_tools()
    from app import config
    from app.agents_gateway import supervisor

    config.settings.groq_api_key = ""
    out = asyncio.run(supervisor.supervise("What is happening in rautahat?",
                                           {"area": "rautahat"}))
    assert out["evidence"]["picture"]["active_incidents"] == 1
    assert "INC-1" in out["reply"]
    assert "picture" in out["tools_called"]
    assert out["evidence"]["incidents"][0]["id"] == "INC-1"


def test_strands_supervisor_importable():
    from resqra_agents.agents.supervisor_strands import build_supervisor_agent
    from resqra_agents.tools.supervisor_tools import (
        find_available_teams_tool,
        get_operational_picture_tool,
        shelter_space_tool,
    )

    assert callable(build_supervisor_agent)
    assert find_available_teams_tool is not None
    assert get_operational_picture_tool is not None
    assert shelter_space_tool is not None
