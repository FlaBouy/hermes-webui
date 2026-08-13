"""Local GPT Voice → Biggy Owner-ACK propose-only handoff.

Same-machine loopback only. Proxies structured proposals to the existing
propose-only gateway at 127.0.0.1:8792. Token is read from the protected
token file on the server — never returned to clients, logs, or OpenAPI.

GPT Voice / Biggy may propose only. Approve, reject, enqueue, and worker
start remain on the Owner-ACK bridge / Biggy GUI.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

GATEWAY_URL = os.environ.get(
    "HERMES_WEBUI_GPT_PROPOSE_GATEWAY_URL",
    "http://127.0.0.1:8792/v1/gpt/propose-task",
).strip()
GATEWAY_HEALTH_URL = os.environ.get(
    "HERMES_WEBUI_GPT_PROPOSE_GATEWAY_HEALTH_URL",
    "http://127.0.0.1:8792/v1/health",
).strip()
TOKEN_FILE_ENV = "GPT_BIGGY_PROPOSE_TOKEN_FILE"
DEFAULT_TOKEN_FILE = Path.home() / ".jarvis-ptt" / "gpt-biggy-propose.token"
MAX_BODY_BYTES = 64 * 1024

_BANNED_FIELDS = (
    "approve",
    "reject",
    "decision",
    "approval_policy",
    "enqueue",
    "start_worker",
    "work_order_id",
)


class ProposeHandoffError(RuntimeError):
    """Gateway unavailable or misconfigured — fail closed."""


def resolve_token_file() -> Path:
    raw = os.environ.get(TOKEN_FILE_ENV, "").strip()
    return Path(raw) if raw else DEFAULT_TOKEN_FILE


def load_propose_token() -> str:
    path = resolve_token_file()
    try:
        if path.is_file():
            token = path.read_text(encoding="utf-8").strip()
            if token:
                return token
    except OSError as exc:
        logger.warning("gpt propose token file unreadable: %s", type(exc).__name__)
    return ""


def gateway_status() -> dict[str, Any]:
    """Capability probe — no secrets."""
    token_configured = bool(load_propose_token())
    gateway_ok = False
    detail = ""
    try:
        req = urllib.request.Request(GATEWAY_HEALTH_URL, method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
            gateway_ok = bool(payload.get("ok") and payload.get("propose_only") is True)
            if not gateway_ok:
                detail = "gateway health unexpected"
    except Exception as exc:  # noqa: BLE001
        detail = f"{type(exc).__name__}"
    return {
        "ok": True,
        "propose_only": True,
        "gateway_url": GATEWAY_URL,
        "gateway_healthy": gateway_ok,
        "token_configured": token_configured,
        "token_file": str(resolve_token_file()),
        "ready": bool(gateway_ok and token_configured),
        "detail": detail,
    }


def _sanitize_payload(body: dict[str, Any]) -> dict[str, Any]:
    clean = dict(body)
    for banned in _BANNED_FIELDS:
        clean.pop(banned, None)
    title = str(clean.get("title") or "").strip()
    prompt = str(clean.get("prompt") or clean.get("body") or "").strip()
    lane = str(clean.get("lane") or "").strip().lower()
    if not title or not prompt:
        raise ValueError("title and prompt are required")
    if lane not in ("cursor", "hermes"):
        raise ValueError("lane must be 'cursor' or 'hermes'")
    out: dict[str, Any] = {
        "title": title[:200],
        "prompt": prompt,
        "lane": lane,
        "target": str(clean.get("target") or clean.get("target_machine") or "THUNDERDOME").strip()
        or "THUNDERDOME",
        "assignee": str(clean.get("assignee") or "").strip(),
        "source": str(clean.get("source") or "gpt_voice").strip() or "gpt_voice",
        "created_by": str(clean.get("created_by") or "gpt").strip() or "gpt",
        "rationale": str(
            clean.get("rationale") or "GPT Voice propose-only handoff awaiting Owner ACK."
        ).strip(),
    }
    if clean.get("repository"):
        out["repository"] = str(clean.get("repository")).strip()
    return out


def propose_task(body: dict[str, Any]) -> dict[str, Any]:
    """Submit a propose-only payload to the local gateway. Fail closed on errors."""
    if not isinstance(body, dict):
        raise ValueError("JSON object required")
    payload = _sanitize_payload(body)
    raw = json.dumps(payload).encode("utf-8")
    if len(raw) > MAX_BODY_BYTES:
        raise ValueError(f"payload too large (max {MAX_BODY_BYTES} bytes)")

    token = load_propose_token()
    if not token:
        raise ProposeHandoffError(
            "Propose token not configured. Task was not staged. "
            "Owner ACK gate remains closed."
        )

    req = urllib.request.Request(
        GATEWAY_URL,
        data=raw,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "X-GPT-Propose-Token": token,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            out = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        try:
            parsed = json.loads(detail)
        except json.JSONDecodeError:
            parsed = {}
        if exc.code == 401:
            raise ProposeHandoffError(
                "Propose gateway rejected credentials. Task was not staged."
            ) from exc
        if isinstance(parsed, dict) and parsed.get("message"):
            raise ProposeHandoffError(str(parsed["message"])) from exc
        raise ProposeHandoffError(
            "Propose gateway unavailable. Task was not staged. "
            "Do not bypass Owner ACK."
        ) from exc
    except ProposeHandoffError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ProposeHandoffError(
            "Propose gateway unavailable. Task was not staged. "
            "Do not bypass Owner ACK."
        ) from exc

    if not isinstance(out, dict) or not out.get("ok") or not out.get("pending_owner_ack"):
        raise ProposeHandoffError(
            "Propose gateway did not stage Owner ACK. Task was not staged."
        )

    speak = str(out.get("speak") or out.get("confirmation") or "").strip()
    if not speak:
        speak = (
            f"Staged '{payload['title']}' for Owner approval in Biggy. "
            "Nothing has started."
        )
    # Narrow public response — no token, no dispose affordances.
    return {
        "ok": True,
        "pending_owner_ack": True,
        "proposal_id": out.get("proposal_id"),
        "status": out.get("status"),
        "lane": out.get("lane") or payload["lane"],
        "target_machine": out.get("target_machine"),
        "confirmation": str(out.get("confirmation") or speak),
        "speak": speak,
        "message": (
            "Task staged for Owner ACK. Await Owner approve/reject in Biggy. "
            "No worker has been started."
        ),
    }
