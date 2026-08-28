#!/usr/bin/env python3
"""Tail the independent flight recorder and export spans to local Phoenix."""

from __future__ import annotations

import json
import os
import signal
import time
from pathlib import Path
from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode


ROOT = Path(os.environ.get("ARGUS_FLIGHT_RECORDER_DIR", os.path.expanduser("~/.argus-v1/observability/flight-recorder")))
STATE = Path(os.environ.get("ARGUS_PHOENIX_EXPORT_STATE", os.path.expanduser("~/.argus-v1/observability/phoenix-export-state.json")))
ENDPOINT = os.environ.get("ARGUS_PHOENIX_OTLP_ENDPOINT", "http://127.0.0.1:6006/v1/traces")
RUNNING = True


def _stop(_signum, _frame):
    global RUNNING
    RUNNING = False


def _load_state() -> dict[str, int]:
    try:
        value = json.loads(STATE.read_text(encoding="utf-8"))
        return {str(key): max(0, int(offset)) for key, offset in value.items()}
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def _save_state(state: dict[str, int]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, STATE)


def _attribute(value: Any) -> str | bool | int | float:
    if isinstance(value, (str, bool, int, float)):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))[:1000]


def export_event(tracer, event: dict[str, Any]) -> None:
    end_ns = int(event.get("epoch_ms") or int(time.time() * 1000)) * 1_000_000
    start_ns = max(0, end_ns - int(event.get("duration_ms") or 0) * 1_000_000)
    span = tracer.start_span(
        f"{event.get('component', 'unknown')}.{event.get('stage', 'unknown')}",
        start_time=start_ns,
    )
    span.set_attribute("argus.correlation_id", str(event.get("correlation_id") or "uncorrelated"))
    span.set_attribute("argus.component", str(event.get("component") or "unknown"))
    span.set_attribute("argus.stage", str(event.get("stage") or "unknown"))
    span.set_attribute("argus.status", str(event.get("status") or "unknown"))
    for key, value in (event.get("attributes") or {}).items():
        span.set_attribute(f"argus.{str(key)[:80]}", _attribute(value))
    if event.get("status") in {"failed", "degraded", "empty_response"}:
        span.set_status(Status(StatusCode.ERROR, str(event.get("status"))))
    else:
        span.set_status(Status(StatusCode.OK))
    span.end(end_time=end_ns)


def main() -> int:
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    provider = TracerProvider(resource=Resource.create({"service.name": "argus-v1"}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=ENDPOINT, timeout=3)))
    trace.set_tracer_provider(provider)
    tracer = trace.get_tracer("argus.flight-recorder.exporter", "1")
    state = _load_state()
    while RUNNING:
        changed = False
        for path in sorted(ROOT.glob("*.jsonl")):
            key = str(path)
            offset = state.get(key, 0)
            try:
                with path.open(encoding="utf-8") as stream:
                    stream.seek(offset)
                    for line in stream:
                        try:
                            event = json.loads(line)
                            if event.get("schema") == "argus.flight_recorder.event.v1":
                                export_event(tracer, event)
                        except (ValueError, json.JSONDecodeError):
                            continue
                    new_offset = stream.tell()
            except OSError:
                continue
            if new_offset != offset:
                state[key] = new_offset
                changed = True
        if changed:
            _save_state(state)
        time.sleep(1.0)
    provider.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
