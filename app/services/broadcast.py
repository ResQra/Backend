import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self._connections: set[WebSocket] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._snapshot_fn = None

    def set_event_loop(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    def set_snapshot_fn(self, fn):
        self._snapshot_fn = fn

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self._connections.add(websocket)
        logger.info("WebSocket connected — total: %d", len(self._connections))

    async def disconnect(self, websocket: WebSocket):
        self._connections.discard(websocket)
        logger.info("WebSocket disconnected — total: %d", len(self._connections))

    async def broadcast(self, event_type: str, data: Any):
        message = json.dumps({"type": event_type, "data": data}, default=str)
        stale: list[WebSocket] = []
        for ws in list(self._connections):
            try:
                await ws.send_text(message)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self._connections.discard(ws)

    def fire_and_forget(self, event_type: str, data: Any):
        """Thread-safe fire-and-forget for use from sync handlers."""
        if self._loop is None or self._loop.is_closed():
            return
        self._loop.call_soon_threadsafe(
            asyncio.ensure_future, self.broadcast(event_type, data)
        )

    def get_snapshot(self) -> dict:
        if self._snapshot_fn:
            return self._snapshot_fn()
        return {}


manager = ConnectionManager()
