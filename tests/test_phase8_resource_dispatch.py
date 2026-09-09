"""Phase 8 exit tests â€” no DB, no keys, no network.

Resource selection + comms + approval safety (Â§16, Â§50, Â§52).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agents"))


def _teams():
    base = {"status": "AVAILABLE", "location": {"lat": 26.76, "lng": 85.27}}
    return [
        {**base, "id": "T-MED", "name": "Red Cross Medical Unit", "capacity": 12,
         "specialization": "medical triage boat"},
        {**base, "id": "T-GEN", "name": "General Rescue Boat", "capacity": 12,
         "specialization": "boat patrol"},
    ]


def test_medical_capability_preferred():
    from resqra_agents.tools.allocation_engine import recommend_team

    incident = {"id": "INC-1", "people": 4, "vulnerabilities": ["pregnant"],
                "location": {"lat": 26.76, "lng": 85.27}}
    rec = recommend_team(incident, _teams())
    assert rec["team_id"] == "T-MED"
    assert any("medical" in r.lower() for r in rec["reasons"])


def test_route_gate_excludes_team():
    from resqra_agents.tools.allocation_engine import recommend_team

    incident = {"id": "INC-1", "people": 2,
                "location": {"lat": 26.76, "lng": 85.27}}
    teams = [{**_teams()[1], "id": "T-ONLY"}]
    rec = recommend_team(incident, teams,
                         route_check=lambda team, inc: (False, "bridge damaged"))
    assert rec["team_id"] is None
    assert "bridge damaged" in " ".join(rec["reasons"])


def test_offline_team_excluded_and_comms_timeout():
    from resqra_agents.tools.allocation_engine import recommend_team

    from app.services import comms as comms_service

    offline = {**_teams()[1], "id": "T-OFF",
               "last_problem": {"severity": "OFFLINE", "message": "radio dead"}}
    incident = {"id": "INC-1", "people": 2,
                "location": {"lat": 26.76, "lng": 85.27}}
    rec = recommend_team(incident, [offline])
    assert rec["team_id"] is None
    assert "OFFLINE" in " ".join(rec["reasons"])

    contact = comms_service.contact_team(offline, "Report status")
    assert contact["timeout"] is True and contact["delivered"] is False

    ok = comms_service.contact_team(_teams()[0], "Dispatched")
    assert ok["delivered"] is True


def test_reason_codes_and_approval_flag():
    from app.agents_gateway import gateway

    rec = gateway._with_codes_and_route(
        {"id": "INC-1", "vulnerabilities": ["pregnant"]},
        {"team_id": "T-MED", "team_name": "Red Cross Medical Unit",
         "reasons": ["medical capability match", "capacity ok"]})
    assert rec["requires_human_approval"] is True
    for code in ("sufficient_capacity", "available", "closer_than_alternatives",
                 "medical_match"):
        assert code in rec["reason_codes"]


def test_costumes_removed_engines_remain():
    """Priority/Resource/Route/Dispatch/Comms live as engines + services,
    not agent classes. Importing the old costumes must fail."""
    import importlib

    for dead in ("resqra_agents.agents.priority",
                 "resqra_agents.agents.team_dispatch",
                 "resqra_agents.agents.route_strands",
                 "resqra_agents.agents.resource_dispatch_strands"):
        try:
            importlib.import_module(dead)
            raise AssertionError(f"{dead} still importable")
        except ModuleNotFoundError:
            pass
    # Engines + pure tools still importable.
    from resqra_agents.tools.allocation_engine import recommend_team
    from resqra_agents.tools.intake_tools import priority_score_tool
    from resqra_agents.tools.resource_tools import (
        contact_team_tool,
        recommend_resource_tool,
    )
    from resqra_agents.tools.routing_tools import explain_routes_tool

    assert callable(recommend_team)
    assert priority_score_tool is not None
    assert recommend_resource_tool is not None
    assert contact_team_tool is not None
    assert explain_routes_tool is not None
