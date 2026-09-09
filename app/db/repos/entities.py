"""Phase 1 generic entity repos — arch §34.1.

Thin DynamoDB wrappers. ActivityEvent remains the audit ledger (§56);
OperationalEvents mirrors domain events for queryability.
"""

from __future__ import annotations

from app.db.client import table


def _repo(table_name: str):
    def put(item: dict) -> dict:
        table(table_name).put_item(Item=item)
        return item

    def get(item_id: str) -> dict | None:
        return table(table_name).get_item(Key={"id": item_id}).get("Item")

    def list_all(limit: int = 200) -> list[dict]:
        return table(table_name).scan(Limit=limit).get("Items", [])

    return put, get, list_all


put_road, get_road, list_roads = _repo("Roads")
put_bridge, get_bridge, list_bridges = _repo("Bridges")
put_hazard, get_hazard, list_hazards = _repo("HazardZones")
put_water, get_water, list_water = _repo("WaterObservations")
put_weather, get_weather, list_weather = _repo("WeatherObservations")
put_operational_event, get_operational_event, list_operational_events = _repo("OperationalEvents")
put_recommendation, get_recommendation, list_recommendations = _repo("AgentRecommendations")
put_decision, get_decision, list_decisions = _repo("HumanDecisions")
