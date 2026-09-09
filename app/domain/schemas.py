"""Phase 0 frozen domain schemas — arch §34, §52-55.

Database-agnostic. DynamoDB is the current store; PostgreSQL/PostGIS is the
evaluated option for spatial-heavy work (§34). Domain code must not import
boto3/dynamodb — repos own persistence.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# --- Shared primitives ---

Lat = Field(ge=-90, le=90)
Lng = Field(ge=-180, le=180)


class GeoPoint(BaseModel):
    lat: float = Lat
    lng: float = Lng
    label: str = ""
    confidence: float | None = Field(default=None, ge=0, le=1)


# Mission lifecycle §53
MissionStatus = Literal[
    "PROPOSED", "AWAITING_APPROVAL", "APPROVED", "DISPATCHED",
    "EN_ROUTE", "ON_SCENE", "COMPLETED",
    "REJECTED", "CANCELLED", "BLOCKED", "REPLANNING", "FAILED",
]

# Incident lifecycle §54
IncidentStatus = Literal[
    "NEW", "VERIFIED", "PRIORITIZED", "AWAITING_ASSIGNMENT",
    "ASSIGNED", "IN_PROGRESS", "RESCUED", "RESOLVED",
    "DUPLICATE", "UNVERIFIED", "ESCALATED", "REOPENED",
]

# Team availability §52 — SOFT_RESERVED prevents double-recommend races
TeamStatus = Literal[
    "AVAILABLE", "SOFT_RESERVED", "APPROVED", "ASSIGNED",
    "ON_MISSION", "RETURNING", "UNAVAILABLE", "OFFLINE",
]

PriorityBand = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]


# --- §34.1 logical entities ---

class User(BaseModel):
    id: str
    phone: str
    name: str
    role: Literal["resident", "coordinator"]


class ResidentProfile(BaseModel):
    user_id: str
    location_text: str | None = None
    location: GeoPoint | None = None
    people_with: int | None = None
    vulnerabilities: list[str] = []
    status: Literal["SAFE", "NEEDS_HELP", "TRAPPED", "EVACUATED"] | None = None


class Incident(BaseModel):
    id: str
    raw_text: str
    user_id: str | None = None
    people: int = 1
    vulnerabilities: list[str] = []
    urgency: Literal["LOW", "MEDIUM", "HIGH"] | None = None
    water_rising: bool = False
    location_text: str | None = None
    location: GeoPoint | None = None
    location_verification: Literal["STATED_GEOCODED", "NEEDS_COORDINATOR_REVIEW"] | None = None
    status: IncidentStatus = "NEW"
    priority_score: float | None = None
    priority_band: PriorityBand | None = None
    assigned_team: str | None = None
    mission_id: str | None = None
    created_at: int = 0


class IncidentUpdate(BaseModel):
    incident_id: str
    actor: str
    message: str
    ts: int


class Team(BaseModel):
    id: str
    name: str
    capacity: int
    status: TeamStatus = "AVAILABLE"
    location: GeoPoint | None = None
    current_mission_id: str | None = None
    contact: str = ""
    specialization: str = ""


class TeamTelemetry(BaseModel):
    team_id: str
    location: GeoPoint
    timestamp: int
    status: TeamStatus


class Mission(BaseModel):
    id: str
    incident_id: str
    team_id: str
    status: MissionStatus = "PROPOSED"
    route_id: str | None = None
    pending_action_id: str | None = None


class Shelter(BaseModel):
    id: str
    name: str
    location: GeoPoint | None = None
    capacity: int = 0
    current_occupancy: int = 0
    status: Literal["OPEN", "FULL", "CLOSED"] = "OPEN"


class Road(BaseModel):
    id: str
    name: str = ""
    status: Literal["OPEN", "BLOCKED", "RESTRICTED", "DAMAGED"] = "OPEN"


class Bridge(BaseModel):
    id: str
    name: str = ""
    status: Literal["OPEN", "RESTRICTED", "DAMAGED", "COLLAPSED"] = "OPEN"


class HazardZone(BaseModel):
    id: str
    area_id: str = ""
    level: Literal["SAFE", "WATCH", "RISING", "UNSAFE", "HOTSPOT"] = "WATCH"
    source: str = ""


class WaterObservation(BaseModel):
    area_id: str
    level_m: float | None = None
    trend: Literal["RISING", "STABLE", "FALLING"] | None = None
    timestamp: int = 0


class WeatherObservation(BaseModel):
    area_id: str
    rainfall_mm: float | None = None
    summary: str = ""
    timestamp: int = 0


class OperationalEvent(BaseModel):
    id: str
    type: str
    source: str
    timestamp: int
    entity_id: str | None = None
    payload: dict = {}
    correlation_id: str | None = None


class AgentRecommendation(BaseModel):
    id: str
    incident_id: str | None = None
    team_id: str | None = None
    route_id: str | None = None
    reasons: list[str] = []
    requires_human_approval: bool = True


class HumanDecision(BaseModel):
    recommendation_id: str
    decision: Literal["APPROVED", "REJECTED", "MODIFIED"]
    coordinator_id: str
    note: str = ""


class AuditEntry(BaseModel):
    id: str
    actor: str
    type: str
    summary: str
    timestamp: int
    payload: dict = {}
