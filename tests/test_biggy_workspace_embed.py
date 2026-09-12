"""Synthetic local-server tests for Biggy Workspace same-origin embed proxy."""

from __future__ import annotations

import json
import threading
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest

from api import auth
from api import biggy_workspace_embed as embed
from api.routes import _handle_biggy_workspace_embed


ROOT = Path(__file__).resolve().parents[1]
GUI_ORIGIN = "http://127.0.0.1:8790"
BRIDGE = "hermes-bridge-test-secret"
OWNER_TOKEN = "synthetic-owner-session-token"


class _UpstreamRecorder(BaseHTTPRequestHandler):
    """Workspace stand-in: mint, static, session, mutation + redirect traps."""

    bridge_secret = BRIDGE
    seen: list[dict] = []
    redirect_once = False

    def log_message(self, fmt, *args):  # noqa: A003
        return

    def _record(self, method: str, body: bytes = b""):
        self.seen.append(
            {
                "method": method,
                "path": urlparse(self.path).path,
                "authorization": self.headers.get("Authorization"),
                "cookie": self.headers.get("Cookie"),
                "origin": self.headers.get("Origin"),
                "body": body,
            }
        )

    def _json(self, status: int, payload: dict, *, extra_headers=None):
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        for name, value in extra_headers or []:
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(raw)

    def _read(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def do_POST(self):  # noqa: N802
        body = self._read()
        self._record("POST", body)
        path = urlparse(self.path).path
        if path == "/api/v1/session/hermes-bridge":
            if (self.headers.get("Authorization") or "") != f"Bearer {self.bridge_secret}":
                return self._json(401, {"error": "unauthorized"})
            return self._json(
                200,
                {
                    "state": "authenticated",
                    "session_token": OWNER_TOKEN,
                    "ttl_seconds": 3600,
                },
            )
        if path == "/api/v1/tasks":
            cookie = self.headers.get("Cookie") or ""
            if f"biggy_owner_session={OWNER_TOKEN}" not in cookie:
                return self._json(401, {"error": "unauthorized"})
            origin = self.headers.get("Origin") or ""
            if origin and origin != GUI_ORIGIN:
                return self._json(403, {"error": "origin_refused"})
            if not origin:
                return self._json(403, {"error": "origin_refused"})
            payload = json.loads(body.decode("utf-8") or "{}")
            return self._json(201, {"task": {"title": payload.get("title"), "id": "t1"}})
        if path == "/api/v1/commands":
            cookie = self.headers.get("Cookie") or ""
            if f"biggy_owner_session={OWNER_TOKEN}" not in cookie:
                return self._json(401, {"error": "unauthorized"})
            origin = self.headers.get("Origin") or ""
            if origin and origin != GUI_ORIGIN:
                return self._json(403, {"error": "origin_refused"})
            if not origin:
                return self._json(403, {"error": "origin_refused"})
            payload = json.loads(body.decode("utf-8") or "{}")
            if payload.get("command") == "ai_assist":
                return self._json(
                    200,
                    {
                        "command": "ai_assist",
                        "available": True,
                        "result": {"text": "LOCAL_AI_OK", "state": "ok"},
                    },
                )
            return self._json(200, {"command": payload.get("command"), "ok": True})
        if path == "/redirect-trap":
            # Off-origin Location — proxy must refuse to follow with Cookie/Bearer.
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:9/steal")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        return self._json(404, {"error": "not_found"})

    def do_GET(self):  # noqa: N802
        self._record("GET")
        path = urlparse(self.path).path
        cookie = self.headers.get("Cookie") or ""
        authed = f"biggy_owner_session={OWNER_TOKEN}" in cookie
        if path == "/api/v1/session":
            return self._json(
                200, {"state": "authenticated" if authed else "login_required"}
            )
        if path == "/":
            body = (
                b'<!doctype html><html><head>'
                b'<link rel="stylesheet" href="static/app.css" />'
                b'</head><body data-ok="1">'
                b'<script src="static/app.js"></script></body></html>'
            )
            self.send_response(200 if authed else 401)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/static/app.js":
            body = b'window.__BIGGY_EMBED_OK=true;'
            self.send_response(200 if authed else 401)
            self.send_header("Content-Type", "application/javascript")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/static/app.css":
            body = b"body{margin:0}"
            self.send_response(200 if authed else 401)
            self.send_header("Content-Type", "text/css")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/redirect-trap":
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:9/steal")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        return self._json(404, {"error": "not_found"})


class _BytesIO:
    def __init__(self, data: bytes = b""):
        self._data = data
        self.written = b""

    def read(self, n: int = -1) -> bytes:
        if n < 0:
            out, self._data = self._data, b""
            return out
        out, self._data = self._data[:n], self._data[n:]
        return out

    def write(self, data: bytes) -> None:
        self.written += data


class _ProxyHandler:
    def __init__(self, *, method="GET", path="/biggy-workspace/", body=b"", headers=None):
        self.command = method
        self.path = path
        self.headers = headers or {}
        self.rfile = _BytesIO(body)
        self.wfile = _BytesIO()
        self.status = None
        self.sent_headers = {}
        self.client_address = ("127.0.0.1", 45000)

    def send_response(self, status):
        self.status = status

    def send_header(self, name, value):
        self.sent_headers[str(name).lower()] = str(value)

    def end_headers(self):
        return


@pytest.fixture()
def upstream(monkeypatch):
    embed._reset_session_cache_for_tests()
    _UpstreamRecorder.seen = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _UpstreamRecorder)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{port}"
    monkeypatch.setenv("HERMES_WEBUI_BIGGY_WORKSPACE_UPSTREAM", origin)
    monkeypatch.setenv("HERMES_WEBUI_BIGGY_WORKSPACE_BRIDGE_SECRET", BRIDGE)
    try:
        yield {"origin": origin, "port": port, "server": server}
    finally:
        server.shutdown()
        server.server_close()
        embed._reset_session_cache_for_tests()


def _call(method: str, path: str, *, body: bytes = b"", headers=None):
    handler = _ProxyHandler(method=method, path=path, body=body, headers=headers or {})
    if body and "Content-Length" not in {k.title() for k in handler.headers}:
        handler.headers = dict(handler.headers)
        handler.headers["Content-Length"] = str(len(body))
    parsed = SimpleNamespace(path=path, query="")
    handled = embed.handle_biggy_workspace_embed(handler, parsed, method)
    return handler, handled


def test_html_relative_asset_and_session_get_roundtrip(upstream):
    handler, handled = _call("GET", "/biggy-workspace/", headers={"Accept": "text/html"})
    assert handled is True
    assert handler.status == 200
    html = handler.wfile.written.decode("utf-8")
    assert 'href="static/app.css"' in html
    assert 'src="static/app.js"' in html

    js_handler, ok = _call(
        "GET",
        "/biggy-workspace/static/app.js",
        headers={"Accept": "application/javascript"},
    )
    assert ok is True
    assert js_handler.status == 200
    assert b"__BIGGY_EMBED_OK" in js_handler.wfile.written

    sess, ok = _call(
        "GET",
        "/biggy-workspace/api/v1/session",
        headers={"Accept": "application/json"},
    )
    assert ok is True
    assert sess.status == 200
    assert json.loads(sess.wfile.written.decode())["state"] == "authenticated"
    assert OWNER_TOKEN not in sess.path


def test_embed_response_headers_allow_same_origin_framing_only(upstream):
    """Scoped embed policy must permit GUI iframe; hostile ancestors stay excluded."""
    from api.helpers import _build_csp_enforced_policy, _security_headers

    handler, handled = _call("GET", "/biggy-workspace/", headers={"Accept": "text/html"})
    assert handled is True
    assert handler.status == 200

    assert handler.sent_headers.get("x-frame-options") == "SAMEORIGIN"
    assert handler.sent_headers.get("x-content-type-options") == "nosniff"
    assert handler.sent_headers.get("referrer-policy") == "strict-origin"
    assert "permissions-policy" in handler.sent_headers
    assert "camera=()" in handler.sent_headers["permissions-policy"]

    csp = handler.sent_headers.get("content-security-policy") or ""
    assert "frame-ancestors 'self'" in csp
    assert "frame-ancestors 'none'" not in csp
    ancestors = csp.split("frame-ancestors", 1)[1].split(";", 1)[0]
    assert "https://evil" not in ancestors
    assert "http://evil" not in ancestors
    assert "*" not in ancestors
    assert "'none'" not in ancestors
    # Other shared directives preserved (not a bare WORLD-style strip).
    assert "object-src 'none'" in csp
    assert "default-src 'self'" in csp
    assert getattr(handler, "_skip_default_csp_report_only_once", False) is True

    # Global shared policy remains DENY / frame-ancestors none (not weakened).
    global_csp = _build_csp_enforced_policy()
    assert "frame-ancestors 'none'" in global_csp
    probe = _ProxyHandler(path="/", headers={})
    _security_headers(probe)
    assert probe.sent_headers.get("x-frame-options") == "DENY"
    assert "frame-ancestors 'none'" in (probe.sent_headers.get("content-security-policy") or "")


def test_post_mutation_requires_real_gui_origin(upstream):
    body = json.dumps({"title": "from-gui", "priority": "normal"}).encode()
    ok_handler, handled = _call(
        "POST",
        "/biggy-workspace/api/v1/tasks",
        body=body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": GUI_ORIGIN,
        },
    )
    assert handled is True
    assert ok_handler.status == 201
    assert json.loads(ok_handler.wfile.written.decode())["task"]["title"] == "from-gui"
    task_posts = [r for r in _UpstreamRecorder.seen if r["path"] == "/api/v1/tasks"]
    assert task_posts and task_posts[-1]["origin"] == GUI_ORIGIN
    assert f"biggy_owner_session={OWNER_TOKEN}" in (task_posts[-1]["cookie"] or "")
    assert task_posts[-1]["authorization"] is None  # bridge bearer never on proxied API

    bad, handled = _call(
        "POST",
        "/biggy-workspace/api/v1/tasks",
        body=json.dumps({"title": "hostile"}).encode(),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": "https://evil.example",
        },
    )
    assert handled is True
    assert bad.status == 403
    assert json.loads(bad.wfile.written.decode())["error"] == "origin_refused"


def test_proxy_refuses_off_origin_redirect_without_following(upstream):
    before = len(_UpstreamRecorder.seen)
    handler, handled = _call(
        "GET",
        "/biggy-workspace/redirect-trap",
        headers={"Accept": "application/json"},
    )
    assert handled is True
    assert handler.status == 503
    assert b"bridge_redirect_refused" in handler.wfile.written
    # Upstream saw exactly one trap hit; no follow-on /steal request.
    after = [r for r in _UpstreamRecorder.seen[before:] if r["path"] in {"/redirect-trap", "/steal"}]
    assert len(after) == 1 and after[0]["path"] == "/redirect-trap"
    assert after[0]["authorization"] is None
    assert f"biggy_owner_session={OWNER_TOKEN}" in (after[0]["cookie"] or "")


def test_check_auth_gates_all_biggy_workspace_paths(monkeypatch):
    monkeypatch.setattr(auth, "is_auth_enabled", lambda: True)
    monkeypatch.setattr(auth, "ensure_trusted_auth_session", lambda handler: None)
    monkeypatch.setattr(auth, "parse_cookie", lambda handler: None)

    paths = (
        "/biggy-workspace/",
        "/biggy-workspace/static/app.js",
        "/biggy-workspace/api/v1/session",
        "/biggy-workspace/api/v1/tasks",
    )
    for path in paths:
        handler = _ProxyHandler(path=path, headers={"Accept": "application/json"})
        allowed = auth.check_auth(handler, SimpleNamespace(path=path, query=""))
        assert allowed is False, path
        # Page paths redirect; /api/ under embed is not Hermes /api/ prefix so 302.
        assert handler.status in {401, 302}, path

    # Authenticated session is admitted.
    monkeypatch.setattr(
        auth,
        "ensure_trusted_auth_session",
        lambda handler: {"auth_type": "password", "username": "rick"},
    )
    for path in paths:
        handler = _ProxyHandler(path=path)
        assert auth.check_auth(handler, SimpleNamespace(path=path, query="")) is True


def test_routes_hook_invokes_embed_handler(upstream):
    handler = _ProxyHandler(
        path="/biggy-workspace/api/v1/session",
        headers={"Accept": "application/json"},
    )
    assert _handle_biggy_workspace_embed(
        handler,
        SimpleNamespace(path="/biggy-workspace/api/v1/session", query=""),
        "GET",
    ) is True
    assert handler.status == 200


def test_config_accepts_plato_upstream_and_loopback_not_applicable_here(monkeypatch):
    assert (
        embed.load_upstream_origin(
            {"HERMES_WEBUI_BIGGY_WORKSPACE_UPSTREAM": "https://plato.tail061f03.ts.net"}
        )
        == "https://plato.tail061f03.ts.net"
    )
    with pytest.raises(embed.EmbedConfigError):
        embed.load_upstream_origin(
            {"HERMES_WEBUI_BIGGY_WORKSPACE_UPSTREAM": "https://plato.tail061f03.ts.net/x"}
        )


def test_embed_unavailable_without_config(monkeypatch):
    embed._reset_session_cache_for_tests()
    monkeypatch.delenv("HERMES_WEBUI_BIGGY_WORKSPACE_UPSTREAM", raising=False)
    monkeypatch.delenv("HERMES_WEBUI_BIGGY_WORKSPACE_BRIDGE_SECRET", raising=False)
    handler, handled = _call("GET", "/biggy-workspace/")
    assert handled is True
    assert handler.status == 503


def test_mint_request_has_no_body_and_get_proxy_never_attaches_data():
    mod = embed
    req = mod._mint_request("https://plato.example", "bridge-secret-16chars")
    assert req.get_method() == "POST"
    assert req.data is None
    header_names = {k.lower() for k, _ in req.header_items()}
    assert "content-type" not in header_names
    assert "content-length" not in header_names
    get_req = mod._proxy_upstream_request(
        "https://plato.example/",
        method="GET",
        headers={"Accept": "text/html"},
        body=b"{}",  # hostile/stale body must not be attached on GET
    )
    assert get_req.get_method() == "GET"
    assert get_req.data is None


def test_unread_mint_body_contaminates_keepalive_get_empty_body_does_not():
    """Exact live 501: Unsupported method ('{}GET') after mint body left unread."""
    from http.client import HTTPConnection
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class ContaminatingUpstream(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        events: list = []

        def log_message(self, fmt, *args):  # noqa: A003
            return

        def do_POST(self):  # noqa: N802
            # Match production app._session_hermes_bridge: do NOT read body.
            ContaminatingUpstream.events.append(
                ("POST", self.command, self.headers.get("Content-Length"))
            )
            raw = json.dumps(
                {
                    "state": "authenticated",
                    "session_token": OWNER_TOKEN,
                    "ttl_seconds": 3600,
                }
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):  # noqa: N802
            ContaminatingUpstream.events.append(
                ("GET", self.command, self.requestline)
            )
            body = b"OK"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def send_error(self, code, message=None, explain=None):
            ContaminatingUpstream.events.append(
                ("ERR", int(code), message, getattr(self, "command", None))
            )
            return super().send_error(code, message, explain)

    ContaminatingUpstream.events = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), ContaminatingUpstream)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        # Defect shape: POST body {} left unread → next GET on same conn is {}GET.
        dirty = HTTPConnection("127.0.0.1", port, timeout=5)
        dirty.request(
            "POST",
            "/api/v1/session/hermes-bridge",
            body=b"{}",
            headers={"Content-Type": "application/json", "Connection": "keep-alive"},
        )
        assert dirty.getresponse().read()
        dirty.request("GET", "/", headers={"Connection": "keep-alive"})
        dirty_resp = dirty.getresponse()
        dirty_body = dirty_resp.read().decode("utf-8", "replace")
        assert dirty_resp.status == 501
        assert "{}GET" in dirty_body or any(
            ev[0] == "ERR" and ev[3] == "{}GET" for ev in ContaminatingUpstream.events
        )
        dirty.close()

        ContaminatingUpstream.events = []
        # Fixed mint shape: no body → keepalive GET stays clean.
        mint_req = embed._mint_request(f"http://127.0.0.1:{port}", BRIDGE)
        assert mint_req.data is None
        clean = HTTPConnection("127.0.0.1", port, timeout=5)
        clean.request(
            mint_req.get_method(),
            "/api/v1/session/hermes-bridge",
            body=mint_req.data,
            headers={k: v for k, v in mint_req.header_items()},
        )
        mint_resp = clean.getresponse()
        assert mint_resp.status == 200
        mint_resp.read()
        clean.request("GET", "/", headers={"Connection": "keep-alive"})
        get_resp = clean.getresponse()
        assert get_resp.status == 200
        assert get_resp.read() == b"OK"
        assert any(ev[0] == "GET" and ev[1] == "GET" for ev in ContaminatingUpstream.events)
        assert not any(ev[0] == "ERR" for ev in ContaminatingUpstream.events)
        clean.close()
    finally:
        server.shutdown()
        server.server_close()


def test_html_roundtrip_preserves_scoped_same_origin_frame_headers(upstream):
    handler, handled = _call("GET", "/biggy-workspace/", headers={"Accept": "text/html"})
    assert handled is True
    assert handler.status == 200
    assert handler.sent_headers.get("x-frame-options") == "SAMEORIGIN"
    csp = handler.sent_headers.get("content-security-policy") or ""
    assert "frame-ancestors 'self'" in csp
    assert "frame-ancestors 'none'" not in csp


def test_proxy_timeout_selector_extends_only_ai_assist_commands():
    """Observable contract: ai_assist commands get 60s; everything else stays 30s."""
    ai_body = json.dumps(
        {"command": "ai_assist", "params": {"prompt": "draft only"}}
    ).encode("utf-8")
    other_body = json.dumps(
        {"command": "create_task", "params": {"title": "x"}}
    ).encode("utf-8")
    assert embed._proxy_timeout_seconds("/api/v1/commands", "POST", ai_body) == 60
    assert embed._proxy_timeout_seconds("/api/v1/commands", "POST", other_body) == 30
    assert embed._proxy_timeout_seconds("/api/v1/commands", "GET", ai_body) == 30
    assert embed._proxy_timeout_seconds("/api/v1/tasks", "POST", ai_body) == 30
    assert embed._proxy_timeout_seconds("/", "GET", b"") == 30
    # Malformed / hostile bodies must not receive the extended budget.
    assert embed._proxy_timeout_seconds("/api/v1/commands", "POST", b"{") == 30
    assert embed._proxy_timeout_seconds("/api/v1/commands", "POST", b"") == 30


def test_ai_assist_proxy_open_uses_extended_timeout(upstream, monkeypatch):
    """Behavioral: opener.open for ai_assist gets 60s; neighboring POST stays 30s."""
    seen: list[dict] = []
    real_opener = embed._upstream_opener()

    class _RecordingOpener:
        def open(self, request, timeout=None):  # noqa: ANN001
            seen.append(
                {
                    "url": request.full_url,
                    "method": request.get_method(),
                    "timeout": timeout,
                    "body": request.data or b"",
                }
            )
            return real_opener.open(request, timeout=timeout)

    monkeypatch.setattr(embed, "_upstream_opener", lambda: _RecordingOpener())

    ai_body = json.dumps(
        {
            "command": "ai_assist",
            "params": {
                "prompt": (
                    "Give me a simple three-step plan for organizing a desk. "
                    "Draft only; do not create tasks."
                )
            },
        }
    ).encode("utf-8")
    handler, handled = _call(
        "POST",
        "/biggy-workspace/api/v1/commands",
        body=ai_body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": GUI_ORIGIN,
        },
    )
    assert handled is True
    assert handler.status == 200
    payload = json.loads(handler.wfile.written.decode("utf-8"))
    assert payload.get("command") == "ai_assist"
    assert payload.get("available") is True

    command_opens = [
        row
        for row in seen
        if row["method"] == "POST" and "/api/v1/commands" in row["url"]
    ]
    assert command_opens, f"expected commands open, seen={seen!r}"
    assert command_opens[-1]["timeout"] == 60

    seen.clear()
    task_body = json.dumps({"title": "neighbor"}).encode("utf-8")
    task_handler, task_ok = _call(
        "POST",
        "/biggy-workspace/api/v1/tasks",
        body=task_body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": GUI_ORIGIN,
        },
    )
    assert task_ok is True
    assert task_handler.status == 201
    task_opens = [
        row for row in seen if row["method"] == "POST" and "/api/v1/tasks" in row["url"]
    ]
    assert task_opens
    assert task_opens[-1]["timeout"] == 30

    # Mint path remains on the short mint timeout (not the proxy AI budget).
    mint_opens = [row for row in seen if "/hermes-bridge" in row["url"]]
    # Cache may already hold a session from the first call; either way mint ≠ 60.
    for row in mint_opens:
        assert row["timeout"] == embed._MINT_TIMEOUT_SECONDS


def test_rag_search_fulfilled_on_smedley_not_forwarded_to_plato(upstream, monkeypatch):
    """Owner library search uses localhost:5004 via Hermes; PLATO never sees rag_search."""
    from io import BytesIO
    from urllib.response import addinfourl
    from email.message import EmailMessage

    real_opener = embed._upstream_opener()

    class _RoutingOpener:
        def open(self, request, timeout=None):  # noqa: ANN001
            if request.full_url == embed._RAG_SIDECAR_RETRIEVE:
                assert request.get_method() == "POST"
                req_body = json.loads((request.data or b"{}").decode("utf-8"))
                assert req_body.get("filter") == {"library_only": True}
                assert isinstance(req_body.get("query"), str) and req_body["query"]
                sidecar_payload = {
                    "matches": [
                        {
                            "source": "library/demo.pdf",
                            "snippet": "Verified excerpt for owner Library search.",
                            "score": 0.9,
                            "pdf_page": 2,
                            "source_hash": "abc",
                            "url": (
                                "/api/biggy/rag/doc/"
                                "library/demo.pdf"
                            ),
                        }
                    ],
                    "coverage": (
                        "library_semantic quality_state passthrough; "
                        "registry/is_empty; not upgraded to verified"
                    ),
                    "collection": "library",
                }
                raw = json.dumps(sidecar_payload).encode("utf-8")
                headers = EmailMessage()
                headers["Content-Type"] = "application/json"
                return addinfourl(BytesIO(raw), headers, request.full_url, code=200)
            return real_opener.open(request, timeout=timeout)

    monkeypatch.setattr(embed, "_upstream_opener", lambda: _RoutingOpener())
    before = list(_UpstreamRecorder.seen)
    body = json.dumps(
        {"command": "rag_search", "params": {"query": "FTA wiring diagram"}}
    ).encode("utf-8")
    handler, handled = _call(
        "POST",
        "/biggy-workspace/api/v1/commands",
        body=body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": GUI_ORIGIN,
        },
    )
    assert handled is True
    assert handler.status == 200
    payload = json.loads(handler.wfile.written.decode("utf-8"))
    assert payload.get("command") == "rag_search"
    assert payload.get("available") is True
    assert payload.get("state") == "ok"
    assert payload["result"]["endpoint_kind"] == "hermes_localhost_retrieve"
    assert payload["result"]["citations"][0]["source"] == "library/demo.pdf"
    assert payload["result"]["citations"][0]["url"] == (
        "/api/biggy/rag/doc/library/demo.pdf#page=2"
    )
    assert "Found 1 matching library source" in payload["result"]["answer"]
    assert "quality_state" not in payload["result"]["answer"]
    assert "Verified excerpt for owner Library search" not in payload["result"]["answer"]
    assert payload["result"]["freshness"]["state"] == "unknown"
    assert payload["result"]["freshness"]["observed_at"] is None
    assert payload["result"]["retrieved_at"]
    assert payload["result"]["collection"] == "library"
    new_cmds = [
        row
        for row in _UpstreamRecorder.seen[len(before) :]
        if row.get("path") == "/api/v1/commands"
    ]
    assert new_cmds == []


def test_rag_search_busy_when_semaphore_held(upstream, monkeypatch):
    """Nonblocking concurrency=1 — second live retrieve returns busy, no sidecar call."""
    embed._reset_retrieve_semaphore_for_tests()
    assert embed._retrieve_semaphore.acquire(blocking=False) is True
    retrieve_opens: list[str] = []
    real_opener = embed._upstream_opener()

    class _CountingOpener:
        def open(self, request, timeout=None):  # noqa: ANN001
            if request.full_url == embed._RAG_SIDECAR_RETRIEVE:
                retrieve_opens.append(request.full_url)
                raise AssertionError("sidecar must not be called when busy")
            return real_opener.open(request, timeout=timeout)

    monkeypatch.setattr(embed, "_upstream_opener", lambda: _CountingOpener())
    try:
        body = json.dumps(
            {"command": "rag_search", "params": {"query": "busy check"}}
        ).encode("utf-8")
        handler, handled = _call(
            "POST",
            "/biggy-workspace/api/v1/commands",
            body=body,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Origin": GUI_ORIGIN,
            },
        )
        assert handled is True
        assert handler.status == 200
        payload = json.loads(handler.wfile.written.decode("utf-8"))
        assert payload.get("state") == "busy"
        assert payload["result"]["state"] == "busy"
        assert retrieve_opens == []
    finally:
        embed._retrieve_semaphore.release()
        embed._reset_retrieve_semaphore_for_tests()


def test_rag_search_index_freshness_from_indexed_at_only(upstream, monkeypatch):
    """Citations alone never mark source freshness fresh."""
    from io import BytesIO
    from urllib.response import addinfourl
    from email.message import EmailMessage

    real_opener = embed._upstream_opener()

    class _RoutingOpener:
        def open(self, request, timeout=None):  # noqa: ANN001
            if request.full_url == embed._RAG_SIDECAR_RETRIEVE:
                assert timeout == embed._RAG_CONNECT_TIMEOUT_SEC
                sidecar_payload = {
                    "matches": [
                        {
                            "source": "library/demo.pdf",
                            "snippet": "Excerpt",
                            "score": 0.9,
                            "pdf_page": 1,
                        }
                    ],
                    "collection": "library",
                    "indexed_at": "2099-01-01T00:00:00Z",
                }
                raw = json.dumps(sidecar_payload).encode("utf-8")
                headers = EmailMessage()
                headers["Content-Type"] = "application/json"
                return addinfourl(BytesIO(raw), headers, request.full_url, code=200)
            return real_opener.open(request, timeout=timeout)

    monkeypatch.setattr(embed, "_upstream_opener", lambda: _RoutingOpener())
    body = json.dumps(
        {"command": "rag_search", "params": {"query": "freshness check"}}
    ).encode("utf-8")
    handler, handled = _call(
        "POST",
        "/biggy-workspace/api/v1/commands",
        body=body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": GUI_ORIGIN,
        },
    )
    assert handled is True
    payload = json.loads(handler.wfile.written.decode("utf-8"))
    assert payload["result"]["freshness"]["state"] == "fresh"
    assert payload["result"]["freshness"]["observed_at"] == "2099-01-01T00:00:00Z"
    assert payload["result"]["retrieved_at"] != "2099-01-01T00:00:00Z"


def test_safe_corpus_open_url_allowlist_rejects_arbitrary():
    doc = "/api/biggy/rag/doc/Vendor%20Data/x.pdf"
    assert embed._safe_corpus_open_url(doc, page=3) == f"{doc}#page=3"
    assert embed._safe_corpus_open_url(
        "/api/biggy/rag/preview/a.txt"
    ) == "/api/biggy/rag/preview/a.txt"
    assert embed._safe_corpus_open_url("https://evil.example/x") is None
    assert embed._safe_corpus_open_url("//evil.example/x") is None
    assert embed._safe_corpus_open_url("/api/other/sidecar/doc/x.pdf") is None
    assert (
        embed._safe_corpus_open_url(
            "/api/biggy/rag/doc/../secret"
        )
        is None
    )
    cites = embed._normalize_library_citations(
        [
            {
                "source": "library/a.pdf",
                "snippet": "body",
                "pdf_page": 1,
                "url": "javascript:alert(1)",
            },
            {
                "source": "library/b.pdf",
                "snippet": "body2",
                "pdf_page": 9,
                "url": "/api/biggy/rag/doc/library/b.pdf",
            },
        ]
    )
    assert cites[0]["url"] is None
    assert cites[1]["url"].endswith("#page=9")
    answer = embed._answer_from_citations(
        cites,
        coverage="quality_state registry is_empty not upgraded to verified",
    )
    assert "quality_state" not in answer
    assert "body2" not in answer


def test_legacy_sidecar_citation_is_mapped_to_current_biggy_route():
    assert embed._safe_corpus_open_url('/api/extensions/smedley-engineering/sidecar/doc/Vendor%20Data/manual.pdf', page=2) == '/api/biggy/rag/doc/Vendor%20Data/manual.pdf#page=2'
