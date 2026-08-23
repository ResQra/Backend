"""Geocoding: OSM Nominatim (primary) + Photon (fuzzy fallback), no API keys.

Nominatim is precise but literal — Indian transliteration variants
("Tariyani" vs the official "Tariani") return nothing. Photon tolerates
near-matches, so the chain is: Nominatim first; on no result, Photon with
token-level fuzzy scoring (y/i normalization etc.) and a reduced
confidence score. F02 rule holds: nothing found → None → caller flags
the incident for coordinator review. We never guess silently.
"""

import asyncio
import time

import httpx

_HEADERS = {"User-Agent": "ResQra/1.0 (flood-response hackathon demo; contact: team@resqra)"}
_MIN_INTERVAL = 1.1
_lock = asyncio.Lock()
_last_call = 0.0

# demo-region bias (Bihar) for Photon ranking
_BIAS_LAT, _BIAS_LNG = 25.9, 85.4


def _norm(word: str) -> str:
    """Normalize a token for fuzzy comparison (common Indic transliterations)."""
    w = word.lower().strip(",.")
    w = w.replace("iy", "i").replace("ee", "i").replace("oo", "u").replace("ph", "f")
    w = w.replace("y", "i").replace("v", "w")
    # collapse doubled letters produced by the swaps (tariyani -> tariani)
    out = w[0] if w else ""
    for ch in w[1:]:
        if ch != out[-1]:
            out += ch
    return out


# generic words that must not drive matching (they match everything)
_GENERIC = {"main", "chowk", "road", "near", "bihar", "india", "village", "block",
            "the", "and", "at", "in", "school", "market", "gaon", "bus", "stand",
            "thana", "station", "chauraha", "mode", "mandi"}


def _tokens(text: str) -> set[str]:
    return {_norm(t) for t in text.split() if len(t) > 2 and _norm(t) not in _GENERIC}


def _confidence(hit: dict) -> float:
    """Explainable score from OSM's result class/type."""
    cls = hit.get("class", "")
    type_ = hit.get("type", "")
    if cls == "place" and type_ in ("house", "building"):
        return 0.9
    if cls in ("amenity", "shop", "tourism"):
        return 0.85
    if cls == "highway":
        return 0.75
    if cls == "place" and type_ in ("neighbourhood", "suburb", "quarter"):
        return 0.7
    if cls == "place" and type_ in ("city", "town", "village"):
        return 0.6
    return 0.5


async def _nominatim(query: str) -> dict | None:
    global _last_call
    async with _lock:
        wait = _MIN_INTERVAL - (time.monotonic() - _last_call)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_call = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    "https://nominatim.openstreetmap.org/search",
                    params={"q": query, "format": "json", "limit": 1, "countrycodes": "in"},
                    headers=_HEADERS,
                )
                data = resp.json()
        except Exception:
            return None
    if not data:
        return None
    hit = data[0]
    return {
        "lat": float(hit["lat"]),
        "lng": float(hit["lon"]),
        "label": (hit.get("display_name") or query)[:120],
        "confidence": _confidence(hit),
    }


async def _photon(query: str) -> dict | None:
    """Fuzzy fallback — score candidates by name-token overlap + region."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                "https://photon.komoot.io/api",
                params={"q": query, "limit": 5, "lat": _BIAS_LAT, "lon": _BIAS_LNG},
                headers=_HEADERS,
            )
            features = resp.json().get("features", [])
    except Exception:
        return None

    q_tokens = _tokens(query)
    head = _norm(query.split()[0]) if query.split() else ""
    best, best_score = None, -1
    for f in features:
        p = f.get("properties", {})
        name = p.get("name") or ""
        name_tokens = _tokens(name)
        # "Runnisaidpur" (typed) vs "Runni Saidpur" (OSM) — compare joined too
        joined = "".join(_norm(t) for t in name.split() if _norm(t) not in _GENERIC)
        score = 0
        score += 3 * len(q_tokens & name_tokens)
        if head and (head in name_tokens or head == joined or (joined and joined in head)):
            score += 6  # the leading word is the place name — match it strongly
        if p.get("state") == "Bihar":
            score += 1
        if p.get("country") == "India":
            score += 1
        if score > best_score:
            best_score = score
            best = f

    if not best or best_score < 9:
        # 9 = head-token match (6) + Bihar (1) + India (1) + one more token (3)?
        # threshold below requires the leading place-name token to match —
        # without it we'd plot a wrong landmark (F02: never guess).
        return None
    p = best["properties"]
    coords = best["geometry"]["coordinates"]  # [lon, lat]
    parts = [p.get("name"), p.get("city") or p.get("county"), p.get("state"), p.get("country")]
    label = ", ".join(x for x in parts if x)[:120]
    matched = len(_tokens(query) & _tokens(p.get("name") or ""))
    # fuzzy hit: cap confidence below the Nominatim floor for exact roads
    conf = min(0.65, 0.4 + 0.1 * matched)
    return {"lat": float(coords[1]), "lng": float(coords[0]), "label": label, "confidence": conf}


async def geocode(query: str) -> dict | None:
    """Query → {"lat", "lng", "label", "confidence"} or None.

    Bihar-biased (demo region) but not restricted: any Indian result can
    match. Failures return None — callers flag, never crash the flow.
    """
    q = (query or "").strip()
    if not q:
        return None
    if "india" not in q.lower() and "bihar" not in q.lower() and "patna" not in q.lower():
        q = f"{q}, Bihar, India"

    result = await _nominatim(q)
    if result:
        return result
    return await _photon(q)
