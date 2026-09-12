"""TD camera native proxy + viewer tests (mock upstream; no live camera activation)."""

from __future__ import annotations

import hmac
import io
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest

import api.auth as auth
import api.routes as routes
from api import td_camera_http, td_camera_relay as relay

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PERSON = ROOT / "tests" / "fixtures" / "td_camera_synthetic_person.png"
WORKSPACE = Path(
    __import__("os").getenv(
        "BIGGY_WORKSPACE_REPO",
        str(ROOT.parent / "Projects" / "biggy-workspace"),
    )
)

try:
    from playwright.sync_api import expect, sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None
    expect = None


def _tiny_jpeg(w: int = 64, h: int = 48) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), (20, 40, 60)).save(buf, format="JPEG", quality=80)
    return buf.getvalue()


def _signed_cookie(raw_token: str) -> str:
    sig = hmac.new(auth._signing_key(), raw_token.encode(), "sha256").hexdigest()
    auth._sessions[raw_token] = time.time() + 60
    return f"{raw_token}.{sig}"


@pytest.fixture(autouse=True)
def _reset():
    relay.reset_for_tests()
    yield
    relay.reset_for_tests()


def test_vendor_assets_present():
    info = relay.vendor_ready()
    assert info["ready"] is True, info
    assert info["license"] == "Apache-2.0"


def test_health_does_not_call_snapshot():
    calls = []

    def fetch(path):
        calls.append(path)
        if path == "/health":
            return 200, {}, json.dumps({
                "status": "ok",
                "source": "HD Pro Webcam C920",
                "camera_active": False,
                "tunnel_process_running": True,
            }).encode()
        raise AssertionError(f"unexpected path {path}")

    relay.configure_for_tests(token="test-token", fetch=fetch)
    out = relay.fetch_health(cache_sec=0)
    assert out["camera_active"] is False
    assert "segmentation" in out  # reported separately from transport
    assert calls == ["/health"]


def test_jpeg_dimension_validation():
    ok = _tiny_jpeg(320, 240)
    assert relay.validate_jpeg_frame(ok) == (320, 240)
    big = _tiny_jpeg(800, 600)
    with pytest.raises(relay.RelayError) as exc:
        relay.validate_jpeg_frame(big)
    assert exc.value.code == "dimensions_out_of_bounds"


def test_independent_leases_stop_by_id_only():
    owner = relay.owner_key_from_session_cookie("same-session")
    a = relay.start_view(owner)
    b = relay.start_view(owner)
    assert a["lease_id"] != b["lease_id"]
    assert "stop_by_lease_id_only" in a["multi_viewer_policy"]
    with pytest.raises(relay.RelayError):
        relay.stop_view(owner, None)
    assert relay.stop_view(owner, a["lease_id"])["stopped"] is True
    # B still alive
    jpeg = _tiny_jpeg(80, 60)

    def fetch(path):
        assert path == "/snapshot.jpg"
        return 200, {}, jpeg

    relay.configure_for_tests(token="t", fetch=fetch)
    data, _ = relay.fetch_snapshot_for_viewer(owner, b["lease_id"])
    assert data.startswith(b"\xff\xd8")


def test_stop_during_inflight_discards_and_does_not_renew():
    owner = relay.owner_key_from_session_cookie("inflight")
    lease = relay.start_view(owner)
    jpeg = _tiny_jpeg(100, 80)
    started = threading.Event()
    release = threading.Event()

    def fetch(path):
        started.set()
        release.wait(timeout=2)
        return 200, {}, jpeg

    relay.configure_for_tests(token="t", fetch=fetch)

    result = {}

    def worker():
        try:
            result["data"] = relay.fetch_snapshot_for_viewer(owner, lease["lease_id"])
        except relay.RelayError as exc:
            result["err"] = exc.code

    t = threading.Thread(target=worker)
    t.start()
    assert started.wait(2)
    relay.stop_view(owner, lease["lease_id"])
    release.set()
    t.join(timeout=3)
    assert result.get("err") == "view_lease_required"
    assert "data" not in result
    # Lease must not have been renewed/recreated
    assert relay.status(viewer_owner_key=owner)["view_active"] is False


def test_rate_reserve_before_upstream():
    owner = relay.owner_key_from_session_cookie("rate")
    lease = relay.start_view(owner)
    jpeg = _tiny_jpeg(64, 48)
    calls = []

    def fetch(path):
        calls.append(path)
        return 200, {}, jpeg

    relay.configure_for_tests(token="t", fetch=fetch)
    relay.fetch_snapshot_for_viewer(owner, lease["lease_id"])
    with pytest.raises(relay.RelayError) as rate:
        relay.fetch_snapshot_for_viewer(owner, lease["lease_id"])
    assert rate.value.code == "rate_limited"
    assert calls == ["/snapshot.jpg"]


def test_http_rejects_secrets_in_query_and_removed_producer(monkeypatch):
    monkeypatch.setattr("api.auth.is_auth_enabled", lambda: False)

    class H:
        def __init__(self, headers=None, body=b""):
            self.headers = headers or {}
            self.rfile = io.BytesIO(body)
            self.wfile = io.BytesIO()
            self.status = None
            self.sent_headers = {}

        def send_response(self, s):
            self.status = s

        def send_header(self, k, v):
            self.sent_headers[k] = v

        def end_headers(self):
            pass

    h = H()
    assert td_camera_http.handle_td_camera(
        h, urlparse("/api/td-camera/frame.jpg?lease_id=secret"), "GET"
    )
    assert h.status == 400
    h2 = H(headers={"Content-Length": "2"}, body=b"{}")
    assert td_camera_http.handle_td_camera(h2, urlparse("/api/td-camera/lease"), "POST")
    assert h2.status == 410


def test_router_csrf_and_auth_gate_frame_start(monkeypatch):
    """Real routes.handle_post CSRF + auth; unauth cookie must not open frames."""
    monkeypatch.setattr(auth, "is_auth_enabled", lambda: True)
    relay.configure_for_tests(
        token="t",
        fetch=lambda path: (
            (200, {}, b'{"status":"ok","source":"C920","camera_active":false,"tunnel_process_running":true}')
            if path == "/health"
            else (200, {}, _tiny_jpeg(64, 48))
        ),
    )

    class H:
        def __init__(self, headers=None, body=b"{}"):
            self.headers = headers or {}
            self.rfile = io.BytesIO(body)
            self.wfile = io.BytesIO()
            self.status = None
            self.sent_headers = {}
            self.client_address = ("127.0.0.1", 1)

        def send_response(self, s):
            self.status = s

        def send_header(self, k, v):
            self.sent_headers[k] = v

        def end_headers(self):
            pass

    # No session → CSRF fails before camera
    bare = H({"Origin": "http://127.0.0.1:8787", "Host": "127.0.0.1:8787", "Content-Length": "2"}, b"{}")
    routes.handle_post(bare, SimpleNamespace(path="/api/td-camera/view/start", query=""))
    assert bare.status == 403

    cookie = _signed_cookie("d" * 64)
    token = auth.csrf_token_for_session(cookie)
    try:
        # Authed without CSRF → 403
        no_csrf = H(
            {
                "Origin": "http://127.0.0.1:8787",
                "Host": "127.0.0.1:8787",
                "Cookie": f"{auth.COOKIE_NAME}={cookie}",
                "Content-Length": "2",
            },
            b"{}",
        )
        routes.handle_post(no_csrf, SimpleNamespace(path="/api/td-camera/view/start", query=""))
        assert no_csrf.status == 403

        ok = H(
            {
                "Origin": "http://127.0.0.1:8787",
                "Host": "127.0.0.1:8787",
                "Cookie": f"{auth.COOKIE_NAME}={cookie}",
                auth.CSRF_HEADER_NAME: token,
                "Content-Length": "2",
            },
            b"{}",
        )
        routes.handle_post(ok, SimpleNamespace(path="/api/td-camera/view/start", query=""))
        assert ok.status == 200
        lease = json.loads(ok.wfile.getvalue())
        assert lease["lease_id"]

        # Fake unverified cookie must not authenticate when auth enabled
        fake = H({"Cookie": f"{auth.COOKIE_NAME}=not-a-real-session"})
        assert td_camera_http.handle_td_camera(fake, urlparse("/api/td-camera/health"), "GET") is True
        assert fake.status == 401
    finally:
        auth._sessions.pop("d" * 64, None)


def test_workspace_viewer_never_opens_camera_for_td():
    app_js = WORKSPACE / "biggy_workspace" / "static" / "app.js"
    if not app_js.is_file():
        pytest.skip("workspace repo not available")
    src = app_js.read_text(encoding="utf-8")
    assert "startTdCameraViewer" in src
    assert "viewer never calls getUserMedia" in src
    start = src.find("async function startTdCameraViewer")
    end = src.find("function setVisionViewerError", start)
    body = src[start:end]
    assert "navigator.mediaDevices" not in body
    assert "getUserMedia(" not in body
    assert "view/start" in src


def _require_playwright():
    if sync_playwright is None:
        pytest.skip("playwright unavailable")
    return sync_playwright


@pytest.fixture
def mock_upstream_and_proxy(monkeypatch):
    monkeypatch.setattr("api.auth.is_auth_enabled", lambda: False)
    jpeg = _tiny_jpeg(320, 240)
    state = {"camera_active": False, "snaps": 0}

    class Upstream(BaseHTTPRequestHandler):
        def log_message(self, *a):  # noqa: A003
            return

        def do_GET(self):  # noqa: N802
            auth_h = self.headers.get("Authorization") or ""
            if auth_h != "Bearer mock-upstream-token":
                self.send_response(401)
                self.end_headers()
                return
            if self.path == "/health":
                body = json.dumps({
                    "status": "ok",
                    "source": "HD Pro Webcam C920",
                    "camera_active": state["camera_active"],
                    "tunnel_process_running": True,
                }).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path == "/snapshot.jpg":
                state["camera_active"] = True
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
    upstream = f"http://127.0.0.1:{up.server_port}"
    relay.configure_for_tests(token="mock-upstream-token", upstream=upstream)

    class Proxy(BaseHTTPRequestHandler):
        def log_message(self, *a):  # noqa: A003
            return

        def _dispatch(self, method):
            parsed = urlparse(self.path)
            if parsed.path.startswith("/static/"):
                rel = parsed.path[len("/static/") :]
                path = (ROOT / "static" / rel).resolve()
                if not str(path).startswith(str((ROOT / "static").resolve())) or not path.is_file():
                    self.send_response(404)
                    self.end_headers()
                    return
                data = path.read_bytes()
                ctype = "application/javascript" if path.suffix == ".js" else "application/octet-stream"
                if path.suffix == ".wasm":
                    ctype = "application/wasm"
                if path.suffix == ".png":
                    ctype = "image/png"
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(data)))
                # Mirror production CSP allowance for local vendored WASM.
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'self'; script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval' blob:; "
                    "worker-src blob: 'self'; img-src 'self' data: blob:; connect-src 'self'; "
                    "frame-ancestors 'none'",
                )
                self.end_headers()
                self.wfile.write(data)
                return
            if parsed.path.startswith("/api/td-camera"):
                td_camera_http.handle_td_camera(self, parsed, method)
                return
            if parsed.path == "/harness":
                body = HARNESS.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'self'; script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval' blob:; "
                    "worker-src blob: 'self'; img-src 'self' data: blob:; connect-src 'self'; "
                    "frame-ancestors 'none'",
                )
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(404)
            self.end_headers()

        def do_GET(self):  # noqa: N802
            self._dispatch("GET")

        def do_POST(self):  # noqa: N802
            self._dispatch("POST")

    proxy = ThreadingHTTPServer(("127.0.0.1", 0), Proxy)
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{proxy.server_port}", state
    finally:
        proxy.shutdown()
        proxy.server_close()
        up.shutdown()
        up.server_close()
        relay.reset_for_tests()


HARNESS = """<!doctype html>
<html><body>
<button id="start">Start</button>
<button id="stop" disabled>Stop</button>
<select id="backdrop"><option value="off">Off</option><option value="blur">Blur</option></select>
<canvas id="out" width="320" height="240" hidden></canvas>
<img id="raw" hidden />
<p id="status">idle</p>
<script src="/static/td-camera/viewer-composite.js"></script>
<script>
let lease=null, timer=0, viewing=false, obj=null, gen=0;
async function start(){
  BiggyTdCameraComposite.reopen();
  const r=await fetch('/api/td-camera/view/start',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:'{}'});
  const j=await r.json(); if(!r.ok) throw new Error(j.error||'start');
  lease=j.lease_id; viewing=true; gen++; document.getElementById('start').disabled=true;
  document.getElementById('stop').disabled=false; tick(gen);
}
async function stop(){
  viewing=false; gen++; clearTimeout(timer);
  BiggyTdCameraComposite.abort();
  await fetch('/api/td-camera/view/stop',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({lease_id:lease})});
  lease=null; document.getElementById('start').disabled=false; document.getElementById('stop').disabled=true;
  document.getElementById('out').hidden=true;
  document.getElementById('status').textContent='stopped';
}
async function tick(myGen){
  if(!viewing || myGen!==gen) return;
  const r=await fetch('/api/td-camera/frame.jpg',{credentials:'same-origin',headers:{'X-TD-Camera-Lease':lease},cache:'no-store'});
  if(myGen!==gen) return;
  if(r.ok){
    const b=await r.blob(); if(obj) URL.revokeObjectURL(obj); obj=URL.createObjectURL(b);
    const raw=document.getElementById('raw'); const out=document.getElementById('out');
    const mode=document.getElementById('backdrop').value;
    if(mode!=='off') out.hidden=true;
    await new Promise((res,rej)=>{raw.onload=res;raw.onerror=rej;raw.src=obj;});
    if(myGen!==gen) return;
    const result=await BiggyTdCameraComposite.compositeToCanvas(raw,out,mode,{generation:BiggyTdCameraComposite.currentGeneration()});
    if(myGen!==gen) return;
    out.hidden=!result.ok; document.getElementById('status').textContent=result.ok?('ok:'+result.seg):(result.error||'fail');
  } else if(r.status!==429){
    const j=await r.json().catch(()=>({})); document.getElementById('status').textContent=j.error||('HTTP '+r.status);
  }
  timer=setTimeout(()=>tick(myGen),200);
}
document.getElementById('start').onclick=()=>start().catch(e=>document.getElementById('status').textContent=e.message);
document.getElementById('stop').onclick=()=>stop().catch(()=>{});
fetch('/api/td-camera/health',{credentials:'same-origin'}).then(r=>r.json()).then(j=>{
  document.getElementById('status').textContent='health:'+j.status+':active='+j.camera_active+':seg='+(j.segmentation&&j.segmentation.ready);
});
</script></body></html>
"""


def test_browser_snapshot_poll_and_health_no_activation(mock_upstream_and_proxy):
    base, state = mock_upstream_and_proxy
    pw = _require_playwright()
    with pw() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(f"{base}/harness", wait_until="domcontentloaded")
        page.wait_for_function(
            "() => (document.getElementById('status').textContent||'').startsWith('health:ok:active=false')",
            timeout=10000,
        )
        assert state["snaps"] == 0
        page.locator("#start").click()
        page.wait_for_function(
            "() => (document.getElementById('status').textContent||'').startsWith('ok:')",
            timeout=15000,
        )
        assert state["snaps"] >= 1
        expect(page.locator("#out")).to_be_visible()
        page.locator("#stop").click()
        page.wait_for_function(
            "() => document.getElementById('status').textContent==='stopped'",
            timeout=10000,
        )
        browser.close()


def test_actual_segmentation_compositor_under_csp(mock_upstream_and_proxy):
    if not FIXTURE_PERSON.is_file():
        pytest.skip("synthetic person fixture missing")
    base, _state = mock_upstream_and_proxy
    import base64

    b64 = base64.b64encode(FIXTURE_PERSON.read_bytes()).decode("ascii")
    data_url = f"data:image/png;base64,{b64}"
    pw = _require_playwright()
    with pw() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(f"{base}/harness", wait_until="domcontentloaded")
        page.wait_for_function("() => !!window.BiggyTdCameraComposite", timeout=10000)
        result = page.evaluate(
            """async (dataUrl) => {
              BiggyTdCameraComposite.reopen();
              const ok = await BiggyTdCameraComposite.loadSegmenter();
              if (!ok) return { ok:false, reason:'load' };
              const img = new Image();
              await new Promise((res,rej)=>{img.onload=res;img.onerror=rej;img.src=dataUrl;});
              const canvas = document.createElement('canvas');
              canvas.hidden = true;
              const r = await BiggyTdCameraComposite.compositeToCanvas(
                img, canvas, 'blur', {generation: BiggyTdCameraComposite.currentGeneration()}
              );
              return { ok:r.ok, seg:r.seg, composited:r.composited, error:r.error||null, w:canvas.width, h:canvas.height };
            }""",
            data_url,
        )
        assert result.get("ok") is True, result
        assert result.get("composited") is True
        assert result.get("seg") == "ok"
        browser.close()
