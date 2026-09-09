"""Phase 1 simulation API — arch §24, §64-67. Phase B adds the run surface.

Unified judge surface. Writes go through services/simulation.apply_event()
so map + agents see the same state as real telemetry (§4.2).
"""

from fastapi import APIRouter, Depends, HTTPException

from app.auth.deps import require_role
from app.events.contracts import SimulationEvent
from app.services import run_manager, simulation as sim_service

router = APIRouter(prefix="/api/simulation", tags=["simulation"],
                   dependencies=[Depends(require_role("coordinator"))])


@router.post("/events")
def post_event(body: dict):
    try:
        event = SimulationEvent(**body).model_dump()
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return sim_service.apply_event(event)


@router.get("/state")
def get_state():
    return sim_service.current_state()


@router.post("/reset")
def reset():
    from app.routers.ops import demo_reset

    return demo_reset()


# --- Phase B: run surface (one-click judge runs) ---


@router.post("/scenarios/{scenario_id}/prepare")
def prepare_scenario(scenario_id: str):
    """Reset to the scenario baseline (seeded fleet/shelters) + counts."""
    from app.routers.ops import demo_reset

    try:
        run_manager.load_scenario(scenario_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Scenario not found")
    out = demo_reset()
    if out.get("status") != "SUCCESS":
        raise HTTPException(status_code=500, detail="Prepare failed")
    state = sim_service.current_state()
    return {"scenario_id": scenario_id, "status": "PREPARED",
            "teams": len(state.get("teams", [])),
            "shelters": len(state.get("shelters", [])),
            "incidents": len(state.get("incidents", []))}


@router.post("/runs")
def create_run(body: dict):
    try:
        return run_manager.create_run(
            scenario_id=body.get("scenario_id", "flood-48h-01"),
            mode=body.get("mode", "AUTONOMOUS_TEST"),
            seed=int(body.get("seed", 0)),
            speed=float(body.get("speed", 3.2)),
            beats_override=body.get("beats_override"),
            debate_always=bool(body.get("debate_always", False)),
            max_debates=int(body.get("max_debates", 220)),
            max_llm_seconds=float(body.get("max_llm_seconds", 3600)),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/runs/{run_id}")
def get_run(run_id: str):
    try:
        return run_manager.get_run(run_id)
    except run_manager.RunNotFoundError:
        raise HTTPException(status_code=404, detail="Run not found")


@router.post("/runs/{run_id}/tick")
def tick_run(run_id: str, body: dict):
    try:
        minutes = float((body or {}).get("minutes", 60))
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="minutes must be a number")
    if minutes <= 0:
        raise HTTPException(status_code=422, detail="minutes must be positive")
    try:
        return run_manager.tick(run_id, minutes)
    except run_manager.RunNotFoundError:
        raise HTTPException(status_code=404, detail="Run not found")
    except run_manager.RunNotRunningError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post("/runs/{run_id}/pause")
def pause_run(run_id: str):
    try:
        return run_manager.set_status(run_id, "PAUSED")
    except run_manager.RunNotFoundError:
        raise HTTPException(status_code=404, detail="Run not found")


@router.post("/runs/{run_id}/resume")
def resume_run(run_id: str):
    try:
        run = run_manager.get_run(run_id)
    except run_manager.RunNotFoundError:
        raise HTTPException(status_code=404, detail="Run not found")
    if run["status"] == "FINISHED" or run["status"] == "STOPPED":
        raise HTTPException(status_code=409, detail=f"run is {run['status']}")
    return run_manager.set_status(run_id, "RUNNING")


@router.post("/runs/{run_id}/speed")
def speed_run(run_id: str, body: dict):
    try:
        speed = float((body or {}).get("speed", 3.2))
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="speed must be a number")
    if speed <= 0:
        raise HTTPException(status_code=422, detail="speed must be positive")
    try:
        return run_manager.set_speed(run_id, speed)
    except run_manager.RunNotFoundError:
        raise HTTPException(status_code=404, detail="Run not found")


@router.post("/runs/{run_id}/ticker")
def ticker_run(run_id: str, body: dict):
    try:
        return run_manager.set_ticker(run_id, bool((body or {}).get("on", True)))
    except run_manager.RunNotFoundError:
        raise HTTPException(status_code=404, detail="Run not found")


@router.post("/runs/{run_id}/stop")
def stop_run(run_id: str):
    try:
        return run_manager.set_status(run_id, "STOPPED")
    except run_manager.RunNotFoundError:
        raise HTTPException(status_code=404, detail="Run not found")


@router.get("/runs/{run_id}/timeline")
def run_timeline(run_id: str, limit: int = 100):
    from app.services import run_score

    try:
        return run_score.get_timeline(run_id, limit=limit)
    except run_manager.RunNotFoundError:
        raise HTTPException(status_code=404, detail="Run not found")


@router.get("/runs/{run_id}/score")
def run_score(run_id: str):
    from app.services import run_score as run_score_mod

    try:
        return run_score_mod.get_score(run_id)
    except run_manager.RunNotFoundError:
        raise HTTPException(status_code=404, detail="Run not found")


@router.post("/runs/{run_id}/autodecide")
def autodecide_run(run_id: str):
    """Phase C: coordinator-agent approves this run's due cards — only in
    AUTONOMOUS_TEST mode. Human-gated runs are left untouched."""
    try:
        return run_manager.auto_approve_due(run_id)
    except run_manager.RunNotFoundError:
        raise HTTPException(status_code=404, detail="Run not found")


@router.post("/runs/{run_id}/debates/collect")
def collect_debates(run_id: str, body: dict | None = None):
    """Phase F: attach finished chamber verdicts now; optionally wait up
    to wait_s seconds for pending chambers (judge/score sync point)."""
    from app.services import debate_pool

    try:
        run_manager.get_run(run_id)
    except run_manager.RunNotFoundError:
        raise HTTPException(status_code=404, detail="Run not found")
    wait_s = 0.0
    try:
        wait_s = float((body or {}).get("wait_s", 0) or 0)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="wait_s must be a number")
    return debate_pool.collect_for_run(run_id, wait_s=min(wait_s, 300))


@router.post("/runs/{run_id}/inject")
async def inject_run(run_id: str, body: dict):
    """Phase D: manual injection — sos_items | sos_burst | sim_event |
    telemetry_minutes. Same provenance as tick-fired beats."""
    try:
        return await run_manager.inject(run_id, body or {})
    except run_manager.RunNotFoundError:
        raise HTTPException(status_code=404, detail="Run not found")
    except run_manager.RunNotRunningError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except (ValueError, LookupError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/scenarios/{scenario_id}/start")
def start_scenario(scenario_id: str):
    """One-click judge start: prepare baseline + create the run."""
    from app.routers.ops import demo_reset

    try:
        run_manager.load_scenario(scenario_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Scenario not found")
    out = demo_reset()
    if out.get("status") != "SUCCESS":
        raise HTTPException(status_code=500, detail="Prepare failed")
    run = run_manager.create_run(scenario_id=scenario_id, mode="AUTONOMOUS_TEST")
    run_manager.set_ticker(run["run_id"], True)
    return run_manager.get_run(run["run_id"])


@router.post("/scenarios/{scenario_id}/stop")
def stop_scenario(scenario_id: str):
    return {"scenario_id": scenario_id, "status": "STOPPED"}


@router.post("/runs/{run_id}/advisories")
def publish_advisory(run_id: str, body: dict):
    """Phase G: coordinator agent reports to residents. Gated to
    AUTONOMOUS_TEST runs; normal mode uses the human console."""
    body = body or {}
    if not body.get("title") or not body.get("body"):
        raise HTTPException(status_code=422, detail="title and body required")
    try:
        return run_manager.publish_advisory(
            run_id, body.get("area_text", ""),
            body.get("title"), body.get("body"),
            severity=str(body.get("severity", "INFO")).upper())
    except run_manager.RunNotFoundError:
        raise HTTPException(status_code=404, detail="Run not found")
