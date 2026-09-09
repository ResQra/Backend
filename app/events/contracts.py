"""Phase 0 frozen event contracts — arch §24, §36, §64.

Two layers, one envelope:
- Operational events (§36): what happened in the world / system.
- Simulation events (§24.1): judge-controlled mutations that write the SAME
  world state with source=DEMO_SIMULATOR + scenario/run provenance (§64).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# §36 operational event types
OperationalEventType = Literal[
    "INCIDENT_CREATED", "INCIDENT_UPDATED", "INCIDENT_PRIORITY_CHANGED",
    "TEAM_LOCATION_UPDATED", "TEAM_STATUS_CHANGED",
    "MISSION_CREATED", "MISSION_UPDATED",
    "WATER_LEVEL_CHANGED", "FLOOD_ZONE_CHANGED",
    "ROAD_BLOCKED", "BRIDGE_DAMAGED",
    "SHELTER_CAPACITY_CHANGED",
    "COMMUNICATION_LOST", "COMMUNICATION_RESTORED",
    "AGENT_RECOMMENDATION_CREATED",
    "HUMAN_APPROVAL", "HUMAN_REJECTION",
]

# §24.1 simulation catalog — the ONLY judge-mutable surface (Phase 9)
SimulationEventType = Literal[
    "NEW_INCIDENT",
    "TEAM_LOCATION_UPDATED",
    "TEAM_STATUS_CHANGED",
    "COMMUNICATION_LOST",
    "WATER_LEVEL_UPDATED",
    "FLASH_FLOOD",
    "ROAD_BLOCKED",
    "BRIDGE_DAMAGED",
    "SHELTER_STATUS_CHANGED",
    "MISSION_UPDATED",
]


class EventEnvelope(BaseModel):
    """Shared envelope for §36 operational events."""

    id: str
    type: str
    source: Literal["RESIDENT", "TEAM", "SIMULATION", "AGENT", "COORDINATOR", "SYSTEM"]
    timestamp: int
    entity_id: str | None = None
    payload: dict = {}
    correlation_id: str | None = None


class SimulationEvent(BaseModel):
    """Unified simulation contract §24. Demo client POSTs this; backend applies
    it to canonical world state, then fans out to agents + realtime gateway."""

    event_id: str = Field(default="")
    type: SimulationEventType
    target: dict = Field(default_factory=dict)  # {"type": "AREA"|"TEAM"|..., "id": ...}
    parameters: dict = Field(default_factory=dict)
    timestamp: int = 0
    source: Literal["DEMO_SIMULATOR"] = "DEMO_SIMULATOR"
    scenario_id: str = "flood-escalation-01"
    run_id: str = ""
