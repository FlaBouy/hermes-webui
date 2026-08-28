"""Recover a completed PA result when n8n closes a webhook with an empty body."""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterator


DEFAULT_HOST = "http://127.0.0.1:5680"
DEFAULT_WORKFLOW_ID = "cD6uUqpzXQl3n3iU"
DEFAULT_KEY_FILE = "/Users/rick/jarvis-n8n/.n8n-api-key"


def _api_key() -> str:
    direct = str(os.environ.get("ARGUS_N8N_API_KEY") or "").strip()
    if direct:
        return direct
    path = Path(os.environ.get("ARGUS_N8N_API_KEY_FILE", DEFAULT_KEY_FILE))
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _dicts(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _dicts(child)


def _matching_result(execution: dict[str, Any], correlation_id: str) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for item in _dicts((execution.get("data") or {}).get("resultData") or {}):
        corr = str(item.get("correlationId") or item.get("correlation_id") or "")
        if corr != correlation_id:
            continue
        if item.get("status") and (
            item.get("spokenText") is not None
            or item.get("answer") is not None
            or item.get("map_view_model") is not None
        ):
            candidates.append(item)
    return dict(candidates[-1]) if candidates else None


def recover_pa_result(
    correlation_id: str,
    *,
    attempts: int = 5,
    delay_s: float = 0.35,
    request_timeout_s: float = 8.0,
) -> dict[str, Any] | None:
    """Poll recent completed executions; never re-execute the workflow."""
    corr = str(correlation_id or "").strip()
    key = _api_key()
    if not corr or not key:
        return None
    host = os.environ.get("ARGUS_N8N_HOST", DEFAULT_HOST).rstrip("/")
    workflow_id = os.environ.get("ARGUS_N8N_PA_WORKFLOW_ID", DEFAULT_WORKFLOW_ID)
    query = urllib.parse.urlencode(
        {"workflowId": workflow_id, "limit": 12, "includeData": "true"}
    )
    url = f"{host}/api/v1/executions?{query}"
    for attempt in range(max(1, attempts)):
        try:
            request = urllib.request.Request(
                url,
                headers={"X-N8N-API-KEY": key, "Accept": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=request_timeout_s) as response:
                payload = json.loads(response.read().decode("utf-8"))
            for execution in payload.get("data") if isinstance(payload, dict) else []:
                if not isinstance(execution, dict) or not execution.get("finished"):
                    continue
                found = _matching_result(execution, corr)
                if found:
                    found["recovered_from_execution_id"] = str(execution.get("id") or "")
                    return found
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        if attempt + 1 < max(1, attempts):
            time.sleep(max(0.0, delay_s))
    return None
