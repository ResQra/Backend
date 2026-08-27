"""Reset DynamoDB tables and seed realistic Nepal Flood disaster data.

Kathmandu Valley (Bagmati, Hanumante, Nakkhu river basins):
- Center: 27.7172, 85.3240
- Realistic rescue teams (Nepal APF, Nepal Army, Nepal Police, Nepal Red Cross)
- Shelters (Dasharath Stadium, Patan Campus, Bhaktapur Campus, TU Kirtipur)
- Authentic multilingual distress calls (Nepali, English, Romanized Nepali)
- Live sensor telemetry (Bagmati river gauge, submerged bridges)
"""

import os
import pathlib
import random
import sys
import time
import uuid
from decimal import Decimal

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import boto3
from app.db.client import dynamo_kwargs
from app.db.tables import TABLES as DB_TABLES
from app.db.repos import activity, incidents, missions, pending_actions, reports, shelters, teams, users

def D(x: float) -> Decimal:
    return Decimal(str(round(x, 6)))

# Kathmandu Valley Center & River Basins
KATHMANDU_CENTER = (27.7000, 85.3200)

NEPAL_TEAMS = [
    ("team_nepal_apf", "APF DISASTER BATTALION", 27.6890, 85.2950, 16, "AVAILABLE", 34, "Armed Police Force Boat Rescue Unit", "Radio 142.5 MHz"),
    ("team_nepal_army", "NEPAL ARMY RESCUE HELI/BOAT", 27.6980, 85.3250, 20, "AVAILABLE", 52, "Special Disaster Response Command", "Radio 148.1 MHz"),
    ("team_nepal_police", "NEPAL POLICE QUICK DISPATCH", 27.6810, 85.3120, 8, "AVAILABLE", 19, "Urban Flood Extraction Squad", "+977-1-4412780"),
    ("team_redcross_nepal", "NEPAL RED CROSS EVAC UNIT", 27.6750, 85.3410, 12, "AVAILABLE", 28, "Medical & Amphibious Evacuation", "+977-1-4270650"),
    ("team_lalitpur_metro", "LALITPUR DISASTER RESCUE", 27.6640, 85.3150, 10, "AVAILABLE", 15, "Inflatable Heavy Raft Unit", "Radio 145.2 MHz"),
    ("team_bhaktapur_squad", "BHAKTAPUR HANUMANTE TEAM", 27.6720, 85.4280, 6, "AVAILABLE", 11, "Light Riverine Inflatable Raft", "Radio 146.8 MHz"),
]

NEPAL_SHELTERS = [
    ("shelter_dasharath", "Dasharath Stadium Sports Complex, Tripureshwor", 27.6948, 85.3135, 1500, 480),
    ("shelter_patan_campus", "Patan Multiple Campus Ground, Patan Dhoka", 27.6775, 85.3210, 800, 260),
    ("shelter_tu_kirtipur", "Tribhuvan University Gymnasium, Kirtipur", 27.6790, 85.2890, 1200, 390),
    ("shelter_bhaktapur", "Bhaktapur Multiple Campus Ground, Dudhpati", 27.6715, 85.4290, 600, 195),
    ("shelter_st_xaviers", "St. Xavier's College Campus, Maitighar", 27.6920, 85.3220, 500, 140),
    ("shelter_boudha", "Hyolmo Monastery Community Center, Boudha", 27.7210, 85.3620, 700, 220),
]

NEPAL_INCIDENTS = [
    {
        "id": "inc_nepal_101",
        "raw_text": "Bagmati river overflowed near Balkhu bridge, 6 people trapped on roof with 2 children. Water rising rapidly!",
        "people": 6,
        "vulnerabilities": ["children", "elderly"],
        "urgency": "HIGH",
        "water_rising": True,
        "location_text": "Balkhu Bridge corridor, Kathmandu",
        "location": {"lat": D(27.6854), "lng": D(27.6854 if False else 85.2912), "label": "Balkhu River Bridge", "confidence": D(0.95)},
        "priority": {"score": D(9), "level": "CRITICAL", "reasons": ["Urgency HIGH (+4)", "6 people (+2)", "Children & elderly (+2)", "Area hotspot (+1)"]},
        "status": "PRIORITIZED",
    },
    {
        "id": "inc_nepal_102",
        "raw_text": "बागमती नदीको बाढीले घर डुबानमा पर्यो, ५ जना छतमा फसेका छौं, वृद्ध आमालाई दमको समस्या छ, तुरुन्त बोट पठाइदिनुहोस्",
        "people": 5,
        "vulnerabilities": ["elderly", "ill"],
        "urgency": "HIGH",
        "water_rising": True,
        "location_text": "Kupondole riverside, Lalitpur",
        "location": {"lat": D(27.6820), "lng": D(85.3140), "label": "Kupondole Bagmati Bank", "confidence": D(0.92)},
        "priority": {"score": D(9), "level": "CRITICAL", "reasons": ["Urgency HIGH (+4)", "5 people (+2)", "Elderly & ill (+2)", "River flood risk (+1)"]},
        "status": "PRIORITIZED",
    },
    {
        "id": "inc_nepal_103",
        "raw_text": "Nakkhu river flash flood washed away ground floor near Dhobighat, 4 people stranded without food or dry clothes",
        "people": 4,
        "vulnerabilities": ["children"],
        "urgency": "HIGH",
        "water_rising": True,
        "location_text": "Dhobighat, Nakkhu corridor",
        "location": {"lat": D(27.6620), "lng": D(85.3110), "label": "Nakkhu River Dhobighat", "confidence": D(0.88)},
        "priority": {"score": D(8), "level": "CRITICAL", "reasons": ["Urgency HIGH (+4)", "4 people (+2)", "Children present (+2)"]},
        "status": "PRIORITIZED",
    },
    {
        "id": "inc_nepal_104",
        "raw_text": "Sanepa residential area water entered 1st floor, 3 adults safe on 2nd floor for now, requesting evacuation when available",
        "people": 3,
        "vulnerabilities": [],
        "urgency": "MEDIUM",
        "water_rising": False,
        "location_text": "Sanepa Heights, Lalitpur",
        "location": {"lat": D(27.6835), "lng": D(85.3050), "label": "Sanepa Heights", "confidence": D(0.90)},
        "priority": {"score": D(4), "level": "MEDIUM", "reasons": ["Urgency MEDIUM (+2)", "3 people (+1)", "Safe for now (+1)"]},
        "status": "VERIFIED",
    },
    {
        "id": "inc_nepal_105",
        "raw_text": "हनुमन्ते खोलाको पानीले भक्तपुर सल्लाघारी सडक डुबान, कार र बसहरु फसेका छन्, करिब १५ जना यात्रु सुरक्षित स्थानमा सर्न खोज्दैछन्",
        "people": 15,
        "vulnerabilities": ["elderly", "children"],
        "urgency": "HIGH",
        "water_rising": True,
        "location_text": "Sallaghari, Bhaktapur",
        "location": {"lat": D(27.6710), "lng": D(85.4180), "label": "Sallaghari Hanumante Corridor", "confidence": D(0.94)},
        "priority": {"score": D(10), "level": "CRITICAL", "reasons": ["Urgency HIGH (+4)", "15 people (+3)", "Vulnerable individuals (+2)", "Blocked transit (+1)"]},
        "status": "PRIORITIZED",
    },
    {
        "id": "inc_nepal_106",
        "raw_text": "Thapathali squatter settlement submerged up to 5 feet, pregnant woman needs emergency transit to maternity hospital",
        "people": 2,
        "vulnerabilities": ["pregnant"],
        "urgency": "HIGH",
        "water_rising": True,
        "location_text": "Thapathali riverside settlement",
        "location": {"lat": D(27.6920), "lng": D(85.3210), "label": "Thapathali Bagmati Bank", "confidence": D(0.96)},
        "priority": {"score": D(8), "level": "CRITICAL", "reasons": ["Urgency HIGH (+4)", "Pregnant woman (+2)", "2 people (+1)", "Hotspot zone (+1)"]},
        "status": "PRIORITIZED",
    },
    {
        "id": "inc_nepal_107",
        "raw_text": "Landslide and mudflow blocked access near Chobhar gorge, 8 people isolated at temple compound",
        "people": 8,
        "vulnerabilities": ["elderly"],
        "urgency": "MEDIUM",
        "water_rising": False,
        "location_text": "Chobhar Gorge Temple",
        "location": {"lat": D(27.6580), "lng": D(85.2920), "label": "Chobhar Gorge", "confidence": D(0.85)},
        "priority": {"score": D(7), "level": "MEDIUM", "reasons": ["Urgency MEDIUM (+2)", "8 people (+3)", "Elderly present (+2)"]},
        "status": "VERIFIED",
    },
]

NEPAL_SENSORS = [
    {
        "idempotency_key": "sensor_bagmati_balkhu_01",
        "event_type": "WATER_LEVEL",
        "source_priority": "SIMULATION",
        "payload": {
            "kind": "WATER_LEVEL",
            "lat": D(27.6854),
            "lng": D(85.2912),
            "value": D(4.85),
            "level": "CRITICAL",
            "source_priority": "SIMULATION",
            "note": "Bagmati River Balkhu Gauge: 4.85m (Danger Mark Exceeded by 1.2m)",
        },
    },
    {
        "idempotency_key": "sensor_hanumante_bhaktapur_02",
        "event_type": "WATER_LEVEL",
        "source_priority": "SIMULATION",
        "payload": {
            "kind": "WATER_LEVEL",
            "lat": D(27.6710),
            "lng": D(85.4180),
            "value": D(3.90),
            "level": "RISING",
            "source_priority": "SIMULATION",
            "note": "Hanumante River Sallaghari Gauge: Water level 3.9m surging rapidly",
        },
    },
    {
        "idempotency_key": "sensor_bridge_balkhu_03",
        "event_type": "BRIDGE_BLOCKED",
        "source_priority": "SIMULATION",
        "payload": {
            "kind": "BRIDGE_BLOCKED",
            "lat": D(27.6860),
            "lng": D(85.2925),
            "level": "UNSAFE",
            "source_priority": "SIMULATION",
            "note": "Balkhu Bridge submerged and closed for vehicle & pedestrian crossing",
        },
    },
    {
        "idempotency_key": "sensor_road_kalanki_04",
        "event_type": "ROAD_BLOCKED",
        "source_priority": "SIMULATION",
        "payload": {
            "kind": "ROAD_BLOCKED",
            "lat": D(27.6880),
            "lng": D(85.2850),
            "level": "WATCH",
            "source_priority": "SIMULATION",
            "note": "Kalanki Ring Road underpass inundated with 3.2 feet water",
        },
    },
]

def reset_and_seed():
    print("Connecting to live AWS DynamoDB (ap-south-1)...")
    dynamodb = boto3.resource("dynamodb", **dynamo_kwargs())
    
    # 1. Clear & recreate table items
    print("Purging old demo data...")
    tables_to_clear = ["Incidents", "Teams", "Shelters", "PendingActions", "Missions", "ActivityEvent", "SimulationEvents", "GovReports"]
    
    for tbl_name in tables_to_clear:
        try:
            tbl = dynamodb.Table(tbl_name)
            scan = tbl.scan()
            with tbl.batch_writer() as batch:
                for item in scan.get("Items", []):
                    # Get primary key
                    key = {}
                    for ks in tbl.key_schema:
                        k_name = ks["AttributeName"]
                        key[k_name] = item[k_name]
                    batch.delete_item(Key=key)
            print(f"  - Cleared {len(scan.get('Items', []))} items from {tbl_name}")
        except Exception as e:
            print(f"  ! Error clearing {tbl_name}: {e}")

    now_ms = int(time.time() * 1000)

    # 2. Seed Nepal Rescue Teams
    print("Seeding Nepal Rescue Fleet...")
    tbl_teams = dynamodb.Table("Teams")
    for tid, name, lat, lng, cap, status, rescued, spec, contact in NEPAL_TEAMS:
        tbl_teams.put_item(
            Item={
                "id": tid,
                "name": name,
                "location": {"lat": D(lat), "lng": D(lng), "label": spec},
                "capacity": cap,
                "status": status,
                "contact": contact,
                "specialization": spec,
                "current_mission_id": None,
                "rescued_total": rescued,
                "updated_at": now_ms,
            }
        )
        print(f"  + Team: {name} (Cap: {cap})")

    # 3. Seed Nepal Shelters
    print("Seeding Nepal Relief Shelters...")
    tbl_shelters = dynamodb.Table("Shelters")
    for sid, name, lat, lng, cap, occ in NEPAL_SHELTERS:
        tbl_shelters.put_item(
            Item={
                "id": sid,
                "name": name,
                "location": {"lat": D(lat), "lng": D(lng)},
                "capacity": cap,
                "current_occupancy": occ,
                "updated_at": now_ms,
            }
        )
        print(f"  + Shelter: {name} ({cap - occ} spaces free)")

    # 4. Seed Nepal Incidents & Approval Cards
    print("Seeding Active Nepal SOS Incidents & Pending Actions...")
    tbl_incidents = dynamodb.Table("Incidents")
    tbl_pending = dynamodb.Table("PendingActions")
    
    for inc in NEPAL_INCIDENTS:
        inc_data = {**inc, "created_at": now_ms, "updated_at": now_ms}
        tbl_incidents.put_item(Item=inc_data)
        
        # Create a pending approval card for the top priority incident
        if inc["id"] == "inc_nepal_101":
            tbl_pending.put_item(
                Item={
                    "id": f"pa_nepal_{inc['id']}",
                    "incident_id": inc["id"],
                    "proposed_team_id": "team_nepal_apf",
                    "state": "PENDING",
                    "reasons": [
                        "APF DISASTER BATTALION is available now",
                        "Boat capacity 16 >= 6 people needed",
                        "Nearest rescue asset: 1.1 km away (ETA ~4 min)",
                    ],
                    "payload": {
                        "incident": inc_data,
                        "team_id": "team_nepal_apf",
                        "team_name": "APF DISASTER BATTALION",
                        "eta_min": 4,
                    },
                    "created_at": now_ms,
                }
            )
        print(f"  + Incident: {inc['id']} - Priority {inc['priority']['score']}/10")

    # 5. Seed Nepal Sensor Telemetry
    print("Seeding Bagmati / Hanumante River Sensor Telemetry...")
    tbl_sensors = dynamodb.Table("SimulationEvents")
    for s in NEPAL_SENSORS:
        tbl_sensors.put_item(Item={**s, "created_at": now_ms})
        print(f"  + Sensor: {s['idempotency_key']}")

    # 6. Seed Official Nepal Advisories
    print("Seeding Official Government Flood Advisories...")
    tbl_reports = dynamodb.Table("GovReports")
    tbl_reports.put_item(
        Item={
            "id": "rep_nepal_001",
            "title": "URGENT: Evacuation Order for Bagmati Riverbank Settlements",
            "body": "Bagmati water level has exceeded the extreme danger threshold (4.85m). All residents within 200m of the river corridor (Balkhu, Kupondole, Sanepa, Thapathali) are urged to evacuate immediately to Dasharath Stadium or Patan Campus shelter.",
            "severity": "CRITICAL",
            "area_text": "Kathmandu & Lalitpur Bagmati Corridor",
            "source": "National Disaster Risk Reduction and Management Authority (NDRRMA)",
            "created_at": now_ms,
        }
    )

    # 7. Log Activity
    activity.log_event(
        actor="system",
        type_="seed_nepal_flood",
        summary="Database reset and seeded with Kathmandu Valley / Nepal Flood Disaster live operational data",
    )

    print("\n[OK] SUCCESS: Database successfully reset and seeded for Nepal Flood Disaster!")

if __name__ == "__main__":
    reset_and_seed()
