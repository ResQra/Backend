"""Phase 3 realtime gateway — arch §36-37.

Single broadcast surface. All emits use canonical §36 UPPER_SNAKE types
(all publishers migrated; the Phase-3 legacy dual-emit map was removed
after proving zero legacy publishes remain). Envelope: {type, data, ts}.
"""

from __future__ import annotations

from typing import Any

from app.services.broadcast import manager

CANONICAL = set([
    "INCIDENT_CREATED", "INCIDENT_UPDATED", "INCIDENT_PRIORITY_CHANGED",
    "TEAM_LOCATION_UPDATED", "TEAM_STATUS_CHANGED",
    "MISSION_CREATED", "MISSION_UPDATED",
    "WATER_LEVEL_CHANGED", "FLOOD_ZONE_CHANGED",
    "ROAD_BLOCKED", "BRIDGE_DAMAGED",
    "SHELTER_CAPACITY_CHANGED",
    "COMMUNICATION_LOST", "COMMUNICATION_RESTORED",
    "AGENT_RECOMMENDATION_CREATED",
    "HUMAN_APPROVAL", "HUMAN_REJECTION",
    "RESIDENT_UPDATED", "SCENARIO_RESET",
])


def publish(event_type: str, data: Any) -> None:
    """Fire-and-forget broadcast safe from sync handlers."""
    manager.fire_and_forget(event_type, data)


def snapshot() -> dict:
    return manager.get_snapshot()
