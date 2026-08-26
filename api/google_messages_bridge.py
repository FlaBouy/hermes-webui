"""Loopback-only seam to Biggy's dedicated Google Messages Chrome profile."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any


_ROOT = Path(__file__).resolve().parents[1]
_BRIDGE_SCRIPT = _ROOT / "scripts" / "biggy_google_messages_bridge.mjs"
_NODE = Path.home() / ".local" / "bin" / "node"


class GoogleMessagesError(RuntimeError):
    """Raised when the local Google Messages browser cannot complete a request."""


def _bridge(action: str, **payload: Any) -> dict[str, Any]:
    node = str(os.getenv("BIGGY_GOOGLE_MESSAGES_NODE") or _NODE)
    request = {"action": action, **payload}
    env = os.environ.copy()
    env.setdefault("BIGGY_GOOGLE_MESSAGES_CDP", "http://127.0.0.1:9223")
    try:
        completed = subprocess.run(
            [node, str(_BRIDGE_SCRIPT)],
            input=json.dumps(request),
            text=True,
            capture_output=True,
            timeout=18,
            check=False,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GoogleMessagesError("Google Messages local bridge is unavailable") from exc
    try:
        result = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise GoogleMessagesError("Google Messages local bridge returned an invalid response") from exc
    if not isinstance(result, dict) or not result.get("ok"):
        detail = str(result.get("error") if isinstance(result, dict) else "")
        raise GoogleMessagesError(detail or "Google Messages request failed")
    return result


def google_messages_status() -> dict[str, Any]:
    try:
        result = _bridge("status")
    except GoogleMessagesError as exc:
        return {
            "ready": False,
            "paired": False,
            "connected": False,
            "detail": str(exc),
        }
    return {
        "ready": bool(result.get("ready")),
        "paired": bool(result.get("paired")),
        "connected": bool(result.get("connected")),
        "detail": str(result.get("detail") or ""),
    }


def send_google_message(to: str, body: str) -> dict[str, Any]:
    result = _bridge("send", to=to, body=body)
    return {
        "ok": True,
        "transport": "google_messages",
        "status": str(result.get("status") or "submitted"),
    }
