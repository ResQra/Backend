"""Reset DynamoDB tables and seed realistic Madhesh Province, Nepal flood disaster data.

Utilizes HDX 'hot_flood_npl' (Humanitarian OpenStreetMap Team Nepal Flood) structures:
- 8 Districts: Rautahat, Dhanusha, Parsa, Saptari, Mahottari, Siraha, Sarlahi, Bara
- HDX Health facilities & designated flood shelters
- Active flood waterways: Bagmati, Kamala, Lalbakaiya, Kosi, Ratu, Sirsaiya
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
from app.services.hdx_loader import HOT_MADHESH_HEALTH_FACILITIES, HOT_MADHESH_WATERWAYS

def D(x: float) -> Decimal:
    return Decimal(str(round(x, 6)))

# ===========================================================================
# 1. MADHESH PROVINCE RESCUE FLEET (8 BATTALIONS)
# ===========================================================================
MADHESH_TEAMS = [
    ("team_apf_chhinnamasta", "APF NO. 2 CHHINNAMASTA BRIGADE", 26.8850, 85.8750, 24, "AVAILABLE", 68, "Heavy Amphibious & Inflatable Boat Wing", "Radio 142.8 MHz", "dhanusha"),
    ("team_army_mideastern", "NEPAL ARMY MID-EASTERN DIVISION", 26.7350, 85.9120, 20, "AVAILABLE", 54, "Special Disaster Response Heli/Boat Squadron", "Radio 148.6 MHz", "dhanusha"),
    ("team_gaur_boat_squad", "GAUR BAGMATI WATER RESCUE UNIT", 26.7610, 26.7610 if False else 85.2750, 16, "AVAILABLE", 42, "Deep Flood Inflatable Motorboat Patrol", "+977-55-520100", "rautahat"),
    ("team_narayani_fast_raft", "NARAYANI RIVERINE RESCUE SQUAD", 27.0120, 84.8720, 14, "AVAILABLE", 39, "Urban Torrent Evacuation Raft", "+977-51-522100", "parsa"),
    ("team_kosi_basin_patrol", "KOSI BASIN HEAVY MOTORBOAT UNIT", 26.5410, 86.7480, 22, "AVAILABLE", 61, "High-Discharge River Extraction Wing", "Radio 144.4 MHz", "saptari"),
    ("team_redcross_madhesh", "NEPAL RED CROSS MADHESH CHAPTER", 26.7260, 85.9220, 12, "AVAILABLE", 31, "Mobile Medical Evacuation Raft", "+977-41-520250", "dhanusha"),
    ("team_jaleshwar_ratu", "JALESWAR RATU DISASTER SQUAD", 26.6450, 85.7980, 10, "AVAILABLE", 23, "Light Inflatable Raft Unit", "Radio 146.2 MHz", "mahottari"),
    ("team_malangwa_rescue", "SARLAHI MALANGWA FLOOD UNIT", 26.8550, 85.5580, 12, "AVAILABLE", 27, "Rural Terai Extraction Squad", "+977-46-520111", "sarlahi"),
]

# ===========================================================================
# 2. AUTHENTIC MULTILINGUAL DISTRESS SIGNALS (MAITHILI, BHOJPURI, NEPALI, ENG)
# ===========================================================================
MADHESH_INCIDENTS = [
    {
        "id": "inc_madhesh_101",
        "raw_text": "बागमती नदी के तटबन्ध टूट गेलै, गौर नगरपालिका वार्ड ४ में ६ फीट पानी भरल छै, ७ आदमी छत पर फँसल छी, २ टा छोट बच्चा आ गर्भवती महिला छै, तुरंत बोट पठाउ!",
        "people": 7,
        "vulnerabilities": ["pregnant", "children"],
        "urgency": "HIGH",
        "water_rising": True,
        "location_text": "Gaur Municipality Ward 4, Rautahat (Bagmati Breach)",
        "location": {"lat": D(26.7620), "lng": D(85.2760), "label": "Gaur Bagmati Breach", "confidence": D(0.96)},
        "priority": {"score": D(10), "level": "CRITICAL", "reasons": ["Urgency HIGH (+4)", "7 people (+2)", "Pregnant & infants (+3)", "Bagmati Embankment Breach (+1)"]},
        "status": "PRIORITIZED",
        "district": "rautahat",
    },
    {
        "id": "inc_madhesh_102",
        "raw_text": "कमला नदी में भारी उफान से जनकपुर-धनुषाधाम सड़क सम्पर्क टूट गइल बा, ५ गो लोग बाँध पर शरण लेले बाड़न, वृद्ध बाबूजी के दवाई खतम हो गइल बा",
        "people": 5,
        "vulnerabilities": ["elderly", "ill"],
        "urgency": "HIGH",
        "water_rising": True,
        "location_text": "Dhanushadham Kamala Bridge Corridor, Dhanusha",
        "location": {"lat": D(26.7920), "lng": D(85.9850), "label": "Dhanushadham Kamala Bank", "confidence": D(0.93)},
        "priority": {"score": D(9), "level": "CRITICAL", "reasons": ["Urgency HIGH (+4)", "5 people (+2)", "Elderly & medical emergency (+2)", "Kamala Barrage Surge (+1)"]},
        "status": "PRIORITIZED",
        "district": "dhanusha",
    },
    {
        "id": "inc_madhesh_103",
        "raw_text": "Narayani Hospital approach road in Birgunj submerged 4 feet under Sirsaiya river overflow, 6 dialyis patients stranded at ground floor gate",
        "people": 6,
        "vulnerabilities": ["ill", "disabled"],
        "urgency": "HIGH",
        "water_rising": True,
        "location_text": "Narayani Hospital Gate, Birgunj, Parsa",
        "location": {"lat": D(27.0140), "lng": D(84.8780), "label": "Narayani Hospital Birgunj", "confidence": D(0.95)},
        "priority": {"score": D(9), "level": "CRITICAL", "reasons": ["Urgency HIGH (+4)", "6 medical dialysis patients (+3)", "Critical Hospital corridor (+2)"]},
        "status": "PRIORITIZED",
        "district": "parsa",
    },
    {
        "id": "inc_madhesh_104",
        "raw_text": "सप्तकोशी नदी के ५६ वटै ढोका खोलिएपछि गोबरगाढा टापु गाउँ पूर्ण जलमग्न, १२ जना स्थानीय मन्दिरको छानामा फसेका छन्, हेलिकप्टर वा मोटरबोट आवश्यक",
        "people": 12,
        "vulnerabilities": ["children", "elderly"],
        "urgency": "HIGH",
        "water_rising": True,
        "location_text": "Gobargadha Island Settlement, Saptari (Kosi Basin)",
        "location": {"lat": D(26.5920), "lng": D(86.9150), "label": "Kosi Gobargadha Island", "confidence": D(0.97)},
        "priority": {"score": D(10), "level": "CRITICAL", "reasons": ["Urgency HIGH (+4)", "12 people (+3)", "Island Isolation & 56-Gate Discharge (+3)"]},
        "status": "PRIORITIZED",
        "district": "saptari",
    },
    {
        "id": "inc_madhesh_105",
        "raw_text": "रातु नदीको बाढी जलेश्वर कारागार र अदालत क्षेत्रमा पस्यो, ३ जना कर्मचारी सुरक्षित दोस्रो तलामा छन् तर खाद्यान्न सकियो",
        "people": 3,
        "vulnerabilities": [],
        "urgency": "MEDIUM",
        "water_rising": False,
        "location_text": "Jaleshwar Municipality Center, Mahottari",
        "location": {"lat": D(26.6480), "lng": D(85.8020), "label": "Jaleshwar Center", "confidence": D(0.90)},
        "priority": {"score": D(4), "level": "MEDIUM", "reasons": ["Urgency MEDIUM (+2)", "3 people (+1)", "Safe upper floor (+1)"]},
        "status": "VERIFIED",
        "district": "mahottari",
    },
    {
        "id": "inc_madhesh_106",
        "raw_text": "Lalbakaiya river embankment near Tikuliya breached, 4 farmers stranded in tractor trailer with strong current flowing around",
        "people": 4,
        "vulnerabilities": [],
        "urgency": "HIGH",
        "water_rising": True,
        "location_text": "Tikuliya Ghat, Lalbakaiya River, Rautahat",
        "location": {"lat": D(26.7820), "lng": D(85.2420), "label": "Tikuliya Lalbakaiya River", "confidence": D(0.92)},
        "priority": {"score": D(8), "level": "CRITICAL", "reasons": ["Urgency HIGH (+4)", "4 people (+2)", "Strong current entrapment (+2)"]},
        "status": "PRIORITIZED",
        "district": "rautahat",
    },
    {
        "id": "inc_madhesh_107",
        "raw_text": "Lahan East-West Highway approach culvert washed out, 2 bus passengers safe at local tea stall waiting for water level to recede",
        "people": 2,
        "vulnerabilities": [],
        "urgency": "LOW",
        "water_rising": False,
        "location_text": "Lahan Highway Bridge, Siraha",
        "location": {"lat": D(26.7190), "lng": D(86.4820), "label": "Lahan Highway Bridge", "confidence": D(0.88)},
        "priority": {"score": D(2), "level": "LOW", "reasons": ["Urgency LOW (+1)", "Low risk (+1)"]},
        "status": "VERIFIED",
        "district": "siraha",
    },
    {
        "id": "inc_madhesh_108",
        "raw_text": "Malangwa border customs checkpost waterlogged 2 feet, 3 border guards safe in observation tower",
        "people": 3,
        "vulnerabilities": [],
        "urgency": "LOW",
        "water_rising": False,
        "location_text": "Malangwa Customs Post, Sarlahi",
        "location": {"lat": D(26.8520), "lng": D(85.5600), "label": "Malangwa Border Post", "confidence": D(0.85)},
        "priority": {"score": D(2), "level": "LOW", "reasons": ["Urgency LOW (+1)", "Low risk (+1)"]},
        "status": "VERIFIED",
        "district": "sarlahi",
    },
]


def reset_and_seed_madhesh():
    print("=" * 60)
    print("ResQra Madhesh Province Terai Flood OS Reset & Seed")
    print("HDX 'hot_flood_npl' (Humanitarian OpenStreetMap Team) Integration")
    print("=" * 60)

    db = boto3.resource("dynamodb", **dynamo_kwargs())

    # 1. Clear Existing Tactical Tables
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
            name="Madhesh Provincial Command Chief",
            role="coordinator",
        )
        print("  [OK] Created resqra-admin account")
    else:
        print("  [OK] resqra-admin verified")

    # 3. Seed 8 Madhesh Rescue Battalions
    now_ms = int(time.time() * 1000)
    for tid, name, lat, lng, cap, st, res_cnt, spec, contact, district in MADHESH_TEAMS:
        teams.put_team({
            "id": tid,
            "name": name,
            "capacity": cap,
            "status": st,
            "rescued_total": res_cnt,
            "specialization": spec,
            "contact": contact,
            "district": district,
            "location": {"lat": D(lat), "lng": D(lng), "label": f"{name} Base", "updated_at": now_ms},
        })
    print(f"  [OK] Seeded {len(MADHESH_TEAMS)} Madhesh Rescue Battalions (APF, Army, Red Cross, Police)")

    # 4. Seed HDX / HOT Hospitals & Relief Centers
    for fac in HOT_MADHESH_HEALTH_FACILITIES:
        shelters.put_shelter({
            "id": fac["id"],
            "name": fac["name"],
            "capacity": fac["capacity"],
            "current_occupancy": int(fac["capacity"] * 0.35),
            "district": fac["district"],
            "location": fac["location"],
            "supplies": {"food_days": 7, "water_litres": 8000, "medical_kits": 50},
            "hdx_source": fac["hdx_source"],
        })
    print(f"  [OK] Seeded {len(HOT_MADHESH_HEALTH_FACILITIES)} HDX / HOT Health Centers & Designated Shelters")

    # 5. Seed Authentic Distress Incidents
    for inc in MADHESH_INCIDENTS:
        inc["created_at"] = int((time.time() - 3600) * 1000)
        inc["updated_at"] = now_ms
        inc["pending_actions"] = []
        incidents.create_incident(inc)
    print(f"  [OK] Seeded {len(MADHESH_INCIDENTS)} Authentic Multilingual Distress Incidents (Maithili/Bhojpuri/Nepali)")

    # 6. Seed Simulation Hydrological Telemetry from HDX Waterways
    from app.db.repos import simulation_events
    sensor_events = [
        {"event_type": "WATER_LEVEL", "payload": {"lat": D(26.7620), "lng": D(85.2760), "level": "UNSAFE", "value": D(6.80), "note": "Bagmati River Gaur Gauge: 6.8m (+2.3m above Catastrophic Red Level)", "district": "rautahat"}},
        {"event_type": "BRIDGE_BLOCKED", "payload": {"lat": D(26.7820), "lng": D(85.2420), "level": "BLOCKED", "note": "Lalbakaiya Tikuliya embankment breached, road impassable", "district": "rautahat"}},
        {"event_type": "WATER_LEVEL", "payload": {"lat": D(26.7920), "lng": D(85.9850), "level": "UNSAFE", "value": D(5.70), "note": "Kamala River Dhanusha Barrage: Peak 180,000 cfs discharge", "district": "dhanusha"}},
        {"event_type": "WATER_LEVEL", "payload": {"lat": D(26.5920), "lng": D(86.9150), "level": "UNSAFE", "value": D(11.20), "note": "Saptakoshi Barrage: 56 Gates Opened, 450,000 cfs Red Alert", "district": "saptari"}},
        {"event_type": "ROAD_BLOCKED", "payload": {"lat": D(27.0140), "lng": D(84.8780), "level": "BLOCKED", "note": "Birgunj Narayani Hospital Approach 4ft waterlogged", "district": "parsa"}},
    ]
    for se in sensor_events:
        idem_key = f"sensor_{se['event_type']}_{int(time.time()*1000)}_{abs(hash(str(se['payload'])))}"
        simulation_events.put_event(idem_key, se["event_type"], se["payload"])
    print(f"  [OK] Seeded {len(sensor_events)} Hydrological & Embankment Telemetry Sensors")

    # 7. Seed Official Advisory Bulletin
    reports.create_report(
        title="DEFCON 1 RED ALERT: Bagmati, Kamala & Kosi River Basins Emergency Overflow",
        body="Madhesh Provincial Disaster Management Authority has activated APF Chhinnamasta Brigade, Nepal Army Mid-Eastern Command, and Red Cross boat units across Gaur, Janakpur, Birgunj, and Saptari. High-risk Terai embankments under evacuation.",
        severity="CRITICAL",
        area_text="Madhesh Province (Rautahat, Dhanusha, Parsa, Saptari, Mahottari, Siraha, Sarlahi, Bara)",
        source="Madhesh Provincial Emergency Operations Center (PEOC)",
    )
    print("  [OK] Seeded Official Provincial Emergency Bulletin")
    print("=" * 60)
    print("Madhesh Province Terai Flood OS Ready! 100% Focused.")
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
    reset_and_seed_madhesh()
