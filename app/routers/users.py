from fastapi import APIRouter, Depends

from app.auth.deps import CurrentUser, get_current_user
from app.db.repos import users
from app.models import LocationIn

router = APIRouter(prefix="/api/users", tags=["users"])


@router.patch("/me/location")
def update_location(body: LocationIn, user: CurrentUser = Depends(get_current_user)):
    """Location heartbeat for the resident app: it PUTs the device GPS every
    ~30 min. Writes to `device_location` — the agent-extracted `location`
    (what the person SAID, F19) is never overwritten by it."""
    item = users.update_device_location(user.id, body.lat, body.lng, body.label)
    return item
