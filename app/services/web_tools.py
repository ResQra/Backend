"""Keyless web grounding for agents — weather, river discharge, gazetteer.

All sources are free without API keys and fail soft (return
{"available": False, ...} on any error) so debates never stall on the
network. Timeouts are short; the debate chamber has its own deadline.
- Open-Meteo forecast API (weather) + flood API (river discharge, GloFAS)
- Wikipedia REST summary (landmark / place verification)
- Tavily (optional): used only when TAVILY_API_KEY is set.
"""

from __future__ import annotations

import os

import httpx

_TIMEOUT = 5.0


def _get(url: str, params: dict | None = None) -> dict | None:
    try:
        r = httpx.get(url, params=params or {}, timeout=_TIMEOUT,
                      headers={"User-Agent": "ResQra-Debate/1.0"})
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


def web_weather(lat: float, lng: float) -> dict:
    """Current + 24h rain at a point (Open-Meteo)."""
    data = _get("https://api.open-meteo.com/v1/forecast", {
        "latitude": lat, "longitude": lng, "current": "precipitation,weather_code",
        "hourly": "precipitation", "forecast_days": 1, "timezone": "auto"})
    if not data:
        return {"available": False, "source": "open-meteo"}
    cur = data.get("current") or {}
    rain_24h = sum((data.get("hourly") or {}).get("precipitation") or [0])
    return {"available": True, "source": "open-meteo",
            "precip_now_mm": cur.get("precipitation"),
            "weather_code": cur.get("weather_code"),
            "rain_next_24h_mm": round(rain_24h, 1)}


def web_river(lat: float, lng: float) -> dict:
    """7-day river discharge forecast (Open-Meteo GloFAS)."""
    data = _get("https://flood-api.open-meteo.com/v1/flood", {
        "latitude": lat, "longitude": lng, "daily": "river_discharge",
        "forecast_days": 7})
    daily = (data or {}).get("daily") or {}
    series = daily.get("river_discharge") or []
    if not series:
        return {"available": False, "source": "open-meteo-glofas"}
    peak = max(series)
    return {"available": True, "source": "open-meteo-glofas",
            "peak_7d_m3s": peak,
            "trend": "rising" if series[-1] > series[0] else "steady/falling"}


def web_place(query: str) -> dict:
    """One-paragraph place check (Wikipedia summary)."""
    data = _get(f"https://en.wikipedia.org/api/rest_v1/page/summary/{query}")
    if not data or data.get("type") == "disambiguation":
        return {"available": False, "source": "wikipedia"}
    coords = (data.get("coordinates") or {})
    return {"available": True, "source": "wikipedia",
            "title": data.get("title"), "summary": (data.get("extract") or "")[:400],
            "lat": coords.get("lat"), "lng": coords.get("lon")}


def web_search(query: str) -> dict:
    """General web search. Tavily when a key exists, else unavailable."""
    key = os.environ.get("TAVILY_API_KEY", "")
    if not key:
        return {"available": False, "source": "tavily",
                "note": "TAVILY_API_KEY not set — weather/river/wiki tools still live"}
    try:
        r = httpx.post("https://api.tavily.com/search",
                       json={"api_key": key, "query": query, "max_results": 3,
                             "include_answer": True},
                       timeout=_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        return {"available": True, "source": "tavily",
                "answer": (data.get("answer") or "")[:600],
                "hits": [{"title": h.get("title"), "url": h.get("url")}
                         for h in (data.get("results") or [])[:3]]}
    except Exception:
        return {"available": False, "source": "tavily"}
