import asyncio
import logging

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.routers import approvals, auth, area, agents, chat, coordinator_chat, events, incidents, live, map, ops, public, shelters, simulation, users, ws
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
app.include_router(incidents.router)
app.include_router(chat.router)
app.include_router(users.router)
app.include_router(public.router)
app.include_router(ops.router)
app.include_router(ws.router)
app.include_router(coordinator_chat.router)
app.include_router(live.router)
# Phase 1 arch surface (§65) — new canonical prefixes, ops/* kept as shims.
app.include_router(shelters.router)
app.include_router(map.router)
app.include_router(agents.router)
app.include_router(events.router)
app.include_router(simulation.router)
app.include_router(approvals.router)


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

    def _prewarm():
        try:
            from app.services import routing as _routing

            _routing.prewarm_district_graph()
            logger.info("District road graph prewarmed")
        except Exception as exc:
            logger.warning("District prewarm failed: %r", exc)

    import threading

    threading.Thread(target=_prewarm, daemon=True).start()


# Serve built frontend if available (unified Docker/Hugging Face/Render deployment)
import pathlib
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

_static_candidates = [
    pathlib.Path(__file__).resolve().parent.parent / "static",
    pathlib.Path(__file__).resolve().parents[2] / "frontend" / "dist",
]
_static_dir = next((p for p in _static_candidates if p.is_dir()), None)

if _static_dir:
    _assets_dir = _static_dir / "assets"
    if _assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="assets")

    @app.get("/{full_path:path}")
    async def _serve_frontend(full_path: str):
        if full_path.startswith("api") or full_path.startswith("ws"):
            return JSONResponse(status_code=404, content={"detail": "Not found"})
        target = _static_dir / full_path
        if full_path and target.is_file():
            return FileResponse(target)
        return FileResponse(_static_dir / "index.html")

