"""VISION Finish Rev B — Focus evidence reopen, freeze, A/V decode, races."""

from __future__ import annotations

import base64
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PNG = ROOT / "tests" / "fixtures" / "td_camera_synthetic_person.png"
_TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _require_playwright():
    playwright = pytest.importorskip("playwright.sync_api")
    return playwright.sync_playwright


@pytest.fixture
def focus_workspace_gui(tmp_path, monkeypatch):
    """Hermes-like GUI + isolated Workspace DB for Focus/Guidance contracts."""
    import hmac
    import sys

    import api.auth as auth
    from api.helpers import _build_csp_enforced_policy

    ws_root = Path("/Users/rick/Projects/biggy-workspace")
    if not (ws_root / "biggy_workspace/app.py").is_file():
        pytest.skip("biggy-workspace unavailable")
    sys.path.insert(0, str(ws_root))
    from biggy_workspace.app import AppState, serve
    from biggy_workspace.db import open_db
    from biggy_workspace.owner_access import setup_owner_password
    from biggy_workspace.store import WorkspaceStore

    monkeypatch.delenv("BIGGY_WORKSPACE_LOCAL_INFERENCE_URL", raising=False)
    db_path = tmp_path / "focus-revb.sqlite3"
    with open_db(db_path) as conn:
        setup_owner_password(conn, "owner-password-16chars")
        store = WorkspaceStore(conn)
        task = store.create_task({"title": "Focus RevB task"})
        task_id = task["id"]

    ws_state = AppState(
        db_path=db_path,
        credential="test-credential-not-a-secret",
        host="127.0.0.1",
        port=0,
        owner_credential="owner-password-16chars",
    )
    ws_server = serve(ws_state)
    ws_state.port = ws_server.server_port
    threading.Thread(target=ws_server.serve_forever, daemon=True).start()
    ws_origin = f"http://127.0.0.1:{ws_server.server_port}"

    # Login workspace for cookie that Hermes embed would mint — Focus uses same-origin
    # /biggy-workspace proxy. Here we proxy by rewriting paths to the Workspace server.
    import urllib.error
    import urllib.request

    def ws_login_cookie() -> str:
        req = urllib.request.Request(
            ws_origin + "/api/v1/session/login",
            data=json.dumps({"password": "owner-password-16chars"}).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer test-credential-not-a-secret",
                "X-Biggy-Client": "api",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            cookie = resp.headers.get("Set-Cookie") or ""
        return cookie.split(";", 1)[0]

    ws_cookie = ws_login_cookie()

    monkeypatch.setattr(auth, "is_auth_enabled", lambda: True)
    raw = "f" * 64
    sig = hmac.new(auth._signing_key(), raw.encode(), "sha256").hexdigest()
    auth._sessions[raw] = time.time() + 600
    hermes_cookie = f"{raw}.{sig}"
    csrf = auth.csrf_token_for_session(hermes_cookie)

    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Focus RevB</title>
<link rel="stylesheet" href="/static/biggy-brand.css">
<script>window.__HERMES_CONFIG__={{csrfToken:{json.dumps(csrf)}}};</script>
</head>
<body>
<div id="mainChat" class="biggy-brand-iwo">
  <div id="composerWrap"><div id="composerBox"><textarea id="msg"></textarea></div></div>
</div>
<script src="/static/biggy-document-viewer.js"></script>
<script src="/static/biggy-brand.js"></script>
</body></html>"""

    analyze_calls = {"n": 0}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            return

        def _send(self, status, body, content_type, extra=None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            if extra:
                for k, v in extra.items():
                    self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _proxy_workspace(self, method, path, query=""):
            target = ws_origin + path.replace("/biggy-workspace", "", 1)
            if query:
                target += "?" + query
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else None
            # Local analyze fulfill (synthetic bridge) — no external model.
            if method == "POST" and path.endswith("/api/v1/vision/analyze"):
                analyze_calls["n"] += 1
                payload = {
                    "available": True,
                    "text": "synthetic-local-guidance: panel looks like a status strip",
                    "provenance": {
                        "model": "fixture-local",
                        "endpoint_kind": "local",
                        "endpoint_host": "127.0.0.1",
                        "route": "v1/chat/completions",
                        "source": "focus_test",
                        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "host": "browser",
                    },
                }
                return self._send(200, json.dumps(payload).encode(), "application/json")
            req = urllib.request.Request(
                target,
                data=body,
                method=method,
                headers={
                    "Content-Type": self.headers.get("Content-Type") or "application/json",
                    "Accept": "application/json",
                    "Cookie": ws_cookie,
                    "Authorization": "Bearer test-credential-not-a-secret",
                    "X-Biggy-Client": "api",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return self._send(
                        resp.status,
                        resp.read(),
                        resp.headers.get("Content-Type") or "application/json",
                    )
            except urllib.error.HTTPError as err:
                return self._send(
                    err.code,
                    err.read(),
                    err.headers.get("Content-Type") or "application/json",
                )

        def do_GET(self):  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/":
                return self._send(200, html.encode(), "text/html; charset=utf-8")
            if path.startswith("/biggy-workspace/"):
                return self._proxy_workspace("GET", path, parsed.query)
            if path.startswith("/static/"):
                fpath = (ROOT / "static" / path[len("/static/") :]).resolve()
                if not str(fpath).startswith(str((ROOT / "static").resolve())) or not fpath.is_file():
                    return self._send(404, b"missing", "text/plain")
                ctype = "application/javascript" if fpath.suffix == ".js" else "text/css"
                if fpath.suffix == ".css":
                    ctype = "text/css"
                return self._send(200, fpath.read_bytes(), ctype)
            return self._send(404, b"no", "text/plain")

        def do_POST(self):  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            if path.startswith("/biggy-workspace/"):
                return self._proxy_workspace("POST", path, parsed.query)
            return self._send(404, b"no", "text/plain")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{server.server_port}"
    yield {
        "origin": origin,
        "cookie": hermes_cookie,
        "cookie_name": "hermes_session",
        "task_id": task_id,
        "analyze_calls": analyze_calls,
        "ws_origin": ws_origin,
        "db_path": db_path,
    }
    server.shutdown()
    ws_server.shutdown()


def test_focus_intake_crop_ask_save_list_reopen(focus_workspace_gui):
    sp = _require_playwright()
    info = focus_workspace_gui
    assert FIXTURE_PNG.is_file()
    with sp() as p:
        from playwright.sync_api import expect

        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        context.add_cookies(
            [
                {
                    "name": info["cookie_name"],
                    "value": info["cookie"],
                    "url": info["origin"],
                    "httpOnly": True,
                    "sameSite": "Lax",
                }
            ]
        )
        page = context.new_page()
        page.goto(info["origin"], wait_until="domcontentloaded")
        page.get_by_test_id("biggy-vision").click()
        page.get_by_test_id("biggy-vision-focus").click()
        expect(page.get_by_test_id("biggy-focus-guidance")).to_be_visible(timeout=10000)
        page.set_input_files('[data-testid="biggy-focus-file"]', str(FIXTURE_PNG))
        page.wait_for_function(
            """() => {
              const t = document.querySelector('[data-testid="biggy-focus-status"]');
              return !!(t && /Intake ready/i.test(t.textContent || ''));
            }""",
            timeout=10000,
        )
        page.get_by_test_id("biggy-guidance-question").fill("What is visible?")
        # Prefer DOM click to avoid overlay interception races.
        page.evaluate("() => document.querySelector('[data-testid=\\'biggy-guidance-ask\\']').click()")
        page.wait_for_function(
            """() => {
              const a = document.querySelector('[data-testid="biggy-guidance-answer"]');
              const s = (a && a.textContent) || '';
              return /synthetic-local-guidance/i.test(s) || /Unavailable/i.test(s) || /Asking local vision/i.test(s) === false && s.length > 0;
            }""",
            timeout=20000,
        )
        ans0 = page.get_by_test_id("biggy-guidance-answer").inner_text()
        assert "synthetic-local-guidance" in ans0, ans0
        assert info["analyze_calls"]["n"] >= 1
        # Crop after answer must invalidate stale guidance.
        page.wait_for_function(
            """() => {
              const c = document.querySelector('[data-testid="biggy-focus-canvas"]');
              return !!(c && !c.hidden && Number(c.dataset.natW) > 10);
            }""",
            timeout=10000,
        )
        page.evaluate(
            """() => {
              const c = document.querySelector('[data-testid="biggy-focus-canvas"]');
              const r = c.getBoundingClientRect();
              const mk = (type, x, y) => new PointerEvent(type, {
                bubbles: true, cancelable: true, pointerId: 1, pointerType: 'mouse',
                clientX: r.left + x, clientY: r.top + y
              });
              c.dispatchEvent(mk('pointerdown', 10, 10));
              c.dispatchEvent(mk('pointermove', Math.min(r.width - 10, 80), Math.min(r.height - 10, 60)));
              c.dispatchEvent(mk('pointerup', Math.min(r.width - 10, 80), Math.min(r.height - 10, 60)));
            }"""
        )
        page.wait_for_timeout(200)
        page.evaluate("() => document.querySelector('[data-testid=\\'biggy-guidance-ask\\']').click()")
        page.wait_for_function(
            """() => {
              const a = document.querySelector('[data-testid="biggy-guidance-answer"]');
              return !!(a && /synthetic-local-guidance/i.test(a.textContent || ''));
            }""",
            timeout=20000,
        )
        page.select_option('[data-testid="biggy-focus-task"]', info["task_id"])
        page.select_option('[data-testid="biggy-focus-role"]', "before")
        page.evaluate("() => document.querySelector('[data-testid=\\'biggy-focus-save\\']').click()")
        page.wait_for_function(
            """() => {
              const t = document.querySelector('[data-testid="biggy-focus-status"]');
              const s = (t && t.textContent) || '';
              return /Saved evidence/i.test(s) || /Save failed/i.test(s);
            }""",
            timeout=20000,
        )
        status = page.get_by_test_id("biggy-focus-status").inner_text()
        assert "Saved evidence" in status, status
        list_text = page.get_by_test_id("biggy-focus-evidence").inner_text()
        assert "before" in list_text or "crop" in list_text or "ev_" in list_text
        page.evaluate("() => { window.__opened = []; const o=window.BiggyDocumentViewer.open.bind(window.BiggyDocumentViewer); window.BiggyDocumentViewer.open=(u,t)=>{window.__opened.push(u); return o(u,t);}; }")
        page.evaluate("() => document.querySelector('[data-testid^=\\'biggy-focus-open-original-\\']').click()")
        opened = page.evaluate("() => window.__opened")
        assert opened and "/api/v1/evidence/" in opened[0] and "original" in opened[0]
        page.evaluate("() => document.querySelector('[data-testid=\\'biggy-focus-clear-crop\\']').click()")
        ans = page.get_by_test_id("biggy-guidance-answer").inner_text()
        assert "synthetic-local-guidance" not in ans.lower() or "cleared" in ans.lower() or "crop" in ans.lower()
        browser.close()


def test_camera_freeze_authorized_frame_into_focus(focus_workspace_gui):
    sp = _require_playwright()
    info = focus_workspace_gui
    with sp() as p:
        from playwright.sync_api import expect

        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1100, "height": 800})
        context.add_cookies(
            [
                {
                    "name": info["cookie_name"],
                    "value": info["cookie"],
                    "url": info["origin"],
                    "httpOnly": True,
                    "sameSite": "Lax",
                }
            ]
        )
        page = context.new_page()
        page.goto(info["origin"], wait_until="domcontentloaded")
        # Inject authorized synthetic raw frame without live TD lease.
        page.evaluate(
            """async () => {
              const bytes = Uint8Array.from(atob('%s'), c => c.charCodeAt(0));
              const blob = new Blob([bytes], {type:'image/png'});
              window.openBiggyVisionSurface('focus');
              let focusApi = null;
              for (let i = 0; i < 80; i++) {
                focusApi = window.BiggyVisionFocusGuidance;
                if (focusApi && document.querySelector('[data-testid="biggy-focus-guidance"]')) break;
                await new Promise(r => setTimeout(r, 50));
              }
              if (!focusApi || typeof focusApi.ingestFreeze !== 'function') {
                throw new Error('focus_guidance_not_ready');
              }
              await focusApi.ingestFreeze({
                blob, contentType: 'image/png', source: 'td_camera_raw'
              });
            }"""
            % base64.b64encode(_TINY_PNG).decode("ascii")
        )
        expect(page.get_by_test_id("biggy-focus-guidance")).to_be_visible(timeout=10000)
        status = page.get_by_test_id("biggy-focus-status").inner_text()
        assert "Camera freeze" in status and "td_camera_raw" in status
        page.select_option('[data-testid="biggy-focus-task"]', info["task_id"])
        page.evaluate("() => document.querySelector('[data-testid=\\'biggy-focus-save\\']').click()")
        page.wait_for_function(
            """() => {
              const t = document.querySelector('[data-testid="biggy-focus-status"]');
              const s = (t && t.textContent) || '';
              return /Saved evidence/i.test(s) || /Save failed/i.test(s);
            }""",
            timeout=20000,
        )
        st = page.get_by_test_id("biggy-focus-status").inner_text()
        assert "Saved evidence" in st, st
        browser.close()


def test_focus_oversize_rejected_before_analyze(focus_workspace_gui):
    sp = _require_playwright()
    info = focus_workspace_gui
    with sp() as p:
        from playwright.sync_api import expect

        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        context.add_cookies(
            [
                {
                    "name": info["cookie_name"],
                    "value": info["cookie"],
                    "url": info["origin"],
                    "httpOnly": True,
                    "sameSite": "Lax",
                }
            ]
        )
        page = context.new_page()
        page.goto(info["origin"], wait_until="domcontentloaded")
        page.get_by_test_id("biggy-vision").click()
        page.get_by_test_id("biggy-vision-focus").click()
        expect(page.get_by_test_id("biggy-focus-guidance")).to_be_visible(timeout=10000)
        # Oversized fake file via DataTransfer is hard; inject frame directly.
        page.evaluate(
            """() => {
              const big = new Blob([new Uint8Array(1600001)], {type:'image/png'});
              const api = window.BiggyVisionFocusGuidance;
              // Use intake path internals via file constructor when available.
              const f = new File([big], 'huge.png', {type:'image/png'});
              return api; // mount already done
            }"""
        )
        # Call intake through DOM file input is preferred; use evaluate on module state.
        page.evaluate(
            """async () => {
              const big = new Blob([new Uint8Array(1600001)], {type:'image/png'});
              const f = new File([big], 'huge.png', {type:'image/png'});
              const input = document.querySelector('[data-testid="biggy-focus-file"]');
              const dt = new DataTransfer();
              dt.items.add(f);
              input.files = dt.files;
              input.dispatchEvent(new Event('change', {bubbles:true}));
            }"""
        )
        page.wait_for_function(
            """() => {
              const t = document.querySelector('[data-testid="biggy-focus-status"]');
              return !!(t && /exceeds/i.test(t.textContent || ''));
            }""",
            timeout=10000,
        )
        before = info["analyze_calls"]["n"]
        page.get_by_test_id("biggy-guidance-ask").click(force=True)
        time.sleep(0.3)
        assert info["analyze_calls"]["n"] == before
        browser.close()


def test_focus_guidance_tab_preserves_snapshot(focus_workspace_gui):
    """Focus image + answer survive Focus↔Guidance↔Overview navigation."""
    sp = _require_playwright()
    info = focus_workspace_gui
    with sp() as p:
        from playwright.sync_api import expect

        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        context.add_cookies(
            [
                {
                    "name": info["cookie_name"],
                    "value": info["cookie"],
                    "url": info["origin"],
                    "httpOnly": True,
                    "sameSite": "Lax",
                }
            ]
        )
        page = context.new_page()
        page.goto(info["origin"], wait_until="domcontentloaded")
        page.get_by_test_id("biggy-vision").click()
        page.get_by_test_id("biggy-vision-focus").click()
        expect(page.get_by_test_id("biggy-focus-guidance")).to_be_visible(timeout=10000)
        page.set_input_files('[data-testid="biggy-focus-file"]', str(FIXTURE_PNG))
        page.wait_for_function(
            """() => /Intake ready/i.test((document.querySelector('[data-testid="biggy-focus-status"]') || {}).textContent || '')""",
            timeout=10000,
        )
        page.get_by_test_id("biggy-guidance-question").fill("tab persist?")
        page.evaluate("() => document.querySelector('[data-testid=\\'biggy-guidance-ask\\']').click()")
        page.wait_for_function(
            """() => /synthetic-local-guidance/i.test((document.querySelector('[data-testid="biggy-guidance-answer"]') || {}).textContent || '')""",
            timeout=20000,
        )
        frame_id = page.evaluate("() => window.BiggyVisionFocusGuidance.getFrame().id")
        # Focus -> Guidance surface button
        page.evaluate("() => window.openBiggyVisionSurface('guidance')")
        expect(page.get_by_test_id("biggy-focus-guidance")).to_be_visible(timeout=10000)
        assert page.evaluate("() => window.BiggyVisionFocusGuidance.getFrame().id") == frame_id
        assert "synthetic-local-guidance" in page.get_by_test_id("biggy-guidance-answer").inner_text()
        expect(page.get_by_test_id("biggy-focus-canvas")).to_be_visible()
        # Guidance -> Overview soft detach keeps snapshot
        page.evaluate("() => window.openBiggyVisionSurface('overview')")
        expect(page.get_by_test_id("biggy-vision-overview-list")).to_be_visible()
        assert page.evaluate("() => window.BiggyVisionFocusGuidance.getFrame().id") == frame_id
        # Return Focus
        page.evaluate("() => window.openBiggyVisionSurface('focus')")
        expect(page.get_by_test_id("biggy-focus-guidance")).to_be_visible(timeout=10000)
        assert page.evaluate("() => window.BiggyVisionFocusGuidance.getFrame().id") == frame_id
        assert "synthetic-local-guidance" in page.get_by_test_id("biggy-guidance-answer").inner_text()
        expect(page.get_by_test_id("biggy-focus-canvas")).to_be_visible()
        # Explicit discard ends state
        page.evaluate("() => document.querySelector('[data-testid=\\'biggy-focus-discard\\']').click()")
        page.wait_for_function(
            """() => window.BiggyVisionFocusGuidance.getFrame() == null""",
            timeout=5000,
        )
        browser.close()
