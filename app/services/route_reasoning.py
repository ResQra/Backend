"""Phase 7 route reasoning — arch §17.2-17.3 (deterministic, no LLM).

The engine calculates; this module interprets: pick the cheapest feasible
candidate and explain every rejection in the arch's voice, e.g.
"Route C is 0.5 km longer than Route A, but Route A crosses a damaged
bridge. Route C is currently the best feasible option."
"""

from __future__ import annotations


def _unique_reasons(routes: list[dict]) -> list[str]:
    seen, out = set(), []
    for r in routes:
        reason = r.get("blocked_reason") or "infeasible"
        # One blocked street can taint dozens of edges — collapse repeats
        # so the coordinator reads one line, not twenty.
        for part in [p.strip() for p in reason.split(";")]:
            if part and part not in seen:
                seen.add(part)
                out.append(part)
    return out


def explain(routes: list[dict]) -> dict:
    feasible = [r for r in (routes or []) if r.get("feasible")]
    invalid = [r for r in (routes or []) if not r.get("feasible")]

    if not routes:
        return {"recommended_id": None,
                "explanation": "No route candidates available.",
                "invalid": []}
    if not feasible:
        reasons = "; ".join(_unique_reasons(invalid))
        return {"recommended_id": None,
                "explanation": f"No feasible route. Blocked by: {reasons}. "
                               "Request alternate analysis or escalate.",
                "invalid": [{"id": r.get("id"),
                             "reason": "; ".join(
                                 [p.strip() for p in (r.get("blocked_reason") or "infeasible").split(";")][:3])}
                            for r in invalid]}

    best = min(feasible, key=lambda r: (r.get("distance_km") or 1e9,
                                        r.get("risk_penalty") or 0))
    parts = []
    for bad in invalid:
        delta = ""
        if bad.get("distance_km") is not None and best.get("distance_km") is not None:
            diff = round(best["distance_km"] - bad["distance_km"], 1)
            delta = (f"Route {best['id']} is {abs(diff)} km "
                     f"{'longer' if diff > 0 else 'shorter'} than {bad['id']}, but " if diff else
                     f"Route {best['id']} matches {bad['id']} on distance, but ")
        reason = "; ".join(
            [p.strip() for p in (bad.get("blocked_reason") or "infeasible").split(";")][:2])
        parts.append(f"{delta}{bad['id']} is rejected — {reason}.")
    parts.append(f"{best['id']} ({best.get('distance_km')} km) is currently "
                 "the best feasible option.")
    return {"recommended_id": best.get("id"),
            "explanation": " ".join(parts),
            "invalid": [{"id": r.get("id"),
                         "reason": "; ".join(
                             [p.strip() for p in (r.get("blocked_reason") or "infeasible").split(";")][:2])}
                        for r in invalid]}
