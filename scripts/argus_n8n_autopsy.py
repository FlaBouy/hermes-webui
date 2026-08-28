#!/usr/bin/env python3
"""Summarize one saved Argus n8n execution without exposing request contents."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import urllib.parse
import urllib.request


BASE = "http://127.0.0.1:5680"
WORKFLOW_ID = "cD6uUqpzXQl3n3iU"
KEY_FILE = Path("/Users/rick/jarvis-n8n/.n8n-api-key")


def api_key() -> str:
    value = os.environ.get("N8N_API_KEY", "").strip()
    if not value and KEY_FILE.is_file():
        value = KEY_FILE.read_text(encoding="utf-8").strip()
    if not value:
        raise RuntimeError("local n8n API key is unavailable")
    return value


def get(path: str) -> dict:
    request = urllib.request.Request(
        BASE + path,
        headers={"Accept": "application/json", "X-N8N-API-KEY": api_key()},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def contains(value, needle: str) -> bool:
    if isinstance(value, str):
        return value == needle
    if isinstance(value, dict):
        return any(contains(item, needle) for item in value.values())
    if isinstance(value, list):
        return any(contains(item, needle) for item in value)
    return False


def summarize(execution: dict, correlation_id: str | None) -> dict:
    run_data = (
        execution.get("data", {})
        .get("resultData", {})
        .get("runData", {})
    )
    nodes = []
    for name, runs in run_data.items():
        duration = sum(int(run.get("executionTime") or 0) for run in runs if isinstance(run, dict))
        nodes.append({"node": name, "duration_ms": duration, "runs": len(runs)})
    nodes.sort(key=lambda item: item["duration_ms"], reverse=True)
    names = {item["node"] for item in nodes}
    return {
        "schema": "argus.n8n.autopsy.v1",
        "workflow_id": WORKFLOW_ID,
        "execution_id": str(execution.get("id") or ""),
        "correlation_id": correlation_id,
        "status": execution.get("status"),
        "finished": execution.get("finished"),
        "planner_path": (
            "local_120b"
            if "Local 120B Plan" in names
            else "deterministic_fast_lane"
            if "Classify Deterministic Plan" in names
            else "unknown"
        ),
        "total_duration_ms": sum(item["duration_ms"] for item in nodes),
        "slowest_nodes": nodes[:10],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--correlation-id")
    parser.add_argument("--limit", type=int, default=12)
    args = parser.parse_args()
    query = urllib.parse.urlencode(
        {
            "workflowId": WORKFLOW_ID,
            # n8n serializes complete node run data when includeData is true.
            # Keep this deliberately bounded so the autopsy never becomes a
            # second reliability incident on a busy local workflow.
            "limit": max(1, min(args.limit, 20)),
            "includeData": "true",
        }
    )
    payload = get("/api/v1/executions?" + query)
    executions = payload.get("data") if isinstance(payload.get("data"), list) else []
    selected = None
    for execution in executions:
        if args.correlation_id and not contains(execution, args.correlation_id):
            continue
        selected = execution
        break
    if not selected:
        raise RuntimeError("no saved Argus execution matched the requested correlation")
    print(json.dumps(summarize(selected, args.correlation_id), indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}), file=sys.stderr)
        raise SystemExit(1)
