"""Reset DynamoDB tables and seed exclusively Rautahat District (Gaur - Bagmati & Lalbakaiya Basin).

Features:
- Primary Asset: GAUR BAGMATI WATER RESCUE UNIT (Rautahat)
- Supporting squadrons in Rautahat District (APF No. 11 Battalion, Nepal Army Gaur, Red Cross Rautahat)
- HDX / HOT designated shelters & health centers in Gaur, Tikuliya, Garuda, and Chandrapur
- Authentic multilingual distress signals (Maithili, Bhojpuri, Nepali, English)
"""

import os
import pathlib
import sys
import time
from decimal import Decimal

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import boto3
from app.db.client import dynamo_kwargs
from app.db.tables import TABLES as DB_TABLES
from app.db.repos import activity, incidents, missions, pending_actions, reports, shelters, teams, users
from app.services.hdx_loader import HOT_RAUTAHAT_HEALTH_FACILITIES, HOT_RAUTAHAT_WATERWAYS

def D(x: float) -> Decimal:
    return Decimal(str(round(x, 6)))

# ===========================================================================
# 1. RAUTAHAT RESCUE FLEET (LED BY GAUR BAGMATI WATER RESCUE UNIT)
# ===========================================================================
RAUTAHAT_TEAMS = [
    # id, name, lat, lng, capacity, status, rescued_total, specialization, contact, district, station notes
    # Stations verified against district record: Gaur HQ 26.7667N 85.2667E; APF Bn No.11 east of Gaur with BOP at
    # Gaur Customs; NRCS chapter +977-55-520141; District Police 055-520840; Provincial Hospital 055-520142.
    ("team_gaur_bagmati", "GAUR BAGMATI WATER RESCUE UNIT", 26.7660, 85.2740, 16, "AVAILABLE", 48, "Swift-water rescue, inflatable motorboat patrol", "Radio 144.2 MHz", "rautahat", "Ward 4 boat station, Bagmati eastern embankment breach corridor"),
    ("team_apf_rautahat", "APF BATTALION NO. 11, RAUTAHAT", 26.7670, 85.2920, 22, "AVAILABLE", 64, "Amphibious flood extraction battalion", "Radio 142.8 MHz", "rautahat", "Battalion HQ east of Gaur; BOP at Gaur Customs, Bairgania road"),
    ("team_nepal_army_gaur", "NEPAL ARMY GAUR CONTINGENT", 26.7620, 85.2580, 18, "AVAILABLE", 52, "Assault boat squad, deep-water extraction", "Radio 148.6 MHz", "rautahat", "Barracks west Gaur, Ring Road rapid deployment"),
    ("team_redcross_rautahat", "NEPAL RED CROSS RAUTAHAT CHAPTER", 26.7645, 85.2700, 12, "AVAILABLE", 34, "Emergency medical triage, zodiac raft", "+977-55-520141", "rautahat", "District chapter HQ Gaur; referral Provincial Hospital 055-520142"),
    ("team_lalbakaiya_patrol", "LALBAKAIYA TIKULIYA FLOOD UNIT", 26.7840, 85.2410, 10, "AVAILABLE", 26, "Riverbank rapid extraction raft", "Radio 146.2 MHz", "rautahat", "Tikuliya Ghat post; coord District Police 055-520840"),
    ("team_chandrapur_sdrf", "CHANDRAPUR HIGHWAY DISASTER WING", 27.1250, 85.3400, 14, "AVAILABLE", 38, "Highway evacuation, 4x4 and raft transport", "Radio 147.5 MHz", "rautahat", "East-West Highway base, Chandranigahapur"),
]

# ===========================================================================
# 2. AUTHENTIC DISTRESS SIGNALS (RAUTAHAT DISTRICT)
# ===========================================================================
RAUTAHAT_INCIDENTS = [
    {
        "id": "inc_rautahat_101",
        "raw_text": "बागमती नदी के तटबन्ध टूट गेलै, गौर नगरपालिका वार्ड ४ में ६ फीट पानी भरल छै, ७ आदमी छत पर फँसल छी, २ टा छोट बच्चा आ गर्भवती महिला छै, तुरंत बोट पठाउ!",
        "people": 7,
        "vulnerabilities": ["pregnant", "children"],
        "urgency": "HIGH",
        "water_rising": True,
        "location_text": "Gaur Municipality Ward 4 (Bagmati Embankment Breach)",
        "location": {"lat": D(26.7620), "lng": D(85.2760), "label": "Gaur Ward 4 Breach", "confidence": D(0.98)},
        "priority": {"score": D(10), "level": "CRITICAL", "reasons": ["Urgency HIGH (+4)", "7 people (+2)", "Pregnant mother & 2 infants (+3)", "Bagmati Breach Zone (+1)"]},
        "status": "PRIORITIZED",
        "district": "rautahat",
    },
    {
        "id": "inc_rautahat_102",
        "raw_text": "Lalbakaiya river embankment near Tikuliya breached, 4 farmers stranded on tractor trailer with surging flood current all around, need immediate rescue boat",
        "people": 4,
        "vulnerabilities": [],
        "urgency": "HIGH",
        "water_rising": True,
        "location_text": "Tikuliya Ghat, Lalbakaiya River Corridor, Rautahat",
        "location": {"lat": D(26.7820), "lng": D(85.2420), "label": "Tikuliya Lalbakaiya Ghat", "confidence": D(0.95)},
        "priority": {"score": D(9), "level": "CRITICAL", "reasons": ["Urgency HIGH (+4)", "4 people (+2)", "Rapid Current Trap (+2)", "Lalbakaiya Embankment Breach (+1)"]},
        "status": "PRIORITIZED",
        "district": "rautahat",
    },
    {
        "id": "inc_rautahat_103",
        "raw_text": "Gaur District Hospital approach road waterlogged 4 feet, 5 dialysis patients stuck at ground floor gate, water level rising rapidly",
        "people": 5,
        "vulnerabilities": ["ill", "elderly"],
        "urgency": "HIGH",
        "water_rising": True,
        "location_text": "Gaur District Hospital Gate, Ward 3",
        "location": {"lat": D(26.7640), "lng": D(85.2780), "label": "Gaur District Hospital", "confidence": D(0.96)},
        "priority": {"score": D(9), "level": "CRITICAL", "reasons": ["Urgency HIGH (+4)", "5 dialysis patients (+2)", "Elderly & medical emergency (+2)", "Hospital Access Cut (+1)"]},
        "status": "PRIORITIZED",
        "district": "rautahat",
    },
    {
        "id": "inc_rautahat_104",
        "raw_text": "गरुडा बजारमा पानी पसेर ४ जना पसले दोस्रो तलामा बसेका छन्, खाद्यान्न सुरक्षित छ तर बाटो पुरै बन्द छ",
        "people": 4,
        "vulnerabilities": [],
        "urgency": "MEDIUM",
        "water_rising": False,
        "location_text": "Garuda Bazaar Center, Rautahat",
        "location": {"lat": D(26.9250), "lng": D(85.3120), "label": "Garuda Bazaar Center", "confidence": D(0.91)},
        "priority": {"score": D(4), "level": "MEDIUM", "reasons": ["Urgency MEDIUM (+2)", "4 people (+1)", "Safe upper floor (+1)"]},
        "status": "VERIFIED",
        "district": "rautahat",
    },
    {
        "id": "inc_rautahat_105",
        "raw_text": "Chandranigahapur East-West Highway culvert flooded with 1 foot water, 2 bus passengers safe at local tea stall",
        "people": 2,
        "vulnerabilities": [],
        "urgency": "LOW",
        "water_rising": False,
        "location_text": "Chandrapur Highway Chowk, Rautahat",
        "location": {"lat": D(27.1240), "lng": D(85.3380), "label": "Chandrapur Highway Chowk", "confidence": D(0.88)},
        "priority": {"score": D(2), "level": "LOW", "reasons": ["Urgency LOW (+1)", "Low risk (+1)"]},
        "status": "VERIFIED",
        "district": "rautahat",
    },
]


# ===========================================================================
# 3. SEEDED RESIDENTS (VISIBLE BEACONS ON THE COORDINATOR MAP)
# ===========================================================================
RAUTAHAT_RESIDENTS = [
    ("+9779800001001", "Ram Kishor Yadav", 26.7660, 85.2770, "Gaur Ward 4, near breached embankment", 7, ["pregnant", "children"], "TRAPPED"),
    ("+9779800001002", "Sunita Devi", 26.7590, 85.2720, "Juddha School relief camp", 2, ["elderly"], "NEEDS_HELP"),
    ("+9779800001003", "Mohammad Salim", 26.7820, 85.2420, "Tikuliya Ghat riverbank", 4, [], "TRAPPED"),
    ("+9779800001004", "Gita Sharma", 26.7640, 85.2780, "Gaur Hospital Chowk", 5, ["ill", "elderly"], "NEEDS_HELP"),
    ("+9779800001005", "Hari Prasad Sah", 26.9250, 85.3120, "Garuda Bazaar upper floor", 4, [], "SAFE"),
    ("+9779800001006", "Mina Kumari", 27.1240, 85.3380, "Chandrapur Highway tea stall", 2, ["children"], "SAFE"),
]


def reset_and_seed_rautahat():
    print("=" * 60)
    print("ResQra Rautahat District Terai Flood OS Reset & Seed")
    print("Dedicated Lead: GAUR BAGMATI WATER RESCUE UNIT (Rautahat)")
    print("HDX 'hot_flood_npl' Integration")
    print("=" * 60)

    db = boto3.resource("dynamodb", **dynamo_kwargs())

    # 1. Clear Existing Tables
    tables_to_clear = ["Incidents", "Teams", "Shelters", "PendingActions", "Missions", "ActivityEvent", "SimulationEvents", "GovReports"]
    for tbl_name in tables_to_clear:
        try:
            t = db.Table(tbl_name)
            items = t.scan().get("Items", [])
            key_names = [k["AttributeName"] for k in t.key_schema]
            with t.batch_writer() as batch:
                for item in items:
                    key = {k: item[k] for k in key_names}
                    batch.delete_item(Key=key)
            print(f"  [OK] Cleared {len(items)} rows from {tbl_name}")
        except Exception as e:
            print(f"  [WARN] Error clearing {tbl_name}: {e}")

    # 2. Seed Admin Users
    from app.auth.security import hash_password
    if not users.find_by_username("resqra-admin"):
        users.create_user(
            username="resqra-admin",
            password_hash=hash_password("resqra-admin-123"),
            name="Rautahat District Incident Commander",
            role="coordinator",
        )
        print("  [OK] Created resqra-admin account")
    else:
        print("  [OK] resqra-admin verified")

    # 3. Seed Rautahat Rescue Fleet
    now_ms = int(time.time() * 1000)
    for tid, name, lat, lng, cap, st, res_cnt, spec, contact, district, notes in RAUTAHAT_TEAMS:
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
    print(f"  [OK] Seeded {len(RAUTAHAT_TEAMS)} Rautahat Rescue Squadrons (Lead: GAUR BAGMATI WATER RESCUE UNIT)")

    # 4. Seed HDX / HOT Hospitals & Relief Centers in Rautahat
    for fac in HOT_RAUTAHAT_HEALTH_FACILITIES:
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
    print(f"  [OK] Seeded {len(HOT_RAUTAHAT_HEALTH_FACILITIES)} HDX / HOT Shelters & Health Facilities in Rautahat")

    # 5. Seed Authentic Distress Incidents in Rautahat
    for inc in RAUTAHAT_INCIDENTS:
        inc["created_at"] = int((time.time() - 3600) * 1000)
        inc["updated_at"] = now_ms
        inc["pending_actions"] = []
        incidents.create_incident(inc)
    print(f"  [OK] Seeded {len(RAUTAHAT_INCIDENTS)} Authentic Distress Incidents in Rautahat")

    # 6. Seed Simulation Hydrological Telemetry in Rautahat
    from app.db.repos import simulation_events
    sensor_events = [
        {"event_type": "WATER_LEVEL", "payload": {"lat": D(26.7620), "lng": D(85.2760), "level": "UNSAFE", "value": D(6.80), "note": "Bagmati River Gaur Bridge Gauge: 6.8m (+2.3m above Catastrophic Level)", "district": "rautahat"}},
        {"event_type": "BRIDGE_BLOCKED", "payload": {"lat": D(26.7820), "lng": D(85.2420), "level": "BLOCKED", "note": "Lalbakaiya Tikuliya embankment breached, road submerged", "district": "rautahat"}},
        {"event_type": "ROAD_BLOCKED", "payload": {"lat": D(26.7640), "lng": D(85.2780), "level": "BLOCKED", "note": "Gaur District Hospital approach road 4ft waterlogged", "district": "rautahat"}},
        {"event_type": "SLUICE_GATE", "payload": {"lat": D(26.7580), "lng": D(85.2710), "level": "CLOSED", "note": "Gaur Ring Road Sluice Gate locked to prevent Bagmati backflow", "district": "rautahat"}},
    ]
    for se in sensor_events:
        idem_key = f"sensor_{se['event_type']}_{int(time.time()*1000)}_{abs(hash(str(se['payload'])))}"
        simulation_events.put_event(idem_key, se["event_type"], se["payload"])
    print(f"  [OK] Seeded {len(sensor_events)} Hydrological & Embankment Telemetry Sensors in Rautahat")

    # 7. Seed Official Advisory Bulletin
    reports.create_report(
        title="DEFCON 1 RED ALERT: Bagmati & Lalbakaiya River Embankment Overflow",
        body="Rautahat District Disaster Management Committee has deployed GAUR BAGMATI WATER RESCUE UNIT, APF No. 11 Battalion, and Nepal Army units across Gaur Municipality and Tikuliya Ghat. Ring road sluice gates engaged.",
        severity="CRITICAL",
        area_text="Rautahat District (Gaur, Tikuliya, Garuda, Chandrapur)",
        source="Rautahat District Emergency Operations Center (DEOC Gaur)",
    )
    print("  [OK] Seeded Official Rautahat District Emergency Bulletin")

    # 8. Seed Resident Beacons (idempotent by phone)
    resident_count = 0
    for phone, name, lat, lng, label, people, vulns, status in RAUTAHAT_RESIDENTS:
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
        resident_count += 1
    print(f"  [OK] Seeded {resident_count} Resident Beacons in Rautahat")
    print("=" * 60)
    print("Rautahat District Flood OS Ready! 100% Focused.")
    print("=" * 60)

if __name__ == "__main__":
    import sys as _sys

    from app.config import settings as _settings

    _endpoint = str(_settings.dynamodb_endpoint_url or "")
    _local = "localhost" in _endpoint or "127.0.0.1" in _endpoint
    if not _local and "--confirm-live" not in _sys.argv:
        print("REFUSING to wipe non-local DynamoDB. Re-run with --confirm-live "
              "if you really mean to reset live tables.")
        _sys.exit(2)
    reset_and_seed_rautahat()
