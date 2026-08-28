"""Deterministic acceptance contract for A.R.G.U.S. travel turns."""

from __future__ import annotations


def _plan(origin: str, destination: str):
    return {
        "ok": True,
        "map_view_model": {
            "schema": "argus.map_view_model.v1",
            "emitted_by": "A.R.G.U.S. PA Tool",
            "available": True,
            "origin": {"label": origin},
            "destination": {"label": destination},
            "route": {"distance_m": 1, "duration_min": 1, "geometry": {"coordinates": []}},
        },
        "recommendation_view_models": [
            {
                "schema": "argus.recommendation_view_model.v1",
                "emitted_by": "A.R.G.U.S. PA Tool",
                "category": "lodging",
                "available": True,
                "options": [{"name": "Verified lodging"}],
            }
        ],
    }


def test_named_venue_is_rematerialized_when_n8n_degrades_it_to_city():
    from api.argus_route_contract import enforce_route_contract

    calls = []

    def planner(*, origin, destination):
        calls.append((origin, destination))
        return _plan(origin, "Neyland Stadium, Knoxville, Tennessee")

    result = enforce_route_contract(
        "Hey Biggy, ask Argus to map a route from Lynn Haven, Florida to Neyland Stadium in Knoxville, Tennessee.",
        {
            "ok": True,
            "reply": "A.R.G.U.S. verified Knoxville.",
            "map_view_model": {
                "available": True,
                "destination": {"label": "Knoxville, Tennessee, United States"},
            },
        },
        plan_trip=planner,
    )

    assert calls == [("Lynn Haven, Florida", "Neyland Stadium in Knoxville, Tennessee")]
    assert result["ok"] is True
    assert result["map_view_model"]["destination"]["label"].startswith("Neyland Stadium")
    assert result["route_contract"]["status"] == "VERIFIED"
    assert result["trip_plan_view_model"]["categories"][0]["category"] == "lodging"


def test_event_phrase_uses_agent_verified_named_destination_before_materializing():
    from api.argus_route_contract import enforce_route_contract

    calls = []

    def planner(*, origin, destination):
        calls.append((origin, destination))
        return _plan(origin, destination)

    result = enforce_route_contract(
        "Ask Argus to map me a route to the Tennessee-Auburn game on October 3rd.",
        {
            "ok": True,
            "reply": "The Tennessee versus Auburn game is at Neyland Stadium. Destination is Neyland Stadium in Knoxville, TN.",
            "map_view_model": {"available": True, "destination": {"label": "Knoxville, Tennessee"}},
        },
        plan_trip=planner,
    )

    assert calls == [("Lynn Haven, Florida", "Neyland Stadium in Knoxville, TN")]
    assert result["ok"] is True


def test_route_contract_fails_closed_when_verified_route_cannot_be_built():
    from api.argus_route_contract import enforce_route_contract

    result = enforce_route_contract(
        "Map a route from Lynn Haven to Neyland Stadium.",
        {"ok": True, "reply": "Route ready.", "map_view_model": None},
        plan_trip=lambda **_kwargs: {"ok": False, "reason": "ROUTE_NOT_FOUND"},
    )

    assert result["ok"] is False
    assert result["error"] == "ROUTE_CONTRACT_FAILED"
    assert result["map_view_model"] is None
    assert result["route_contract"]["status"] == "REJECTED"


def test_non_route_turn_does_not_invoke_travel_materializer():
    from api.argus_route_contract import enforce_route_contract

    source = {"ok": True, "reply": "The weather card is ready."}
    result = enforce_route_contract(
        "What will the weather be there?",
        source,
        plan_trip=lambda **_kwargs: (_ for _ in ()).throw(AssertionError("must not run")),
    )

    assert result == source
