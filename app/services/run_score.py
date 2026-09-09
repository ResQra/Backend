"""Phase E run score + timeline (arch §45, §68).

Everything is derived from the ledger filtered by run_id — never
hand-counted. Response times are SIM-minutes (wall clock is meaningless
in a compressed run). Verdicts are PASS/PARTIAL/FAIL with details.
"""

from __future__ import annotations

from app.db.repos import activity, incidents, missions, simulation_runs
from app.services.run_manager import RunNotFoundError, clock_label


def _pct(sorted_vals: list[float], pct: float) -> float | None:
    if not sorted_vals:
        return None
    k = min(len(sorted_vals) - 1, max(0, int(round((pct / 100) * (len(sorted_vals) - 1)))))
    return sorted_vals[k]


def _round1(v: float | None) -> float | None:
    return None if v is None else round(float(v), 1)


def _run_incidents(run_id: str) -> list[dict]:
    """All run incidents incl. RESCUED (open-queue misses those)."""
    from boto3.dynamodb.conditions import Attr

    from app.db.client import table

    items = table("Incidents").scan(
        FilterExpression=Attr("run_id").eq(run_id)).get("Items", [])
    fallback = [i for i in incidents.list_open_incidents() if i.get("run_id") == run_id]
    seen = {i["id"] for i in items}
    return items + [i for i in fallback if i["id"] not in seen]


def _run_missions(run_id: str) -> list[dict]:
    return [m for m in missions.list_missions() if m.get("run_id") == run_id]


def _run_events(run_id: str, limit: int = 500) -> list[dict]:
    evs = activity.recent_events(limit)
    return [e for e in evs
            if e.get("run_id") == run_id or (e.get("payload") or {}).get("run_id") == run_id]


def get_timeline(run_id: str, limit: int = 100) -> dict:
    run = simulation_runs.get_run(run_id)
    if run is None:
        raise RunNotFoundError(run_id)
    evs = sorted(_run_events(run_id, max(limit, 500)),
                 key=lambda e: -int(e.get("ts") or 0))[:max(1, min(limit, 500))]
    return {"run_id": run_id, "count": len(evs), "events": evs}


def _verdict(criterion: str, status: str, detail: str) -> dict:
    assert status in ("PASS", "PARTIAL", "FAIL")
    return {"criterion": criterion, "status": status, "detail": detail}


def get_score(run_id: str) -> dict:
    from app.services.run_manager import public_run

    run = simulation_runs.get_run(run_id)
    if run is None:
        raise RunNotFoundError(run_id)
    incs = _run_incidents(run_id)
    ms = _run_missions(run_id)
    evs = _run_events(run_id)

    rescued = [i for i in incs if i.get("status") == "RESCUED"]
    open_incs = [i for i in incs if i.get("status") != "RESCUED"]
    lives_saved = sum(int(i.get("people") or 1) for i in rescued)
    lives_at_risk = sum(int(i.get("people") or 1) for i in open_incs)
    critical_open = [i for i in open_incs
                     if (i.get("priority") or {}).get("score", 0) >= 8
                     or i.get("urgency") == "HIGH"]
    with_mission = {m.get("incident_id") for m in ms}
    coverage = (len([i for i in incs if i.get("id") in with_mission]) / len(incs)) if incs else 0.0

    deltas = []
    for m in ms:
        if m.get("sim_min") is None:
            continue
        inc = next((i for i in incs if i["id"] == m.get("incident_id")), None)
        base = (inc or {}).get("sim_min")
        if base is None:
            continue
        deltas.append(max(0.0, float(m["sim_min"]) - float(base)))
    deltas.sort()

    by_type: dict[str, int] = {}
    for e in evs:
        by_type[e.get("type", "?")] = by_type.get(e.get("type", "?"), 0) + 1
    debates = [e for e in evs if e.get("type") == "debate_concluded"]
    forwards = [e for e in debates
                if str((e.get("payload") or {}).get("winner", "")).upper() in ("DISPATCH", "WAIT")]
    auto_ok = sum(1 for e in evs if e.get("type") == "pending_action_approved"
                  and "autonomous" in str((e.get("payload") or {}).get("note", "")
                                          + e.get("summary", "")))
    # approved-by-agent marker lives on the card, not the event: recount via missions
    replans = [e for e in evs if e.get("type") == "allocation_recommended"
               and ((e.get("payload") or {}).get("stability") or {}).get("verdict") == "REPLANNED"]
    comms = [e for e in evs if e.get("type") == "communication_lost"]
    recs_after_comms = 0
    if comms:
        first = min(int(e.get("ts") or 0) for e in comms)
        recs_after_comms = sum(1 for e in evs if e.get("type") == "allocation_recommended"
                               and int(e.get("ts") or 0) > first)

    total = len(incs)
    scored = [i for i in incs if (i.get("priority") or {}).get("reasons") != ["awaiting triage"]]
    triage_frac = len(scored) / total if total else 0.0
    rescue_rate = len(rescued) / total if total else 0.0
    final = (run.get("status") in ("FINISHED", "STOPPED"))

    verdicts = [
        _verdict("sos_ingested", "PASS" if total else "FAIL",
                 f"{total} run incidents ingested"),
        _verdict("triage_complete",
                 "PASS" if triage_frac >= 0.99 else ("PARTIAL" if triage_frac >= 0.8 else "FAIL"),
                 f"{len(scored)}/{total} scored"),
        _verdict("dispatch_coverage",
                 "PASS" if coverage >= 1.0 and total else ("PARTIAL" if coverage >= 0.7 else "FAIL"),
                 f"{len(with_mission)}/{total} incidents with missions"),
        _verdict("rescue_rate",
                 "PASS" if rescue_rate >= 0.8 else ("PARTIAL" if rescue_rate >= 0.5 else "FAIL"),
                 f"{len(rescued)}/{total} rescued"),
        _verdict("comms_handled",
                 "PASS" if (not comms or recs_after_comms > 0) else "PARTIAL",
                 f"{len(comms)} comms losses, {recs_after_comms} re-recommendations after"),
        _verdict("debate_integrity",
                 "PASS" if debates else "PARTIAL",
                 f"{len(debates)} debates concluded ({len(forwards)} forwarded)"),
    ]
    return {
        "run_id": run_id,
        "status": run.get("status"),
        "final": final,
        "clock_label": clock_label(float(run.get("clock_min") or 0)),
        "incidents_total": total,
        "open_count": len(open_incs),
        "rescued_count": len(rescued),
        "critical_open": len(critical_open),
        "lives_saved": lives_saved,
        "lives_at_risk": lives_at_risk,
        "dispatch_coverage": round(coverage, 3),
        "response_p50_sim_min": _round1(_pct(deltas, 50)),
        "response_p90_sim_min": _round1(_pct(deltas, 90)),
        "response_samples": len(deltas),
        "debates_held": len(debates),
        "auto_approvals": auto_ok,
        "replans": len(replans),
        "comms_losses": len(comms),
        "missions": len(ms),
        "event_counts": by_type,
        "verdicts": verdicts,
    }
