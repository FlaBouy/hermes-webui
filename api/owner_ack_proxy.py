"""Same-origin Owner-ACK bridge proxy for Biggy (and other GUIs).

Browsers on ThunderDome must not call http://127.0.0.1:8791 — that hits TD
loopback, not Smedley's owner-ack-bridge. The WebUI (on Smedley) proxies to
the local bridge so clients only talk same-origin.

Upstream defaults to loopback; override with HERMES_WEBUI_OWNER_ACK_BRIDGE_URL
when the bridge is remote relative to this WebUI process.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import quote, urljoin, urlparse

logger = logging.getLogger(__name__)

DEFAULT_BRIDGE_BASE = "http://127.0.0.1:8791"
MAX_BODY_BYTES = 64 * 1024
ALLOWED_METHODS = frozenset({"GET", "POST"})


def bridge_base_url() -> str:
    raw = (
        os.environ.get("HERMES_WEBUI_OWNER_ACK_BRIDGE_URL")
        or os.environ.get("OWNER_ACK_BRIDGE_URL")
        or DEFAULT_BRIDGE_BASE
    ).strip()
    return raw.rstrip("/") or DEFAULT_BRIDGE_BASE


def _validate_upstream(base: str) -> str | None:
    try:
        parsed = urlparse(base)
    except Exception:
        return "invalid bridge URL"
    if parsed.scheme not in {"http", "https"}:
        return "bridge URL must be http(s)"
    host = (parsed.hostname or "").lower()
    if not host:
        return "bridge URL missing host"
    # Fail closed: only loopback or private LAN hosts.
    if host in {"127.0.0.1", "localhost", "::1"}:
        return None
    if host.endswith(".local"):
        return None
    parts = host.split(".")
    if len(parts) == 4 and all(p.isdigit() for p in parts):
        a, b = int(parts[0]), int(parts[1])
        if a == 10 or (a == 172 and 16 <= b <= 31) or (a == 192 and b == 168):
            return None
    return "bridge URL host is not loopback/private"


def bridge_status() -> dict[str, Any]:
    """Capability probe — no secrets."""
    base = bridge_base_url()
    reject = _validate_upstream(base)
    out: dict[str, Any] = {
        "ok": False,
        "service": "owner-ack-proxy",
        "bridge_url": base,
        "health_path": "/v1/health",
        "gui_id": "biggy",
        "reachable": False,
        "error": reject or "",
    }
    if reject:
        return out
    try:
        req = urllib.request.Request(urljoin(base + "/", "v1/health"), method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            payload = json.loads(resp.read().decode("utf-8") or "{}")
            out["reachable"] = True
            out["ok"] = bool(isinstance(payload, dict) and payload.get("ok"))
            out["health"] = {
                k: payload.get(k)
                for k in ("ok", "service", "bind", "port", "root")
                if isinstance(payload, dict) and k in payload
            }
            if not out["ok"]:
                out["error"] = "bridge health unexpected"
    except Exception as exc:  # noqa: BLE001
        out["error"] = type(exc).__name__
        logger.debug("owner-ack bridge health failed: %s", type(exc).__name__)
    return out


def _upstream_path(path: str) -> str | None:
    """Map /api/owner-ack/... → /v1/... allowlisted paths only."""
    raw = (path or "").strip()
    if raw.startswith("/api/owner-ack"):
        raw = raw[len("/api/owner-ack") :]
    raw = raw or "/"
    if not raw.startswith("/"):
        raw = "/" + raw
    # Normalize and reject traversal.
    if ".." in raw or raw.startswith("//"):
        return None
    if raw in {"/", "/health", "/v1/health"}:
        return "/v1/health"
    if raw == "/v1/owner-ack" or raw.startswith("/v1/owner-ack/"):
        return raw
    # Convenience aliases under /api/owner-ack/*
    if raw == "/owner-ack" or raw.startswith("/owner-ack/"):
        return "/v1" + raw
    if raw.startswith("/v1/"):
        # Only owner-ack + health under /v1/
        if raw == "/v1/health" or raw == "/v1/owner-ack" or raw.startswith("/v1/owner-ack/"):
            return raw
        return None
    return None


def proxy_request(
    *,
    method: str,
    path: str,
    body: bytes | None = None,
    content_type: str | None = None,
) -> tuple[int, dict[str, Any]]:
    """Forward an allowlisted Owner-ACK request to the upstream bridge."""
    method = (method or "GET").upper()
    if method not in ALLOWED_METHODS:
        return 405, {"ok": False, "error": "method_not_allowed"}
    upstream_path = _upstream_path(path)
    if not upstream_path:
        return 404, {"ok": False, "error": "not_found"}
    base = bridge_base_url()
    reject = _validate_upstream(base)
    if reject:
        return 503, {"ok": False, "error": reject, "bridge_url": base}

    if body and len(body) > MAX_BODY_BYTES:
        return 413, {"ok": False, "error": "body_too_large"}

    url = urljoin(base + "/", upstream_path.lstrip("/"))
    # Preserve path encoding for proposal ids.
    if upstream_path.startswith("/v1/owner-ack/") and upstream_path.count("/") >= 3:
        parts = upstream_path.split("/")
        # /v1/owner-ack/<id>[/approve|/reject]
        if len(parts) >= 4 and parts[3]:
            parts[3] = quote(parts[3], safe="")
            url = urljoin(base + "/", "/".join(parts).lstrip("/"))

    headers = {"Accept": "application/json"}
    if content_type:
        headers["Content-Type"] = content_type
    token = (os.environ.get("OWNER_ACK_TOKEN") or "").strip()
    if token:
        headers["X-Owner-Ack-Token"] = token

    req = urllib.request.Request(
        url,
        data=body if method == "POST" else None,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8") or "{}"
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = {"ok": False, "error": "invalid_upstream_json", "raw": raw[:200]}
            if not isinstance(payload, dict):
                payload = {"ok": False, "error": "invalid_upstream_json"}
            payload.setdefault("bridge_url", base)
            return int(resp.status), payload
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8") or "{}")
        except Exception:
            payload = {"ok": False, "error": f"upstream_http_{exc.code}"}
        if not isinstance(payload, dict):
            payload = {"ok": False, "error": f"upstream_http_{exc.code}"}
        payload.setdefault("bridge_url", base)
        return int(exc.code), payload
    except Exception as exc:  # noqa: BLE001
        logger.warning("owner-ack proxy failed: %s", type(exc).__name__)
        return 503, {
            "ok": False,
            "error": "bridge_unreachable",
            "detail": type(exc).__name__,
            "bridge_url": base,
        }
