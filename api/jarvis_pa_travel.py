"""Read-only, source-backed travel data for Jarvis II PA.

This adapter deliberately uses the existing local maps skill as its sole data
provider.  It returns canonical places and nearby public POIs, never hotel
availability, prices, booking status, or calendar conclusions.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


_MAPS_CLIENT = Path("/Users/rick/.hermes/profiles/biggy/skills/productivity/maps/scripts/maps_client.py")


def _run(*args: str) -> dict[str, Any]:
    if not _MAPS_CLIENT.is_file():
        raise RuntimeError("local_maps_skill_unavailable")
    result = subprocess.run(
        ["python3", str(_MAPS_CLIENT), *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=35,
    )
    if result.returncode:
        raise RuntimeError("local_maps_skill_failed")
    data = json.loads(result.stdout)
    if not isinstance(data, dict):
        raise RuntimeError("local_maps_skill_invalid_response")
    return data


def resolve_travel(*, destination: str, include_lodging: bool = True) -> dict[str, Any]:
    destination = str(destination or "").strip()
    if not destination or len(destination) > 240:
        raise ValueError("destination must be 1 to 240 characters")
    resolved = _run("search", destination)
    places = resolved.get("results") if isinstance(resolved.get("results"), list) else []
    if not places:
        return {"ok": False, "reason": "DESTINATION_NOT_FOUND", "source": "OpenStreetMap/Nominatim"}
    place = places[0]
    lat, lon = place.get("lat"), place.get("lon")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return {"ok": False, "reason": "DESTINATION_NOT_GEOCODABLE", "source": "OpenStreetMap/Nominatim"}
    lodging: list[dict[str, Any]] = []
    if include_lodging:
        pois = _run("nearby", str(lat), str(lon), "hotel", "--radius", "1500", "--limit", "5")
        for poi in pois.get("results") if isinstance(pois.get("results"), list) else []:
            if not isinstance(poi, dict) or not poi.get("name") or not poi.get("maps_url"):
                continue
            distance = poi.get("distance_m")
            cue = f"{round(float(distance) * 0.000621371, 1)} mi from {place.get('name') or destination}" if isinstance(distance, (int, float)) else "Nearby public POI"
            lodging.append({
                "name": str(poi["name"]),
                "cue": cue,
                "url": str(poi["maps_url"]),
                "source_host": "OpenStreetMap",
                "address": str(poi.get("address") or ""),
                "directions_url": str(poi.get("directions_url") or ""),
            })
    return {
        "ok": True,
        "schema": "jarvis.pa.travel_evidence.v1",
        "source": "OpenStreetMap/Nominatim",
        "destination": {"label": str(place.get("name") or destination), "lat": lat, "lon": lon},
        "recommendation_view_model": {
            "schema": "jarvis.recommendation_view_model.v1",
            "emitted_by": "Jarvis II PA Tool",
            "category": "lodging",
            "title": f"Lodging near {place.get('name') or destination}",
            "available": bool(lodging),
            "reason": None if lodging else "NO_PUBLIC_POIS_FOUND",
            "options": lodging,
            "source": "OpenStreetMap/Nominatim",
            "notice": "Public POIs only; no rates, availability, or booking status.",
        },
    }
