"""Seed demo data: 6 rescue teams + 6 shelters around Patna.

Usage:
    python scripts/seed.py

Run scripts/create_tables.py first.
"""

import pathlib
import sys
import time
from decimal import Decimal

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.db.repos import activity, shelters, teams  # noqa: E402


def D(x: float) -> Decimal:
    """DynamoDB rejects float — coordinates must be Decimal."""
    return Decimal(str(x))

# Patna 25.5941, 85.1376 — offsets are small enough to look clustered
TEAMS = [
    ("team_alpha", "TEAM ALPHA", 25.6021, 85.1191, 4, "AVAILABLE", 11),
    ("team_beta", "TEAM BETA", 25.5831, 85.1581, 15, "AVAILABLE", 23),
    ("team_gamma", "TEAM GAMMA", 25.6161, 85.1451, 8, "ON_MISSION", 17),
    ("team_delta", "TEAM DELTA", 25.5741, 85.1271, 12, "AVAILABLE", 9),
    ("team_epsilon", "TEAM EPSILON", 25.5901, 85.0941, 10, "AVAILABLE", 14),
    ("team_zeta", "TEAM ZETA", 25.6281, 85.1111, 6, "RETURNING", 5),
]

SHELTERS = [
    ("shelter_1", "Govt High School, Kankarbagh", 25.5812, 85.1471, 400, 112),
    ("shelter_2", "Miller High School, Raja Bazar", 25.6042, 85.1301, 350, 88),
    ("shelter_3", "Bihar Veterinary College Ground", 25.6112, 85.1011, 600, 240),
    ("shelter_4", "Patna Women's College", 25.6012, 85.1371, 300, 95),
    ("shelter_5", "Moin-ul-Haq Stadium", 25.5932, 85.1221, 800, 410),
    ("shelter_6", "Danapur Cantonment Hall", 25.6292, 85.0471, 250, 61),
]


def main() -> None:
    now = int(time.time() * 1000)
    for tid, name, lat, lng, cap, status, rescued in TEAMS:
        teams.put_team(
            {
                "id": tid,
                "name": name,
                "location": {"lat": D(lat), "lng": D(lng)},
                "capacity": cap,
                "status": status,
                "current_mission_id": None,
                "rescued_total": rescued,
                "updated_at": now,
            }
        )
        print(f"+ team {name}")
    for sid, name, lat, lng, cap, occ in SHELTERS:
        shelters.put_shelter(
            {
                "id": sid,
                "name": name,
                "location": {"lat": D(lat), "lng": D(lng)},
                "capacity": cap,
                "current_occupancy": occ,
                "updated_at": now,
            }
        )
        print(f"+ shelter {name}")
    activity.log_event(
        actor="system",
        type_="seed",
        summary=f"Seeded {len(TEAMS)} teams and {len(SHELTERS)} shelters (Patna)",
    )
    print("done")


if __name__ == "__main__":
    main()
