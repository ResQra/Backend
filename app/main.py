from botocore.exceptions import BotoCoreError, ClientError
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.routers import auth, chat, incidents, ops, public, users

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
app.include_router(incidents.router)
app.include_router(chat.router)
app.include_router(users.router)
app.include_router(public.router)
app.include_router(ops.router)
