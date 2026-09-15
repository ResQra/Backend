"""Generate realistic connected road graph for Rautahat district.
Provides instant offline routing for tactical response without waiting for Overpass.
"""
import json
from pathlib import Path

def generate_rautahat_road_graph():
    out_dir = Path("geo/data")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "road_graph.json"

    # Define connected segments with intermediate points for realism
    roads = [
        # 1. Main Highway: Gaur -> Pipara -> Garuda -> Chandrapur (Highway 35)
        {
            "id": "osm_hwy35_gaur_pipara",
            "name": "Gaur-Pipara Highway",
            "type": "primary",
            "blocked": False,
            "coords": [
                [26.7645, 85.2700],
                [26.7680, 85.2710],
                [26.7750, 85.2760],
                [26.7900, 85.2900],
                [26.8020, 85.3010],
                [26.8120, 85.3080],
                [26.8150, 85.3100]
            ]
        },
        {
            "id": "osm_hwy35_pipara_garuda",
            "name": "Pipara-Garuda Highway",
            "type": "primary",
            "blocked": False,
            "coords": [
                [26.8150, 85.3100],
                [26.8350, 85.3130],
                [26.8550, 85.3160],
                [26.8720, 85.3180],
                [26.8740, 85.3160]
            ]
        },
        {
            "id": "osm_hwy35_garuda_chandrapur",
            "name": "Garuda-Chandrapur Highway",
            "type": "primary",
            "blocked": False,
            "coords": [
                [26.8720, 85.3180],
                [26.9100, 85.3210],
                [26.9600, 85.3260],
                [27.0200, 85.3320],
                [27.0800, 85.3370],
                [27.1250, 85.3400],
                [27.1260, 85.3420]
            ]
        },
        # 2. East-West Highway (Mahendra Highway) at Chandrapur
        {
            "id": "osm_mahendra_hwy_chandrapur",
            "name": "East-West Highway Chandranigahapur",
            "type": "trunk",
            "blocked": False,
            "coords": [
                [27.1250, 85.2900],
                [27.1250, 85.3200],
                [27.1250, 85.3400],
                [27.1250, 85.3700],
                [27.1250, 85.4000]
            ]
        },
        # 3. Gaur City Core & Ring Road Network
        {
            "id": "osm_gaur_bairgania_border_road",
            "name": "Gaur-Bairgania Border Road",
            "type": "secondary",
            "blocked": False,
            "coords": [
                [26.7600, 85.2720],
                [26.7620, 85.2760],
                [26.7640, 85.2750],
                [26.7645, 85.2700],
                [26.7660, 85.2740]
            ]
        },
        {
            "id": "osm_gaur_east_ward4_access",
            "name": "Gaur Ward 4 Embankment Access",
            "type": "residential",
            "blocked": False,
            "coords": [
                [26.7620, 85.2760],
                [26.7640, 85.2750],
                [26.7660, 85.2740],
                [26.7670, 85.2850],
                [26.7670, 85.2920]
            ]
        },
        {
            "id": "osm_gaur_west_ring_road",
            "name": "Gaur West Ring Road",
            "type": "secondary",
            "blocked": False,
            "coords": [
                [26.7600, 85.2600],
                [26.7620, 85.2580],
                [26.7645, 85.2700],
                [26.7660, 85.2740],
                [26.7680, 85.2710],
                [26.7690, 85.2670]
            ]
        },
        # 4. Gaur to Tikuliya Ghat (Lalbakaiya Corridor)
        {
            "id": "osm_gaur_tikuliya_link",
            "name": "Gaur-Tikuliya Ghat Road",
            "type": "secondary",
            "blocked": False,
            "coords": [
                [26.7690, 85.2670],
                [26.7720, 85.2600],
                [26.7780, 85.2500],
                [26.7830, 85.2430],
                [26.7840, 85.2410],
                [26.7860, 85.2390]
            ]
        },
        # 5. Tikuliya to Garuda Cross-District Link
        {
            "id": "osm_tikuliya_garuda_crosslink",
            "name": "Tikuliya-Garuda Feeder",
            "type": "tertiary",
            "blocked": False,
            "coords": [
                [26.7840, 85.2410],
                [26.8100, 85.2600],
                [26.8400, 85.2850],
                [26.8720, 85.3180]
            ]
        },
    ]

    bridges = [
        {
            "id": "osm_bridge_bagmati_gaur_east",
            "name": "Bagmati Embankment Crossing Bridge",
            "type": "bridge",
            "blocked": False,
            "coords": [
                [26.7660, 85.2740],
                [26.7670, 85.2850]
            ]
        },
        {
            "id": "osm_bridge_lalbakaiya_tikuliya",
            "name": "Tikuliya Ghat Lalbakaiya Bridge",
            "type": "bridge",
            "blocked": False,
            "coords": [
                [26.7830, 85.2430],
                [26.7840, 85.2410]
            ]
        }
    ]

    payload = {
        "area": "rautahat",
        "description": "Rautahat District Road & Infrastructure Graph (ResQra Digital Twin)",
        "roads": roads,
        "bridges": bridges
    }

    out_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Generated {out_file} with {len(roads)} roads and {len(bridges)} bridges.")

if __name__ == "__main__":
    generate_rautahat_road_graph()
