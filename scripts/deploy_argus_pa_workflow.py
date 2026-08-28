#!/usr/bin/env python3
"""Safely validate or deploy the canonical Argus PA workflow to local n8n.

The API credential is read from the environment or its local key file and is
never accepted as a command-line argument or printed.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_FILE = ROOT / "workflows" / "jarvis-ii-pa-core-poc.json"
WORKFLOW_ID = "cD6uUqpzXQl3n3iU"
WORKFLOW_NAME = "Jarvis II — PA Core POC"
N8N_BASE = "http://127.0.0.1:5680"
KEY_FILE = Path("/Users/rick/jarvis-n8n/.n8n-api-key")


def api_key() -> str:
    value = os.environ.get("N8N_API_KEY", "").strip()
    if not value and KEY_FILE.is_file():
        value = KEY_FILE.read_text(encoding="utf-8").strip()
    if not value:
        raise RuntimeError("local n8n API key is unavailable")
    return value


def request(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Accept": "application/json", "X-N8N-API-KEY": api_key()}
    if body is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(N8N_BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"n8n {method} failed with HTTP {exc.code}: {detail}") from exc


def canonical_workflow() -> dict:
    payload = json.loads(WORKFLOW_FILE.read_text(encoding="utf-8"))
    workflow = payload[0] if isinstance(payload, list) and len(payload) == 1 else payload
    if not isinstance(workflow, dict):
        raise RuntimeError("canonical workflow must be one JSON object")
    if workflow.get("id") != WORKFLOW_ID or workflow.get("name") != WORKFLOW_NAME:
        raise RuntimeError("canonical workflow identity does not match the Argus PA pin")
    names = {str(node.get("name")) for node in workflow.get("nodes", [])}
    required = {
        "Classify Deterministic Plan",
        "Deterministic Plan?",
        "Local 120B Plan",
        "Governed PA Response",
    }
    if not required.issubset(names):
        raise RuntimeError(f"canonical workflow is missing required nodes: {sorted(required - names)}")
    return workflow


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="deploy after validation")
    args = parser.parse_args()

    source = canonical_workflow()
    live = request("GET", f"/api/v1/workflows/{WORKFLOW_ID}")
    if live.get("id") != WORKFLOW_ID or live.get("name") != WORKFLOW_NAME:
        raise RuntimeError("live workflow identity does not match the Argus PA pin")

    print(
        json.dumps(
            {
                "status": "validated",
                "workflow_id": WORKFLOW_ID,
                "active": bool(live.get("active")),
                "source_nodes": len(source.get("nodes", [])),
                "live_nodes": len(live.get("nodes", [])),
                "apply": args.apply,
            },
            sort_keys=True,
        )
    )
    if not args.apply:
        return 0

    was_active = bool(live.get("active"))
    update = {key: source[key] for key in ("name", "nodes", "connections", "settings")}
    deployed = request("PUT", f"/api/v1/workflows/{WORKFLOW_ID}", update)
    if bool(deployed.get("active")) != was_active:
        raise RuntimeError("deployment unexpectedly changed workflow activation")
    if len(deployed.get("nodes", [])) != len(source.get("nodes", [])):
        raise RuntimeError("deployed workflow node count does not match canonical source")
    print(
        json.dumps(
            {
                "status": "deployed",
                "workflow_id": WORKFLOW_ID,
                "active": bool(deployed.get("active")),
                "nodes": len(deployed.get("nodes", [])),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}), file=sys.stderr)
        raise SystemExit(1)
