"""Local, correlation-bound flight recorder for Argus/Biggy/Smedley turns.

The recorder is deliberately independent of the UI and n8n.  A broken card,
webhook, or browser can therefore be autopsied from the same durable timeline.
It writes only bounded metadata; prompts, answers, tokens, and credentials are
never persisted here.
"""

from __future__ import annotations

import json
import hashlib
import os
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_LOCK = threading.Lock()
_ROOT = Path(
    os.environ.get(
        "ARGUS_FLIGHT_RECORDER_DIR",
        os.path.expanduser("~/.argus-v1/observability/flight-recorder"),
    )
)
_SENSITIVE_MARKERS = ("token", "secret", "password", "authorization", "api_key", "cookie")


def _otlp_attribute(key: str, value: Any) -> dict[str, Any]:
    safe = _safe_value(key, value)
    if isinstance(safe, bool):
        encoded = {"boolValue": safe}
    elif isinstance(safe, int):
        encoded = {"intValue": str(safe)}
    elif isinstance(safe, float):
        encoded = {"doubleValue": safe}
    else:
        encoded = {"stringValue": json.dumps(safe, ensure_ascii=False) if isinstance(safe, (dict, list)) else str(safe)}
    return {"key": key[:80], "value": encoded}


def _export_otlp(event: dict[str, Any]) -> None:
    endpoint = str(os.environ.get("ARGUS_OTEL_HTTP_ENDPOINT") or "").strip()
    if not endpoint:
        return
    corr = event["correlation_id"]
    trace_id = hashlib.sha256(corr.encode("utf-8")).hexdigest()[:32]
    event_fingerprint = json.dumps(event, sort_keys=True, separators=(",", ":"))
    span_id = hashlib.sha256(event_fingerprint.encode("utf-8")).hexdigest()[:16]
    end_ns = int(event["epoch_ms"]) * 1_000_000
    start_ns = max(0, end_ns - int(event.get("duration_ms") or 0) * 1_000_000)
    attrs = {
        "argus.correlation_id": corr,
        "argus.component": event["component"],
        "argus.stage": event["stage"],
        "argus.status": event["status"],
        **(event.get("attributes") or {}),
    }
    body = {
        "resourceSpans": [{
            "resource": {"attributes": [_otlp_attribute("service.name", "argus-v1")]},
            "scopeSpans": [{
                "scope": {"name": "argus.flight-recorder", "version": "1"},
                "spans": [{
                    "traceId": trace_id,
                    "spanId": span_id,
                    "name": f"{event['component']}.{event['stage']}",
                    "kind": 1,
                    "startTimeUnixNano": str(start_ns),
                    "endTimeUnixNano": str(end_ns),
                    "attributes": [_otlp_attribute(str(k), v) for k, v in attrs.items()],
                    "status": {"code": 2 if event["status"] in {"failed", "degraded", "empty_response"} else 1},
                }],
            }],
        }],
    }
    try:
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=0.8) as response:
            response.read(1)
    except OSError:
        pass


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _safe_value(key: str, value: Any) -> Any:
    lowered = key.lower()
    if any(marker in lowered for marker in _SENSITIVE_MARKERS):
        return "[redacted]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:500]
    if isinstance(value, list):
        return [_safe_value(key, item) for item in value[:20]]
    if isinstance(value, dict):
        return {str(k)[:80]: _safe_value(str(k), v) for k, v in list(value.items())[:40]}
    return str(value)[:500]


def record_event(
    correlation_id: str,
    *,
    component: str,
    stage: str,
    status: str,
    duration_ms: int | float | None = None,
    **attributes: Any,
) -> dict[str, Any]:
    """Append one bounded event and return it for tests/diagnostics."""
    event: dict[str, Any] = {
        "schema": "argus.flight_recorder.event.v1",
        "timestamp_utc": _utc(),
        "epoch_ms": int(time.time() * 1000),
        "correlation_id": str(correlation_id or "uncorrelated")[:160],
        "component": str(component or "unknown")[:80],
        "stage": str(stage or "unknown")[:100],
        "status": str(status or "unknown")[:80],
    }
    if duration_ms is not None:
        event["duration_ms"] = max(0, int(round(float(duration_ms))))
    if attributes:
        event["attributes"] = {
            str(key)[:80]: _safe_value(str(key), value)
            for key, value in attributes.items()
        }
    try:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        path = _ROOT / f"{day}.jsonl"
        line = json.dumps(event, separators=(",", ":"), ensure_ascii=False) + "\n"
        with _LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as stream:
                stream.write(line)
                stream.flush()
    except OSError:
        # Observability must never take the user-facing path down.
        pass
    if os.environ.get("ARGUS_OTEL_HTTP_ENDPOINT"):
        threading.Thread(target=_export_otlp, args=(event,), daemon=True).start()
    return event


def terminal_event(correlation_id: str, *, component: str, ok: bool, **attributes: Any) -> dict[str, Any]:
    return record_event(
        correlation_id,
        component=component,
        stage="terminal",
        status="completed" if ok else "degraded",
        **attributes,
    )
