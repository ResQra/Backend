import asyncio
import json
import logging
import time
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
        from app.db.client import dynamo_to_json

        # Dynamo Decimals -> real JSON numbers (default=str used to turn
        # live coordinates into strings and silently break map markers).
        message = json.dumps(
            {"type": event_type, "data": dynamo_to_json(data),
             "ts": int(time.time() * 1000)},
        )
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
            logger.warning("broadcast dropped (no loop): %s", event_type)
            return
        try:
            coro = self.broadcast(event_type, data)
            fut = asyncio.run_coroutine_threadsafe(coro, self._loop)

            def _done(f):
                try:
                    f.result()
                except Exception:
                    logger.exception("broadcast failed: %s", event_type)

            fut.add_done_callback(_done)
        except Exception:
            logger.exception("broadcast schedule failed: %s", event_type)

    def send_to_all(self, event_type: str, data: Any = None):
        """Compat alias — gateway legacy call was send_to_all(dict)."""
        if isinstance(event_type, dict) and data is None:
            payload = event_type
            etype = payload.get("event", "RESIDENT_UPDATED")
            self.fire_and_forget(etype, payload)
            return
        self.fire_and_forget(event_type, data)

    def get_snapshot(self) -> dict:
        if self._snapshot_fn:
            return self._snapshot_fn()
        return {}


manager = ConnectionManager()
