import math

_BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"


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
