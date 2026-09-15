"""Seed default digital twin data (Rautahat district) when database is empty.

Ensures that the Ops Coordinator console, tactical map, queue, fleet roster,
and AI assistant work out of the box with live operations data.
"""

import logging
import time
from decimal import Decimal

logger = logging.getLogger(__name__)


def D(x: float) -> Decimal:
    return Decimal(str(round(x, 6)))


def seed_defaults_if_empty(resource=None):
    from app.db.repos import incidents, pending_actions, reports, shelters, simulation_events, teams, users
    from app.auth.security import hash_password

    # 1. Admin user
    if not users.find_by_username("resqra-admin"):
        try:
            users.create_user(
                username="resqra-admin",
                password_hash=hash_password("ResQra123"),
                name="Rautahat District Incident Commander",
                role="coordinator",
            )
        except Exception:
            pass

    # Check if teams are already seeded
    try:
        existing_teams = teams.list_teams()
        if existing_teams:
            return
    except Exception:
        pass

    logger.info("[DB] Seeding default Rautahat district operations data...")

    try:
        from scripts.reset_and_seed_rautahat import (
            HOT_RAUTAHAT_HEALTH_FACILITIES,
            RAUTAHAT_INCIDENTS,
            RAUTAHAT_RESIDENTS,
            RAUTAHAT_TEAMS,
        )
    except Exception as exc:
        logger.warning("[DB] Could not load seed data: %s", exc)
        return

    now_ms = int(time.time() * 1000)

    # 2. Rescue fleet
    for tid, name, lat, lng, cap, st, res_cnt, spec, contact, district, notes in RAUTAHAT_TEAMS:
        try:
            teams.put_team({
                "id": tid,
                "name": name,
                "capacity": cap,
                "status": st,
                "rescued_total": res_cnt,
                "specialization": spec,
                "contact": contact,
                "district": district,
                "notes": notes,
                "location": {"lat": D(lat), "lng": D(lng), "label": f"{name} Station", "updated_at": now_ms},
            })
        except Exception:
            pass

    # 3. Shelters & Health facilities
    for fac in HOT_RAUTAHAT_HEALTH_FACILITIES:
        try:
            shelters.put_shelter({
                "id": fac["id"],
                "name": fac["name"],
                "capacity": fac["capacity"],
                "current_occupancy": int(fac["capacity"] * 0.32),
                "district": fac["district"],
                "location": fac["location"],
                "supplies": {"food_days": 7, "water_litres": 6000, "medical_kits": 45},
                "hdx_source": fac["hdx_source"],
            })
        except Exception:
            pass

    # 4. Distress incidents
    for inc in RAUTAHAT_INCIDENTS:
        try:
            inc_copy = dict(inc)
            inc_copy["created_at"] = int((time.time() - 3600) * 1000)
            inc_copy["updated_at"] = now_ms
            inc_copy["pending_actions"] = []
            incidents.create_incident(inc_copy)
        except Exception:
            pass

    # 5. Telemetry sensors
    sensor_events = [
        {"event_type": "WATER_LEVEL", "payload": {"lat": D(26.7620), "lng": D(85.2760), "level": "UNSAFE", "value": D(6.80), "note": "Bagmati River Gaur Bridge Gauge: 6.8m (+2.3m above Catastrophic Level)", "district": "rautahat"}},
        {"event_type": "BRIDGE_BLOCKED", "payload": {"lat": D(26.7820), "lng": D(85.2420), "level": "BLOCKED", "note": "Lalbakaiya Tikuliya embankment breached, road submerged", "district": "rautahat"}},
        {"event_type": "ROAD_BLOCKED", "payload": {"lat": D(26.7640), "lng": D(85.2780), "level": "BLOCKED", "note": "Gaur District Hospital approach road 4ft waterlogged", "district": "rautahat"}},
        {"event_type": "SLUICE_GATE", "payload": {"lat": D(26.7580), "lng": D(85.2710), "level": "CLOSED", "note": "Gaur Ring Road Sluice Gate locked to prevent Bagmati backflow", "district": "rautahat"}},
    ]
    for se in sensor_events:
        try:
            idem_key = f"sensor_{se['event_type']}_{int(time.time()*1000)}_{abs(hash(str(se['payload'])))}"
            simulation_events.put_event(idem_key, se["event_type"], se["payload"])
        except Exception:
            pass

    # 6. Advisory bulletin
    try:
        reports.create_report(
            title="DEFCON 1 RED ALERT: Bagmati & Lalbakaiya River Embankment Overflow",
            body="Rautahat District Disaster Management Committee has deployed GAUR BAGMATI WATER RESCUE UNIT, APF No. 11 Battalion, and Nepal Army units across Gaur Municipality and Tikuliya Ghat. Ring road sluice gates engaged.",
            severity="CRITICAL",
            area_text="Rautahat District (Gaur, Tikuliya, Garuda, Chandrapur)",
            source="Rautahat District Emergency Operations Center (DEOC Gaur)",
        )
    except Exception:
        pass

    # 7. Resident beacons
    for phone, name, lat, lng, label, people, vulns, status in RAUTAHAT_RESIDENTS:
        try:
            existing = users.find_by_phone(phone)
            if existing:
                user_id = existing["id"]
            else:
                user_id = users.create_user(phone=phone, name=name, role="resident")["id"]
            users.update_user_info(
                user_id,
                location={"lat": D(lat), "lng": D(lng), "label": label, "confidence": D(0.9)},
                location_text=label,
                people_with=people,
                vulnerabilities=vulns,
                status=status,
                device_location={"lat": D(lat), "lng": D(lng), "label": label},
            )
        except Exception:
            pass

    # 8. Pending action card
    try:
        pending_actions.create_action(
            type_="ALLOCATE",
            incident_id="inc_rautahat_101",
            proposed_team_id="team_gaur_bagmati",
            reasons=["Critical severity (score 10)", "Bagmati breach corridor", "Immediate swift-water boat required"],
            payload={"incident_id": "inc_rautahat_101", "team_id": "team_gaur_bagmati", "eta_minutes": 6},
        )
    except Exception:
        pass

    logger.info("[DB] Default Rautahat operations data seeded successfully.")
