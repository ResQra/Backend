"""Phase 5 exit tests â€” no DB, no LLM keys, no network.

Resident input â†’ structured + prioritized incident (Â§13-14, Â§54).
Run: .venv/Scripts/python -m pytest tests/test_phase5_intake_priority.py -q
"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agents"))
os.environ.pop("GROQ_API_KEY", None)


def test_priority_bands_deterministic():
    from resqra_agents.tools.priority_engine import compute_priority

    critical = compute_priority(
        {"urgency": "CRITICAL", "people": 9,
         "vulnerabilities": ["children", "elderly"]})
    assert critical["band"] == "CRITICAL"
    assert critical["score"] >= 12
    assert any("children" in r for r in critical["reasons"])

    low = compute_priority({"urgency": "LOW", "people": 1, "vulnerabilities": []})
    assert low["band"] == "LOW"

    # Deterministic: same input, same output.
    again = compute_priority(
        {"urgency": "CRITICAL", "people": 9,
         "vulnerabilities": ["children", "elderly"]})
    assert again == critical


def test_intake_regex_fallback_structured():
    from resqra_agents.agents.report_intake import extract

    out = extract("6 people stuck near school, water rising fast, 2 children")
    assert out["people_count"] == 6
    assert "children" in out["vulnerabilities"]
    assert out["water_rising"] is True
    assert out["location_text"]


def test_status_normalization_rule():
    # Mirrors routers/incidents.py Phase 5 rule (Â§54).
    def next_status(verification, scored):
        norm = "UNVERIFIED" if verification == "NEEDS_COORDINATOR_REVIEW" else "VERIFIED"
        if scored and norm == "VERIFIED":
            return "PRIORITIZED"
        return norm

    assert next_status("GEOCODED", True) == "PRIORITIZED"
    assert next_status("GPS", True) == "PRIORITIZED"
    assert next_status("NEEDS_COORDINATOR_REVIEW", True) == "UNVERIFIED"
    assert next_status("GEOCODED", False) == "VERIFIED"


def test_gateway_intake_seam_without_keys():
    from app.agents_gateway import gateway

    out = asyncio.run(gateway.intake_extract(
        "6 people stuck near school, water rising fast"))
    assert out["people"] == 6
    assert out["water_rising"] is True


def test_strands_tools_importable():
    from resqra_agents.tools.intake_tools import (
        normalize_extraction_tool,
        priority_score_tool,
        regex_extract_tool,
    )

    assert normalize_extraction_tool is not None
    assert regex_extract_tool is not None
    assert priority_score_tool is not None
