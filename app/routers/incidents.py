import time
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends

from app.auth.deps import CurrentUser, get_current_user
from app.db.repos import activity, incidents, users
from app.models import IncidentCreate
from app.utils.geo import geohash_encode
from app.utils.geocode import geocode


def D(x) -> Decimal:
    """DynamoDB rejects float — coordinates must be Decimal."""
    return Decimal(str(x))


router = APIRouter(prefix="/api/incidents", tags=["incidents"])


@router.post("")
async def create_incident(body: IncidentCreate, user: CurrentUser = Depends(get_current_user)):
    """F01 entry point: raw distress text (optionally pre-structured) →
    incident with status NEW. Location priority: exact GPS if provided,
    else geocode the landmark text (OSM Nominatim, free); if neither
    yields coordinates the incident is flagged NEEDS_COORDINATOR_REVIEW
    (F02 — never guess). The TriageAgent scores it afterwards via its seam."""
    ts = Decimal(str(time.time()))

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
    }
    incidents.create_incident(item)

    if verification == "GEOCODED":
        activity.log_event(
            actor="agent",
            type_="location_identified",
            summary=(
                f"Incident {item['id']} location identified via landmark: "
                f"{location['label']} ({int(float(location['confidence']) * 100)}% confidence)"
            ),
            payload={"incident_id": item["id"]},
        )
    elif verification == "NEEDS_COORDINATOR_REVIEW":
        activity.log_event(
            actor="agent",
            type_="location_unverified",
            summary=(
                f"Incident {item['id']} location '{body.location_text}' could not be "
                f"resolved — flagged for coordinator verification"
            ),
            payload={"incident_id": item["id"]},
        )
    activity.log_event(
        actor="system",
        type_="incident_received",
        summary=f"Incident {item['id']} received from {user.name}",
        payload={"incident_id": item["id"]},
    )
    return item


@router.get("/mine")
def my_incidents(user: CurrentUser = Depends(get_current_user)):
    """F13: resident tracks own requests only — enforced server-side."""
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
