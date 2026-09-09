"""Phase 8 communication simulation — arch §50 (abstraction over LLM).

Demo contact mechanism: success when the team is dispatchable, timeout when
OFFLINE/UNAVAILABLE or reporting comms loss. Replies update backend state
via callers; nothing stays trapped as text.
"""

from __future__ import annotations


def contact_team(team: dict, message: str) -> dict:
    status = str(team.get("status") or "UNKNOWN").upper()
    problem = team.get("last_problem") if isinstance(team.get("last_problem"), dict) else {}
    if status in ("OFFLINE", "UNAVAILABLE") or \
            str(problem.get("severity", "")).upper() == "OFFLINE":
        return {"delivered": False, "timeout": True,
                "reply": None, "detail": f"{team.get('name') or team.get('id')} unreachable"}
    if status == "ON_MISSION":
        return {"delivered": True, "timeout": False,
                "reply": "Acknowledged — updating from the field.",
                "detail": "delivered to active mission"}
    return {"delivered": True, "timeout": False,
            "reply": "Acknowledged — standing by for tasking.",
            "detail": "delivered"}
