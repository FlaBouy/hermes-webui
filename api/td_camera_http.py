"""HTTP handlers: Hermes GUI proxy to native TD camera (no browser producer)."""

from __future__ import annotations

import json
from urllib.parse import parse_qs

from api import td_camera_relay as relay


def _json(handler, status: int, payload: dict) -> bool:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)
    return True


def _owner_key(handler) -> str:
    """Defense in depth: when auth is enabled, require a verified session cookie."""
    from api.auth import is_auth_enabled, parse_cookie, verify_session

    cookie = parse_cookie(handler)
    if is_auth_enabled():
        if not cookie or not verify_session(cookie):
            raise relay.RelayError("unauthenticated", 401)
        return relay.owner_key_from_session_cookie(cookie)
    if cookie:
        return relay.owner_key_from_session_cookie(cookie)
    return relay.owner_key_from_session_cookie("td-camera-auth-disabled")


def handle_td_camera(handler, parsed, method: str) -> bool | None:
    path = str(getattr(parsed, "path", "") or "")
    if not path.startswith("/api/td-camera"):
        return False

    try:
        if method == "GET" and path == "/api/td-camera/health":
            _owner_key(handler)
            return _json(handler, 200, relay.fetch_health())

        if method == "GET" and path == "/api/td-camera/status":
            key = _owner_key(handler)
            return _json(handler, 200, relay.status(viewer_owner_key=key))

        if method == "GET" and path == "/api/td-camera/frame.jpg":
            key = _owner_key(handler)
            lease_id = str(handler.headers.get("X-TD-Camera-Lease") or "")
            qs = parse_qs(str(getattr(parsed, "query", "") or ""))
            if qs.get("lease_id") or qs.get("token"):
                return _json(handler, 400, {"error": "secrets_in_query_forbidden"})
            if not lease_id:
                return _json(handler, 403, {"error": "view_lease_required"})
            data, headers = relay.fetch_snapshot_for_viewer(key, lease_id)
            handler.send_response(200)
            for name, value in headers.items():
                handler.send_header(name, value)
            handler.send_header("Content-Length", str(len(data)))
            handler.end_headers()
            handler.wfile.write(data)
            return True

        if method == "POST" and path == "/api/td-camera/view/start":
            key = _owner_key(handler)
            relay.read_json_body(handler)
            return _json(handler, 200, relay.start_view(key))

        if method == "POST" and path == "/api/td-camera/view/stop":
            key = _owner_key(handler)
            body = relay.read_json_body(handler)
            lease_id = str(body.get("lease_id") or handler.headers.get("X-TD-Camera-Lease") or "") or None
            return _json(handler, 200, relay.stop_view(key, lease_id))

        if method == "POST" and path == "/api/td-camera/view/heartbeat":
            key = _owner_key(handler)
            body = relay.read_json_body(handler)
            lease_id = str(body.get("lease_id") or handler.headers.get("X-TD-Camera-Lease") or "")
            return _json(handler, 200, relay.heartbeat_view(key, lease_id))

        if path in {
            "/api/td-camera/lease",
            "/api/td-camera/frame",
            "/api/td-camera/heartbeat",
            "/api/td-camera/release",
            "/td-camera/producer",
        } or path.startswith("/td-camera/"):
            return _json(handler, 410, {"error": "browser_producer_removed"})

    except relay.RelayError as exc:
        return _json(handler, int(exc.status), {"error": exc.code})
    except ValueError:
        return _json(handler, 400, {"error": "bad_request"})

    return _json(handler, 404, {"error": "not_found"})
