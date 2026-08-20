"""Regression coverage for generic PA destination resolution."""

from api import jarvis_pa_travel as travel


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
        "schema": "jarvis.pa.place_evidence.v1",
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
