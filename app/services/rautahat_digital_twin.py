"""Rautahat District Flood Management Digital Twin Service.

Exposes structured GIS, Hydrology, Flood Extent, Infrastructure, and AI Feature
data for Rautahat District (Gaur - Bagmati & Lalbakaiya Basin).
"""

from __future__ import annotations
import json
import pathlib
from typing import Any

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[3]
TWIN_ROOT = PROJECT_ROOT / "data" / "rautahat_digital_twin"
if not TWIN_ROOT.exists():
    TWIN_ROOT = PROJECT_ROOT / "Backend" / "data" / "rautahat_digital_twin"




def load_geojson(subfolder: str, filename: str) -> dict[str, Any]:
    file_path = TWIN_ROOT / subfolder / filename
    if not file_path.exists():
        return {"type": "FeatureCollection", "features": []}
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_district_boundary() -> dict[str, Any]:
    return load_geojson("01_boundary", "rautahat_district.geojson")


def get_municipalities_geojson() -> dict[str, Any]:
    return load_geojson("01_boundary", "rautahat_municipalities.geojson")


def get_rivers_geojson() -> dict[str, Any]:
    return load_geojson("03_hydrology", "rivers.geojson")


def get_embankments_geojson() -> dict[str, Any]:
    return load_geojson("03_hydrology", "embankment_breaches.geojson")


def get_flood_2024_geojson() -> dict[str, Any]:
    return load_geojson("06_flood_history", "flood_2024_extent.geojson")


def get_infrastructure_geojson() -> dict[str, Any]:
    return load_geojson("08_infrastructure", "infrastructure_shelters.geojson")


def get_rescue_fleet_geojson() -> dict[str, Any]:
    return load_geojson("09_rescue_resources", "rescue_fleet.geojson")


def get_digital_twin_summary() -> dict[str, Any]:
    return {
        "district": "Rautahat",
        "province": "Madhesh Province",
        "country": "Nepal",
        "headquarters": "Gaur Municipality",
        "total_municipalities": 18,
        "lead_rescue_unit": "GAUR BAGMATI WATER RESCUE UNIT (Rautahat)",
        "active_defcon_level": "DEFCON 1 (CRITICAL RED ALERT)",
        "monitored_basins": ["Bagmati River Corridor", "Lalbakaiya River Corridor", "Jhanjh Stream"],
        "critical_gauges": [
            {"station": "Bagmati Gaur Bridge", "level_m": 6.80, "danger_level_m": 4.50, "status": "DANGER_OVERFLOW"},
            {"station": "Lalbakaiya Tikuliya", "level_m": 5.40, "danger_level_m": 3.80, "status": "EMBANKMENT_BREACH"},
        ],
        "hdx_cod_ab_aligned": True,
        "hdx_hot_npl_aligned": True,
    }
