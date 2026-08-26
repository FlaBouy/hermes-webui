"""Read-only Mapbox-backed trip planning for A.R.G.U.S."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from api.biggy_mapbox_config import resolve_mapbox_public_token


_SOURCE = "Mapbox Geocoding v6, Directions v5, Search Box"
_CATEGORY_SPECS = (
    ("lodging", "hotel", "Lodging", "Public POIs only; no rates, availability, or booking status."),
    ("meals", "food_and_drink", "Meals", "Public POIs only; verify hours and reservations directly."),
    ("entertainment", "museum", "Entertainment", "Public POIs only; verify events, tickets, and hours directly."),
)


class MapboxUnavailable(RuntimeError):
    pass


def _get_json(url: str, params: dict[str, Any], *, timeout: int = 15) -> dict[str, Any]:
    token = resolve_mapbox_public_token()
    if not token:
        raise MapboxUnavailable("MAPBOX_TOKEN_UNAVAILABLE")
    query = urllib.parse.urlencode({**params, "access_token": token}, doseq=True)
    request = urllib.request.Request(f"{url}?{query}", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise MapboxUnavailable("MAPBOX_REQUEST_FAILED") from exc
    if not isinstance(payload, dict):
        raise MapboxUnavailable("MAPBOX_INVALID_RESPONSE")
    return payload


def _public_place_fallback(query: str) -> dict[str, Any] | None:
    """Resolve a named POI only when Mapbox lacks a precise match.

    Mapbox remains the route, map, and card provider. This narrowly scoped
    lookup supplies coordinates for named venues, plants, and attractions that
    Mapbox's licensed place index does not carry. It never supplies a route,
    listing, or cached answer.
    """
    params = urllib.parse.urlencode(
        {"q": query, "format": "jsonv2", "limit": 1, "countrycodes": "us"}
    )
    request = urllib.request.Request(
        f"https://nominatim.openstreetmap.org/search?{params}",
        headers={"Accept": "application/json", "User-Agent": "Argus-PA/1.0 (read-only place verification)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            rows = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError):
        return None
    row = rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else {}
    try:
        lon, lat = float(row.get("lon")), float(row.get("lat"))
    except (TypeError, ValueError):
        return None
    label = str(row.get("display_name") or query).strip()
    return {"label": label, "lon": lon, "lat": lat, "place_source": "OpenStreetMap Nominatim fallback"}


def _coordinates(feature: dict[str, Any]) -> tuple[float, float] | None:
    geometry = feature.get("geometry") if isinstance(feature.get("geometry"), dict) else {}
    point = geometry.get("coordinates") if isinstance(geometry.get("coordinates"), list) else []
    if len(point) >= 2 and isinstance(point[0], (int, float)) and isinstance(point[1], (int, float)):
        return float(point[0]), float(point[1])
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    coords = props.get("coordinates") if isinstance(props.get("coordinates"), dict) else {}
    lon, lat = coords.get("longitude"), coords.get("latitude")
    return (float(lon), float(lat)) if isinstance(lon, (int, float)) and isinstance(lat, (int, float)) else None


def _label(feature: dict[str, Any], fallback: str) -> str:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    return str(props.get("full_address") or feature.get("place_name") or feature.get("name_preferred") or feature.get("text") or feature.get("name") or fallback).strip()


def _place_matches_query(query: str, label: str) -> bool:
    """Reject a city-only result for a multiword named POI query."""
    query_words = {word.lower().strip(",.") for word in query.replace("-", " ").split() if len(word) >= 4}
    label_words = {word.lower().strip(",.") for word in label.replace("-", " ").split()}
    # Generic locality overlap is not proof of a named venue. For example,
    # "Jordan-Hare Stadium, Auburn, Alabama" previously accepted the Search
    # Box result "Auburn, Alabama" because those two locality words matched.
    # A named-place query must retain its place kind in the resolved label or
    # fall through to the exact-place verifier.
    place_kinds = {
        "stadium", "arena", "airport", "hospital", "university", "college",
        "park", "museum", "theater", "theatre", "center", "centre",
        "plant", "factory", "terminal", "station", "school", "church",
    }
    requested_kinds = query_words & place_kinds
    if requested_kinds and not (requested_kinds & label_words):
        return False
    return len(query_words) < 2 or len(query_words & label_words) >= 2


def _geocode(query: str) -> dict[str, Any] | None:
    # Search Box is Mapbox's POI/place endpoint.  Address geocoding alone can
    # collapse a named stadium, plant, or attraction to its surrounding city.
    # Resolve a named place there first, then retain geocoding as the generic
    # fallback for addresses and localities.
    session_token = str(uuid.uuid4())
    try:
        suggested = _get_json(
            "https://api.mapbox.com/search/searchbox/v1/suggest",
            {
                "q": query,
                "limit": 1,
                "country": "US",
                "session_token": session_token,
            },
        )
        suggestions = suggested.get("suggestions") if isinstance(suggested.get("suggestions"), list) else []
        first = suggestions[0] if suggestions and isinstance(suggestions[0], dict) else {}
        mapbox_id = str(first.get("mapbox_id") or "").strip()
        if mapbox_id:
            resolved = _get_json(
                "https://api.mapbox.com/search/searchbox/v1/retrieve/"
                + urllib.parse.quote(mapbox_id, safe=""),
                {"session_token": session_token},
            )
            features = resolved.get("features") if isinstance(resolved.get("features"), list) else []
            if features and isinstance(features[0], dict):
                point = _coordinates(features[0])
                if point:
                    lon, lat = point
                    label = _label(features[0], query)
                    if _place_matches_query(query, label):
                        return {"label": label, "lon": lon, "lat": lat, "place_source": "Mapbox Search Box"}
    except MapboxUnavailable:
        # The existing geocoder is still a valid fallback and reports its own
        # upstream failure if it is unavailable too.
        pass

    payload = _get_json("https://api.mapbox.com/search/geocode/v6/forward", {"q": query, "limit": 1, "autocomplete": "false", "country": "US"})
    features = payload.get("features") if isinstance(payload.get("features"), list) else []
    if not features or not isinstance(features[0], dict):
        return _public_place_fallback(query)
    point = _coordinates(features[0])
    if not point:
        return _public_place_fallback(query)
    lon, lat = point
    resolved = {"label": _label(features[0], query), "lon": lon, "lat": lat, "place_source": "Mapbox Geocoding v6"}
    # A generic geocoder can return a surrounding city for a named POI. Do
    # not discard the exact query in that case; seek a named-place fallback.
    if not _place_matches_query(query, resolved["label"]):
        return _public_place_fallback(query) or resolved
    return resolved


def resolve_place(*, query: str) -> dict[str, Any]:
    """Resolve one named destination using fresh Mapbox place evidence.

    This is deliberately separate from routing: callers can establish the
    destination first, then use the returned canonical label for a route.  It
    supports venues, plants, attractions, and ordinary named places without
    requiring the caller to supply an address, city, or state.
    """
    query = str(query or "").strip()
    if not query or len(query) > 240:
        raise ValueError("query must be 1 to 240 characters")
    place = _geocode(query)
    if not place:
        return {"ok": False, "reason": "PLACE_NOT_FOUND", "source": _SOURCE}
    return {
        "ok": True,
        "schema": "argus.pa.place_evidence.v1",
        "source": "Mapbox Geocoding v6",
        "query": query,
        "place": place,
    }


def _poi_card(feature: dict[str, Any], *, location_label: str) -> dict[str, Any] | None:
    point = _coordinates(feature)
    if not point:
        return None
    lon, lat = point
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    address = str(props.get("full_address") or props.get("address") or "").strip()
    query = urllib.parse.quote(f"{lon},{lat}", safe=",")
    return {
        "name": _label(feature, "Public listing")[:160],
        "cue": (address or f"Near {location_label}")[:180],
        "url": f"https://www.google.com/maps/search/?api=1&query={query}",
        "source_host": "Mapbox",
        "address": address[:240],
        "directions_url": f"https://www.google.com/maps/dir/?api=1&destination={query}",
    }


def _category_pois(category: str, *, lon: float, lat: float) -> list[dict[str, Any]]:
    try:
        payload = _get_json(f"https://api.mapbox.com/search/searchbox/v1/category/{urllib.parse.quote(category, safe='_')}", {"proximity": f"{lon},{lat}", "limit": 5, "language": "en"}, timeout=18)
    except MapboxUnavailable:
        return []
    features = payload.get("features") if isinstance(payload.get("features"), list) else []
    return [feature for feature in features if isinstance(feature, dict)][:5]


def _recommendation(category: str, title: str, notice: str, features: list[dict[str, Any]], location_label: str) -> dict[str, Any]:
    options = [card for feature in features if (card := _poi_card(feature, location_label=location_label))]
    return {"schema": "argus.recommendation_view_model.v1", "emitted_by": "A.R.G.U.S. PA Tool", "category": category, "title": f"{title} near {location_label}", "available": bool(options), "reason": None if options else "NO_PUBLIC_POIS_FOUND", "options": options[:5], "source": _SOURCE, "notice": notice}


def resolve_travel(*, destination: str, include_lodging: bool = True) -> dict[str, Any]:
    destination = str(destination or "").strip()
    if not destination or len(destination) > 240:
        raise ValueError("destination must be 1 to 240 characters")
    place = _geocode(destination)
    if not place:
        return {"ok": False, "reason": "DESTINATION_NOT_FOUND", "source": _SOURCE}
    features = _category_pois("hotel", lon=place["lon"], lat=place["lat"]) if include_lodging else []
    return {"ok": True, "schema": "argus.pa.travel_evidence.v1", "source": _SOURCE, "destination": place, "recommendation_view_model": _recommendation("lodging", "Lodging", "Public POIs only; no rates, availability, or booking status.", features, place["label"])}


def plan_trip(*, origin: str, destination: str) -> dict[str, Any]:
    """Return fresh Mapbox evidence; never cache trip results as memory."""
    origin, destination = str(origin or "").strip(), str(destination or "").strip()
    if not origin or len(origin) > 240:
        raise ValueError("origin must be 1 to 240 characters")
    if not destination or len(destination) > 240:
        raise ValueError("destination must be 1 to 240 characters")
    origin_place, destination_place = _geocode(origin), _geocode(destination)
    if not origin_place or not destination_place:
        return {"ok": False, "reason": "ENDPOINT_NOT_FOUND", "source": _SOURCE}
    coordinates = f"{origin_place['lon']},{origin_place['lat']};{destination_place['lon']},{destination_place['lat']}"
    data = _get_json(f"https://api.mapbox.com/directions/v5/mapbox/driving/{coordinates}", {"overview": "full", "geometries": "geojson", "alternatives": "false", "steps": "false"})
    routes = data.get("routes") if isinstance(data.get("routes"), list) else []
    if not routes or not isinstance(routes[0], dict):
        return {"ok": False, "reason": "ROUTE_NOT_FOUND", "source": _SOURCE}
    route = routes[0]
    geometry = route.get("geometry") if isinstance(route.get("geometry"), dict) else None
    mid_lon, mid_lat = (origin_place["lon"] + destination_place["lon"]) / 2, (origin_place["lat"] + destination_place["lat"]) / 2
    if isinstance(geometry, dict) and isinstance(geometry.get("coordinates"), list) and geometry["coordinates"]:
        middle = geometry["coordinates"][len(geometry["coordinates"]) // 2]
        if isinstance(middle, list) and len(middle) >= 2 and isinstance(middle[0], (int, float)) and isinstance(middle[1], (int, float)):
            mid_lon, mid_lat = float(middle[0]), float(middle[1])
    requests = [(category, canonical, destination_place["lon"], destination_place["lat"], destination_place["label"], title, notice) for category, canonical, title, notice in _CATEGORY_SPECS]
    requests.append(("fuel", "gas_station", mid_lon, mid_lat, "the route midpoint area", "Fuel planning", "Public midpoint-area POIs only; not verified as on-route or open."))
    with ThreadPoolExecutor(max_workers=len(requests)) as pool:
        groups = list(pool.map(lambda item: _category_pois(item[1], lon=item[2], lat=item[3]), requests))
    models = [_recommendation(item[0], item[5], item[6], features, item[4]) for item, features in zip(requests, groups)]
    encoded_origin, encoded_destination = urllib.parse.quote(origin_place["label"], safe=""), urllib.parse.quote(destination_place["label"], safe="")
    map_view_model = {"schema": "argus.map_view_model.v1", "emitted_by": "A.R.G.U.S. PA Tool", "available": True, "origin": origin_place, "destination": destination_place, "route": {"distance_m": route.get("distance"), "duration_min": round(float(route.get("duration") or 0) / 60, 2), "mode": "driving", "geometry": geometry}, "navigation": {"google_maps_url": f"https://www.google.com/maps/dir/?api=1&origin={encoded_origin}&destination={encoded_destination}&travelmode=driving", "waze_url": f"https://www.waze.com/ul?q={encoded_destination}&navigate=yes"}, "source": _SOURCE, "notice": "Mapbox route and temporary public POIs only; verify road conditions and availability before travel."}
    return {"ok": True, "schema": "argus.pa.trip_plan.v1", "source": _SOURCE, "origin": origin_place, "destination": destination_place, "map_view_model": map_view_model, "recommendation_view_models": models, "notice": "Read-only planning evidence. A.R.G.U.S. cannot book, purchase, reserve, or verify live availability."}
