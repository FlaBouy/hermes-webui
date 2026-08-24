"""Small, read-only fleet status/launch contract for the Biggy cockpit."""

from __future__ import annotations

import json
import os
import socket
import time
from datetime import datetime
from pathlib import Path


_REGISTRY_ROOT = Path(
    os.environ.get(
        "BIGGY_FLEET_REGISTRY_ROOT",
        "/Users/rick/Mounts/Z/DATA/n8n_share/fleet-coordination/registry",
    )
)

_MACHINES = (
    {
        "id": "SMEDLEY",
        "label": "SMEDLEY",
        "kind": "hermes",
        "launch_url": "http://192.168.0.15:8787/",
    },
    {
        "id": "THUNDERDOME",
        "label": "TD",
        "kind": "rdp",
        "host": "192.168.0.20",
        "launch_url": "rdp://full%20address=s:192.168.0.20",
    },
    {
        "id": "HAL9000",
        "label": "HAL",
        "kind": "rdp",
        "host": "192.168.0.13",
        "launch_url": "rdp://full%20address=s:192.168.0.13",
    },
    {
        "id": "PROMETHEUS",
        "label": "PROMETHEUS",
        "kind": "rdp",
        "host": "192.168.0.16",
        "launch_url": "rdp://full%20address=s:192.168.0.16",
    },
    {
        "id": "PLATO",
        "label": "PLATO",
        "kind": "web",
        "host": "192.168.0.25",
        "launch_url": "https://192.168.0.25/",
    },
)


def _read_worker(machine_id: str) -> dict:
    target = _REGISTRY_ROOT / f"{machine_id}-worker-status.json"
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _tcp_online(host: str, ports: tuple[int, ...]) -> bool:
    for port in ports:
        try:
            with socket.create_connection((host, port), timeout=0.16):
                return True
        except OSError:
            continue
    return False


def _machine_state(machine: dict, now: float) -> tuple[str, str | None, str | None]:
    machine_id = machine["id"]
    if machine_id == "SMEDLEY":
        return "online", "idle", None

    worker = _read_worker(machine_id)
    worker_state = str(worker.get("state") or "").strip().lower() or None
    updated_at = worker.get("updated_at")
    try:
        if isinstance(updated_at, str):
            stamp = datetime.fromisoformat(updated_at.replace("Z", "+00:00")).timestamp()
        else:
            stamp = float(updated_at)
        age = max(0.0, now - stamp)
    except (TypeError, ValueError, OverflowError):
        age = None

    if worker_state in {"error", "failed", "blocked"} and age is not None and age <= 300:
        return "error", worker_state, "worker reported an error"
    if worker_state in {"running", "working", "claimed", "busy"} and age is not None and age <= 180:
        return "busy", worker_state, None
    if age is not None and age <= 180:
        return "online", worker_state, None

    # PLATO has no Cursor worker heartbeat. Its TrueNAS management listener is
    # the useful liveness signal. The same probe is a conservative fallback for
    # a desktop whose worker status feed is temporarily absent.
    host = str(machine.get("host") or "")
    ports = (443, 80) if machine.get("kind") == "web" else (3389,)
    if host and _tcp_online(host, ports):
        return "online", worker_state, None
    return "offline", worker_state, "status feed is stale or host is unreachable"


def fleet_status() -> dict:
    now = time.time()
    machines = []
    for machine in _MACHINES:
        state, worker_state, detail = _machine_state(machine, now)
        item = {
            "id": machine["id"],
            "label": machine["label"],
            "kind": machine["kind"],
            "state": state,
            "worker_state": worker_state,
            "launch_url": machine["launch_url"],
        }
        if detail:
            item["detail"] = detail
        machines.append(item)
    return {
        "schema": "biggy.fleet_status.v1",
        "generated_at": now,
        "machines": machines,
    }
