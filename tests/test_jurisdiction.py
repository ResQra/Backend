"""Jurisdiction fast-drop tests — no DB, no keys, no network."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "agents"))


def test_hint_district_wins():
    from app.utils.geo import jurisdiction_hint_from_text as hint

    assert hint("Help in New Delhi") == "OUT_OF_DISTRICT"
    assert hint("coming from Delhi to Gaur, Ward 4") == "IN_DISTRICT"
    assert hint("Water in Gaur Ward 4") == "IN_DISTRICT"
    assert hint("some vague flooding here") == "UNKNOWN"
    assert hint(None) == "UNKNOWN"
    assert hint("Kathmandu valley rescue") == "OUT_OF_DISTRICT"


def test_hint_mirror_matches_backend():
    from app.utils.geo import jurisdiction_hint_from_text as backend_hint
    from resqra_agents.tools.geo import jurisdiction_hint_from_text as agent_hint

    samples = ["Help in New Delhi", "Gaur Ward 4 water", "flood near Patna bypass",
               "coming from Delhi to Gaur", "Bagmati rising fast", "", None,
               "Kathmandu Durbar Marg", "Bairgania border crossing"]
    for s in samples:
        assert backend_hint(s) == agent_hint(s), s


def test_intake_extract_flags_jurisdiction():
    from resqra_agents.agents.report_intake import extract

    assert extract("Help New Delhi Connaught Place")["jurisdiction_hint"] == "OUT_OF_DISTRICT"
    assert extract("6 people stuck near school, water rising")["jurisdiction_hint"] in (
        "IN_DISTRICT", "UNKNOWN")


def test_bbox_exact():
    from app.utils.geo import in_operational_area

    assert in_operational_area(26.766, 85.277) is True
    assert in_operational_area(28.6139, 77.2090) is False
