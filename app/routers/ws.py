import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services.broadcast import manager

logger = logging.getLogger(__name__)

router = APIRouter()


async def _heartbeat(ws: WebSocket):
    try:
        while True:
            await asyncio.sleep(30)
            await ws.send_json({"type": "ping"})
    except Exception:
        pass


@router.websocket("/ws/ops")
async def ops_websocket(websocket: WebSocket):
    # Coordinator-only: same token-query pattern as /api/ops/assistant/live.
    # Browsers can't set WS headers, so token comes via ?token=.
    qp = websocket.query_params
    token = qp.get("token")
    if token:
        from app.routers.live import _auth_ws as _live_auth

        if _live_auth(token) is None:
            await websocket.close(code=4401)
            return
    await manager.connect(websocket)
    try:
        try:
            snapshot = manager.get_snapshot()
        except Exception:
            logger.exception("ops snapshot failed — sending empty baseline")
            snapshot = {"incidents": [], "teams": [], "sensor_events": []}
        # Plain json: Dynamo Decimals need explicit conversion (HTTP
        # responses get FastAPI's encoder; sockets don't — raw Decimals
        # used to crash this handler and silently kill live updates).
        from app.db.client import dynamo_to_json

        await websocket.send_text(json.dumps(
            {"type": "snapshot", "data": dynamo_to_json(snapshot)}))

        heartbeat = asyncio.create_task(_heartbeat(websocket))
        try:
            while True:
                data = await websocket.receive_text()
                if data == "pong":
                    continue
                try:
                    msg = json.loads(data)
                    if msg.get("type") == "ping":
                        await websocket.send_json({"type": "pong"})
                    elif msg.get("type") == "pong":
                        continue
                except json.JSONDecodeError:
                    pass
        finally:
            heartbeat.cancel()
            try:
                await heartbeat
            except asyncio.CancelledError:
                pass
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(websocket)
