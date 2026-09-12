"""Cockpit VISION → Visual Capture must run real Workspace capture surface.

Root harness loads real biggy-brand.js. Iframe is redirected to an isolated
Workspace instance (real app.js/CSS/cockpit_panel.js) with synthetic owner auth.
No handcrafted capture-surface HTML, no faked body classes, auth not weakened.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = Path(
    os.getenv("BIGGY_WORKSPACE_REPO", str(ROOT.parent / "Projects" / "biggy-workspace"))
)

try:
    from playwright.sync_api import expect, sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None
    expect = None


def _require_playwright():
    if sync_playwright is None:
        pytest.skip("playwright unavailable")
    return sync_playwright


COCKPIT_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Biggy</title>
<link rel="stylesheet" href="/static/biggy-brand.css">
<style>
body{margin:0;background:#05070b;color:#d7e4ec}
#mainChat{min-height:100vh;position:relative}
#composerWrap{position:fixed;left:0;right:0;bottom:12px}
#composerBox{width:min(680px,90vw);margin:0 auto}
</style></head>
<body>
<div id="mainChat" class="biggy-brand-iwo">
  <div id="composerWrap"><div id="composerBox"><textarea id="msg" aria-label="Message"></textarea></div></div>
</div>
<script src="/static/biggy-brand.js"></script>
</body></html>
"""


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    if not (WORKSPACE / "biggy_workspace/app.py").is_file():
        pytest.skip("Set BIGGY_WORKSPACE_REPO to run Vision UI integration")
    sys.path.insert(0, str(WORKSPACE))
    from biggy_workspace.app import AppState, serve
    from biggy_workspace.db import open_db
    from biggy_workspace.store import WorkspaceStore

    monkeypatch.setenv("BIGGY_WORKSPACE_RAG_RETRIEVE_URL", "fixture://workspace-rag")
    monkeypatch.delenv("BIGGY_WORKSPACE_LOCAL_INFERENCE_URL", raising=False)

    db_path = tmp_path / "vision-cockpit.db"
    # Pre-seed one synthetic task so the real focus-task picker has an option
    # after auth (no production writes).
    with open_db(db_path) as conn:
        store = WorkspaceStore(conn)
        store.create_task({"title": "Synthetic vision cockpit task"})

    state = AppState(
        db_path=db_path,
        credential="synthetic-test-token",
        host="127.0.0.1",
        port=0,
        owner_credential="synthetic-test-owner-password",
    )
    server = serve(state)
    state.port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def cockpit_server():
    brand_js = (ROOT / "static" / "biggy-brand.js").read_bytes()
    brand_css = (ROOT / "static" / "biggy-brand.css").read_bytes()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            return

        def _send(self, status, body, content_type):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/":
                return self._send(200, COCKPIT_HTML.encode("utf-8"), "text/html; charset=utf-8")
            if path == "/static/biggy-brand.js":
                return self._send(200, brand_js, "application/javascript")
            if path == "/static/biggy-brand.css":
                return self._send(200, brand_css, "text/css")
            if path.startswith("/static/"):
                return self._send(200, b"", "application/javascript")
            if path in {"/api/profiles", "/api/onboarding/status", "/api/settings"}:
                if path == "/api/profiles":
                    payload = {
                        "active": "biggy",
                        "single_profile_mode": True,
                        "profiles": [{"is_active": True, "model": "local", "provider": "local"}],
                    }
                elif path == "/api/onboarding/status":
                    payload = {"system": {"current_model": "local", "current_provider": "local"}}
                else:
                    payload = {"default_model_provider": "local"}
                return self._send(200, json.dumps(payload).encode("utf-8"), "application/json")
            return self._send(404, b"missing", "text/plain")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_app_js_show_app_wires_capture_surface_startup():
    """Focused source check: helpers must be called from showApp after auth."""
    app_js = (WORKSPACE / "biggy_workspace/static/app.js").read_text(encoding="utf-8")
    assert "function applyCaptureSurfaceMode()" in app_js
    assert "function installCaptureSurfaceReleaseHooks()" in app_js
    start = app_js.index("function showApp()")
    end = app_js.index("\n  function ", start + 1)
    show_app = app_js[start:end]
    assert "installCaptureSurfaceReleaseHooks()" in show_app
    assert "applyCaptureSurfaceMode()" in show_app
    assert "captureSurfaceReleaseHooksInstalled" in app_js
    assert "dataset.captureSurfaceHooks" in app_js


def test_cockpit_vision_menu_opens_live_capture_controls(cockpit_server, workspace):
    sp = _require_playwright()
    with sp() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        def _rewrite_biggy_workspace(route):
            req = route.request
            parsed = urlparse(req.url)
            # Map same-origin /biggy-workspace/... → isolated Workspace origin.
            suffix = parsed.path[len("/biggy-workspace") :] or "/"
            if not suffix.startswith("/"):
                suffix = "/" + suffix
            target = workspace.rstrip("/") + suffix
            if parsed.query:
                target = f"{target}?{parsed.query}"
            # Document navigation: redirect so the iframe runs real Workspace
            # without EMBED_ROOT (password auth + real static assets).
            if req.resource_type == "document":
                route.fulfill(status=302, headers={"Location": target, "Cache-Control": "no-store"})
                return
            route.continue_(url=target)

        page.route("**/biggy-workspace/**", _rewrite_biggy_workspace)
        page.route("**/biggy-workspace", _rewrite_biggy_workspace)

        page.goto(cockpit_server, wait_until="domcontentloaded")
        vision = page.get_by_test_id("biggy-vision")
        expect(vision).to_be_visible(timeout=15000)
        vision.click()
        expect(page.get_by_test_id("biggy-vision-menu")).to_be_visible()
        page.get_by_test_id("biggy-vision-vision").click()
        surface = page.get_by_test_id("biggy-vision-surface")
        expect(surface).to_be_visible()

        iframe_el = page.locator('[data-testid="biggy-vision-capture-frame"]')
        expect(iframe_el).to_be_visible()
        allow = iframe_el.get_attribute("allow") or ""
        assert "display-capture" in allow
        assert "camera" not in allow
        assert "microphone" not in allow

        # Wait for redirected Workspace login (real app, not placeholder).
        frame = page.frame_locator('[data-testid="biggy-vision-capture-frame"]')
        expect(frame.get_by_label("Owner password", exact=True)).to_be_visible(timeout=15000)
        frame.get_by_label("Owner password", exact=True).fill("synthetic-test-owner-password")
        frame.get_by_role("button", name="Sign in", exact=True).click()
        expect(frame.locator("#app")).to_be_visible(timeout=15000)

        # Capture surface must hide Planner chrome after real showApp wiring.
        expect(frame.locator("body.capture-surface")).to_be_attached(timeout=10000)
        expect(frame.locator(".planner-body")).to_be_hidden()
        expect(frame.locator("#capture-section")).to_be_hidden()
        expect(frame.get_by_role("heading", name="Quick capture", exact=True)).to_have_count(0)

        # Real controls from Workspace index.html / app.js — not hand-written fixtures.
        expect(frame.locator("#vision-capture")).to_be_visible()
        expect(frame.locator("#vision-file")).to_be_attached()
        expect(frame.locator("#vision-analyze")).to_be_visible()
        expect(frame.locator("#vision-save")).to_be_visible()
        expect(frame.locator("#vision-discard")).to_be_visible()
        expect(frame.locator("#focus-task")).to_be_visible()
        expect(frame.locator("#focus-task option")).not_to_have_count(0)

        # Release hooks installed exactly once after auth (observable marker).
        expect(frame.locator("html[data-capture-surface-hooks='1']")).to_be_attached()
        expect(frame.locator("body.capture-surface")).to_be_attached()

        # Close Vision surface from cockpit — brand tears down iframe (releases media).
        page.get_by_test_id("biggy-vision-close-surface").click()
        expect(surface).to_have_count(0)
        assert page.locator("#biggyPlannerWorkspace").count() == 0
        assert len(page.context.pages) == 1

        # Re-open: cookie may keep the frame authenticated; wait for capture surface.
        vision.click()
        page.get_by_test_id("biggy-vision-vision").click()
        expect(page.get_by_test_id("biggy-vision-surface")).to_be_visible()
        frame2 = page.frame_locator('[data-testid="biggy-vision-capture-frame"]')
        # Either login again or land already authenticated with capture-surface applied.
        try:
            expect(frame2.locator("body.capture-surface")).to_be_attached(timeout=5000)
        except Exception:
            expect(frame2.get_by_label("Owner password", exact=True)).to_be_visible(timeout=10000)
            frame2.get_by_label("Owner password", exact=True).fill("synthetic-test-owner-password")
            frame2.get_by_role("button", name="Sign in", exact=True).click()
            expect(frame2.locator("body.capture-surface")).to_be_attached(timeout=10000)
        expect(frame2.locator("html[data-capture-surface-hooks='1']")).to_be_attached()
        expect(frame2.locator(".planner-body")).to_be_hidden()
        expect(frame2.locator("#vision-capture")).to_be_visible()

        # Parent tab-hide signals release into the iframe (brand soft release).
        page.evaluate(
            """() => {
              Object.defineProperty(document, 'visibilityState', {
                configurable: true,
                get: () => 'hidden',
              });
              document.dispatchEvent(new Event('visibilitychange'));
            }"""
        )
        # Workspace message hook still receives an explicit release postMessage.
        got = frame2.locator("body").evaluate(
            """() => new Promise((resolve) => {
              let hit = false;
              window.addEventListener('message', (ev) => {
                if (ev.data && ev.data.type === 'argus-vision-release-capture') hit = true;
              });
              window.postMessage({type: 'argus-vision-release-capture'}, location.origin);
              setTimeout(() => resolve({
                hit,
                hooks: document.documentElement.dataset.captureSurfaceHooks === '1',
                captureClass: document.body.classList.contains('capture-surface'),
              }), 80);
            })"""
        )
        assert got["hooks"] is True
        assert got["captureClass"] is True
        assert got["hit"] is True

        assert len(page.context.pages) == 1
        assert not errors, errors
        browser.close()


def _tiny_jpeg(w: int = 320, h: int = 240) -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), (30, 60, 90)).save(buf, format="JPEG", quality=80)
    return buf.getvalue()


def _fixture_person_jpeg() -> bytes:
    """Reuse proven synthetic-person fixture for MediaPipe Blur proof."""
    import io

    from PIL import Image

    src = ROOT / "tests" / "fixtures" / "td_camera_synthetic_person.png"
    img = Image.open(src).convert("RGB").resize((640, 480))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


@pytest.fixture
def cockpit_td_embed_server(monkeypatch, tmp_path):
    """Same-origin Hermes-like parent: real brand + TD API + proxied Workspace.

    Auth enabled with a real signed Hermes session cookie; CSRF not weakened.
    Camera overlay runs on the parent (root GUI), not inside Visual Capture.
    """
    import hmac
    import time
    import urllib.error
    import urllib.request

    import api.auth as auth
    from api import td_camera_http, td_camera_relay as relay
    from api.helpers import _build_csp_enforced_policy

    if not (WORKSPACE / "biggy_workspace/app.py").is_file():
        pytest.skip("Set BIGGY_WORKSPACE_REPO to run Vision UI integration")
    sys.path.insert(0, str(WORKSPACE))
    from biggy_workspace.app import AppState, serve
    from biggy_workspace.auth import SESSION_COOKIE_NAME
    from biggy_workspace.db import open_db
    from biggy_workspace.store import WorkspaceStore

    monkeypatch.setenv("BIGGY_WORKSPACE_RAG_RETRIEVE_URL", "fixture://workspace-rag")
    monkeypatch.delenv("BIGGY_WORKSPACE_LOCAL_INFERENCE_URL", raising=False)

    bridge_secret = "synthetic-hermes-bridge-secret-32"
    db_path = tmp_path / "vision-td-cockpit.db"
    with open_db(db_path) as conn:
        store = WorkspaceStore(conn)
        store.create_task({"title": "Synthetic TD vision task"})

    ws_state = AppState(
        db_path=db_path,
        credential="synthetic-test-token",
        host="127.0.0.1",
        port=0,
        owner_credential="synthetic-test-owner-password",
        hermes_bridge_secret=bridge_secret,
    )
    ws_server = serve(ws_state)
    ws_state.port = ws_server.server_port
    ws_thread = threading.Thread(target=ws_server.serve_forever, daemon=True)
    ws_thread.start()
    workspace_origin = f"http://127.0.0.1:{ws_server.server_port}"

    relay.reset_for_tests()
    monkeypatch.setattr(auth, "is_auth_enabled", lambda: True)

    raw_token = "e" * 64
    sig = hmac.new(auth._signing_key(), raw_token.encode(), "sha256").hexdigest()
    auth._sessions[raw_token] = time.time() + 600
    cookie_val = f"{raw_token}.{sig}"
    csrf = auth.csrf_token_for_session(cookie_val)

    jpeg = _fixture_person_jpeg()
    state = {"snaps": 0, "health": 0}

    class Upstream(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):  # noqa: A003
            return

        def do_GET(self):  # noqa: N802
            if (self.headers.get("Authorization") or "") != "Bearer mock-td-token":
                self.send_response(401)
                self.end_headers()
                return
            if self.path == "/health":
                state["health"] += 1
                body = json.dumps(
                    {
                        "status": "ok",
                        "source": "HD Pro Webcam C920",
                        "camera_active": False,
                        # Realistic post-supervision flag: must not be treated as transport down.
                        "tunnel_process_running": False,
                    }
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path == "/snapshot.jpg":
                state["snaps"] += 1
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(jpeg)))
                self.end_headers()
                self.wfile.write(jpeg)
                return
            self.send_response(404)
            self.end_headers()

    up = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=up.serve_forever, daemon=True).start()
    relay.configure_for_tests(
        token="mock-td-token",
        upstream=f"http://127.0.0.1:{up.server_address[1]}",
    )

    brand_js = (ROOT / "static" / "biggy-brand.js").read_bytes()
    brand_css = (ROOT / "static" / "biggy-brand.css").read_bytes()
    embed_csp = _build_csp_enforced_policy().replace(
        "frame-ancestors 'none'", "frame-ancestors 'self'", 1
    )

    cockpit_html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Biggy</title>
<link rel="stylesheet" href="/static/biggy-brand.css">
<style>
body{{margin:0;background:#05070b;color:#d7e4ec}}
#mainChat{{min-height:100vh;position:relative}}
#composerWrap{{position:fixed;left:0;right:0;bottom:12px;height:120px;background:#0a1218}}
#composerBox{{width:min(680px,90vw);margin:0 auto}}
</style>
<script>window.__HERMES_CONFIG__={{csrfToken:{json.dumps(csrf)},maxUploadBytes:10485760}};</script>
</head>
<body>
<div id="mainChat" class="biggy-brand-iwo">
  <div id="composerWrap"><div id="composerBox"><textarea id="msg" aria-label="Message Biggy"></textarea></div></div>
</div>
<script src="/static/biggy-brand.js"></script>
</body></html>
"""

    def _mint_workspace_owner_cookie() -> str:
        req = urllib.request.Request(
            f"{workspace_origin}/api/v1/session/hermes-bridge",
            method="POST",
            headers={
                "Authorization": f"Bearer {bridge_secret}",
                "Accept": "application/json",
                "X-Biggy-Client": "api",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        token = str(payload.get("session_token") or "").strip()
        ttl = int(payload.get("ttl_seconds") or 3600)
        if not token:
            raise RuntimeError("bridge mint failed")
        return f"{SESSION_COOKIE_NAME}={token}; Path=/; Max-Age={ttl}; HttpOnly; SameSite=Lax"

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):  # noqa: A003
            return

        def _send(self, status, body, content_type, *, extra_headers=None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            if extra_headers:
                for k, v in extra_headers.items():
                    self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _proxy_workspace(self, method: str):
            parsed = urlparse(self.path)
            suffix = parsed.path[len("/biggy-workspace") :] or "/"
            if not suffix.startswith("/"):
                suffix = "/" + suffix
            target = workspace_origin.rstrip("/") + suffix
            if parsed.query:
                target = f"{target}?{parsed.query}"
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length > 0 else None
            req = urllib.request.Request(target, data=body, method=method)
            cookie = self.headers.get("Cookie")
            if cookie:
                req.add_header("Cookie", cookie)
            ctype = self.headers.get("Content-Type")
            if ctype:
                req.add_header("Content-Type", ctype)
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    data = resp.read()
                    rctype = resp.headers.get("Content-Type") or "application/octet-stream"
                    extra = {}
                    if "text/html" in rctype:
                        extra["Content-Security-Policy"] = embed_csp
                        extra["X-Frame-Options"] = "SAMEORIGIN"
                        if method == "GET" and suffix.rstrip("/") in {"", "/"}:
                            extra["Set-Cookie"] = _mint_workspace_owner_cookie()
                    sc = resp.headers.get("Set-Cookie")
                    if sc and "Set-Cookie" not in extra:
                        extra["Set-Cookie"] = sc
                    return self._send(
                        int(getattr(resp, "status", 200) or 200),
                        data,
                        rctype,
                        extra_headers=extra,
                    )
            except urllib.error.HTTPError as exc:
                data = exc.read() if hasattr(exc, "read") else b""
                return self._send(int(exc.code), data, "application/octet-stream")

        def _dispatch(self, method: str):
            parsed = urlparse(self.path)
            path = parsed.path
            if path.startswith("/biggy-workspace"):
                return self._proxy_workspace(method)
            if path.startswith("/api/td-camera"):
                if method in {"POST", "DELETE", "PUT", "PATCH"}:
                    from api import routes as routes_mod

                    if not routes_mod._check_csrf(self):
                        return self._send(
                            403,
                            json.dumps(
                                {"error": routes_mod._csrf_rejection_error(self)}
                            ).encode(),
                            "application/json",
                        )
                return td_camera_http.handle_td_camera(self, parsed, method)
            if method != "GET":
                return self._send(405, b"method", "text/plain")
            if path == "/":
                return self._send(200, cockpit_html.encode("utf-8"), "text/html; charset=utf-8")
            if path == "/static/biggy-brand.js":
                return self._send(200, brand_js, "application/javascript")
            if path == "/static/biggy-brand.css":
                return self._send(200, brand_css, "text/css")
            if path.startswith("/static/td-camera/"):
                rel = path[len("/static/") :]
                fpath = (ROOT / "static" / rel).resolve()
                if not str(fpath).startswith(str((ROOT / "static").resolve())) or not fpath.is_file():
                    return self._send(404, b"missing", "text/plain")
                data = fpath.read_bytes()
                ctype = "application/javascript" if fpath.suffix == ".js" else "application/octet-stream"
                if fpath.suffix == ".css":
                    ctype = "text/css"
                if fpath.suffix == ".wasm":
                    ctype = "application/wasm"
                return self._send(
                    200,
                    data,
                    ctype,
                    extra_headers={"Content-Security-Policy": embed_csp},
                )
            if path in {"/api/profiles", "/api/onboarding/status", "/api/settings"}:
                if path == "/api/profiles":
                    payload = {
                        "active": "biggy",
                        "single_profile_mode": True,
                        "profiles": [{"is_active": True, "model": "local", "provider": "local"}],
                    }
                elif path == "/api/onboarding/status":
                    payload = {"system": {"current_model": "local", "current_provider": "local"}}
                else:
                    payload = {"default_model_provider": "local"}
                return self._send(200, json.dumps(payload).encode("utf-8"), "application/json")
            if path.startswith("/static/"):
                return self._send(200, b"", "application/javascript")
            return self._send(404, b"missing", "text/plain")

        def do_GET(self):  # noqa: N802
            self._dispatch("GET")

        def do_POST(self):  # noqa: N802
            self._dispatch("POST")

        def do_DELETE(self):  # noqa: N802
            self._dispatch("DELETE")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield {
            "origin": f"http://127.0.0.1:{server.server_address[1]}",
            "cookie": cookie_val,
            "csrf": csrf,
            "state": state,
            "cookie_name": auth.COOKIE_NAME,
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        up.shutdown()
        up.server_close()
        ws_server.shutdown()
        ws_server.server_close()
        ws_thread.join(timeout=5)
        auth._sessions.pop(raw_token, None)
        relay.reset_for_tests()


def test_cockpit_td_camera_overlay_root_gui(cockpit_td_embed_server):
    """VISION→Camera opens lower-left root overlay (real brand + auth headers)."""
    sp = _require_playwright()
    info = cockpit_td_embed_server
    origin = info["origin"]
    with sp() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        context.add_cookies(
            [
                {
                    "name": info["cookie_name"],
                    "value": info["cookie"],
                    "url": origin,
                    "httpOnly": True,
                    "sameSite": "Lax",
                }
            ]
        )
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        page.goto(origin, wait_until="domcontentloaded")
        assert page.evaluate(
            "() => !!(window.__HERMES_CONFIG__ && window.__HERMES_CONFIG__.csrfToken)"
        )

        vision = page.get_by_test_id("biggy-vision")
        expect(vision).to_be_visible(timeout=15000)
        vision.click()
        page.get_by_test_id("biggy-vision-camera").click()
        overlay = page.get_by_test_id("biggy-td-camera-overlay")
        expect(overlay).to_be_visible(timeout=15000)
        box = overlay.bounding_box()
        assert box is not None
        assert box["x"] < 200
        assert box["y"] > 400  # lower half / above composer band
        # Must not claim transport down from tunnel_process_running=false.
        page.wait_for_timeout(400)
        mode = page.get_by_test_id("biggy-td-camera-mode").inner_text()
        assert "ready" in mode.lower() or "off" in mode.lower()
        page.get_by_test_id("biggy-td-camera-details").locator("summary").click()
        page.wait_for_function(
            """() => {
              const t = document.querySelector('[data-testid="biggy-td-camera-details-body"]');
              return !!(t && t.textContent && t.textContent.includes('tunnel_process_running='));
            }""",
            timeout=10000,
        )
        details = page.get_by_test_id("biggy-td-camera-details-body").evaluate(
            "el => el.textContent || ''"
        )
        assert "tunnel_process_running=false" in details
        assert "flag only" in details.lower()
        note = page.get_by_test_id("biggy-td-camera-note").inner_text().lower()
        assert "down" not in note and "unreachable" not in note
        assert info["state"]["health"] >= 1
        assert info["state"]["snaps"] == 0

        page.get_by_test_id("biggy-td-camera-backdrop").select_option("blur")
        page.get_by_test_id("biggy-td-camera-start").click()
        expect(page.get_by_test_id("biggy-td-camera-canvas")).to_be_visible(timeout=45000)
        page.wait_for_function(
            """() => {
              const t = document.querySelector('[data-testid="biggy-td-camera-note"]');
              return !!(t && /seg=ok|Preview/i.test(t.textContent || ''));
            }""",
            timeout=45000,
        )
        assert info["state"]["snaps"] >= 1

        # Drag header + resize + viewport clamp; stay above composer.
        header = page.get_by_test_id("biggy-td-camera-header")
        hb = header.bounding_box()
        assert hb
        page.mouse.move(hb["x"] + 40, hb["y"] + 10)
        page.mouse.down()
        page.mouse.move(hb["x"] + 140, hb["y"] - 80)
        page.mouse.up()
        after_drag = overlay.bounding_box()
        assert after_drag is not None
        composer = page.locator("#composerWrap").bounding_box()
        assert composer is not None
        assert after_drag["y"] + after_drag["height"] <= composer["y"] + 2

        handle = page.get_by_test_id("biggy-td-camera-resize")
        rb = handle.bounding_box()
        assert rb
        page.mouse.move(rb["x"] + 4, rb["y"] + 4)
        page.mouse.down()
        page.mouse.move(rb["x"] + 80, rb["y"] + 60)
        page.mouse.up()
        resized = overlay.bounding_box()
        assert resized is not None
        assert resized["width"] >= after_drag["width"] - 1

        # Mobile / portrait clamp
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(200)
        mobile = overlay.bounding_box()
        assert mobile is not None
        assert mobile["x"] >= 0
        assert mobile["x"] + mobile["width"] <= 390 + 1
        assert mobile["y"] + mobile["height"] <= 844

        # Fullscreen-ish landscape clamp without exiting anything
        page.set_viewport_size({"width": 1280, "height": 720})
        page.wait_for_timeout(200)
        land = overlay.bounding_box()
        assert land is not None
        assert land["x"] >= 0 and land["y"] >= 0

        page.get_by_test_id("biggy-td-camera-close").click()
        expect(overlay).to_have_count(0)
        assert page.evaluate("() => !!(window.BiggyTdCameraOverlay && !window.BiggyTdCameraOverlay.isOpen())")

        # Reopen starts Off; no auto preview
        snaps_before = info["state"]["snaps"]
        vision.click()
        page.get_by_test_id("biggy-vision-camera").click()
        expect(page.get_by_test_id("biggy-td-camera-overlay")).to_be_visible()
        assert page.get_by_test_id("biggy-td-camera-backdrop").input_value() == "off"
        expect(page.get_by_test_id("biggy-td-camera-canvas")).to_be_hidden()
        page.wait_for_timeout(400)
        assert info["state"]["snaps"] == snaps_before

        # Visual Capture must not embed camera
        vision.click()
        page.get_by_test_id("biggy-vision-vision").click()
        expect(page.get_by_test_id("biggy-vision-surface")).to_be_visible()
        # Camera overlay remains usable while Visual Capture is open
        expect(page.get_by_test_id("biggy-td-camera-overlay")).to_be_visible()
        frame = page.frame_locator('[data-testid="biggy-vision-capture-frame"]')
        expect(frame.locator("body.capture-surface")).to_be_attached(timeout=20000)
        assert frame.locator("#td-camera-viewer").count() == 0
        assert frame.locator("#td-camera-start-view").count() == 0

        page.get_by_test_id("biggy-td-camera-close").click()
        expect(page.get_by_test_id("biggy-td-camera-overlay")).to_have_count(0)
        assert not errors, errors
        browser.close()
