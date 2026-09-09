"""Phase B run manager — 48h sim clock + story beats (arch §67-68).

Sim clock starts Day 1 06:00 (clock_min 0). Ticks advance it; beats with
at_min <= clock fire in order. Beat kinds:
  SIM_EVENT → services/simulation.apply_event (runs today)
  SOS_BURST → DEFERRED until Phase D implements burst injection
  FREEZE    → finishes the run
Unknown kinds are reported ERROR, never silently dropped.

Threading: one lock guards tick-vs-ticker double-fire. The auto-ticker is a
daemon loop that only advances runs with ticker_on=True (manual/sync ticks
stay deterministic for tests).
"""

from __future__ import annotations

import copy
import pathlib
import threading
import time
import uuid

import yaml

from app.db.repos import activity, simulation_runs

SCENARIOS_DIR = pathlib.Path(__file__).resolve().parents[3] / "simulation" / "scenarios"

MODES = {"AUTONOMOUS_TEST", "HUMAN_GATED"}
DAY_START_MIN = 6 * 60  # Day 1 06:00
# Fresh cards wait this long (sim-min) before autonomous approval: the
# debate + decision itself consumes rescue time.
DEBATE_DELAY_MIN = 30.0

_lock = threading.Lock()
_ticker = {"thread": None, "running": False}


class RunNotFoundError(LookupError):
    pass


class RunNotRunningError(RuntimeError):
    pass


def clock_label(clock_min: float) -> str:
    total = int(DAY_START_MIN + clock_min)
    day = int(clock_min // 1440) + 1
    return f"Day {day} {total // 60 % 24:02d}:{total % 60:02d}"


def load_scenario(scenario_id: str) -> dict:
    path = SCENARIOS_DIR / f"{scenario_id}.yaml"
    if not path.exists():
        raise LookupError(f"Scenario not found: {scenario_id}")
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    data.setdefault("id", scenario_id)
    data.setdefault("duration_min", 2880)
    data.setdefault("beats", [])
    return data


def _new_run_id(scenario_id: str) -> str:
    return f"run_{scenario_id.replace('-', '_')}_{uuid.uuid4().hex[:6]}"


def create_run(scenario_id: str, mode: str = "AUTONOMOUS_TEST", seed: int = 0,
               speed: float = 3.2, beats_override: list | None = None,
               debate_always: bool | None = None, max_debates: int = 220,
               max_llm_seconds: float = 3600) -> dict:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {sorted(MODES)}")
    scenario = load_scenario(scenario_id)
    if debate_always is None:
        # The story decides: flood-48h-01 debates every SOS.
        debate_always = bool(scenario.get("debate_always", False))
    run_id = _new_run_id(scenario_id)
    item = {
        "id": run_id,
        "scenario_id": scenario_id,
        "mode": mode,
        "seed": seed,
        "speed": float(speed),
        "debate_always": bool(debate_always),
        "max_debates": int(max_debates),
        "debates_used": 0,
        "max_llm_seconds": float(max_llm_seconds),
        "llm_seconds_used": 0.0,
        "status": "RUNNING",
        "clock_min": 0.0,
        "duration_min": scenario.get("duration_min", 2880),
        "beats": copy.deepcopy(beats_override) if beats_override is not None else copy.deepcopy(scenario.get("beats", [])),
        "fired_beats": [],
        "deferred_beats": [],
        "ticker_on": False,
        "created_at": int(time.time() * 1000),
    }
    simulation_runs.create_run(item)
    activity.log_event(actor="system", type_="run_started",
                       summary=f"Run {run_id} started [{scenario_id}/{mode}]",
                       payload={"run_id": run_id, "scenario_id": scenario_id,
                                "mode": mode, "seed": seed},
                       run_id=run_id)
    return public_run(simulation_runs.get_run(run_id))


def get_run(run_id: str) -> dict:
    run = simulation_runs.get_run(run_id)
    if run is None:
        raise RunNotFoundError(run_id)
    return public_run(run)


def public_run(run: dict) -> dict:
    clock = float(run.get("clock_min") or 0)
    return {
        "run_id": run["id"],
        "scenario_id": run.get("scenario_id"),
        "mode": run.get("mode"),
        "seed": run.get("seed"),
        "speed": run.get("speed"),
        "status": run.get("status"),
        "clock_min": clock,
        "clock_label": clock_label(clock),
        "duration_min": run.get("duration_min"),
        "fired_beats": run.get("fired_beats") or [],
        "deferred_beats": run.get("deferred_beats") or [],
        "ticker_on": bool(run.get("ticker_on")),
    }


def set_status(run_id: str, status: str) -> dict:
    run = simulation_runs.get_run(run_id)
    if run is None:
        raise RunNotFoundError(run_id)
    simulation_runs.update_run(run_id, status=status)
    activity.log_event(actor="system", type_=f"run_{status.lower()}",
                       summary=f"Run {run_id} → {status}",
                       payload={"run_id": run_id, "status": status},
                       run_id=run_id)
    return get_run(run_id)


def set_speed(run_id: str, speed: float) -> dict:
    run = simulation_runs.get_run(run_id)
    if run is None:
        raise RunNotFoundError(run_id)
    simulation_runs.update_run(run_id, speed=float(speed))
    return get_run(run_id)


def set_ticker(run_id: str, on: bool) -> dict:
    run = simulation_runs.get_run(run_id)
    if run is None:
        raise RunNotFoundError(run_id)
    simulation_runs.update_run(run_id, ticker_on=bool(on))
    if on:
        ensure_ticker()
    return get_run(run_id)


def _resolve_auto(event: dict) -> dict:
    """Resolve AUTO_* targets/params against live state (judge-proof ids)."""
    event = copy.deepcopy(event)
    target = event.get("target") or {}
    params = event.get("parameters") or {}
    if target.get("id") == "AUTO_LEAD_TEAM":
        from app.db.repos import teams
        teams_list = teams.list_teams()
        if not teams_list:
            raise LookupError("No teams to resolve AUTO_LEAD_TEAM")
        target["id"] = teams_list[0]["id"]
    if target.get("id") == "AUTO_FIRST_SHELTER":
        from app.db.repos import shelters
        all_s = shelters.list_shelters()
        if not all_s:
            raise LookupError("No shelters to resolve AUTO_FIRST_SHELTER")
        target["id"] = all_s[0]["id"]
        if params.get("current_occupancy") == "AUTO_FILL":
            params["current_occupancy"] = int(all_s[0].get("capacity") or 0)
    event["target"] = target
    event["parameters"] = params
    return event


def _fire_beat(run: dict, beat: dict) -> dict:
    """Execute one due beat. Returns {id, status, detail}."""
    run_id, scenario_id = run["id"], run.get("scenario_id")
    kind = (beat.get("kind") or "").upper()
    if kind == "SIM_EVENT":
        from app.services import simulation as sim_service
        try:
            event = _resolve_auto(beat.get("event") or {})
            event["scenario_id"] = scenario_id
            event["run_id"] = run_id
            sim_service.apply_event(event)
        except (LookupError, ValueError) as exc:
            return {"id": beat.get("id"), "status": "ERROR", "detail": str(exc)[:160]}
        return {"id": beat.get("id"), "status": "FIRED", "detail": event.get("type")}
    if kind == "SOS_BURST":
        # Phase D: burst injection through real intake.
        # Sync tick context → drive the coroutine explicitly. (The async
        # inject endpoint awaits it directly instead.)
        import asyncio

        from app.services import burst as burst_service

        burst_id = beat.get("burst_id") or beat.get("id")
        try:
            out = asyncio.run(burst_service.inject_sos_burst(
                run_id, burst_id,
                sim_min=float(run.get("clock_min") or 0)))
        except LookupError as exc:
            return {"id": beat.get("id"), "status": "ERROR", "detail": str(exc)[:160]}
        return {"id": beat.get("id"), "status": "FIRED",
                "detail": f"{out['incidents_created']} SOS ingested"}
    if kind == "FREEZE":
        simulation_runs.update_run(run_id, status="FINISHED")
        activity.log_event(actor="system", type_="run_finished",
                           summary=f"Run {run_id} finished at {clock_label(float(run.get('clock_min') or 0))}",
                           payload={"run_id": run_id}, run_id=run_id)
        return {"id": beat.get("id"), "status": "FIRED", "detail": "run finished"}
    return {"id": beat.get("id"), "status": "ERROR",
            "detail": f"unknown beat kind {kind!r}"}


def tick(run_id: str, minutes: float) -> dict:
    """Advance the clock synchronously, firing due beats. Returns run + fired."""
    with _lock:
        run = simulation_runs.get_run(run_id)
        if run is None:
            raise RunNotFoundError(run_id)
        if run.get("status") != "RUNNING":
            raise RunNotRunningError(f"run {run_id} is {run.get('status')}")
        clock = float(run.get("clock_min") or 0) + float(minutes)
        duration = float(run.get("duration_min") or 2880)
        if clock >= duration:
            clock = duration
        fired_ids = set(run.get("fired_beats") or [])
        deferred_ids = set(run.get("deferred_beats") or [])
        fired_now: list[dict] = []
        for beat in sorted(run.get("beats") or [], key=lambda b: float(b.get("at_min", 0))):
            bid = beat.get("id")
            if bid in fired_ids or float(beat.get("at_min", 0)) > clock:
                continue
            result = _fire_beat(run, beat)
            fired_now.append(result)
            if result["status"] == "DEFERRED":
                deferred_ids.add(bid)
            else:
                fired_ids.add(bid)
            if simulation_runs.get_run(run_id).get("status") == "FINISHED":
                break
        simulation_runs.update_run(run_id, clock_min=clock,
                                   fired_beats=sorted(fired_ids),
                                   deferred_beats=sorted(deferred_ids))
        from app.services import burst as burst_service

        # Order matters: new beats → recommend → approve → move, so freshly
        # approved teams start moving in the same tick.
        auto = {"run_id": run_id, "decided": [], "skipped": []}
        rec = {"run_id": run_id, "recommended": [], "skipped": []}
        debates_pending = 0
        if (simulation_runs.get_run(run_id) or {}).get("mode") == "AUTONOMOUS_TEST":
            rec = recommend_new(run_id)
            auto = auto_approve_due(run_id)
        telemetry = burst_service.advance_teams(run_id, float(minutes), clock_min=clock)
        try:
            from app.services import debate_pool as _pool

            _pool.collect_for_run(run_id)
            debates_pending = _pool.pending_count(run_id)
        except Exception:
            pass
        out = public_run(simulation_runs.get_run(run_id))
        out["fired"] = fired_now
        out["telemetry"] = telemetry
        out["recommended"] = rec["recommended"]
        out["autodecided"] = auto["decided"]
        out["debates_pending"] = debates_pending
        return out


async def inject(run_id: str, body: dict) -> dict:
    """Manual injection surface for judges/tests (Phase D).

    Accepts one of: {"sos_items": [...]} | {"sos_burst": id} |
    {"sim_event": {...}} | {"telemetry_minutes": N}.
    """
    from app.services import burst as burst_service
    from app.services import simulation as sim_service

    run = simulation_runs.get_run(run_id)
    if run is None:
        raise RunNotFoundError(run_id)
    if run.get("status") != "RUNNING":
        raise RunNotRunningError(f"run {run_id} is {run.get('status')}")
    body = body or {}
    if "sos_items" in body:
        items = body.get("sos_items") or []
        return await burst_service.inject_sos_items(run_id, items)
    if "sos_burst" in body:
        return await burst_service.inject_sos_burst(run_id, body.get("sos_burst"))
    if "sim_event" in body:
        event = dict(body.get("sim_event") or {})
        event["scenario_id"] = run.get("scenario_id")
        event["run_id"] = run_id
        return sim_service.apply_event(event)
    if "telemetry_minutes" in body:
        # Team movement consumes sim time: the clock advances first so
        # rescue durations elapse honestly instead of teleporting.
        minutes = float(body.get("telemetry_minutes") or 0)
        if minutes <= 0:
            raise ValueError("telemetry_minutes must be positive")
        clock = min(float(run.get("clock_min") or 0) + minutes,
                    float(run.get("duration_min") or 2880))
        simulation_runs.update_run(run_id, clock_min=clock)
        return burst_service.advance_teams(run_id, minutes, clock_min=clock)
    raise ValueError("inject needs sos_items | sos_burst | sim_event | telemetry_minutes")


def recommend_new(run_id: str) -> dict:
    """Phase E: close the autonomous loop — every new PRIORITIZED run
    incident without a mission or pending card gets a recommendation.
    debate_always runs force the chamber (needs the Phase F pool at scale).
    """
    from app.agents_gateway import gateway
    from app.db.repos import incidents, pending_actions

    run = simulation_runs.get_run(run_id)
    if run is None:
        raise RunNotFoundError(run_id)
    force = bool(run.get("debate_always"))
    clock = float(run.get("clock_min") or 0)
    recommended, skipped = [], []
    for inc in incidents.list_open_incidents():
        if inc.get("run_id") != run_id or inc.get("status") != "PRIORITIZED":
            continue
        if inc.get("mission_id") or inc.get("assigned_team"):
            continue
        prior = pending_actions.list_for_incident(inc["id"])
        mine = [c for c in prior if c.get("state") == "PENDING"]
        if mine:
            continue
        # Settled debates are not re-litigated every tick: force the chamber
        # only for incidents with no verdict yet. Replans still flow through
        # the trigger-gated path below.
        settled = any(((c.get("payload") or {}).get("debate") or {}).get("winner")
                      for c in prior)
        try:
            gateway.recommend_for_incident(inc["id"], force_debate=force and not settled,
                                           defer_debate=True, sim_min=clock)
            recommended.append(inc["id"])
        except Exception as exc:
            skipped.append({"id": inc["id"], "reason": str(exc)[:160]})
    return {"run_id": run_id, "recommended": recommended, "skipped": skipped}


def _ticker_loop() -> None:
    while _ticker["running"]:
        try:
            for run in simulation_runs.list_runs(limit=20):
                if run.get("status") == "RUNNING" and run.get("ticker_on"):
                    try:
                        tick(run["id"], float(run.get("speed") or 3.2))
                    except (RunNotFoundError, RunNotRunningError):
                        pass
        except Exception:
            pass
        time.sleep(1.0)


def ensure_ticker() -> None:
    if _ticker["thread"] is not None and _ticker["thread"].is_alive():
        return
    _ticker["running"] = True
    th = threading.Thread(target=_ticker_loop, daemon=True, name="sim-ticker")
    _ticker["thread"] = th
    th.start()


def auto_approve_due(run_id: str) -> dict:
    """Phase C: in AUTONOMOUS_TEST runs, the coordinator agent approves the
    run's own pending cards through the identical gate as the console
    (same audit, same idempotency). Anything else is skipped, never forced.

    Deliberation costs sim time: a fresh card waits DEBATE_DELAY_MIN before
    it may be approved, so debate + decision show up in response times and
    triage order genuinely matters under load.
    """
    from app.db.repos import pending_actions

    run = simulation_runs.get_run(run_id)
    if run is None:
        raise RunNotFoundError(run_id)
    decided, skipped, deliberating = [], [], []
    if run.get("mode") != "AUTONOMOUS_TEST":
        return {"run_id": run_id, "decided": decided,
                "skipped": skipped, "note": "not an autonomous run"}
    from app.routers import ops as ops_router

    clock = float(run.get("clock_min") or 0)
    for card in pending_actions.scan_pending_all():
        if card.get("state") != "PENDING" or card.get("run_id") != run_id:
            continue
        born = card.get("sim_min")
        if born is not None and clock - float(born) < DEBATE_DELAY_MIN:
            deliberating.append(card["id"])
            continue
        try:
            ops_router._apply_decision(card["id"], "APPROVED", None,
                                       "coordinator-agent",
                                       note=f"autonomous approval in run {run_id}",
                                       via="autonomous_test")
            decided.append(card["id"])
        except Exception as exc:
            skipped.append({"id": card["id"], "reason": str(exc)[:160]})
    return {"run_id": run_id, "decided": decided, "skipped": skipped,
            "deliberating": deliberating}


def publish_advisory(run_id: str, area_text: str, title: str, body: str,
                     severity: str = "INFO") -> dict:
    """Phase G: the coordinator agent reports to residents (GovReports feed).
    Gated to AUTONOMOUS_TEST runs — normal mode publishes via the human
    console (POST /api/ops/reports) only."""
    from app.db.repos import activity, reports

    run = simulation_runs.get_run(run_id)
    if run is None:
        raise RunNotFoundError(run_id)
    if run.get("mode") != "AUTONOMOUS_TEST":
        return {"run_id": run_id, "published": False,
                "reason": "advisories publish autonomously only in AUTONOMOUS_TEST runs"}
    item = reports.create_report(title=title, body=body, severity=severity,
                                 source="COORDINATOR_AGENT", area_text=area_text,
                                 created_by="coordinator-agent")
    activity.log_event(actor="agent", type_="resident_advisory_published",
                       summary=f"Coordinator agent published advisory: {title}",
                       payload={"run_id": run_id, "report_id": item["id"],
                                "area_text": area_text, "severity": severity},
                       run_id=run_id)
    return {"run_id": run_id, "published": True, "report": item}
