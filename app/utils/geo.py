import math

_BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"

# Operational district bbox (Rautahat + margin for border villages).
# SOS outside this box is out-of-area: scored 0 and kept out of the
# rescue queue instead of competing with real district emergencies.
RAUTAHAT_BBOX = (26.60, 85.13, 27.20, 85.47)


def in_operational_area(lat, lng) -> bool:
    """True when a point falls inside the district bbox."""
    try:
        sw_lat, sw_lng, ne_lat, ne_lng = RAUTAHAT_BBOX
        return sw_lat <= float(lat) <= ne_lat and sw_lng <= float(lng) <= ne_lng
    except (TypeError, ValueError):
        return False


# Cheap text pre-filter: places unambiguously far outside the district.
# Local names always win (checked first) so "coming from Delhi to Gaur"
# stays in-district. Anything unmatched returns UNKNOWN and falls through
# to exact geocode + bbox check — never a false drop.
DISTRICT_KEYWORDS = (
    "rautahat", "gaur", "tikuliya", "garuda", "chandrapur", "chandranigahapur",
    "juddha", "bagmati", "lalbakaiya", "bairgania", "katahariya", "rajpur",
    "baudhimai", "rajdevi", "brindaban", "gadhimai", "madhesh",
    "ward no", "ward ",
)

FAR_PLACE_KEYWORDS = (
    "delhi", "new delhi", "mumbai", "kolkata", "calcutta", "chennai", "bangalore",
    "bengaluru", "hyderabad", "kathmandu", "lalitpur", "bhaktapur", "pokhara",
    "biratnagar", "janakpur", "dharan", "butwal", "nepalgunj", "dhangadhi",
    "patna", "bihar", "uttar pradesh", "jharkhand", "kolkata",
)


def jurisdiction_hint_from_text(text: str | None) -> str:
    """IN_DISTRICT | OUT_OF_DISTRICT | UNKNOWN — text only, no network.

    Mirrors agents/resqra_agents/tools/geo.py (keep the keyword lists in
    sync when editing either).
    """
    import re

    lowered = f" {(text or '').lower()} "
    if any(re.search(rf"\b{re.escape(k)}\b", lowered) for k in DISTRICT_KEYWORDS):
        return "IN_DISTRICT"
    if any(re.search(rf"\b{re.escape(k)}\b", lowered) for k in FAR_PLACE_KEYWORDS):
        return "OUT_OF_DISTRICT"
    return "UNKNOWN"


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Distance between two points — used by nearest-shelter and allocation."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def geohash_encode(lat: float, lng: float, precision: int = 5) -> str:
    """Precision 5 ≈ 5km cell — the 'geohash trick' from BRAINSTORM §4.5.

    Turns area clustering into simple key counting; no geo library needed.
    """
    lat_range = [-90.0, 90.0]
    lng_range = [-180.0, 180.0]
    bits = [16, 8, 4, 2, 1]
    bit = ch = 0
    even = True
    out = ""
    while len(out) < precision:
        if even:
            mid = (lng_range[0] + lng_range[1]) / 2
            if lng >= mid:
                ch |= bits[bit]
                lng_range[0] = mid
            else:
                lng_range[1] = mid
        else:
            mid = (lat_range[0] + lat_range[1]) / 2
            if lat >= mid:
                ch |= bits[bit]
                lat_range[0] = mid
            else:
                lat_range[1] = mid
        even = not even
        if bit < 4:
            bit += 1
        else:
            out += _BASE32[ch]
            bit = ch = 0
    return out
