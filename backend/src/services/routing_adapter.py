"""Routing adapter service.

Provides a small abstraction over mapping/routing providers. If a
`GOOGLE_MAPS_API_KEY` environment variable is set the adapter will attempt
to call the Google Maps Directions API. When no key is available it returns a
deterministic simulated route useful for local development and testing.

The function `compute_route` returns a dict with shape:
{
  "legs": [ {"origin":..., "destination":..., "distance_m":..., "duration_s":...}, ... ],
  "total_distance_m": ..., "total_duration_s": ..., "polyline": "..."
}
"""
from __future__ import annotations
import os
import requests
import datetime as dt
from typing import List, Dict, Any, Optional


def _simulate_route(origin: str, destinations: List[str]) -> Dict[str, Any]:
    legs = []
    total_distance = 0
    total_duration = 0
    # deterministic pseudo-values based on string lengths
    prev = origin
    for d in destinations:
        dist = max(1000, (len(prev) + len(d)) * 37)  # meters
        dur = max(300, int(dist / 8))  # seconds, rough speed
        legs.append({
            "origin": prev,
            "destination": d,
            "distance_m": dist,
            "duration_s": dur,
        })
        total_distance += dist
        total_duration += dur
        prev = d

    return {
        "provider": "mock",
        "generated_at": dt.datetime.utcnow().isoformat() + "Z",
        "legs": legs,
        "total_distance_m": total_distance,
        "total_duration_s": total_duration,
        "polyline": "",  # empty for mock
    }


def _google_directions(origin: str, destinations: List[str], api_key: str, optimize: bool = False) -> Dict[str, Any]:
    # Compose waypoints string for Google Directions API
    base = "https://maps.googleapis.com/maps/api/directions/json"
    waypoints = "|".join(destinations) if destinations else ""
    params = {
        "origin": origin,
        "destination": destinations[-1] if destinations else origin,
        "key": api_key,
    }
    if waypoints:
        params["waypoints"] = ("optimize:true|" + waypoints) if optimize else waypoints

    r = requests.get(base, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()
    # Map the response into our simpler schema
    legs = []
    total_distance = 0
    total_duration = 0
    if data.get("status") != "OK":
        return {"provider": "google", "ok": False, "raw": data}

    route = data.get("routes", [])[0]
    for leg in route.get("legs", []):
        dist = leg.get("distance", {}).get("value", 0)
        dur = leg.get("duration", {}).get("value", 0)
        legs.append({
            "origin": leg.get("start_address"),
            "destination": leg.get("end_address"),
            "distance_m": dist,
            "duration_s": dur,
        })
        total_distance += dist
        total_duration += dur

    poly = route.get("overview_polyline", {}).get("points", "")
    return {
        "provider": "google",
        "ok": True,
        "legs": legs,
        "total_distance_m": total_distance,
        "total_duration_s": total_duration,
        "polyline": poly,
        "raw": None,
    }


def compute_route(origin: str, destinations: List[str], api_key: Optional[str] = None, optimize: bool = False) -> Dict[str, Any]:
    """Compute a route covering the provided destinations starting from origin.

    - If `api_key` is provided we attempt a real call to Google Maps.
    - If no `api_key` is present, return a simulated route for local dev.
    """
    if api_key:
        try:
            return _google_directions(origin, destinations, api_key, optimize=optimize)
        except Exception:
            # Best-effort: fall back to simulation on network / API errors
            return _simulate_route(origin, destinations)
    return _simulate_route(origin, destinations)
