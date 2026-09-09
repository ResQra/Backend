"""Shelter-awareness tests — no DB, no keys, no network.

An SOS from inside an open shelter with free beds must score lower
(with a named reason) and surface a shelter-in-place option; a full
shelter must change nothing.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agents"))

SHELTERS = [
    {"id": "S-1", "name": "Stadium Camp",
     "location": {"lat": 26.7680, "lng": 85.2810},
     "capacity": 100, "current_occupancy": 20, "status": "OPEN"},
    {"id": "S-FULL", "name": "Full Hall",
     "location": {"lat": 26.9000, "lng": 85.4000},
     "capacity": 50, "current_occupancy": 50, "status": "OPEN"},
]


def _incident_at(lat, lng):
    return {"id": "INC-T", "urgency": "HIGH", "people": 4,
            "vulnerabilities": [], "location": {"lat": lat, "lng": lng}}


def test_shelter_perimeter_lowers_score_with_reason():
    from resqra_agents.tools.priority_engine import compute_priority

    inside = compute_priority(_incident_at(26.7680, 85.2810), shelters=SHELTERS)
    outside = compute_priority(_incident_at(26.7600, 85.2600), shelters=SHELTERS)
    assert inside["score"] == outside["score"] - 2
    assert any("Stadium Camp" in r for r in inside["reasons"])
    assert any(f["name"] == "shelter_proximity" and f["points"] == -2
               for f in inside["factors"])


def test_full_shelter_changes_nothing():
    from resqra_agents.tools.priority_engine import compute_priority

    at_full = compute_priority(_incident_at(26.9000, 85.4000), shelters=SHELTERS)
    no_ctx = compute_priority(_incident_at(26.9000, 85.4000))
    assert at_full["score"] == no_ctx["score"]


def test_allocation_surfaces_shelter_option():
    from resqra_agents.tools.allocation_engine import recommend_team

    teams = [{"id": "T-1", "name": "Boat One", "status": "AVAILABLE",
              "capacity": 10, "location": {"lat": 26.7700, "lng": 85.2850}}]
    rec = recommend_team(_incident_at(26.7680, 85.2810), teams, shelters=SHELTERS)
    assert rec["shelter_option"]["shelter_id"] == "S-1"
    assert any("Stadium Camp" in r for r in rec["reasons"])


def test_no_shelters_no_option_no_crash():
    from resqra_agents.tools.allocation_engine import recommend_team
    from resqra_agents.tools.priority_engine import compute_priority

    teams = [{"id": "T-1", "name": "Boat One", "status": "AVAILABLE",
              "capacity": 10, "location": {"lat": 26.7700, "lng": 85.2850}}]
    assert compute_priority(_incident_at(26.7680, 85.2810))["score"] >= 0
    assert recommend_team(_incident_at(26.7680, 85.2810), teams)["shelter_option"] is None
