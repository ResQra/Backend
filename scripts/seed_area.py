"""Area-agnostic seed script: seeds demo data for ANY region.

Usage:
    python backend/scripts/seed_area.py --area patna
    python backend/scripts/seed_area.py --lat 25.59 --lng 85.14 --radius 0.05
    python backend/scripts/seed_area.py --area kathmandu --radius 0.03

Run scripts/create_tables.py first.
"""

import argparse
import random
import sys
import time
import uuid
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import boto3  # noqa: E402
from app.db.client import dynamo_kwargs  # noqa: E402

PRESETS = {
    "patna":     (25.5941, 85.1376),
    "kathmandu": (27.7172, 85.3240),
    "guwahati":  (26.1445, 91.7362),
    "mumbai":    (19.0760, 72.8777),
    "chennai":   (13.0827, 80.2707),
}

TABLES = [
    "Users", "OtpCodes", "ChatHistory", "Incidents", "Teams",
    "Missions", "Shelters", "ActivityEvent", "AreaRisk",
    "GovReports", "Guides", "PendingActions", "SimulationEvents",
]

TEAM_NAMES = [
    "ALPHA", "BETA", "GAMMA", "DELTA", "EPSILON", "ZETA",
]

TEAM_STATUSES = ["AVAILABLE", "AVAILABLE", "AVAILABLE", "ON_MISSION", "RETURNING", "OFFLINE"]

SHELTER_NAMES = [
    "Govt Primary School, {area}",
    "Community Hall, {area}",
    "Sports Ground, {area}",
    "Municipal Office, {area}",
    "Temple Grounds, {area}",
    "College Campus, {area}",
]

SOS_MESSAGES = [
    "Help! Water rising fast, family of 5 stuck on rooftop",
    "मेरे घर में पानी घुस गया है, कृपया मदद करें",
    "Road collapsed near our house, can't get out",
    "Flood water up to first floor, elderly parents need help",
    "बाढ़ आ गई है, बच्चे बहुत डरे हुए हैं",
    "Stuck in traffic on flyover, water surrounding car",
    "Need immediate rescue - 3 kids and 2 elderly",
    "Bridge is breaking, people stranded on both sides",
    "हम पानी में फंसे हैं, कृपया जल्दी आएं",
    "Building looks unstable, should we evacuate?",
    "Can't reach hospital, roads are all flooded",
    "Electric pole fell in water, very dangerous",
    "Water supply contaminated, need clean water urgently",
    "Multiple families stranded at community center roof",
    "भूस्खलन हुआ है, रास्ता बंद है",
]

SENSOR_EVENT_TYPES = [
    ("WATER_LEVEL", lambda c, r: {
        "water_level_m": D(round(random.uniform(0.5, 4.0), 2)),
        "trend": random.choice(["rising", "stable", "falling"]),
    }),
    ("ROAD_BLOCKED", lambda c, r: {
        "road_name": f"Main Road-{random.randint(1,20)}",
        "block_type": random.choice(["flood", "debris", "collapse"]),
        "severity": random.choice(["PARTIAL", "FULL"]),
    }),
    ("BRIDGE_BLOCKED", lambda c, r: {
        "bridge_id": f"BRG-{random.randint(100,999)}",
        "block_type": random.choice(["structural_damage", "flood_submerged"]),
    }),
    ("PEOPLE_DENSITY", lambda c, r: {
        "count": D(random.randint(50, 500)),
        "zone": random.choice(["evacuation_zone", "shelter_area", "road"]),
    }),
    ("FLOOD_AREA", lambda c, r: {
        "area_sq_km": D(round(random.uniform(0.1, 5.0), 2)),
        "depth_m": D(round(random.uniform(0.3, 3.0), 2)),
    }),
]

INCIDENT_STATUSES = ["NEW", "NEW", "NEW", "VERIFIED", "VERIFIED", "PRIORITIZED", "ASSIGNED", "IN_PROGRESS", "RESCUED", "RESOLVED"]


def D(x: float) -> Decimal:
    return Decimal(str(x))


def jitter(lat: float, lng: float, radius: float) -> tuple[float, float]:
    return (
        lat + random.uniform(-radius, radius),
        lng + random.uniform(-radius, radius),
    )


def ensure_tables():
    dynamodb = boto3.resource("dynamodb", **dynamo_kwargs())
    existing = {t.name for t in dynamodb.tables.all()}
    for name in TABLES:
        if name not in existing:
            print(f"  creating table {name}...")
            table_def = _get_table_schema(name)
            dynamodb.create_table(**table_def)
    print("  tables ready")


def _get_table_schema(name: str):
    from app.db.tables import TABLES as DB_TABLES
    spec = DB_TABLES[name]
    return {
        "TableName": name,
        "KeySchema": spec["KeySchema"],
        "AttributeDefinitions": spec["AttributeDefinitions"],
        "BillingMode": "PAY_PER_REQUEST",
        **({"GlobalSecondaryIndexes": spec["GlobalSecondaryIndexes"]}
           if "GlobalSecondaryIndexes" in spec else {}),
    }


def seed_teams(table_resource, center_lat: float, center_lng: float, radius: float) -> list[str]:
    team_ids = []
    for i, (name, status) in enumerate(zip(TEAM_NAMES, TEAM_STATUSES)):
        tid = f"team_{name.lower()}"
        lat, lng = jitter(center_lat, center_lng, radius)
        item = {
            "id": tid,
            "name": f"TEAM {name}",
            "location": {"lat": D(lat), "lng": D(lng)},
            "capacity": random.randint(4, 15),
            "status": status,
            "current_mission_id": None,
            "rescued_total": random.randint(0, 30),
            "updated_at": int(time.time() * 1000),
        }
        table_resource.put_item(Item=item)
        team_ids.append(tid)
        print(f"  + team {name} ({lat:.4f}, {lng:.4f})")
    return team_ids


def seed_shelters(table_resource, center_lat: float, center_lng: float, radius: float) -> list[str]:
    shelter_ids = []
    for i in range(6):
        sid = f"shelter_{i+1}"
        lat, lng = jitter(center_lat, center_lng, radius)
        cap = random.choice([250, 300, 350, 400, 500, 600, 800])
        occ = random.randint(0, int(cap * 0.7))
        item = {
            "id": sid,
            "name": SHELTER_NAMES[i].format(area=f"Zone-{i+1}"),
            "location": {"lat": D(lat), "lng": D(lng)},
            "capacity": cap,
            "current_occupancy": occ,
            "updated_at": int(time.time() * 1000),
        }
        table_resource.put_item(Item=item)
        shelter_ids.append(sid)
        print(f"  + shelter Zone-{i+1} ({lat:.4f}, {lng:.4f})")
    return shelter_ids


def seed_incidents(table_resource, center_lat: float, center_lng: float, radius: float):
    count = random.randint(10, 15)
    for i in range(count):
        lat, lng = jitter(center_lat, center_lng, radius)
        now_ms = int(time.time() * 1000)
        item = {
            "id": f"inc_{uuid.uuid4().hex[:12]}",
            "user_id": f"user_{random.randint(1000,9999)}",
            "message": random.choice(SOS_MESSAGES),
            "location": {"lat": D(lat), "lng": D(lng)},
            "status": random.choice(INCIDENT_STATUSES),
            "priority": {
                "score": D(round(random.uniform(0.1, 9.9), 2)),
                "level": random.choice(["LOW", "MEDIUM", "HIGH", "CRITICAL"]),
            },
            "created_at": now_ms,
            "updated_at": now_ms,
        }
        table_resource.put_item(Item=item)
    print(f"  + {count} incidents")


def seed_sensor_events(table_resource, center_lat: float, center_lng: float, radius: float):
    count = random.randint(5, 10)
    for i in range(count):
        lat, lng = jitter(center_lat, center_lng, radius)
        evt_type, payload_fn = random.choice(SENSOR_EVENT_TYPES)
        key = f"sensor_{evt_type.lower()}_{uuid.uuid4().hex[:8]}"
        payload = payload_fn((center_lat, center_lng), radius)
        payload["source_priority"] = "SIMULATION"
        payload["location"] = {"lat": D(lat), "lng": D(lng)}
        item = {
            "idempotency_key": key,
            "event_type": evt_type,
            "payload": payload,
            "created_at": int(time.time() * 1000),
            "source_priority": "SIMULATION",
        }
        table_resource.put_item(Item=item)
    print(f"  + {count} sensor events")


def main():
    parser = argparse.ArgumentParser(description="Seed demo data for any region")
    parser.add_argument("--area", choices=list(PRESETS.keys()), help="Preset area name")
    parser.add_argument("--lat", type=float, help="Center latitude")
    parser.add_argument("--lng", type=float, help="Center longitude")
    parser.add_argument("--radius", type=float, default=0.05, help="Scatter radius (default 0.05)")
    args = parser.parse_args()

    if args.area:
        center_lat, center_lng = PRESETS[args.area]
        area_label = args.area.title()
    elif args.lat is not None and args.lng is not None:
        center_lat, center_lng = args.lat, args.lng
        area_label = f"custom({center_lat},{center_lng})"
    else:
        parser.error("Provide --area <name> or --lat and --lng")
        return

    radius = args.radius

    print(f"Seeding demo data for {area_label} (center {center_lat}, {center_lng}, radius {radius})...")
    ensure_tables()

    dynamodb = boto3.resource("dynamodb", **dynamo_kwargs())

    print("Seeding teams...")
    seed_teams(dynamodb.Table("Teams"), center_lat, center_lng, radius)

    print("Seeding shelters...")
    seed_shelters(dynamodb.Table("Shelters"), center_lat, center_lng, radius)

    print("Seeding incidents...")
    seed_incidents(dynamodb.Table("Incidents"), center_lat, center_lng, radius)

    print("Seeding sensor events...")
    seed_sensor_events(dynamodb.Table("SimulationEvents"), center_lat, center_lng, radius)

    print(f"Done! Seeded data for {area_label}.")


if __name__ == "__main__":
    main()
