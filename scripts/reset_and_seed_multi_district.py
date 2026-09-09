"""Reset DynamoDB tables and seed realistic multi-district flood disaster data.

3 Active Live Corridors:
1. Kathmandu Valley, Nepal (Bagmati & Hanumante Basins) - DEFCON 1 ACTIVE
2. Patna, Bihar (Ganga & Punpun Basins) - DEFCON 1 ACTIVE
3. Guwahati, Assam (Brahmaputra & Deepor Beel Basins) - DEFCON 1 ACTIVE
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

def D(x: float) -> Decimal:
    return Decimal(str(round(x, 6)))

# ===========================================================================
# 1. KATHMANDU VALLEY, NEPAL SEED DATA
# ===========================================================================
NEPAL_TEAMS = [
    ("team_nepal_apf", "APF DISASTER BATTALION", 27.6890, 85.2950, 16, "AVAILABLE", 34, "Armed Police Force Boat Rescue Unit", "Radio 142.5 MHz", "kathmandu"),
    ("team_nepal_army", "NEPAL ARMY RESCUE HELI/BOAT", 27.6980, 85.3250, 20, "AVAILABLE", 52, "Special Disaster Response Command", "Radio 148.1 MHz", "kathmandu"),
    ("team_nepal_police", "NEPAL POLICE QUICK DISPATCH", 27.6810, 85.3120, 8, "AVAILABLE", 19, "Urban Flood Extraction Squad", "+977-1-4412780", "kathmandu"),
    ("team_redcross_nepal", "NEPAL RED CROSS EVAC UNIT", 27.6750, 85.3410, 12, "AVAILABLE", 28, "Medical & Amphibious Evacuation", "+977-1-4270650", "kathmandu"),
    ("team_lalitpur_metro", "LALITPUR DISASTER RESCUE", 27.6640, 85.3150, 10, "AVAILABLE", 15, "Inflatable Heavy Raft Unit", "Radio 145.2 MHz", "kathmandu"),
    ("team_bhaktapur_squad", "BHAKTAPUR HANUMANTE TEAM", 27.6720, 85.4280, 6, "AVAILABLE", 11, "Light Riverine Inflatable Raft", "Radio 146.8 MHz", "kathmandu"),
]

NEPAL_SHELTERS = [
    ("shelter_dasharath", "Dasharath Stadium Sports Complex, Tripureshwor", 27.6948, 85.3135, 1500, 480, "kathmandu"),
    ("shelter_patan_campus", "Patan Multiple Campus Ground, Patan Dhoka", 27.6775, 85.3210, 800, 260, "kathmandu"),
    ("shelter_tu_kirtipur", "Tribhuvan University Gymnasium, Kirtipur", 27.6790, 85.2890, 1200, 390, "kathmandu"),
    ("shelter_bhaktapur", "Bhaktapur Multiple Campus Ground, Dudhpati", 27.6715, 85.4290, 600, 195, "kathmandu"),
    ("shelter_st_xaviers", "St. Xavier's College Campus, Maitighar", 27.6920, 85.3220, 500, 140, "kathmandu"),
    ("shelter_boudha", "Hyolmo Monastery Community Center, Boudha", 27.7210, 85.3620, 700, 220, "kathmandu"),
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
        "location": {"lat": D(27.6854), "lng": D(85.2912), "label": "Balkhu River Bridge", "confidence": D(0.95)},
        "priority": {"score": D(9), "level": "CRITICAL", "reasons": ["Urgency HIGH (+4)", "6 people (+2)", "Children & elderly (+2)", "Area hotspot (+1)"]},
        "status": "PRIORITIZED",
        "district": "kathmandu",
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
        "district": "kathmandu",
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
        "district": "kathmandu",
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
        "district": "kathmandu",
    },
    {
        "id": "inc_nepal_105",
        "raw_text": "Hanumante river overflow in Radhe Radhe Bhaktapur, 8 people trapped inside ground floor grocery store",
        "people": 8,
        "vulnerabilities": ["elderly"],
        "urgency": "HIGH",
        "water_rising": True,
        "location_text": "Radhe Radhe, Bhaktapur",
        "location": {"lat": D(27.6740), "lng": D(85.4020), "label": "Radhe Radhe Chowk", "confidence": D(0.91)},
        "priority": {"score": D(8), "level": "CRITICAL", "reasons": ["Urgency HIGH (+4)", "8 people (+3)", "Hanumante flood basin (+1)"]},
        "status": "PRIORITIZED",
        "district": "kathmandu",
    },
    {
        "id": "inc_nepal_106",
        "raw_text": "Chobhar gorge road blocked by landslide, 2 vehicle passengers stranded safely on upper ridge",
        "people": 2,
        "vulnerabilities": [],
        "urgency": "LOW",
        "water_rising": False,
        "location_text": "Chobhar Gorge Road, Kirtipur",
        "location": {"lat": D(27.6600), "lng": D(85.2850), "label": "Chobhar Gorge", "confidence": D(0.85)},
        "priority": {"score": D(2), "level": "LOW", "reasons": ["Urgency LOW (+1)", "Safe location (+1)"]},
        "status": "VERIFIED",
        "district": "kathmandu",
    },
    {
        "id": "inc_nepal_107",
        "raw_text": "Patan Hospital maternity ward power generator submerged, need urgent evacuation assistance for 3 new mothers and infants",
        "people": 6,
        "vulnerabilities": ["pregnant", "children", "ill"],
        "urgency": "HIGH",
        "water_rising": True,
        "location_text": "Lagankhel, Patan Hospital corridor",
        "location": {"lat": D(27.6680), "lng": D(85.3230), "label": "Patan Hospital Lagankhel", "confidence": D(0.94)},
        "priority": {"score": D(10), "level": "CRITICAL", "reasons": ["Urgency HIGH (+4)", "Mothers & infants (+3)", "Medical infrastructure failure (+3)"]},
        "status": "PRIORITIZED",
        "district": "kathmandu",
    },
]

# ===========================================================================
# 2. PATNA, BIHAR SEED DATA (GANGES / KOSI BASIN)
# ===========================================================================
PATNA_TEAMS = [
    ("team_patna_ndrf_9", "9TH BN NDRF BIHTA SQUAD", 25.5680, 84.8850, 24, "AVAILABLE", 65, "Heavy Inflatable Motorboat Unit", "Radio 143.2 MHz", "patna"),
    ("team_patna_sdrf_digha", "SDRF BIHAR DIGHA GHAT UNIT", 25.6420, 85.1050, 16, "AVAILABLE", 42, "Deep River Rescue Boat Wing", "+91-612-2217350", "patna"),
    ("team_patna_danapur_army", "DANAPUR ARMY CANTONMENT RAFT", 25.6320, 85.0450, 20, "AVAILABLE", 38, "Amphibious Military Vehicle & Raft", "Radio 148.4 MHz", "patna"),
    ("team_patna_police_gandhi", "GANDHI GHAT RESCUE POST", 25.6210, 85.1720, 10, "AVAILABLE", 22, "Fast Water Evacuation Patrol", "+91-612-2300100", "patna"),
    ("team_patna_redcross", "BIHAR RED CROSS MEDICAL RAFT", 25.6080, 85.1430, 8, "AVAILABLE", 17, "Mobile Triage & Trauma Raft", "Radio 145.6 MHz", "patna"),
]

PATNA_SHELTERS = [
    ("shelter_patna_gandhi_maidan", "Gandhi Maidan Relief Mega-Camp, Central Patna", 25.6180, 85.1440, 3000, 920, "patna"),
    ("shelter_patna_patliputra", "Patliputra Sports Complex Gymnasium, Kankarbagh", 25.5920, 85.1580, 1800, 610, "patna"),
    ("shelter_patna_science_college", "Patna Science College Ground, Ashok Rajpath", 25.6200, 85.1750, 1200, 340, "patna"),
    ("shelter_patna_danapur_school", "Danapur Railway High School Camp", 25.6280, 85.0510, 800, 250, "patna"),
    ("shelter_patna_polytechnic", "Govt Polytechnic Ground, Gulzarbagh", 25.5980, 85.2020, 900, 280, "patna"),
]

PATNA_INCIDENTS = [
    {
        "id": "inc_patna_201",
        "raw_text": "Ganga river breached temporary bundh near Digha Ghat, 7 people trapped on rooftop including 1 pregnant woman and 2 toddlers. Water level rising fast!",
        "people": 7,
        "vulnerabilities": ["pregnant", "children"],
        "urgency": "HIGH",
        "water_rising": True,
        "location_text": "Digha Ghat riverside, Patna",
        "location": {"lat": D(25.6450), "lng": D(85.1020), "label": "Digha Ghat Bundh", "confidence": D(0.96)},
        "priority": {"score": D(10), "level": "CRITICAL", "reasons": ["Urgency HIGH (+4)", "7 people (+2)", "Pregnant & toddlers (+3)", "River bundh breach (+1)"]},
        "status": "PRIORITIZED",
        "district": "patna",
    },
    {
        "id": "inc_patna_202",
        "raw_text": "Rajendra Nagar overbridge underpass completely flooded 8 feet deep, 4 people stuck inside a stranded ambulance with oxygen running low!",
        "people": 4,
        "vulnerabilities": ["ill", "elderly"],
        "urgency": "HIGH",
        "water_rising": True,
        "location_text": "Rajendra Nagar Bridge Underpass, Patna",
        "location": {"lat": D(25.6010), "lng": D(85.1610), "label": "Rajendra Nagar Underpass", "confidence": D(0.93)},
        "priority": {"score": D(9), "level": "CRITICAL", "reasons": ["Urgency HIGH (+4)", "Ambulance trapped (+3)", "Critical medical distress (+2)"]},
        "status": "PRIORITIZED",
        "district": "patna",
    },
    {
        "id": "inc_patna_203",
        "raw_text": "Danapur Diara island village submerged under Punpun-Ganga backflow, 12 villagers gathered on temple terrace without drinking water",
        "people": 12,
        "vulnerabilities": ["elderly", "children"],
        "urgency": "HIGH",
        "water_rising": True,
        "location_text": "Diara Riverine Settlement, Danapur",
        "location": {"lat": D(25.6550), "lng": D(85.0600), "label": "Danapur Diara Island", "confidence": D(0.91)},
        "priority": {"score": D(9), "level": "CRITICAL", "reasons": ["Urgency HIGH (+4)", "12 people (+3)", "Island isolation (+2)"]},
        "status": "PRIORITIZED",
        "district": "patna",
    },
    {
        "id": "inc_patna_204",
        "raw_text": "Kankarbagh Colony Road No. 4 ground floors waterlogged 3 feet, 3 elderly residents safe on upper floor requesting food packets",
        "people": 3,
        "vulnerabilities": ["elderly"],
        "urgency": "MEDIUM",
        "water_rising": False,
        "location_text": "Kankarbagh Colony, Patna",
        "location": {"lat": D(25.5950), "lng": D(85.1520), "label": "Kankarbagh Colony", "confidence": D(0.89)},
        "priority": {"score": D(4), "level": "MEDIUM", "reasons": ["Urgency MEDIUM (+2)", "3 people (+1)", "Elderly present (+1)"]},
        "status": "VERIFIED",
        "district": "patna",
    },
    {
        "id": "inc_patna_205",
        "raw_text": "Kurji Holy Family Hospital approach road waterlogged, 2 security staff safe at main gate directing incoming traffic",
        "people": 2,
        "vulnerabilities": [],
        "urgency": "LOW",
        "water_rising": False,
        "location_text": "Kurji Hospital Road, Patna",
        "location": {"lat": D(25.6360), "lng": D(85.1180), "label": "Kurji Hospital Gate", "confidence": D(0.88)},
        "priority": {"score": D(2), "level": "LOW", "reasons": ["Urgency LOW (+1)", "Low risk (+1)"]},
        "status": "VERIFIED",
        "district": "patna",
    },
]

# ===========================================================================
# 3. GUWAHATI, ASSAM SEED DATA (BRAHMAPUTRA BASIN)
# ===========================================================================
GUWAHATI_TEAMS = [
    ("team_guwahati_ndrf_1", "1ST BN NDRF PATGAON SQUAD", 26.1150, 91.6420, 22, "AVAILABLE", 58, "Heavy Flood Inflatable Motorboat", "Radio 144.1 MHz", "guwahati"),
    ("team_guwahati_sdrf_pandu", "SDRF ASSAM PANDU PORT WING", 26.1750, 91.6880, 18, "AVAILABLE", 49, "Deep Brahmaputra Current Specialist", "+91-361-2237000", "guwahati"),
    ("team_guwahati_army_amphib", "EASTERN COMMAND AMPHIBIOUS SQUAD", 26.1550, 91.7550, 25, "AVAILABLE", 62, "Armored Amphibious Evac Craft", "Radio 149.2 MHz", "guwahati"),
    ("team_guwahati_asdma_uzan", "ASDMA DISASTER UNIT UZANBAZAR", 26.1920, 91.7650, 12, "AVAILABLE", 31, "Riverine Inflatable Raft", "+91-361-2730000", "guwahati"),
    ("team_guwahati_kamrup_patrol", "KAMRUP METRO QUICK RESCUE", 26.1420, 91.7920, 8, "AVAILABLE", 19, "Urban Waterlogged Extraction Raft", "Radio 146.4 MHz", "guwahati"),
]

GUWAHATI_SHELTERS = [
    ("shelter_guwahati_sarusajai", "Sarusajai Stadium Relief Camp, Lokhra", 26.1120, 91.7580, 2500, 780, "guwahati"),
    ("shelter_guwahati_cotton_univ", "Cotton University Indoor Stadium, Panbazar", 26.1880, 91.7510, 1500, 490, "guwahati"),
    ("shelter_guwahati_commerce_col", "Guwahati Commerce College Ground, Chandmari", 26.1820, 91.7820, 1000, 310, "guwahati"),
    ("shelter_guwahati_jalukbari", "Gauhati University Campus Camp, Jalukbari", 26.1520, 91.6620, 1200, 380, "guwahati"),
    ("shelter_guwahati_noonmati", "Noonmati Refinery Community Hall", 26.1950, 91.8150, 700, 210, "guwahati"),
]

GUWAHATI_INCIDENTS = [
    {
        "id": "inc_guwahati_301",
        "raw_text": "Brahmaputra river surge crossed danger mark at Pandu Ghat, 8 fishermen families marooned on thatched roof, strong river current!",
        "people": 8,
        "vulnerabilities": ["elderly", "children"],
        "urgency": "HIGH",
        "water_rising": True,
        "location_text": "Pandu Ghat Old Port, Guwahati",
        "location": {"lat": D(26.1780), "lng": D(91.6840), "label": "Pandu Ghat Riverbank", "confidence": D(0.95)},
        "priority": {"score": D(10), "level": "CRITICAL", "reasons": ["Urgency HIGH (+4)", "8 people (+3)", "Extreme Brahmaputra current (+3)"]},
        "status": "PRIORITIZED",
        "district": "guwahati",
    },
    {
        "id": "inc_guwahati_302",
        "raw_text": "Deepor Beel wetland overflow submerged Pamohi village road, 5 villagers stranded in cowshed with rising mud water",
        "people": 5,
        "vulnerabilities": ["children"],
        "urgency": "HIGH",
        "water_rising": True,
        "location_text": "Pamohi Village, Deepor Beel, Guwahati",
        "location": {"lat": D(26.1280), "lng": D(91.6550), "label": "Deepor Beel Pamohi", "confidence": D(0.92)},
        "priority": {"score": D(9), "level": "CRITICAL", "reasons": ["Urgency HIGH (+4)", "5 people (+2)", "Wetland flash surge (+3)"]},
        "status": "PRIORITIZED",
        "district": "guwahati",
    },
    {
        "id": "inc_guwahati_303",
        "raw_text": "Anil Nagar & Nabin Nagar urban flood 4 feet high, 1 stroke patient unable to walk trapped in ground floor flat",
        "people": 3,
        "vulnerabilities": ["disabled", "elderly", "ill"],
        "urgency": "HIGH",
        "water_rising": True,
        "location_text": "Anil Nagar By-lane 3, Guwahati",
        "location": {"lat": D(26.1720), "lng": D(91.7740), "label": "Anil Nagar Residential", "confidence": D(0.94)},
        "priority": {"score": D(9), "level": "CRITICAL", "reasons": ["Urgency HIGH (+4)", "Paralyzed stroke patient (+3)", "Urban drainage blockage (+2)"]},
        "status": "PRIORITIZED",
        "district": "guwahati",
    },
    {
        "id": "inc_guwahati_304",
        "raw_text": "Bharalu river sluice gate overflowed, water entered market area, 4 shopkeepers safely moved stock to 1st floor",
        "people": 4,
        "vulnerabilities": [],
        "urgency": "MEDIUM",
        "water_rising": False,
        "location_text": "Bharalumukh Market, Guwahati",
        "location": {"lat": D(26.1750), "lng": D(91.7320), "label": "Bharalumukh Sluice Gate", "confidence": D(0.88)},
        "priority": {"score": D(4), "level": "MEDIUM", "reasons": ["Urgency MEDIUM (+2)", "4 people (+1)", "Safe upper floor (+1)"]},
        "status": "VERIFIED",
        "district": "guwahati",
    },
    {
        "id": "inc_guwahati_305",
        "raw_text": "Noonmati hillside minor landslide blocked access lane, 2 pedestrians safe on main highway waiting for clearing",
        "people": 2,
        "vulnerabilities": [],
        "urgency": "LOW",
        "water_rising": False,
        "location_text": "Noonmati Hill Road, Guwahati",
        "location": {"lat": D(26.1920), "lng": D(91.8100), "label": "Noonmati Hill Road", "confidence": D(0.85)},
        "priority": {"score": D(2), "level": "LOW", "reasons": ["Urgency LOW (+1)", "Low hazard (+1)"]},
        "status": "VERIFIED",
        "district": "guwahati",
    },
]


def reset_and_seed():
    print("=" * 60)
    print("ResQra Multi-District Database Reset & Seed")
    print("Seeding 3 Live Disaster Corridors: Kathmandu, Patna, Guwahati")
    print("=" * 60)

    db = boto3.resource("dynamodb", **dynamo_kwargs())

    # 1. Clear Existing Data (without clearing users table to preserve logins)
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

    # 2. Seed Admin Users if missing
    from app.auth.security import hash_password
    if not users.find_by_username("resqra-admin"):
        users.create_user(
            username="resqra-admin",
            password_hash=hash_password("resqra-admin-123"),
            name="ResQra Command Officer",
            role="coordinator",
        )
        print("  [OK] Created resqra-admin account")
    else:
        print("  [OK] resqra-admin account verified")

    if not users.find_by_username("coordinator"):
        users.create_user(
            username="coordinator",
            password_hash=hash_password("coordinator-123"),
            name="Regional Operations Chief",
            role="coordinator",
        )
        print("  [OK] Created coordinator account")

    # 3. Seed All Rescue Teams across 3 Districts
    all_teams = NEPAL_TEAMS + PATNA_TEAMS + GUWAHATI_TEAMS
    for tid, name, lat, lng, cap, st, res_cnt, spec, contact, district in all_teams:
        teams.put_team({
            "id": tid,
            "name": name,
            "capacity": cap,
            "status": st,
            "rescued_total": res_cnt,
            "specialization": spec,
            "contact": contact,
            "district": district,
            "location": {"lat": D(lat), "lng": D(lng), "label": f"{name} Base", "updated_at": int(time.time() * 1000)},
        })
    print(f"  [OK] Seeded {len(all_teams)} Rescue Teams across Nepal, Patna, and Guwahati")

    # 4. Seed All Shelters
    all_shelters = NEPAL_SHELTERS + PATNA_SHELTERS + GUWAHATI_SHELTERS
    for sid, name, lat, lng, cap, occ, district in all_shelters:
        shelters.put_shelter({
            "id": sid,
            "name": name,
            "capacity": cap,
            "current_occupancy": occ,
            "district": district,
            "location": {"lat": D(lat), "lng": D(lng), "label": name},
            "supplies": {"food_days": 5, "water_litres": 3000, "medical_kits": 25},
        })
    print(f"  [OK] Seeded {len(all_shelters)} Emergency Shelters")

    # 5. Seed All Incidents
    all_incidents = NEPAL_INCIDENTS + PATNA_INCIDENTS + GUWAHATI_INCIDENTS
    for inc in all_incidents:
        inc["created_at"] = int((time.time() - 3600) * 1000)
        inc["updated_at"] = int(time.time() * 1000)
        inc["pending_actions"] = []
        incidents.create_incident(inc)
    print(f"  [OK] Seeded {len(all_incidents)} Live Distress Calls across all 3 districts")

    # 6. Seed Simulation Sensor Spikes
    from app.db.repos import simulation_events
    sensor_events = [
        # Nepal
        {"event_type": "WATER_LEVEL", "payload": {"lat": D(27.6854), "lng": D(85.2912), "level": "UNSAFE", "value": D(4.85), "note": "Bagmati River Balkhu gauge peak (+1.85m overflow)", "district": "kathmandu"}},
        {"event_type": "BRIDGE_BLOCKED", "payload": {"lat": D(27.6620), "lng": D(85.3110), "level": "BLOCKED", "note": "Nakkhu river suspension bridge submerged", "district": "kathmandu"}},
        # Patna
        {"event_type": "WATER_LEVEL", "payload": {"lat": D(25.6450), "lng": D(85.1020), "level": "UNSAFE", "value": D(49.80), "note": "Ganga River Digha Ghat gauge (+1.2m above Red Danger Level)", "district": "patna"}},
        {"event_type": "ROAD_BLOCKED", "payload": {"lat": D(25.6010), "lng": D(85.1610), "level": "BLOCKED", "note": "Rajendra Nagar underpass 8ft water accumulation", "district": "patna"}},
        # Guwahati
        {"event_type": "WATER_LEVEL", "payload": {"lat": D(26.1780), "lng": D(91.6840), "level": "UNSAFE", "value": D(50.20), "note": "Brahmaputra River Pandu Port gauge (+0.52m above Red Line)", "district": "guwahati"}},
        {"event_type": "ROAD_BLOCKED", "payload": {"lat": D(26.1280), "lng": D(91.6550), "level": "BLOCKED", "note": "Pamohi access road inundated by Deepor Beel backflow", "district": "guwahati"}},
    ]
    for se in sensor_events:
        idem_key = f"sensor_{se['event_type']}_{int(time.time()*1000)}_{abs(hash(str(se['payload'])))}"
        simulation_events.put_event(idem_key, se["event_type"], se["payload"])
    print(f"  [OK] Seeded {len(sensor_events)} Hydrological & Road Blockage Sensors")

    # 7. Seed Official Advisory Reports
    reports.create_report(
        title="RED ALERT: Catastrophic River Basins Overflow (Nepal, Bihar, Assam)",
        body="Emergency operations centers activated across Kathmandu (Bagmati), Patna (Ganges), and Guwahati (Brahmaputra). All available boat units deployed.",
        severity="CRITICAL",
        area_text="Kathmandu Valley, Patna Urban, Guwahati Metro",
        source="Joint Multi-Agency Disaster Coordination Center",
    )
    print("  [OK] Seeded Official Emergency Bulletins")
    print("=" * 60)
    print("Multi-District Database Ready! All 3 Corridors Live.")
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
    reset_and_seed()
