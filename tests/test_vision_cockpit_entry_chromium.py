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
