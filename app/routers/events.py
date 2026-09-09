"""Phase 1 events API Ã¢â‚¬â€ arch Ã‚Â§36-37. Poll + SSE over the audit ledger."""

import asyncio
import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.auth.deps import get_current_user
from app.db.repos import activity

router = APIRouter(prefix="/api/events", tags=["events"])


@router.get("")
def list_events(limit: int = 50, _=Depends(get_current_user)):
    return {"events": activity.recent_events(limit)}


@router.get("/stream")
async def stream(_=Depends(get_current_user)):
    """SSE fallback for clients without WebSocket (arch §37)."""

    async def gen():
        seen: set[str] = set()
        for _ in range(30):
            for ev in activity.recent_events(20):
                eid = str(ev.get("id"))
                if eid not in seen:
                    seen.add(eid)
                    yield f"data: {json.dumps(ev, default=str)}\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(gen(), media_type="text/event-stream")
