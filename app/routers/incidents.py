import time
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends

from app.agents_gateway import gateway
from app.auth.deps import CurrentUser, get_current_user
from app.db.repos import activity, incidents, users
from app.models import IncidentCreate
from app.utils.geo import geohash_encode
from app.utils.geocode import geocode


def D(x) -> Decimal:
    """DynamoDB rejects float — coordinates must be Decimal."""
    return Decimal(str(x))


def _validated_run_id(run_id: str | None) -> str:
    """HTTP-supplied run tags are only honored for a live run. Anything
    else (typo, forged, finished) becomes untagged rather than polluting
    some run's ledger, score, or timeline."""
    if not run_id:
        return ""
    try:
        from app.db.repos import simulation_runs as _runs

        run = _runs.get_run(run_id)
        if run is not None and run.get("status") == "RUNNING":
            return run_id
    except Exception:
        pass
    return ""


router = APIRouter(prefix="/api/incidents", tags=["incidents"])


@router.post("")
async def create_incident(body: IncidentCreate, user: CurrentUser = Depends(get_current_user)):
    """F01 entry point: raw distress text (optionally pre-structured) →
    incident with status NEW. Location priority: exact GPS if provided,
    else geocode the landmark text (OSM Nominatim, free); if neither
    yields coordinates the incident is flagged NEEDS_COORDINATOR_REVIEW
    (F02 — never guess). The TriageAgent scores it afterwards via its seam."""
    ts = Decimal(str(time.time()))
    # Resident-supplied run tags are only honored for a live run.
    run_id = _validated_run_id(body.run_id)

    # Fast drop (intake focus): obvious out-of-area SOS dies here, before
    # geocode network calls, triage scoring, or any downstream agent work.
    # GPS coords get an exact bbox check; bare text gets the far-place
    # gazetteer (local names always win; unknowns fall through to geocode).
    # The record is still persisted + logged for audit — dropped from the
    # pipeline, never silently vanished.
    from app.utils.geo import in_operational_area, jurisdiction_hint_from_text

    fast_drop_location = None
    fast_drop = False
    if body.location:
        if in_operational_area(body.location.lat, body.location.lng):
            pass  # local — normal flow
        else:
            fast_drop, fast_drop_location = True, {
                "lat": D(body.location.lat), "lng": D(body.location.lng),
                "label": body.location.label or "GPS location (out of area)",
            }
    elif body.location_text and jurisdiction_hint_from_text(
            f"{body.raw_text} {body.location_text}") == "OUT_OF_DISTRICT":
        fast_drop = True

    if fast_drop:
        item = {
            "id": f"inc_{uuid.uuid4().hex[:10]}",
            "user_id": user.id,
            "status": "NEW",
            "raw_text": body.raw_text,
            "people": body.people,
            "vulnerabilities": body.vulnerabilities,
            "urgency": body.urgency,
            "water_rising": body.water_rising,
            "location_text": body.location_text,
            "location": fast_drop_location,
            "location_verification": "OUT_OF_AREA_TEXT"
            if fast_drop_location is None else "OUT_OF_AREA_GPS",
            "priority": {"score": 0, "band": "LOW",
                         "reasons": ["outside operational district (Rautahat) — "
                                     "dropped at intake, no triage spent"]},
            "created_at": ts,
            "assigned_team": None,
            "mission_id": None,
            "out_of_area": True,
            "run_id": run_id,
        }
        incidents.create_incident(item)
        activity.log_event(
            actor="agent",
            type_="incident_out_of_area",
            summary=f"Incident {item['id']} dropped at intake (out of area, no triage spent)",
            payload={"incident_id": item["id"]},
            run_id=run_id,
        )
        return item

    location = None
    verification = None
    if body.location:
        location = {
            "lat": D(body.location.lat),
            "lng": D(body.location.lng),
            "label": body.location.label or "GPS location",
            "confidence": D(body.location.confidence) if body.location.confidence is not None else None,
        }
        verification = "GPS"
    elif body.location_text:
        geo = await geocode(body.location_text)
        if geo:
            location = {
                "lat": D(geo["lat"]),
                "lng": D(geo["lng"]),
                "label": geo["label"],
                "confidence": D(geo["confidence"]),
            }
            verification = "GEOCODED"
        else:
            # Always plot something: fall back to the reporter's device GPS
            # (heartbeat) so the incident still lands on the map, flagged.
            try:
                owner = users.get_user(user.id) or {}
            except Exception:
                owner = {}
            dev = owner.get("device_location")
            if isinstance(dev, dict) and dev.get("lat") is not None:
                location = {
                    "lat": D(dev["lat"]),
                    "lng": D(dev["lng"]),
                    "label": f"Device GPS — landmark '{body.location_text}' unresolved",
                }
                verification = "NEEDS_COORDINATOR_REVIEW"
            else:
                verification = "NEEDS_COORDINATOR_REVIEW"

    item = {
        "id": f"inc_{uuid.uuid4().hex[:10]}",
        "user_id": user.id,
        "status": "NEW",
        "raw_text": body.raw_text,
        "people": body.people,
        "vulnerabilities": body.vulnerabilities,
        "urgency": body.urgency,
        "water_rising": body.water_rising,
        "location_text": body.location_text,
        "location": location,
        "location_verification": verification,
        "area_geohash": (
            geohash_encode(float(location["lat"]), float(location["lng"]))
            if location
            else None
        ),
        "priority": {"score": 0, "reasons": ["awaiting triage"]},
        "created_at": ts,
        "assigned_team": None,
        "mission_id": None,
        "out_of_area": False,
        "run_id": run_id,
    }
    if location:
        from app.utils.geo import in_operational_area

        if not in_operational_area(location["lat"], location["lng"]):
            item["out_of_area"] = True
    incidents.create_incident(item)

    if item["out_of_area"]:
        # Outside Rautahat: the jurisdiction guard in the priority engine
        # scores 0. Stay NEW and out of the rescue queue. Still logged +
        # visible to the resident + reviewable, never silently dropped.
        item["priority"] = {"score": 0, "band": "LOW",
                            "reasons": ["outside operational district (Rautahat) — "
                                        "routed to review, not the rescue queue"]}
        incidents.update_incident(item["id"], priority=item["priority"],
                                  out_of_area=True)
        activity.log_event(
            actor="agent",
            type_="incident_out_of_area",
            summary=f"Incident {item['id']} outside operational district — routed to review",
            payload={"incident_id": item["id"],
                     "location": {k: str(v) for k, v in (location or {}).items()}},
            run_id=run_id,
        )
        try:
            from app.services import realtime as _rt

            _rt.publish("INCIDENT_CREATED", {"incident": item})
        except Exception:
            pass
        return item

    # Phase 5 normalization (§54): NEW → VERIFIED / UNVERIFIED on location.
    norm_status = "UNVERIFIED" if verification == "NEEDS_COORDINATOR_REVIEW" else "VERIFIED"
    item["status"] = norm_status
    incidents.update_incident(item["id"], status=norm_status)

    # F03: score immediately through the PriorityAgent seam. Best-effort —
    # if no agent runtime is configured the incident keeps "awaiting triage"
    # and the coordinator can still act on it.
    scored = False
    try:
        item["priority"] = await gateway.triage_score(item)
        update = {"priority": item["priority"]}
        # Scored + verified → PRIORITIZED (§54). Unverified stays flagged.
        if norm_status == "VERIFIED":
            update["status"] = "PRIORITIZED"
            item["status"] = "PRIORITIZED"
        incidents.update_incident(item["id"], **update)
        scored = True
        activity.log_event(
            actor="agent",
            type_="priority_scored",
            summary=(
                f"PriorityAgent scored {item['id']}: {item['priority']['score']} "
                f"({item['priority']['band']})"
            ),
            payload={
                "incident_id": item["id"],
                "score": item["priority"]["score"],
                "band": item["priority"]["band"],
            },
            run_id=run_id,
        )
    except gateway.AgentNotConnectedError:
        pass

    if verification == "GEOCODED":
        activity.log_event(
            actor="agent",
            type_="location_identified",
            summary=(
                f"Incident {item['id']} location identified via landmark: "
                f"{location['label']} ({int(float(location['confidence']) * 100)}% confidence)"
            ),
            payload={"incident_id": item["id"]},
            run_id=run_id,
        )
    elif verification == "NEEDS_COORDINATOR_REVIEW":
        activity.log_event(
            actor="agent",
            type_="location_unverified",
            summary=(
                f"Incident {item['id']} location '{body.location_text}' could not be "
                f"resolved Ã¢â‚¬â€ flagged for coordinator verification"
            ),
            payload={"incident_id": item["id"]},
            run_id=run_id,
        )
    activity.log_event(
        actor="system",
        type_="incident_received",
        summary=f"Incident {item['id']} received from {user.name}",
        payload={"incident_id": item["id"]},
        run_id=run_id,
    )
    try:
        from app.services import realtime as _rt

        _rt.publish("INCIDENT_CREATED", {"incident": item})
        _rt.publish("INCIDENT_UPDATED", {"incident": item})
        if scored:
            _rt.publish("INCIDENT_PRIORITY_CHANGED", {"incident": item})
    except Exception:
        pass
    return item


@router.get("/mine")
def my_incidents(user: CurrentUser = Depends(get_current_user)):
    """F13: resident tracks own requests only Ã¢â‚¬â€ enforced server-side."""
    return {"incidents": incidents.list_user_incidents(user.id)}


@router.get("/{incident_id}")
def get_incident(incident_id: str, user: CurrentUser = Depends(get_current_user)):
    item = incidents.get_incident(incident_id)
    if item is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Incident not found")
    # Residents may only read their own incidents; coordinators see all
    if user.role != "coordinator" and item.get("user_id") != user.id:
        raise HTTPException(status_code=403, detail="Not your incident")
    return item
