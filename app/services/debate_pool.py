"""Phase F async debate pool — bounded chamber workers for runs.

Recommend path stays fast: the deterministic card persists immediately and
the chamber runs on a worker. Completed verdicts attach to the live card
via collect_for_run (non-blocking) or the /debates/collect endpoint.
Budget exhaustion degrades to explicit DETERMINISTIC_FALLBACK.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor

_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="chamber")
_lock = threading.RLock()  # reentrant: submit_for_run nests into _budget
# (run_id, incident_id) -> Future; guarded by _lock
_tracked: dict[tuple[str, str], Future] = {}


def _budget(run_id: str) -> tuple[bool, str]:
    """Check-and-increment the run's debate budget, atomically for threads.
    Returns (allowed, note)."""
    from app.db.repos import simulation_runs

    with _lock:
        run = simulation_runs.get_run(run_id)
        if run is None:
            return False, "run not found"
        used = int(run.get("debates_used") or 0)
        cap = run.get("max_debates")
        cap = int(cap) if cap is not None else 220
        if used >= cap:
            return False, f"debate budget exhausted ({used}/{cap})"
        simulation_runs.update_run(run_id, debates_used=used + 1)
        return True, ""


def submit_for_run(run_id: str, incident_id: str, snapshot: dict) -> dict:
    """Queue a chamber. Returns a PENDING marker, or an explicit FALLBACK
    marker when the budget is gone (never silent, never blocking).

    Resubmits are free: an unfinished chamber for the same incident is
    reused, so per-tick re-evaluations don't burn budget or Groq calls.
    """
    with _lock:
        existing = _tracked.get((run_id, incident_id))
    if existing is not None and not existing.done():
        return {"incident_id": incident_id, "status": "PENDING", "deferred": True}
    with _lock:
        # Evict stale done entries so never-collected runs can't grow memory.
        if len(_tracked) >= 500:
            for key in [k for k, f in _tracked.items() if f.done()][:250]:
                _tracked.pop(key, None)
    allowed, note = _budget(run_id)
    if not allowed:
        return {"incident_id": incident_id, "winner": "DETERMINISTIC_FALLBACK",
                "fallback": True, "deferred": False,
                "verdict": f"Chamber skipped — {note}. Deterministic path stands.",
                "trigger": "budget"}
    from app.agents_gateway.gateway import _run_chamber_sync

    fut = _pool.submit(_run_chamber_sync, incident_id, snapshot)
    with _lock:
        _tracked[(run_id, incident_id)] = fut
    return {"incident_id": incident_id, "status": "PENDING", "deferred": True}


def pending_count(run_id: str) -> int:
    with _lock:
        keys = [k for k in _tracked if k[0] == run_id]
    return sum(1 for k in keys if not _tracked[k].done())


def collect_for_run(run_id: str, wait_s: float = 0) -> dict:
    """Attach completed verdicts to live cards + ledger. Non-blocking
    unless wait_s > 0 (then waits up to wait_s per pending chamber)."""
    from app.db.repos import activity, pending_actions, simulation_runs

    collected: list[dict] = []
    deadline = time.time() + float(wait_s or 0)
    while True:
        with _lock:
            keys = [k for k in _tracked if k[0] == run_id]
        outstanding = [k for k in keys if not _tracked[k].done()]
        if not outstanding or time.time() >= deadline:
            break
        time.sleep(0.5)
    with _lock:
        keys = [k for k in _tracked if k[0] == run_id and _tracked[k].done()]
    for key in keys:
        _, incident_id = key
        with _lock:
            fut = _tracked.pop(key)
        try:
            verdict = fut.result() or {}
        except Exception as exc:
            verdict = {"incident_id": incident_id, "winner": "DETERMINISTIC_FALLBACK",
                       "fallback": True,
                       "verdict": f"Chamber worker failed ({type(exc).__name__})"}
        verdict = {"incident_id": incident_id, **verdict}
        try:
            # Attach to the live card if still pending, else to the latest
            # decided card — autodecide often beats the chamber in one tick.
            all_cards = pending_actions.list_for_incident(incident_id)
            live = [c for c in all_cards if c.get("state") == "PENDING"]
            target = live[0] if live else (all_cards[0] if all_cards else None)
            if target:
                payload = dict(target.get("payload") or {})
                payload["debate"] = verdict
                pending_actions.update_action(target["id"], payload=payload)
            activity.log_event(
                actor="agent", type_="debate_concluded",
                summary=f"Chamber on {incident_id}: {verdict.get('winner')} "
                        f"({verdict.get('rounds', '?')} rounds)",
                payload={"incident_id": incident_id,
                         "winner": verdict.get("winner"),
                         "verdict": str(verdict.get("verdict") or "")[:800]},
                run_id=run_id)
            try:
                run = simulation_runs.get_run(run_id) or {}
                simulation_runs.update_run(
                    run_id, llm_seconds_used=float(run.get("llm_seconds_used") or 0)
                    + float(verdict.get("elapsed_s") or 0))
            except Exception:
                pass
        except Exception:
            pass
        collected.append(verdict)
    return {"run_id": run_id, "collected": len(collected), "verdicts": collected}
