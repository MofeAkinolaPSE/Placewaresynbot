"""
places_service.py — Multi-source prospect discovery with cost-tiered fallback.

Priority order (automatic, no config needed):
  1. Google Places API   — richest data (ratings, reviews), requires GOOGLE_PLACES_API_KEY
  2. OpenStreetMap / Overpass API — FREE, no key, no account, ~10k req/day fair-use limit
  3. Mock dataset        — offline fallback for dev/demo

For Placeware's use-case (3-5 searches/week) Overpass is effectively free forever.

Scoring formula (max 95 — leaves headroom for fit_signals boost during score-ingest):
  base               30
  rating (0-5)   up to 30  (Google Places only; OSM has no ratings)
  has website       +15
  has phone         +10
  >100 reviews      +10  (or >20 reviews: +5)
  cap                95
"""

import os
import hashlib
import logging
import time
from typing import Optional

import requests

log = logging.getLogger(__name__)

PLACES_API_BASE  = "https://maps.googleapis.com/maps/api/place"
OVERPASS_API_URL = "https://overpass-api.de/api/interpreter"

# OSM amenity/shop tags that map to pharma business types
_OSM_TAG_MAP: dict[str, list[tuple[str, str]]] = {
    "pharmacy":     [("amenity", "pharmacy"), ("shop", "chemist")],
    "hospital":     [("amenity", "hospital")],
    "clinic":       [("amenity", "clinic"), ("amenity", "doctors")],
    "healthcare":   [("amenity", "pharmacy"), ("amenity", "hospital"), ("amenity", "clinic")],
    "distributor":  [("shop", "medical_supply"), ("office", "pharmaceutical")],
    "lab":          [("amenity", "laboratory"), ("healthcare", "laboratory")],
}

# ── Mock dataset ──────────────────────────────────────────────────────────────
# Used when GOOGLE_PLACES_API_KEY is not configured.  Realistic Nigeria data.
_MOCK_PLACES: list[dict] = [
    {
        "place_id": "mock-ng-001",
        "name": "Medplus Pharmacy Victoria Island",
        "formatted_address": "220B Kofo Abayomi St, Victoria Island, Lagos",
        "lat": 6.4281, "lng": 3.4219,
        "rating": 4.5, "user_ratings_total": 312,
        "website": "https://medplusng.com",
        "phone_number": "+234-1-461-2100",
    },
    {
        "place_id": "mock-ng-002",
        "name": "HealthPlus Pharmacy Lekki",
        "formatted_address": "Lekki Phase 1, Lagos",
        "lat": 6.4363, "lng": 3.4699,
        "rating": 4.3, "user_ratings_total": 189,
        "website": "https://healthplus.com.ng",
        "phone_number": "+234-1-453-0000",
    },
    {
        "place_id": "mock-ng-003",
        "name": "MediCare Pharmacy Ikeja",
        "formatted_address": "14 Allen Avenue, Ikeja, Lagos",
        "lat": 6.6044, "lng": 3.3484,
        "rating": 4.1, "user_ratings_total": 74,
        "website": None,
        "phone_number": "+234-803-123-4567",
    },
    {
        "place_id": "mock-ng-004",
        "name": "NaPharm Nigeria Ltd",
        "formatted_address": "Plot 6 Block A, Apapa Industrial Estate, Lagos",
        "lat": 6.4500, "lng": 3.3700,
        "rating": 3.9, "user_ratings_total": 41,
        "website": "https://napharm.ng",
        "phone_number": None,
    },
    {
        "place_id": "mock-ng-005",
        "name": "Kees Pharmaceutical Ibadan",
        "formatted_address": "7 Ring Road, Ibadan, Oyo State",
        "lat": 7.3777, "lng": 3.9470,
        "rating": 4.2, "user_ratings_total": 56,
        "website": None,
        "phone_number": "+234-812-000-1111",
    },
    {
        "place_id": "mock-ng-006",
        "name": "StepCure Pharmacy Maitama",
        "formatted_address": "Plot 1047 Cadastral Zone, Maitama, Abuja FCT",
        "lat": 9.0820, "lng": 7.4910,
        "rating": 4.7, "user_ratings_total": 223,
        "website": "https://stepcure.com.ng",
        "phone_number": "+234-9-870-0001",
    },
    {
        "place_id": "mock-ng-007",
        "name": "Shafa Pharmacy Kaduna",
        "formatted_address": "23 Independence Way, Kaduna",
        "lat": 10.5222, "lng": 7.4383,
        "rating": 4.0, "user_ratings_total": 33,
        "website": None,
        "phone_number": "+234-802-345-6789",
    },
    {
        "place_id": "mock-ng-008",
        "name": "Alpha Pharmacy & Stores Enugu",
        "formatted_address": "Ogui Road, Enugu",
        "lat": 6.4584, "lng": 7.5464,
        "rating": 3.8, "user_ratings_total": 18,
        "website": "https://alphapharmacyng.com",
        "phone_number": None,
    },
    {
        "place_id": "mock-ng-009",
        "name": "LifeGate Pharmacy Port Harcourt",
        "formatted_address": "Stadium Road, Port Harcourt, Rivers State",
        "lat": 4.8156, "lng": 7.0498,
        "rating": 4.4, "user_ratings_total": 98,
        "website": None,
        "phone_number": "+234-807-123-4567",
    },
    {
        "place_id": "mock-ng-010",
        "name": "TrustCare Pharmaceuticals Nnewi",
        "formatted_address": "Nnewi, Anambra State",
        "lat": 6.0059, "lng": 6.9130,
        "rating": 4.6, "user_ratings_total": 145,
        "website": "https://trustcare.ng",
        "phone_number": "+234-805-999-8888",
    },
    {
        "place_id": "mock-ng-011",
        "name": "Pharmaplus Kano",
        "formatted_address": "Zoo Road, Kano, Kano State",
        "lat": 12.0022, "lng": 8.5920,
        "rating": 4.2, "user_ratings_total": 67,
        "website": "https://pharmaplus.ng",
        "phone_number": "+234-803-456-7890",
    },
    {
        "place_id": "mock-ng-012",
        "name": "CureAll Pharmacy Warri",
        "formatted_address": "Effurun Road, Warri, Delta State",
        "lat": 5.5204, "lng": 5.7499,
        "rating": 3.7, "user_ratings_total": 29,
        "website": None,
        "phone_number": "+234-806-789-0123",
    },
]


# ── OpenStreetMap / Overpass (free, no API key) ───────────────────────────────

def _geocode_location(location: str) -> Optional[tuple[float, float]]:
    """
    Convert a location string to (lat, lng) using Nominatim (OSM geocoder).
    Free, no key required. Returns None on failure.
    """
    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": location, "format": "json", "limit": 1},
            headers={"User-Agent": "ACE/1.0 (contact@placeware.ng)"},
            timeout=8,
        )
        resp.raise_for_status()
        results = resp.json()
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])
    except Exception as exc:
        log.warning("Nominatim geocode failed for '%s': %s", location, exc)
    return None


def _search_overpass(
    location: str,
    business_type: str,
    radius_m: int = 5000,
    limit: int = 20,
) -> list[dict]:
    """
    Search OpenStreetMap via Overpass API. Completely free, no credentials needed.
    Fair-use limit: ~10,000 requests/day — more than enough for weekly searches.

    Returns normalized prospect dicts compatible with crm_prospects columns.
    """
    coords = _geocode_location(location)
    if not coords:
        log.warning("Overpass: could not geocode '%s', skipping OSM search", location)
        return []

    lat, lng = coords
    biz_lower = business_type.lower().strip()
    tag_pairs = _OSM_TAG_MAP.get(biz_lower) or [("amenity", biz_lower), ("shop", biz_lower)]

    # Build Overpass QL union of all matching tag pairs
    union_parts = "\n  ".join(
        f'node["{k}"="{v}"](around:{radius_m},{lat},{lng});'
        f'\n  way["{k}"="{v}"](around:{radius_m},{lat},{lng});'
        for k, v in tag_pairs
    )
    query = f"""
[out:json][timeout:25];
(
  {union_parts}
);
out center {limit};
"""

    try:
        resp = requests.post(
            OVERPASS_API_URL,
            data={"data": query},
            headers={"User-Agent": "ACE/1.0 (contact@placeware.ng)"},
            timeout=30,
        )
        resp.raise_for_status()
        elements = resp.json().get("elements", [])
    except Exception as exc:
        log.error("Overpass API request failed: %s", exc)
        return []

    results: list[dict] = []
    for el in elements[:limit]:
        tags = el.get("tags") or {}
        name = tags.get("name") or tags.get("brand") or tags.get("operator")
        if not name:
            continue  # skip unnamed nodes (not useful as CRM leads)

        # Lat/lng: nodes have direct coords; ways have a "center" sub-object
        if el.get("type") == "node":
            el_lat, el_lng = el.get("lat"), el.get("lon")
        else:
            center = el.get("center") or {}
            el_lat, el_lng = center.get("lat"), center.get("lon")

        # Build a stable place_id from OSM type + id
        place_id = f"osm-{el.get('type', 'node')}-{el.get('id', '')}"

        phone   = tags.get("phone") or tags.get("contact:phone")
        website = tags.get("website") or tags.get("contact:website") or tags.get("url")
        street  = tags.get("addr:street", "")
        housenr = tags.get("addr:housenumber", "")
        city    = tags.get("addr:city", "")
        address = f"{housenr} {street}, {city}".strip(", ") or location

        place = {
            "place_id":           place_id,
            "company_name":       name,
            "formatted_address":  address,
            "lat":                float(el_lat) if el_lat is not None else None,
            "lng":                float(el_lng) if el_lng is not None else None,
            "rating":             None,   # OSM has no ratings
            "user_ratings_total": None,
            "website":            website,
            "phone_number":       phone,
        }
        place["places_score"] = _score_place(place)
        place["source"]       = "openstreetmap"
        results.append(place)

    log.info(
        "Overpass: found %d named '%s' businesses near %s (radius %dm)",
        len(results), business_type, location, radius_m,
    )
    return results


# ── Scoring ───────────────────────────────────────────────────────────────────

def _score_place(place: dict) -> float:
    """
    Rule-based lead score derived from Places data.
    Max 95 — leaves headroom for fit_signals boost during score-ingest step.
    """
    score = 30.0
    rating = float(place.get("rating") or 0)
    score += (rating / 5.0) * 30.0          # 0-30 from rating
    if place.get("website"):
        score += 15.0                        # established web presence
    if place.get("phone_number"):
        score += 10.0                        # contactable
    total = int(place.get("user_ratings_total") or 0)
    if total > 100:
        score += 10.0                        # well-reviewed
    elif total > 20:
        score += 5.0                         # some reviews
    return round(min(score, 95.0), 1)


# ── Normalisation ─────────────────────────────────────────────────────────────

def _normalize_place(raw: dict) -> dict:
    """Map a raw Places API result (or mock dict) to crm_prospects columns."""
    geo = (raw.get("geometry") or {}).get("location") or {}
    lat_raw = raw.get("lat") or geo.get("lat") or 0
    lng_raw = raw.get("lng") or geo.get("lng") or 0
    return {
        "place_id":           raw.get("place_id"),
        "company_name":       raw.get("name") or raw.get("company_name") or "Unknown",
        "formatted_address":  raw.get("formatted_address") or raw.get("vicinity"),
        "lat":                float(lat_raw) if lat_raw else None,
        "lng":                float(lng_raw) if lng_raw else None,
        "rating":             float(raw.get("rating") or 0) or None,
        "user_ratings_total": int(raw.get("user_ratings_total") or 0) or None,
        "website":            raw.get("website") or raw.get("url"),
        "phone_number":       raw.get("formatted_phone_number") or raw.get("phone_number"),
    }


# ── Cache key ─────────────────────────────────────────────────────────────────

def cache_key(location: str, business_type: str, radius_m: int) -> str:
    raw = f"{location.lower().strip()}|{business_type.lower().strip()}|{radius_m}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


# ── Main public function ──────────────────────────────────────────────────────

def search_places(
    location: str,
    business_type: str,
    radius_m: int = 5000,
    limit: int = 20,
    api_key: Optional[str] = None,
) -> list[dict]:
    """
    Search for businesses matching `business_type` near `location`.

    Tiered strategy (automatic — no configuration needed):
      1. Google Places API  — if GOOGLE_PLACES_API_KEY is set
      2. OpenStreetMap / Overpass — free, no key, works out of the box
      3. Mock dataset        — offline fallback when both above fail

    Returns normalized dicts compatible with crm_prospects columns.
    Each result includes `places_score` and `source` field.
    """
    key = api_key or os.getenv("GOOGLE_PLACES_API_KEY", "").strip()

    # ── Tier 1: Google Places (when key is available) ─────────────────────────
    if key:
        result = _search_google_places(location, business_type, radius_m, limit, key)
        if result:
            return result
        log.warning("Google Places returned no results — falling through to Overpass")

    # ── Tier 2: OpenStreetMap / Overpass (free, no key needed) ───────────────
    log.info(
        "Using OpenStreetMap/Overpass for '%s' near '%s' (free tier)",
        business_type, location,
    )
    osm_results = _search_overpass(location, business_type, radius_m, limit)
    if osm_results:
        return osm_results

    # No mock fallback: invented pharmacies were being saved as prospects. Nothing found = empty.
    log.warning("Overpass returned no results for '%s' near '%s'", business_type, location)
    return []


def _search_google_places(
    location: str,
    business_type: str,
    radius_m: int,
    limit: int,
    key: str,
) -> list[dict]:
    """Internal: run Google Places Text Search + Details enrichment."""
    query = f"{business_type} in {location}"
    raw_results: list[dict] = []
    next_page_token: Optional[str] = None

    # ── Text Search (up to 3 pages = 60 results) ──────────────────────────────
    for _page in range(3):
        if len(raw_results) >= limit:
            break
        params: dict[str, str | int] = {"query": query, "key": key}
        if next_page_token:
            params = {"pagetoken": next_page_token, "key": key}
        try:
            resp = requests.get(
                f"{PLACES_API_BASE}/textsearch/json",
                params=params,
                timeout=8,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            log.error("Places Text Search failed: %s", exc)
            break

        status = data.get("status")
        if status == "ZERO_RESULTS":
            break
        if status != "OK":
            log.warning("Places API status=%s — query=%s", status, query)
            break

        for result in data.get("results", []):
            raw_results.append(result)
            if len(raw_results) >= limit:
                break

        next_page_token = data.get("next_page_token")
        if not next_page_token:
            break

    # ── Place Details enrichment (phone + website) ────────────────────────────
    enriched: list[dict] = []
    for raw in raw_results[:limit]:
        place = _normalize_place(raw)
        try:
            det_resp = requests.get(
                f"{PLACES_API_BASE}/details/json",
                params={
                    "place_id": raw.get("place_id"),
                    "fields": "formatted_phone_number,website",
                    "key": key,
                },
                timeout=5,
            )
            det_resp.raise_for_status()
            det = det_resp.json().get("result") or {}
            if det.get("formatted_phone_number"):
                place["phone_number"] = det["formatted_phone_number"]
            if det.get("website"):
                place["website"] = det["website"]
        except Exception as exc:
            log.debug("Place Details call failed for %s: %s", raw.get("place_id"), exc)

        place["places_score"] = _score_place(place)
        place["source"] = "google_places"
        enriched.append(place)

    return enriched


# ── Near a point (GPS) or a typed area — what the Lead Finder uses ─────────────

def _geocode_ng(location: str) -> Optional[tuple]:
    """Nominatim, restricted to Nigeria. Returns (lat, lng, label)."""
    try:
        resp = requests.get("https://nominatim.openstreetmap.org/search",
                            params={"q": location, "format": "json", "limit": 1, "countrycodes": "ng"},
                            headers={"User-Agent": "ACE/1.0 (contact@placeware.ng)"}, timeout=10)
        resp.raise_for_status()
        r = resp.json()
        if r:
            return float(r[0]["lat"]), float(r[0]["lon"]), r[0].get("display_name") or location
    except Exception as exc:
        log.warning("Nominatim geocode failed for '%s': %s", location, exc)
    return None


def _distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    import math
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin(math.radians(lat2 - lat1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    return 2 * 6371000.0 * math.asin(math.sqrt(a))


def search_places_near(lat: Optional[float] = None, lng: Optional[float] = None, location: str = "",
                       business_type: str = "pharmacy", radius_m: int = 5000, limit: int = 10) -> dict:
    """Real businesses of `business_type` within `radius_m` of the rep's position (GPS) or of a typed
    area, nearest first, exactly `limit` of them at most. OpenStreetMap (free, no key). No mock data:
    if nothing is found the list is empty and the caller says so."""
    if lat is not None and lng is not None:
        origin, label = (float(lat), float(lng)), "your location"
    elif location:
        g = _geocode_ng(location)
        if not g:
            raise ValueError(f"Could not find '{location}' in Nigeria. Try a town or area name, or use your location.")
        origin, label = (g[0], g[1]), g[2]
    else:
        raise ValueError("Use your location or type an area")
    tags = _OSM_TAG_MAP.get(business_type.lower().strip()) or [("amenity", business_type.lower()), ("shop", business_type.lower())]
    olat, olng = origin
    parts = "\n  ".join(f'node["{k}"="{v}"](around:{radius_m},{olat},{olng});\n  way["{k}"="{v}"](around:{radius_m},{olat},{olng});'
                        for k, v in tags)
    key = os.getenv("GOOGLE_PLACES_API_KEY", "").strip()
    if key:
        g = _google_nearby(olat, olng, business_type, radius_m, limit, key, label)
        if g:
            return {"places": g, "origin": {"lat": olat, "lng": olng}, "origin_label": label, "source": "google_places"}
    cache_k = (round(olat, 3), round(olng, 3), business_type, radius_m)
    hit = _NEAR_CACHE.get(cache_k)
    if hit and time.time() - hit[0] < 900:
        elements = hit[1]
    else:
        query = f"[out:json][timeout:25];\n(\n  {parts}\n);\nout center 400;"
        elements = _overpass(query)
        _NEAR_CACHE[cache_k] = (time.time(), elements)
    found = []
    for el in elements:
        t = el.get("tags") or {}
        name = t.get("name") or t.get("brand") or t.get("operator")
        if not name:
            continue
        if el.get("type") == "node":
            elat, elng = el.get("lat"), el.get("lon")
        else:
            c = el.get("center") or {}
            elat, elng = c.get("lat"), c.get("lon")
        if elat is None or elng is None:
            continue
        street = " ".join(x for x in [t.get("addr:housenumber"), t.get("addr:street")] if x)
        area = t.get("addr:suburb") or t.get("addr:city") or t.get("addr:state") or ""
        place = {
            "place_id": f"osm-{el.get('type', 'node')}-{el.get('id')}",
            "company_name": name,
            "formatted_address": ", ".join(x for x in [street, area] if x) or None,
            "lat": float(elat), "lng": float(elng),
            "phone_number": t.get("phone") or t.get("contact:phone"),
            "website": t.get("website") or t.get("contact:website"),
            "opening_hours": t.get("opening_hours"),
            "rating": None, "user_ratings_total": None,
            "distance_m": round(_distance_m(olat, olng, float(elat), float(elng))),
            "source": "openstreetmap",
            "search_query": f"{business_type} within {radius_m / 1000:g} km of {label}",
        }
        place["places_score"] = _score_place(place)
        found.append(place)
    seen, uniq = set(), []
    for p in sorted(found, key=lambda x: x["distance_m"]):
        k = (p["company_name"].lower(), round(p["lat"], 4), round(p["lng"], 4))
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    return {"places": uniq[:limit], "origin": {"lat": olat, "lng": olng}, "origin_label": label, "source": "openstreetmap"}


# Public Overpass servers are often overloaded (504 / timeouts); try each in turn.
OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
_NEAR_CACHE: dict = {}


class PlacesUnavailable(RuntimeError):
    """No map service answered - the caller tells the rep to try again."""


def _overpass(query: str) -> list:
    last = None
    for url in OVERPASS_MIRRORS:
        try:
            r = requests.post(url, data={"data": query}, headers={"User-Agent": "ACE/1.0 (contact@placeware.ng)"}, timeout=30)
            if r.status_code == 200:
                return r.json().get("elements", [])
            last = f"{url} {r.status_code}"
        except Exception as exc:
            last = f"{url} {exc}"
        log.warning("Overpass mirror failed: %s", last)
    raise PlacesUnavailable("The map service (OpenStreetMap) is busy. Try again in a minute.")


_GOOGLE_TYPES = {"pharmacy": "pharmacy", "hospital": "hospital", "clinic": "doctor", "healthcare": "health", "lab": "health", "distributor": "store"}


def _google_nearby(lat: float, lng: float, business_type: str, radius_m: int, limit: int, key: str, label: str) -> list:
    """Google Places Nearby Search around the rep, with phone numbers from Place Details."""
    try:
        params = {"location": f"{lat},{lng}", "radius": radius_m, "type": _GOOGLE_TYPES.get(business_type, "pharmacy"), "key": key}
        r = requests.get(f"{PLACES_API_BASE}/nearbysearch/json", params=params, timeout=15)
        r.raise_for_status()
        results = r.json().get("results", [])
    except Exception as exc:
        log.warning("Google nearby search failed: %s", exc)
        return []
    out = []
    for g in results:
        loc = (g.get("geometry") or {}).get("location") or {}
        if not loc:
            continue
        out.append({"place_id": g.get("place_id"), "company_name": g.get("name"), "formatted_address": g.get("vicinity"),
                    "lat": loc.get("lat"), "lng": loc.get("lng"), "rating": g.get("rating"), "user_ratings_total": g.get("user_ratings_total"),
                    "phone_number": None, "website": None, "opening_hours": None,
                    "distance_m": round(_distance_m(lat, lng, loc["lat"], loc["lng"])), "source": "google_places",
                    "search_query": f"{business_type} within {radius_m / 1000:g} km of {label}"})
    out.sort(key=lambda x: x["distance_m"])
    out = out[:limit]
    for p in out:
        try:
            d = requests.get(f"{PLACES_API_BASE}/details/json", params={"place_id": p["place_id"], "fields": "formatted_phone_number,website", "key": key},
                             timeout=10).json().get("result", {})
            p["phone_number"], p["website"] = d.get("formatted_phone_number"), d.get("website")
        except Exception:
            pass
        p["places_score"] = _score_place(p)
    return out
