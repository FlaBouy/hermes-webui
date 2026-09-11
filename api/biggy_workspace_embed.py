"""Same-origin authenticated Biggy Workspace embed proxy.

Open Workspace loads /biggy-workspace/ inside the Hermes GUI iframe. Hermes
requires the existing GUI session (check_auth), mints a short-lived Workspace
owner session via server-to-server hermes-bridge, and injects that cookie on
upstream requests. Browser never sees owner passwords or bridge secrets in URLs.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

logger = logging.getLogger(__name__)

EMBED_PREFIX = "/biggy-workspace"
_SESSION_COOKIE = "biggy_owner_session"
_PLACEHOLDERS = frozenset(
    {"replace-with-a-long-random-secret", "changeme", "secret", "password"}
)
_REFRESH_SKEW_SECONDS = 60
_MINT_TIMEOUT_SECONDS = 10
_PROXY_TIMEOUT_SECONDS = 30
_MAX_BODY_BYTES = 8 * 1024 * 1024

_lock = threading.RLock()
_cached_token: str | None = None
_cached_expires_at: float = 0.0


class EmbedConfigError(RuntimeError):
    pass


class _RefuseRedirectHandler(HTTPRedirectHandler):
    """Never auto-follow redirects — prevents Cookie/Bearer leaking off upstream."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def _upstream_opener():
    # Default opener follows redirects and can re-send Authorization. Refuse all
    # redirects so session Cookie and bridge Bearer never leave the configured
    # upstream origin via Location.
    return build_opener(_RefuseRedirectHandler)


def _truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def load_upstream_origin(environ: dict[str, str] | None = None) -> str | None:
    env = environ if environ is not None else os.environ
    raw = str(env.get("HERMES_WEBUI_BIGGY_WORKSPACE_UPSTREAM", "")).strip().rstrip("/")
    if not raw:
        return None
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.path not in {"", "/"}:
        raise EmbedConfigError(
            "HERMES_WEBUI_BIGGY_WORKSPACE_UPSTREAM must be an http(s) origin "
            "(scheme://host[:port], no path/query/fragment)"
        )
    if parsed.username is not None or parsed.password is not None:
        raise EmbedConfigError(
            "HERMES_WEBUI_BIGGY_WORKSPACE_UPSTREAM must not include userinfo"
        )
    if parsed.query or parsed.fragment:
        raise EmbedConfigError(
            "HERMES_WEBUI_BIGGY_WORKSPACE_UPSTREAM must not include query or fragment"
        )
    return f"{parsed.scheme}://{parsed.netloc}"


def load_bridge_secret(environ: dict[str, str] | None = None) -> str | None:
    env = environ if environ is not None else os.environ
    file_path = str(env.get("HERMES_WEBUI_BIGGY_WORKSPACE_BRIDGE_SECRET_FILE", "")).strip()
    if file_path:
        try:
            value = Path(file_path).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise EmbedConfigError(
                "HERMES_WEBUI_BIGGY_WORKSPACE_BRIDGE_SECRET_FILE could not be read"
            ) from exc
    else:
        value = str(env.get("HERMES_WEBUI_BIGGY_WORKSPACE_BRIDGE_SECRET", "")).strip()
        if not value:
            return None
    if value in _PLACEHOLDERS:
        raise EmbedConfigError(
            "HERMES_WEBUI_BIGGY_WORKSPACE_BRIDGE_SECRET must not use a placeholder"
        )
    if len(value) < 16:
        raise EmbedConfigError(
            "HERMES_WEBUI_BIGGY_WORKSPACE_BRIDGE_SECRET must be at least 16 characters"
        )
    return value


def embed_configured(environ: dict[str, str] | None = None) -> bool:
    try:
        return bool(load_upstream_origin(environ) and load_bridge_secret(environ))
    except EmbedConfigError:
        return False


def is_embed_path(path: str) -> bool:
    return path == EMBED_PREFIX or path.startswith(EMBED_PREFIX + "/")


def _map_upstream_path(path: str) -> str | None:
    if not is_embed_path(path):
        return None
    rest = path[len(EMBED_PREFIX) :]
    if rest in {"", "/"}:
        return "/"
    if ".." in rest.split("/"):
        return None
    if not rest.startswith("/"):
        return None
    return rest


def _read_body(handler, *, max_bytes: int = _MAX_BODY_BYTES) -> bytes:
    length_raw = handler.headers.get("Content-Length") if handler.headers else None
    if not length_raw:
        return b""
    try:
        length = int(length_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid Content-Length") from exc
    if length < 0 or length > max_bytes:
        raise ValueError("Request body too large")
    return handler.rfile.read(length) if length else b""


def _clear_cached_session() -> None:
    global _cached_token, _cached_expires_at
    with _lock:
        _cached_token = None
        _cached_expires_at = 0.0


def _mint_request(upstream: str, bridge_secret: str) -> Request:
    """Build hermes-bridge mint Request.

    Must not attach a JSON body. Production Workspace ``_session_hermes_bridge``
    never reads the POST body; an unread ``{}`` on an HTTP/1.1 keepalive (or
    upstream connection pool) contaminates the next request as ``{}GET`` → 501.
    """
    url = f"{upstream.rstrip('/')}/api/v1/session/hermes-bridge"
    return Request(
        url,
        data=None,
        headers={
            "Authorization": f"Bearer {bridge_secret}",
            "Accept": "application/json",
            "X-Biggy-Client": "api",
            # Discourage pooling a mint socket that older clients dirtied with a body.
            "Connection": "close",
        },
        method="POST",
    )


def _proxy_upstream_request(
    url: str,
    *,
    method: str,
    headers: dict[str, str],
    body: bytes,
) -> Request:
    """Build upstream proxy Request; GET/HEAD never carry a body."""
    method_u = str(method or "GET").upper()
    if method_u in {"GET", "HEAD"}:
        return Request(url, data=None, headers=headers, method=method_u)
    return Request(
        url,
        data=body if body else None,
        headers=headers,
        method=method_u,
    )


def _mint_session(upstream: str, bridge_secret: str) -> tuple[str, int]:
    request = _mint_request(upstream, bridge_secret)
    if request.data is not None:
        raise EmbedConfigError("bridge_mint_invalid_request")
    opener = _upstream_opener()
    try:
        with opener.open(request, timeout=_MINT_TIMEOUT_SECONDS) as response:
            body = response.read()
            status = getattr(response, "status", 200)
    except HTTPError as exc:
        if 300 <= int(exc.code) < 400:
            raise EmbedConfigError("bridge_redirect_refused") from exc
        detail = "bridge_mint_failed"
        try:
            payload = json.loads(exc.read().decode("utf-8") or "{}")
            if isinstance(payload, dict) and payload.get("error"):
                detail = str(payload["error"])
        except Exception:
            pass
        raise EmbedConfigError(detail) from exc
    except (TimeoutError, URLError, OSError) as exc:
        raise EmbedConfigError("bridge_upstream_unreachable") from exc
    if status != 200:
        raise EmbedConfigError("bridge_mint_failed")
    try:
        payload = json.loads(body.decode("utf-8") or "{}")
    except json.JSONDecodeError as exc:
        raise EmbedConfigError("bridge_mint_invalid") from exc
    token = str(payload.get("session_token") or "").strip()
    ttl = int(payload.get("ttl_seconds") or 0)
    if not token or ttl < 1:
        raise EmbedConfigError("bridge_mint_invalid")
    return token, ttl


def _owner_session_token() -> str:
    global _cached_token, _cached_expires_at
    upstream = load_upstream_origin()
    secret = load_bridge_secret()
    if not upstream or not secret:
        raise EmbedConfigError("bridge_not_configured")
    now = time.time()
    with _lock:
        if _cached_token and now < (_cached_expires_at - _REFRESH_SKEW_SECONDS):
            return _cached_token
    token, ttl = _mint_session(upstream, secret)
    with _lock:
        _cached_token = token
        _cached_expires_at = time.time() + ttl
        return _cached_token


def _proxy_request_headers(handler, *, session_token: str) -> dict[str, str]:
    headers: dict[str, str] = {
        "Cookie": f"{_SESSION_COOKIE}={session_token}",
        "Accept": handler.headers.get("Accept") or "*/*",
    }
    raw = getattr(handler, "headers", None)
    if raw and hasattr(raw, "items"):
        for name, value in raw.items():
            lower = str(name).lower()
            if lower in {
                "host",
                "content-length",
                "connection",
                "transfer-encoding",
                "authorization",
                "cookie",
                "x-hermes-csrf-token",
            } or lower.startswith("x-hermes-"):
                continue
            if lower in {"origin", "referer", "content-type", "accept", "accept-language"}:
                headers[str(name)] = str(value)
    return headers


def _embed_security_headers(handler) -> None:
    """Security headers for /biggy-workspace/* only — same-origin framing allowed.

    Shared ``api.helpers._security_headers`` sets X-Frame-Options: DENY and
    frame-ancestors 'none', which blocks the authenticated GUI iframe. Mirror
    the scoped V6 world policy in routes._handle_biggy_v6_world_asset: keep the
    rest of the enforced CSP / nosniff / referrer / permissions policy, but
    permit framing by 'self' only. Do not weaken the global app policy.
    """
    from api.helpers import (
        _build_csp_enforced_policy,
        _csp_extra_connect_src,
        _csp_extra_frame_src,
    )

    extra_connect_src = _csp_extra_connect_src()
    extra_frame_src = _csp_extra_frame_src()
    handler._csp_extra_connect_src = extra_connect_src
    handler._csp_extra_frame_src = extra_frame_src
    csp = _build_csp_enforced_policy(extra_connect_src, extra_frame_src)
    if "frame-ancestors 'none'" not in csp:
        raise RuntimeError("expected shared CSP frame-ancestors 'none' to rewrite")
    csp = csp.replace("frame-ancestors 'none'", "frame-ancestors 'self'", 1)
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("X-Frame-Options", "SAMEORIGIN")
    handler.send_header("Referrer-Policy", "strict-origin")
    handler.send_header("Content-Security-Policy", csp)
    handler.send_header(
        "Permissions-Policy",
        "camera=(), microphone=(self), geolocation=(), clipboard-write=(self)",
    )
    # Global report-only still advertises frame-ancestors 'none'; skip it once
    # so it does not contradict this scoped enforced policy (same as V6 world).
    handler._skip_default_csp_report_only_once = True


def _send_bytes(handler, status: int, body: bytes, *, content_type: str) -> bool:
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    try:
        _embed_security_headers(handler)
    except Exception:
        # Fail closed on framing: if scoped headers cannot be applied, do not
        # fall back to global DENY silently for HTML embeds — still try nosniff.
        try:
            handler.send_header("X-Content-Type-Options", "nosniff")
            handler.send_header("X-Frame-Options", "SAMEORIGIN")
            handler.send_header(
                "Content-Security-Policy",
                "default-src 'self'; frame-ancestors 'self'; base-uri 'self'",
            )
            handler._skip_default_csp_report_only_once = True
        except Exception:
            pass
    try:
        from api.helpers import flush_pending_auth_cookies

        flush_pending_auth_cookies(handler)
    except Exception:
        pass
    handler.end_headers()
    handler.wfile.write(body)
    return True


def _unavailable(handler, parsed, message: str) -> bool:
    wants_json = "/api/" in str(getattr(parsed, "path", "") or "")
    if wants_json or "application/json" in str(handler.headers.get("Accept") or ""):
        body = json.dumps({"error": message}).encode("utf-8")
        return _send_bytes(handler, 503, body, content_type="application/json")
    html = (
        "<!doctype html><meta charset=utf-8><title>Workspace unavailable</title>"
        "<body style='font:14px system-ui;padding:2rem'>"
        "<h1>Biggy Workspace embed unavailable</h1>"
        f"<p>{message.replace('<', '')}</p>"
        "<p>Atlas deploy handoff: configure upstream + shared bridge secret. "
        "No owner password is required in the GUI iframe when bridge is live.</p>"
        "</body>"
    ).encode("utf-8")
    return _send_bytes(handler, 503, html, content_type="text/html; charset=utf-8")


def handle_biggy_workspace_embed(handler, parsed, method: str) -> bool | None:
    """Proxy /biggy-workspace/* when path matches; False if not this route.

    Returns True when handled. Caller must already have passed Hermes check_auth.
    """
    path = str(getattr(parsed, "path", "") or "")
    upstream_path = _map_upstream_path(path)
    if upstream_path is None:
        if is_embed_path(path):
            return _unavailable(handler, parsed, "invalid_embed_path")
        return False

    try:
        upstream = load_upstream_origin()
        secret = load_bridge_secret()
    except EmbedConfigError as exc:
        logger.warning("Biggy Workspace embed config error: %s", exc)
        return _unavailable(handler, parsed, "bridge_not_configured")
    if not upstream or not secret:
        return _unavailable(handler, parsed, "bridge_not_configured")

    try:
        session_token = _owner_session_token()
    except EmbedConfigError as exc:
        logger.warning("Biggy Workspace embed mint failed: %s", exc)
        _clear_cached_session()
        return _unavailable(handler, parsed, str(exc) or "bridge_mint_failed")

    query = str(getattr(parsed, "query", "") or "")
    target = urlunsplit(("", "", upstream_path, query, ""))
    url = upstream + target

    try:
        body = _read_body(handler) if method.upper() in {"POST", "PUT", "PATCH", "DELETE"} else b""
    except ValueError as exc:
        status = 413 if "too large" in str(exc).lower() else 400
        return _send_bytes(
            handler,
            status,
            json.dumps({"error": str(exc)}).encode("utf-8"),
            content_type="application/json",
        )

    headers = _proxy_request_headers(handler, session_token=session_token)
    request = _proxy_upstream_request(
        url, method=method, headers=headers, body=body
    )
    opener = _upstream_opener()
    try:
        with opener.open(request, timeout=_PROXY_TIMEOUT_SECONDS) as response:
            resp_body = response.read()
            status = int(getattr(response, "status", 200))
            content_type = response.headers.get("Content-Type") or "application/octet-stream"
            return _send_bytes(handler, status, resp_body, content_type=content_type)
    except HTTPError as exc:
        if 300 <= int(exc.code) < 400:
            # Do not forward Location or follow with Cookie/Bearer.
            return _unavailable(handler, parsed, "bridge_redirect_refused")
        try:
            resp_body = exc.read() or b""
        except Exception:
            resp_body = b""
        content_type = exc.headers.get("Content-Type") if exc.headers else None
        if exc.code in {401, 403}:
            _clear_cached_session()
        return _send_bytes(
            handler,
            int(exc.code),
            resp_body,
            content_type=content_type or "application/json",
        )
    except (TimeoutError, URLError, OSError):
        logger.warning(
            "Biggy Workspace embed proxy failed for %s %s",
            method,
            path,
            exc_info=True,
        )
        return _unavailable(handler, parsed, "bridge_upstream_unreachable")


# Test helpers
def _reset_session_cache_for_tests() -> None:
    _clear_cached_session()
