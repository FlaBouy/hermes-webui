"""Regression coverage for generic PA destination resolution."""

from api import argus_travel
from api import argus_travel as travel


def test_resolve_place_accepts_named_destination_without_address(monkeypatch):
    """Venues, plant sites, and attractions do not require city/state input."""
    monkeypatch.setattr(
        travel,
        "_geocode",
        lambda query: {"label": "Jordan-Hare Stadium, Auburn, Alabama", "lon": -85.48, "lat": 32.60}
        if query == "Auburn vs Florida game venue"
        else None,
    )

    result = travel.resolve_place(query="Auburn vs Florida game venue")

    assert result == {
        "ok": True,
        "schema": "argus.pa.place_evidence.v1",
        "source": "Mapbox Geocoding v6",
        "query": "Auburn vs Florida game venue",
        "place": {"label": "Jordan-Hare Stadium, Auburn, Alabama", "lon": -85.48, "lat": 32.60},
    }


def test_resolve_place_reports_not_found_without_guessing(monkeypatch):
    monkeypatch.setattr(travel, "_geocode", lambda _query: None)

    assert travel.resolve_place(query="Unverified plant site") == {
        "ok": False,
        "reason": "PLACE_NOT_FOUND",
        "source": "Mapbox Geocoding v6, Directions v5, Search Box",
    }


def test_geocode_preserves_named_venue_through_search_box(monkeypatch):
    """POI search must win over a city-level geocoding fallback."""
    calls = []

    def fake_get_json(url, params, **_kwargs):
        calls.append(url)
        if url.endswith("/suggest"):
            return {"suggestions": [{"mapbox_id": "poi.venue-1"}]}
        if "/retrieve/" in url:
            return {
                "features": [
                    {
                        "properties": {"full_address": "Jordan-Hare Stadium, Auburn, Alabama"},
                        "geometry": {"coordinates": [-85.489, 32.602]},
                    }
                ]
            }
        raise AssertionError("geocoding fallback should not be used for a resolved POI")

    monkeypatch.setattr(travel, "_get_json", fake_get_json)

    assert travel._geocode("Jordan-Hare Stadium, Auburn, AL") == {
        "label": "Jordan-Hare Stadium, Auburn, Alabama",
        "lon": -85.489,
        "lat": 32.602,
        "place_source": "Mapbox Search Box",
    }
    assert any(url.endswith("/suggest") for url in calls)


def test_named_stadium_cannot_degrade_to_city_result():
    assert not travel._place_matches_query(
        "Jordan-Hare Stadium, Auburn, Alabama",
        "Auburn, Alabama, United States",
    )


def test_city_level_search_result_falls_through_to_exact_named_venue(monkeypatch):
    """A generic Mapbox city hit must yield to exact venue verification."""

    def fake_get_json(url, _params, **_kwargs):
        if url.endswith("/suggest"):
            return {"suggestions": [{"mapbox_id": "place.auburn"}]}
        if "/retrieve/" in url:
            return {
                "features": [
                    {
                        "properties": {"full_address": "Auburn, Alabama, United States"},
                        "geometry": {"coordinates": [-85.481729, 32.60655]},
                    }
                ]
            }
        return {
            "features": [
                {
                    "properties": {"full_address": "Auburn, Alabama, United States"},
                    "geometry": {"coordinates": [-85.481729, 32.60655]},
                }
            ]
        }

    exact = {
        "label": "Jordan-Hare Stadium, 251 South Donahue Drive, Auburn, Alabama",
        "lon": -85.4891613,
        "lat": 32.6021616,
        "place_source": "OpenStreetMap Nominatim fallback",
    }
    monkeypatch.setattr(travel, "_get_json", fake_get_json)
    monkeypatch.setattr(travel, "_public_place_fallback", lambda _query: exact)

    assert travel._geocode("Jordan-Hare Stadium, Auburn, Alabama") == exact


def test_trip_recommendations_are_all_local_to_destination(monkeypatch):
    origin = {"label": "Lynn Haven, FL", "lon": -85.65, "lat": 30.25}
    destination = {"label": "Mercedes-Benz Stadium, Atlanta, GA 30313", "lon": -84.40, "lat": 33.76}
    monkeypatch.setattr(
        argus_travel,
        "_geocode",
        lambda query: origin if "Lynn" in query else destination,
    )
    monkeypatch.setattr(
        argus_travel,
        "_get_json",
        lambda *_args, **_kwargs: {
            "routes": [{"distance": 1000, "duration": 600, "geometry": {"type": "LineString", "coordinates": []}}]
        },
    )
    calls = []

    def category(category, *, lon, lat):
        calls.append((category, lon, lat))
        return []

    monkeypatch.setattr(argus_travel, "_category_pois", category)

    result = argus_travel.plan_trip(
        origin="Lynn Haven, Florida", destination="Mercedes-Benz Stadium"
    )

    assert result["ok"] is True
    assert {item[0] for item in calls} == {"hotel", "food_and_drink", "museum", "gas_station"}
    assert all((lon, lat) == (destination["lon"], destination["lat"]) for _, lon, lat in calls)
    fuel = next(model for model in result["recommendation_view_models"] if model["category"] == "fuel")
    assert fuel["title"].startswith("Fuel near Mercedes-Benz Stadium")
