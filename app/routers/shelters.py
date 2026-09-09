"""Phase 1 shelters API — arch §65. Canonical shelter CRUD without AI."""

from fastapi import APIRouter, Depends, HTTPException

from app.auth.deps import get_current_user, require_role
from app.db.repos import activity, shelters
from app.models import ShelterOccupancyUpdate
from app.services import realtime

router = APIRouter(prefix="/api/shelters", tags=["shelters"])


@router.get("")
def list_shelters(_=Depends(get_current_user)):
    return {"shelters": shelters.list_shelters()}


@router.get("/{shelter_id}")
def get_shelter(shelter_id: str, _=Depends(get_current_user)):
    item = shelters.get_shelter(shelter_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Shelter not found")
    return item


@router.patch("/{shelter_id}/occupancy")
def set_occupancy(shelter_id: str, body: ShelterOccupancyUpdate,
                  _=Depends(require_role("coordinator"))):
    from app.services import world_sync

    try:
        out = world_sync.apply_shelter_occupancy(
            shelter_id, body.current_occupancy, source="COORDINATOR")
    except LookupError:
        raise HTTPException(status_code=404, detail="Shelter not found")
    item = out["shelter"]
    activity.log_event(actor="human", type_="shelter_occupancy_updated",
                       summary=f"Shelter {shelter_id} occupancy -> {body.current_occupancy}",
                       payload={"shelter_id": shelter_id})
    return item
