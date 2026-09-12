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
# Owner ai_assist can legitimately take Workspace adapter wall-clock (45s) plus
# a bounded inventory probe (~3s). Extend only that command path.
_PROXY_AI_ASSIST_TIMEOUT_SECONDS = 60
# Library search is fulfilled on Smedley against localhost:5004 — same budgets as
# Workspace rag_retrieve (nonblocking concurrency=1 + connect/read wall).
_PROXY_RAG_SEARCH_TIMEOUT_SECONDS = 25
_RAG_SIDECAR_RETRIEVE = "http://127.0.0.1:5004/rag/retrieve"
_RAG_QUERY_MAX_CHARS = 1000
_RAG_RESPONSE_MAX_BYTES = 512_000
_RAG_CONNECT_TIMEOUT_SEC = 2.0
_RAG_READ_TIMEOUT_SEC = 18.0
_RAG_READ_CHUNK_BYTES = 8192
_RAG_MAX_CONCURRENT = 1
_RAG_INDEX_STALE_AFTER_SEC = 300
_MAX_BODY_BYTES = 8 * 1024 * 1024

_lock = threading.RLock()
_cached_token: str | None = None
_cached_expires_at: float = 0.0
_retrieve_semaphore = threading.Semaphore(_RAG_MAX_CONCURRENT)


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


def _is_ai_assist_commands_request(upstream_path: str, method: str, body: bytes) -> bool:
    """True only for POST /api/v1/commands with command=ai_assist."""
    return _commands_request_command(upstream_path, method, body) == "ai_assist"


def _is_rag_search_commands_request(upstream_path: str, method: str, body: bytes) -> bool:
    """True only for POST /api/v1/commands with command=rag_search."""
    return _commands_request_command(upstream_path, method, body) == "rag_search"


def _commands_request_command(upstream_path: str, method: str, body: bytes) -> str | None:
    if str(method or "").upper() != "POST":
        return None
    path = str(upstream_path or "").rstrip("/") or "/"
    if path != "/api/v1/commands":
        return None
    if not body:
        return None
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    command = payload.get("command")
    return command if isinstance(command, str) else None


def _proxy_timeout_seconds(upstream_path: str, method: str, body: bytes) -> float:
    """Default 30s; ai_assist and rag_search use extended budgets."""
    command = _commands_request_command(upstream_path, method, body)
    if command == "ai_assist":
        return float(_PROXY_AI_ASSIST_TIMEOUT_SECONDS)
    if command == "rag_search":
        return float(_PROXY_RAG_SEARCH_TIMEOUT_SECONDS)
    return float(_PROXY_TIMEOUT_SECONDS)


def _now_z() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _set_response_socket_timeout(resp: Any, seconds: float) -> None:
    try:
        sock = resp.fp.raw._sock  # type: ignore[attr-defined]
        sock.settimeout(max(0.05, seconds))
    except Exception:
        return


def _read_bounded(resp: Any, limit: int, *, deadline: float) -> bytes:
    """Read at most limit+1 bytes under an honest wall-clock deadline."""
    buf = bytearray()
    while len(buf) <= limit:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("wall-clock deadline exceeded")
        _set_response_socket_timeout(resp, remaining)
        chunk = resp.read(min(_RAG_READ_CHUNK_BYTES, limit + 1 - len(buf)))
        if not chunk:
            break
        buf.extend(chunk)
    return bytes(buf)


def _normalize_library_citations(matches: Any) -> list[dict[str, Any]]:
    """Normalize sidecar ``matches`` from api.smedley_rag_retrieval only."""
    out: list[dict[str, Any]] = []
    if not isinstance(matches, list):
        return out
    for raw in matches[:16]:
        if not isinstance(raw, dict):
            continue
        source = str(raw.get("source") or "").strip()
        snippet = str(raw.get("snippet") or "").strip()
        if not source or not snippet:
            continue
        page = raw.get("pdf_page")
        if page is not None and type(page) not in (int, float):
            page = None
        score = raw.get("score")
        if score is not None and type(score) not in (int, float):
            score = None
        out.append(
            {
                "source": source[:500],
                "snippet": snippet[:4000],
                "score": float(score) if score is not None else None,
                "page": int(page) if page is not None else None,
                "source_hash": str(raw.get("source_hash") or "")[:128] or None,
                "generation": str(raw.get("generation") or "")[:128] or None,
                "chunk_id": str(raw.get("chunk_id") or "")[:128] or None,
            }
        )
    return out


def _index_freshness(result: dict[str, Any]) -> dict[str, Any]:
    """Source/index freshness ≠ retrieval clock. Citations alone never imply fresh."""
    indexed_at = result.get("indexed_at")
    if not isinstance(indexed_at, str) or not indexed_at.strip():
        return {
            "state": "unknown",
            "observed_at": None,
            "detail": "Index freshness not reported by retrieve response.",
        }
    stamp = indexed_at.strip()
    try:
        # Accept RFC3339 Z or offset; fall back to unknown on parse failure.
        normalized = stamp.replace("Z", "+00:00")
        from datetime import datetime, timezone

        observed = datetime.fromisoformat(normalized)
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - observed.astimezone(timezone.utc)).total_seconds()
        state = "fresh" if age <= _RAG_INDEX_STALE_AFTER_SEC else "stale"
    except (TypeError, ValueError, OverflowError):
        return {
            "state": "unknown",
            "observed_at": None,
            "detail": "Index freshness timestamp unparseable.",
        }
    return {
        "state": state,
        "observed_at": stamp,
        "detail": None,
    }


def _answer_from_citations(citations: list[dict[str, Any]], *, coverage: str) -> str:
    if not citations:
        return "No matching library excerpts were found."
    lines = ["Here are matching library excerpts:"]
    if coverage:
        lines.append(coverage[:500])
    for i, c in enumerate(citations, start=1):
        page = f", page {c['page']}" if c.get("page") is not None else ""
        lines.append(f"{i}. {c['source']}{page}")
        lines.append(c["snippet"][:500])
    return "\n".join(lines)[:16_000]


def _rag_command_payload(
    *,
    available: bool,
    state: str,
    message: str,
    query: str = "",
    result: dict[str, Any] | None = None,
) -> tuple[int, bytes, str]:
    shaped: dict[str, Any] = {
        "command": "rag_search",
        "available": available,
        "state": state,
        "message": message,
    }
    if result is not None:
        shaped["result"] = result
    elif query:
        shaped["query"] = query
    return 200, json.dumps(shaped).encode("utf-8"), "application/json"


def _fulfill_rag_search_on_smedley(body: bytes) -> tuple[int, bytes, str]:
    """Run library retrieve on localhost:5004 — never forward to PLATO.

    Schema SoT: ``/Users/rick/bin/rag_retrieval.py`` shim →
    ``api.smedley_rag_retrieval.build_retrieve_response`` (matches/collection;
    optional filter.project_folder). Library owner path sends library_only only
    (no project_folder). No auth header (current local caller). Retrieval-only.
    """
    try:
        payload = json.loads(body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return 400, json.dumps({"error": "invalid command body"}).encode("utf-8"), "application/json"
    if not isinstance(payload, dict):
        return 400, json.dumps({"error": "invalid command body"}).encode("utf-8"), "application/json"
    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    query = params.get("query", "")
    if not isinstance(query, str):
        query = ""
    q = query.strip()
    if not q or len(q) > _RAG_QUERY_MAX_CHARS:
        return (
            400,
            json.dumps(
                {"error": f"Ask a library question of 1–{_RAG_QUERY_MAX_CHARS} characters"}
            ).encode("utf-8"),
            "application/json",
        )
    if not _retrieve_semaphore.acquire(blocking=False):
        stamp = _now_z()
        return _rag_command_payload(
            available=True,
            state="busy",
            message="Library search is busy. Try again in a moment.",
            result={
                "state": "busy",
                "answer": "",
                "citations": [],
                "message": "Library search is busy. Try again in a moment.",
                "query": q,
                "retrieved_at": stamp,
                "endpoint_kind": "hermes_localhost_retrieve",
                "freshness": {
                    "state": "unavailable",
                    "observed_at": None,
                    "detail": "busy",
                },
                "coverage": "",
                "collection": None,
            },
        )
    try:
        # library_only only — omit project_folder (library-wide scope).
        req_body = json.dumps(
            {"query": q, "topk": 5, "filter": {"library_only": True}}
        ).encode("utf-8")
        request = Request(
            _RAG_SIDECAR_RETRIEVE,
            data=req_body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        opener = _upstream_opener()
        deadline = time.monotonic() + _RAG_READ_TIMEOUT_SEC
        try:
            with opener.open(request, timeout=_RAG_CONNECT_TIMEOUT_SEC) as response:
                raw = _read_bounded(response, _RAG_RESPONSE_MAX_BYTES, deadline=deadline)
                if len(raw) > _RAG_RESPONSE_MAX_BYTES:
                    return (
                        502,
                        json.dumps({"error": "library search response too large"}).encode(
                            "utf-8"
                        ),
                        "application/json",
                    )
        except HTTPError as exc:
            if 300 <= int(exc.code) < 400:
                return (
                    502,
                    json.dumps({"error": "library search redirect refused"}).encode("utf-8"),
                    "application/json",
                )
            return _rag_command_payload(
                available=False,
                state="unavailable",
                message="Library search could not complete.",
            )
        except (TimeoutError, URLError, OSError):
            return _rag_command_payload(
                available=False,
                state="unavailable",
                message="Library search timed out or could not be reached.",
            )
        try:
            result = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return _rag_command_payload(
                available=False,
                state="unavailable",
                message="Library search returned an unexpected response.",
            )
        if not isinstance(result, dict):
            return _rag_command_payload(
                available=False,
                state="unavailable",
                message="Library search returned an unexpected response.",
            )
        citations = _normalize_library_citations(result.get("matches"))
        coverage = str(result.get("coverage") or "")[:1000]
        stamp = _now_z()
        freshness = _index_freshness(result)
        if coverage and not freshness.get("detail"):
            freshness["detail"] = coverage[:300]
        result_state = "empty" if not citations else (
            "stale" if freshness.get("state") == "stale" else "ok"
        )
        return _rag_command_payload(
            available=True,
            state=result_state,
            message="Library search completed." if citations else "No matching excerpts.",
            result={
                "state": result_state,
                "answer": _answer_from_citations(citations, coverage=coverage),
                "citations": citations,
                "message": "Library search completed." if citations else "No matching excerpts.",
                "query": q,
                "retrieved_at": stamp,
                "endpoint_kind": "hermes_localhost_retrieve",
                "freshness": freshness,
                "coverage": coverage,
                "collection": result.get("collection"),
            },
        )
    finally:
        _retrieve_semaphore.release()


def _reset_retrieve_semaphore_for_tests() -> None:
    """Test helper — drain then restore a free permit."""
    while _retrieve_semaphore.acquire(blocking=False):
        pass
    _retrieve_semaphore.release()


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
    # Library search: fulfill on Smedley against localhost:5004 so PLATO never
    # needs outbound sidecar credentials and :5004 stays off the browser.
    if _is_rag_search_commands_request(upstream_path, method, body):
        status, resp_body, content_type = _fulfill_rag_search_on_smedley(body)
        return _send_bytes(handler, status, resp_body, content_type=content_type)

    request = _proxy_upstream_request(
        url, method=method, headers=headers, body=body
    )
    opener = _upstream_opener()
    proxy_timeout = _proxy_timeout_seconds(upstream_path, method, body)
    try:
        with opener.open(request, timeout=proxy_timeout) as response:
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
