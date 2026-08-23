from fastapi import APIRouter, Depends, HTTPException

from app.auth.deps import CurrentUser, get_current_user
from app.db.repos import areas, guides, incidents, reports, shelters

router = APIRouter(prefix="/api/public", tags=["public"])

# Resident-facing projection (BRAINSTORM §4.4): shelters + OWN incident +
# coarse area risk. Teams and other people's incidents are never here —
# the split is enforced server-side, not by hiding frontend layers.


@router.get("/map-data")
def map_data(user: CurrentUser = Depends(get_current_user)):
    mine = incidents.list_user_incidents(user.id)
    my_open = next(
        (i for i in mine if i.get("status") in incidents.OPEN_STATUSES), None
    )
    return {
        "shelters": shelters.list_shelters(),
        "my_incident": my_open,
        "areas": areas.list_areas(),
    }


@router.get("/reports")
def gov_reports(user: CurrentUser = Depends(get_current_user)):
    """Official advisories/notices for residents — newest first."""
    return {"reports": reports.list_reports()}


@router.get("/guides")
def list_guides(category: str | None = None, language: str | None = None):
    """Preparedness / survival guides. Optional ?category=before|during|
    after|health|kit and ?language=en|hi filters."""
    items = guides.list_guides(category)
    if language:
        items = [g for g in items if g.get("language") == language]
    return {"guides": items}


@router.get("/guides/{guide_id}")
def get_guide(guide_id: str):
    item = guides.get_guide(guide_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Guide not found")
    return item
