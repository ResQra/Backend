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
    await manager.connect(websocket)
    try:
        snapshot = manager.get_snapshot()
        await websocket.send_json({"type": "snapshot", "data": snapshot})

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
                except json.JSONDecodeError:
                    pass
        finally:
            heartbeat.cancel()
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(websocket)
