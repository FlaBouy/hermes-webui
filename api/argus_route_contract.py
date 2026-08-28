"""Acceptance boundary for A.R.G.U.S. route turns.

n8n remains the agentic planner and compliance orchestrator.  This module is
the final deterministic gate between that workflow and persistent/glass UI
state: a successful route turn must resolve and materialize the requested
endpoints itself.  Conversational prose is never accepted as route evidence.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Callable


_ROUTE_INTENT = re.compile(
    r"(?i)\b(?:map(?:ped|ping)?|route(?:d|s|ing)?|directions?|drive|driving)\b"
)
_NAMED_PLACE_KIND = re.compile(
    r"(?i)\b(?:stadium|arena|field|park|center|centre|airport|hotel|motel|"
    r"plant|factory|terminal|station|museum|theater|theatre|university|college)\b"
)
_EVENT_PHRASE = re.compile(r"(?i)\b(?:game|match|event|tournament|concert)\b")


def owner_request_text(objective: str) -> str:
    """Strip orchestration instructions from a wrapped owner utterance."""
    text = str(objective or "").strip()
    match = re.search(r"(?is)\bOwner request:\s*(.+)", text)
    if not match:
        return text
    owner = match.group(1)
    return re.split(
        r"(?is)\.\s+(?:The relevant event date|Complete each requested|"
        r"Weather must use|Return only verified)",
        owner,
        maxsplit=1,
    )[0].strip()


def requires_route_contract(objective: str) -> bool:
    return bool(_ROUTE_INTENT.search(owner_request_text(objective)))


def _clean_endpoint(value: str) -> str:
    value = str(value or "").strip(" \t\r\n,.;:?")
    value = re.split(
        r"(?i)\s+(?:and\s+(?:check|see|find|get|give|tell|show|make)|"
        r"while\s+(?:check|find)|for\s+conflicts?)\b",
        value,
        maxsplit=1,
    )[0]
    return value.strip(" \t\r\n,.;:?")


def _canonical_destination_claim(result: dict[str, Any]) -> str:
    texts = [
        str(result.get("reply") or ""),
        str(result.get("spoken_text") or ""),
        str(result.get("spoken_reply") or ""),
    ]
    for text in texts:
        match = re.search(
            r"(?is)\bDestination\s+is\s+(.+?)(?=\.(?:\s|$)|\n|\bRoute\s+is\b|$)",
            text,
        )
        if match:
            return _clean_endpoint(match.group(1))
    model = result.get("map_view_model")
    destination = model.get("destination") if isinstance(model, dict) else None
    label = str(destination.get("label") or "").strip() if isinstance(destination, dict) else ""
    return _clean_endpoint(label)


def route_endpoints(objective: str, result: dict[str, Any]) -> tuple[str, str]:
    """Return explicit endpoints, using the agent's verified venue for events."""
    owner = owner_request_text(objective)
    origin = "Lynn Haven, Florida"
    destination = ""

    direct = re.search(
        r"(?is)\bfrom\s+(.+?)\s+to\s+(.+?)(?=\.(?:\s|$)|\?|$)", owner
    )
    if direct:
        origin = _clean_endpoint(direct.group(1)) or origin
        destination = _clean_endpoint(direct.group(2))
    else:
        to_match = re.search(
            r"(?is)\b(?:map|route|drive|directions?)\b.{0,80}?\bto\s+(.+?)(?=\.(?:\s|$)|\?|$)",
            owner,
        )
        if to_match:
            destination = _clean_endpoint(to_match.group(1))
        else:
            direct_target = re.search(
                r"(?is)\b(?:map|route)\s+(?!a\s+route\b|the\s+route\b)(.+?)(?=\.(?:\s|$)|\?|$)",
                owner,
            )
            if direct_target:
                destination = _clean_endpoint(direct_target.group(1))

    claim = _canonical_destination_claim(result)
    if not destination or (_EVENT_PHRASE.search(destination) and claim):
        destination = claim
    return origin, destination


def _reject(result: dict[str, Any], *, reason: str, origin: str, destination: str) -> dict[str, Any]:
    failed = copy.deepcopy(result)
    failed.update(
        {
            "ok": False,
            "error": "ROUTE_CONTRACT_FAILED",
            "map_view_model": None,
            "lodging_view_model": None,
            "recommendation_view_model": None,
            "trip_plan_view_model": None,
            "reply": "**A.R.G.U.S.:** I could not create a verified route card for that request.",
            "spoken_text": "Argus could not create a verified route card for that request.",
            "spoken_reply": "Argus could not create a verified route card for that request.",
            "route_contract": {
                "schema": "argus.route_acceptance.v1",
                "status": "REJECTED",
                "reason": reason,
                "origin_query": origin,
                "destination_query": destination,
            },
        }
    )
    return failed


def enforce_route_contract(
    objective: str,
    result: dict[str, Any],
    *,
    plan_trip: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    """Materialize a verified route generation or reject the whole turn."""
    if not requires_route_contract(objective) or not isinstance(result, dict) or not result.get("ok"):
        return result

    origin, destination = route_endpoints(objective, result)
    if not destination:
        return _reject(result, reason="DESTINATION_UNRESOLVED", origin=origin, destination="")

    try:
        planned = plan_trip(origin=origin, destination=destination)
    except Exception as exc:
        return _reject(
            result,
            reason=f"TRAVEL_MATERIALIZER_ERROR:{type(exc).__name__}",
            origin=origin,
            destination=destination,
        )
    if not isinstance(planned, dict) or not planned.get("ok"):
        reason = str(planned.get("reason") or "ROUTE_NOT_VERIFIED") if isinstance(planned, dict) else "ROUTE_NOT_VERIFIED"
        return _reject(result, reason=reason, origin=origin, destination=destination)

    model = planned.get("map_view_model")
    resolved = model.get("destination") if isinstance(model, dict) else None
    resolved_label = str(resolved.get("label") or "").strip() if isinstance(resolved, dict) else ""
    if not isinstance(model, dict) or model.get("available") is False or not resolved_label:
        return _reject(result, reason="INVALID_MAP_VIEW_MODEL", origin=origin, destination=destination)
    if _NAMED_PLACE_KIND.search(destination) and not _NAMED_PLACE_KIND.search(resolved_label):
        return _reject(result, reason="NAMED_DESTINATION_DEGRADED", origin=origin, destination=destination)

    accepted = copy.deepcopy(result)
    categories = [
        item for item in (planned.get("recommendation_view_models") or [])
        if isinstance(item, dict)
    ]
    accepted["map_view_model"] = model
    accepted["trip_plan_view_model"] = {
        "schema": "argus.trip_plan_view_model.v1",
        "emitted_by": "A.R.G.U.S. PA Tool",
        "available": any(item.get("available") is not False for item in categories),
        "categories": categories,
        "source": planned.get("source"),
        "notice": planned.get("notice"),
    }
    accepted["lodging_view_model"] = next(
        (item for item in categories if str(item.get("category") or "").lower() == "lodging"),
        None,
    )
    accepted["route_contract"] = {
        "schema": "argus.route_acceptance.v1",
        "status": "VERIFIED",
        "origin_query": origin,
        "destination_query": destination,
        "resolved_destination": resolved_label,
        "source": planned.get("source"),
    }
    return accepted
