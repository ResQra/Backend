"""Explicit chat command parsing — no DB, no keys, no network."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.chat_commands import parse_command

PENDING = [{"id": "pa_1", "proposed_team_id": "team_apf_rautahat",
            "incident_id": "inc_rautahat_101"}]
TEAMS = [{"id": "team_apf_rautahat", "name": "APF BATTALION NO. 11, RAUTAHAT"},
         {"id": "team_gaur_bagmati", "name": "GAUR BAGMATI WATER RESCUE UNIT"}]
INCS = [{"id": "inc_rautahat_101", "location_text": "Gaur Ward 4",
         "status": "PRIORITIZED"}]


def test_approve_by_team_name():
    out = parse_command("approve APF battalion", PENDING, TEAMS, INCS)
    assert out == {"action": "approve", "pending_id": "pa_1",
                   "team_id": "team_apf_rautahat",
                   "incident_id": "inc_rautahat_101"}, out


def test_reject_synonyms():
    for verb in ("reject", "deny", "decline"):
        out = parse_command(f"{verb} apf", PENDING, TEAMS, INCS)
        assert out["action"] == "reject" and out["pending_id"] == "pa_1", (verb, out)


def test_bare_verb_asks_which():
    out = parse_command("approve", PENDING, TEAMS, INCS)
    assert out["action"] == "clarify"


def test_unknown_team_clarifies_never_guesses():
    out = parse_command("approve dragon squadron", PENDING, TEAMS, INCS)
    assert out["action"] == "clarify" and "No pending" in out["reply"]


def test_assign_parses():
    out = parse_command("assign gaur bagmati to inc_rautahat_101", PENDING, TEAMS, INCS)
    assert out == {"action": "assign", "team_id": "team_gaur_bagmati",
                   "incident_id": "inc_rautahat_101"}, out


def test_chatter_is_none():
    assert parse_command("what is happening here?", PENDING, TEAMS, INCS)["action"] == "none"
    assert parse_command(" approve", PENDING, TEAMS, INCS)["action"] == "clarify"
