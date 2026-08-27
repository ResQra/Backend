import asyncio
import logging

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.routers import auth, area, chat, disasters, incidents, ops, public, users, ws
from app.services.broadcast import manager as broadcast_manager

logger = logging.getLogger(__name__)

app = FastAPI(
    title="ResQra API",
    description="Flood emergency response backend — API layer only; "
    "Strands agents plug in via app/agents_gateway/gateway.py",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(BotoCoreError)
@app.exception_handler(ClientError)
async def db_unavailable(request: Request, exc: Exception):
    return JSONResponse(
        status_code=503,
        content={
            "detail": "Database unavailable — check AWS credentials, or set "
            "DYNAMODB_ENDPOINT_URL for DynamoDB Local"
        },
    )


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "resqra-api"}


app.include_router(auth.router)
app.include_router(area.router)
app.include_router(disasters.router)
app.include_router(incidents.router)
app.include_router(chat.router)
app.include_router(users.router)
app.include_router(public.router)
app.include_router(ops.router)
app.include_router(ws.router)


@app.on_event("startup")
async def on_startup():
    broadcast_manager.set_event_loop(asyncio.get_running_loop())

    def _snapshot():
        from app.db.repos import incidents, teams, simulation_events

        return {
            "incidents": incidents.list_open_incidents(),
            "teams": teams.list_teams(),
            "sensor_events": simulation_events.list_by_type("WATER_LEVEL", limit=10)
            + simulation_events.list_by_type("ROAD_BLOCKED", limit=10)
            + simulation_events.list_by_type("BRIDGE_BLOCKED", limit=10)
            + simulation_events.list_by_type("PEOPLE_DENSITY", limit=10)
            + simulation_events.list_by_type("FLOOD_AREA", limit=10),
        }

    broadcast_manager.set_snapshot_fn(_snapshot)
    logger.info("WebSocket endpoint available at /ws/ops")
