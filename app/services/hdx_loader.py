"""HDX / HOT (Humanitarian OpenStreetMap Team) Data Loader for Rautahat District, Nepal.

Focuses exclusively on Rautahat District (Gaur - Bagmati & Lalbakaiya Basin):
- Health facilities and designated emergency relief shelters in Rautahat
- Active flood waterways: Bagmati River and Lalbakaiya River
- Critical bridge causeways: Tikuliya Bridge, Gaur Ring Road Sluice Gate, Garuda Causeway
"""

from __future__ import annotations
from decimal import Decimal

def D(x: float) -> Decimal:
    return Decimal(str(round(x, 6)))

# ---------------------------------------------------------------------------
# HDX / HOT HEALTH FACILITIES & SHELTERS (Rautahat District)
# ---------------------------------------------------------------------------
HOT_RAUTAHAT_HEALTH_FACILITIES = [
    {
        "id": "hdx_health_gaur_district",
        "name": "Gaur District Hospital & Trauma Centre",
        "district": "rautahat",
        "sector": "gaur_urban",
        "location": {"lat": D(26.7640), "lng": D(85.2780), "label": "Gaur Municipality Ward 3, Rautahat"},
        "capacity": 1400,
        "type": "District Referral Hospital & Boat Landing Post",
        "emergency_beds": 160,
        "hdx_source": "hotosm_npl_health_facilities",
    },
    {
        "id": "hdx_shelter_gaur_stadium",
        "name": "Rautahat District Sports Stadium Shelter",
        "district": "rautahat",
        "sector": "gaur_urban",
        "location": {"lat": D(26.7680), "lng": D(85.2810), "label": "Gaur High Ground Stadium"},
        "capacity": 3000,
        "type": "Primary Evacuation Camp",
        "emergency_beds": 400,
        "hdx_source": "hotosm_npl_buildings_polygons",
    },
    {
        "id": "hdx_shelter_juddha_school",
        "name": "Juddha Higher Secondary School Relief Camp",
        "district": "rautahat",
        "sector": "gaur_urban",
        "location": {"lat": D(26.7590), "lng": D(85.2720), "label": "Gaur Ward 2, Court Road"},
        "capacity": 1800,
        "type": "Designated Community Shelter",
        "emergency_beds": 220,
        "hdx_source": "hotosm_npl_buildings_polygons",
    },
    {
        "id": "hdx_shelter_tikuliya_school",
        "name": "Tikuliya Ghat Community Relief Point",
        "district": "rautahat",
        "sector": "lalbakaiya_tikuliya",
        "location": {"lat": D(26.7860), "lng": D(85.2440), "label": "Tikuliya Embankment Camp"},
        "capacity": 950,
        "type": "Riverbank Evacuation Post",
        "emergency_beds": 110,
        "hdx_source": "hotosm_npl_buildings_polygons",
    },
    {
        "id": "hdx_shelter_garuda_complex",
        "name": "Garuda Municipal Evacuation Complex",
        "district": "rautahat",
        "sector": "garuda",
        "location": {"lat": D(26.9240), "lng": D(85.3110), "label": "Garuda Bazaar, Rautahat"},
        "capacity": 2200,
        "type": "Central Plain Relief Hub",
        "emergency_beds": 250,
        "hdx_source": "hotosm_npl_buildings_polygons",
    },
    {
        "id": "hdx_health_chandrapur_hospital",
        "name": "Chandranigahapur Community Hospital & Highway Hub",
        "district": "rautahat",
        "sector": "chandrapur",
        "location": {"lat": D(27.1260), "lng": D(85.3420), "label": "Chandrapur East-West Highway"},
        "capacity": 2500,
        "type": "Highway Staging Hospital",
        "emergency_beds": 300,
        "hdx_source": "hotosm_npl_health_facilities",
    },
]

# ---------------------------------------------------------------------------
# HDX / HOT WATERWAYS & RIVER FLOOD CORRIDORS (Rautahat District)
# ---------------------------------------------------------------------------
HOT_RAUTAHAT_WATERWAYS = [
    {
        "id": "river_bagmati_rautahat",
        "name": "Bagmati River Basin (Gaur Embankment Corridor)",
        "district": "rautahat",
        "danger_level_m": 4.5,
        "current_surge_m": 6.8,
        "status": "CATASTROPHIC_OVERFLOW_RED_ALERT",
        "hdx_code": "hotosm_npl_waterways_bagmati",
        "coordinates": [[27.05, 85.35], [26.88, 85.32], [26.76, 85.28]],
    },
    {
        "id": "river_lalbakaiya_rautahat",
        "name": "Lalbakaiya River (Tikuliya Embankment Breach)",
        "district": "rautahat",
        "danger_level_m": 3.8,
        "current_surge_m": 5.4,
        "status": "EMBANKMENT_BREACHED",
        "hdx_code": "hotosm_npl_waterways_lalbakaiya",
        "coordinates": [[26.95, 85.22], [26.80, 85.25], [26.74, 85.27]],
    },
]

def get_hdx_shelters() -> list[dict]:
    return HOT_RAUTAHAT_HEALTH_FACILITIES

def get_hdx_waterways() -> list[dict]:
    return HOT_RAUTAHAT_WATERWAYS
