from typing import Literal

from pydantic import BaseModel, Field


# --- Auth ---

class OtpRequest(BaseModel):
    phone: str = Field(min_length=8, max_length=15)
    name: str = Field(min_length=1, max_length=80)


class OtpVerify(BaseModel):
    phone: str = Field(min_length=8, max_length=15)
    code: str = Field(min_length=4, max_length=8)
    name: str | None = Field(default=None, max_length=80)  # carried from step 1


class AdminLogin(BaseModel):
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=6, max_length=128)


class PasswordChange(BaseModel):
    old_password: str
    new_password: str = Field(min_length=6, max_length=128)


class PhoneChange(BaseModel):
    new_phone: str = Field(min_length=8, max_length=15)


class TokenResponse(BaseModel):
    token: str
    user_id: str
    role: str
    name: str | None = None  # display name (admins: "Control Room", etc.)


class MeResponse(BaseModel):
    id: str
    phone: str
    name: str
    role: str


# --- Incidents ---

class LocationIn(BaseModel):
    lat: float
    lng: float
    label: str = ""
    confidence: float | None = None  # 0..1 from the IntakeAgent geocoder


class IncidentCreate(BaseModel):
    raw_text: str = Field(min_length=3, max_length=2000)
    people: int | None = None
    vulnerabilities: list[str] = []
    urgency: Literal["LOW", "MEDIUM", "HIGH"] | None = None
    water_rising: bool | None = None
    location: LocationIn | None = None  # set later by IntakeAgent geocoding
    location_text: str | None = None
    run_id: str = Field(default="", max_length=64)  # Phase A: simulation-run provenance


class StatusUpdate(BaseModel):
    status: Literal[
        "NEW", "UNVERIFIED", "VERIFIED", "PRIORITIZED", "AWAITING_ASSIGNMENT",
        "ASSIGNED", "IN_PROGRESS", "RESCUED", "RESOLVED",
        "DUPLICATE", "ESCALATED", "REOPENED",
    ]


class AssignRequest(BaseModel):
    team_id: str


class ApprovalDecision(BaseModel):
    decision: Literal["APPROVED", "REJECTED"]
    note: str = Field(default="", max_length=500)
    override_team_id: str | None = None


class TeamCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    capacity: int = Field(ge=1, le=500)
    status: Literal["AVAILABLE", "ON_MISSION", "RETURNING", "OFFLINE", "UNAVAILABLE"] = "AVAILABLE"
    location: LocationIn | None = None
    contact: str = Field(default="", max_length=80)
    specialization: str = Field(default="", max_length=120)
    notes: str = Field(default="", max_length=500)
    district: str = Field(default="rautahat", max_length=40)


class TeamStatusUpdate(BaseModel):
    status: Literal["AVAILABLE", "SOFT_RESERVED", "ON_MISSION", "RETURNING", "UNAVAILABLE", "OFFLINE"]


class TeamLocationUpdate(BaseModel):
    lat: float
    lng: float
    label: str = ""
    source: Literal["TEAM", "SIMULATION", "COORDINATOR"] = "TEAM"


class TeamProblemReport(BaseModel):
    message: str = Field(min_length=3, max_length=1000)
    severity: Literal["INFO", "WARNING", "BLOCKED", "OFFLINE"] = "WARNING"
    lat: float | None = None
    lng: float | None = None


class SensorEventCreate(BaseModel):
    kind: Literal["WATER_LEVEL", "ROAD_BLOCKED", "BRIDGE_BLOCKED", "PEOPLE_DENSITY", "FLOOD_AREA"]
    lat: float
    lng: float
    value: float | None = None
    level: Literal["SAFE", "WATCH", "RISING", "UNSAFE", "HOTSPOT"] = "RISING"
    note: str = Field(default="", max_length=1000)
    source_priority: Literal["SIMULATION", "TEAM", "PUBLIC_API"] = "SIMULATION"
    idempotency_key: str | None = None


class ShelterOccupancyUpdate(BaseModel):
    current_occupancy: int = Field(ge=0)
    source: Literal["SIMULATION", "COORDINATOR", "TEAM"] = "COORDINATOR"


# --- Chat ---

class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class ChatMessageOut(BaseModel):
    role: str
    content: str
    ts: float


# --- Gov reports / advisories ---

class ReportCreate(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=3, max_length=5000)
    severity: Literal["INFO", "WARNING", "CRITICAL"] = "INFO"
    source: str = Field(default="", max_length=200)  # e.g. "District Administration, Patna"
    area_text: str | None = None  # e.g. "Kankarbagh, Patna" — areas affected
    link: str | None = None
