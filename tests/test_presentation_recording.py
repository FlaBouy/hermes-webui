"""Presentation recording store + HTTP + desktop GUI harness."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from api import presentation_http, presentation_store as store
from api import routes

try:
    from playwright.sync_api import expect, sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None
    expect = None

FIXTURE_WEBM = ROOT / "tests" / "fixtures" / "presentation_minimal.webm"


def _require_playwright():
    if sync_playwright is None:
        pytest.skip("playwright unavailable")
    return sync_playwright


def _owner(material: str = "owner-a") -> str:
    return store.derive_owner_key(material)


@pytest.fixture
def presentation_share(tmp_path, monkeypatch):
    mount = tmp_path / "mount"
    dest = mount / "Presentation Videos"
    mount.mkdir()
    dest.mkdir()
    monkeypatch.setenv("BIGGY_PRESENTATION_MOUNT_ROOT", str(mount))
    monkeypatch.setenv("BIGGY_PRESENTATION_DIR", str(dest))
    mount_res = mount.resolve()

    def _ismount(path: str | bytes | os.PathLike) -> bool:
        try:
            return Path(path).resolve() == mount_res
        except OSError:
            return False

    monkeypatch.setattr(store.os.path, "ismount", _ismount)
    store.reset_for_tests()
    yield {"mount": mount, "dest": dest}
    store.reset_for_tests()


def test_share_unconfigured_fails_closed(monkeypatch):
    monkeypatch.delenv("BIGGY_PRESENTATION_DIR", raising=False)
    monkeypatch.delenv("BIGGY_PRESENTATION_MOUNT_ROOT", raising=False)
    store.reset_for_tests()
    st = store.share_status()
    assert st["ready"] is False
    assert st["error"] == "presentation_share_unconfigured"
    with pytest.raises(store.PresentationError) as ctx:
        store.start_session(_owner())
    assert ctx.value.status == 503


def test_share_missing_mount_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("BIGGY_PRESENTATION_MOUNT_ROOT", str(tmp_path / "missing-mount"))
    monkeypatch.setenv("BIGGY_PRESENTATION_DIR", str(tmp_path / "missing-mount" / "videos"))
    store.reset_for_tests()
    st = store.share_status()
    assert st["ready"] is False
    assert st["error"] == "presentation_mount_unavailable"


def test_leftover_dir_not_mounted_fails(tmp_path, monkeypatch):
    """Existing directory must not stand in for an actual mount."""
    mount = tmp_path / "leftover"
    dest = mount / "videos"
    mount.mkdir()
    dest.mkdir()
    monkeypatch.setenv("BIGGY_PRESENTATION_MOUNT_ROOT", str(mount))
    monkeypatch.setenv("BIGGY_PRESENTATION_DIR", str(dest))
    monkeypatch.setattr(store.os.path, "ismount", lambda p: False)
    store.reset_for_tests()
    st = store.share_status()
    assert st["ready"] is False
    assert st["mount_verified"] is False
    assert st["error"] == "presentation_mount_not_mounted"


def test_write_probe_unique_and_cleaned(presentation_share):
    st = store.share_status()
    assert st["ready"] is True
    assert st["mount_verified"] is True
    partial = presentation_share["dest"] / ".partial"
    leftovers = list(partial.glob(".write_probe_*")) if partial.exists() else []
    assert leftovers == []


def test_fake_bytes_not_marked_saved(presentation_share):
    """Regression for coordinator item 4 — arbitrary bytes must not finalize as saved."""
    owner = _owner("fake")
    sid = store.start_session(owner)["session_id"]
    payload = b"\x00\x01fake-webm-chunk-" + os.urandom(400)
    digest = hashlib.sha256(payload).hexdigest()
    store.receive_chunk(owner, sid, 0, payload, content_sha256=digest)
    with pytest.raises(store.PresentationError) as ctx:
        store.finalize_session(
            owner,
            sid,
            mime="video/webm",
            duration_ms=1500,
            total_chunks=1,
            title="t",
        )
    assert ctx.value.code in {
        "invalid_webm_magic",
        "invalid_webm_segment",
        "invalid_webm_no_cluster",
    }
    assert list(presentation_share["dest"].glob("presentation-*/recording.*")) == []
    recovery = store.session_recovery_status(owner, sid)
    assert recovery["saved"] is False
    assert recovery["state"] == "interrupted"


def test_chunk_sequence_idempotent_finalize_real_webm(presentation_share):
    owner = _owner("real")
    started = store.start_session(owner)
    sid = started["session_id"]
    assert started["max_chunk_bytes"] == store.MAX_CHUNK_BYTES
    assert started["max_duration_ms"] == store.MAX_DURATION_MS
    webm = FIXTURE_WEBM.read_bytes()
    assert webm.startswith(store.EBML_MAGIC)
    mid = len(webm) // 2
    p0, p1 = webm[:mid], webm[mid:]
    r1 = store.receive_chunk(owner, sid, 0, p0, content_sha256=hashlib.sha256(p0).hexdigest())
    assert r1["idempotent"] is False
    r2 = store.receive_chunk(owner, sid, 0, p0, content_sha256=hashlib.sha256(p0).hexdigest())
    assert r2["idempotent"] is True
    with pytest.raises(store.PresentationError) as bad_seq:
        store.receive_chunk(owner, sid, 2, p1)
    assert bad_seq.value.code == "chunk_out_of_order"
    store.receive_chunk(owner, sid, 1, p1, content_sha256=hashlib.sha256(p1).hexdigest())
    total_hash = hashlib.sha256(webm).hexdigest()
    meta = store.finalize_session(
        owner,
        sid,
        mime="video/webm",
        duration_ms=1500,
        total_chunks=2,
        title="t",
        content_sha256=total_hash,
    )
    assert meta["state"] == "saved"
    assert meta["bytes"] == len(webm)
    assert meta["content_sha256"] == total_hash
    path = presentation_share["dest"] / meta["filename"]
    assert path.is_file() and path.read_bytes() == webm
    assert store.SAFE_REL_RECORDING_RE.match(meta["filename"])
    # Index persisted under share
    idx = presentation_share["dest"] / ".index" / f"{meta['file_id']}.json"
    assert idx.is_file()
    # Empty finalize rejected
    sid2 = store.start_session(owner)["session_id"]
    with pytest.raises(store.PresentationError) as empty:
        store.finalize_session(owner, sid2, mime="video/webm", duration_ms=100, total_chunks=0)
    assert empty.value.code == "no_chunks"


def test_index_reload_after_memory_clear(presentation_share):
    owner = _owner("persist")
    sid = store.start_session(owner)["session_id"]
    webm = FIXTURE_WEBM.read_bytes()
    store.receive_chunk(owner, sid, 0, webm)
    meta = store.finalize_session(
        owner, sid, mime="video/webm", duration_ms=900, total_chunks=1, title="persist"
    )
    file_id = meta["file_id"]
    store.reset_for_tests()
    # Memory cleared — must reload from .index
    reloaded = store.get_file_meta(owner, file_id)
    assert reloaded["file_id"] == file_id
    assert reloaded.get("recovery") in {"index_reloaded", "live"}
    path, m2 = store.open_file(owner, file_id)
    assert path.is_file() and m2["owner_key"] == owner


def test_interrupt_not_marked_saved(presentation_share):
    owner = _owner("interrupt")
    sid = store.start_session(owner)["session_id"]
    store.receive_chunk(owner, sid, 0, b"partial-only")
    out = store.mark_interrupted(owner, sid, reason="pagehide")
    assert out["saved"] is False
    assert out["state"] == "interrupted"
    assert list(presentation_share["dest"].glob("presentation-*/recording.*")) == []


def test_ownership_csrf_and_range(presentation_share, monkeypatch):
    import hmac

    import api.auth as auth

    monkeypatch.setattr(auth, "is_auth_enabled", lambda: True)
    raw = "c" * 64
    sig = hmac.new(auth._signing_key(), raw.encode(), "sha256").hexdigest()
    auth._sessions[raw] = time.time() + 600
    cookie = f"{raw}.{sig}"
    csrf = auth.csrf_token_for_session(cookie)
    owner = store.derive_owner_key(raw)

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def __init__(self, headers, body=b"", path="/"):
            self.headers = headers
            self.rfile = BytesIO(body)
            self.wfile = BytesIO()
            self.status = None
            self.path = path
            self._headers_out = {}

        def send_response(self, code, message=None):
            self.status = code

        def send_header(self, k, v):
            self._headers_out[k] = v

        def end_headers(self):
            return

        def log_message(self, *a):
            return

    try:
        bare = H({"Content-Length": "2", "Origin": "http://127.0.0.1:8787"}, b"{}")
        routes.handle_post(
            bare, type("P", (), {"path": "/api/presentation/session/start", "query": ""})()
        )
        assert bare.status in {403, 401}

        ok = H(
            {
                "Content-Length": "2",
                "Origin": "http://127.0.0.1:8787",
                "Host": "127.0.0.1:8787",
                "Cookie": f"{auth.COOKIE_NAME}={cookie}",
                auth.CSRF_HEADER_NAME: csrf,
            },
            b"{}",
        )
        routes.handle_post(
            ok, type("P", (), {"path": "/api/presentation/session/start", "query": ""})()
        )
        assert ok.status == 200
        sid = json.loads(ok.wfile.getvalue())["session_id"]

        other = store.derive_owner_key("other-session-material")
        with pytest.raises(store.PresentationError) as forb:
            store.finalize_session(
                other, sid, mime="video/webm", duration_ms=10, total_chunks=1
            )
        assert forb.value.status == 403

        # Finalize for real owner + Range GET
        webm = FIXTURE_WEBM.read_bytes()
        store.receive_chunk(owner, sid, 0, webm)
        meta = store.finalize_session(
            owner, sid, mime="video/webm", duration_ms=1200, total_chunks=1
        )
        file_id = meta["file_id"]
        rng = H(
            {
                "Cookie": f"{auth.COOKIE_NAME}={cookie}",
                "Range": "bytes=0-15",
            },
            b"",
            path=f"/api/presentation/file/{file_id}",
        )
        presentation_http.handle_presentation(
            rng,
            type("P", (), {"path": f"/api/presentation/file/{file_id}", "query": ""})(),
            "GET",
        )
        assert rng.status == 206
        assert rng._headers_out.get("Accept-Ranges") == "bytes"
        assert rng._headers_out.get("Content-Range", "").startswith("bytes 0-15/")
        assert rng.wfile.getvalue() == webm[:16]
    finally:
        auth._sessions.pop(raw, None)


@pytest.fixture
def presentation_gui_server(presentation_share, monkeypatch):
    import hmac

    import api.auth as auth
    from api.helpers import _build_csp_enforced_policy

    monkeypatch.setattr(auth, "is_auth_enabled", lambda: True)
    raw = "d" * 64
    sig = hmac.new(auth._signing_key(), raw.encode(), "sha256").hexdigest()
    auth._sessions[raw] = time.time() + 600
    cookie = f"{raw}.{sig}"
    csrf = auth.csrf_token_for_session(cookie)
    embed_csp = _build_csp_enforced_policy()

    brand_js = (ROOT / "static" / "biggy-brand.js").read_bytes()
    brand_css = (ROOT / "static" / "biggy-brand.css").read_bytes()
    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Biggy</title>
<link rel="stylesheet" href="/static/biggy-brand.css">
<style>
body{{margin:0;background:#05070b;color:#d7e4ec}}
#mainChat{{min-height:100vh;position:relative}}
#composerWrap{{position:fixed!important;left:0!important;right:0!important;bottom:0!important;top:auto!important;height:280px!important;background:#122;z-index:5}}
#composerBox{{position:absolute!important;left:50%!important;transform:translateX(-50%)!important;bottom:24px!important;top:auto!important;width:min(680px,90vw)!important;height:72px!important;background:#0a1218!important}}
</style>
<script>window.__HERMES_CONFIG__={{csrfToken:{json.dumps(csrf)}}};</script>
</head>
<body>
<div id="mainChat" class="biggy-brand-iwo">
  <div id="composerWrap"><div id="composerBox"><textarea id="msg" aria-label="Message Biggy"></textarea></div></div>
</div>
<script src="/static/biggy-brand.js?v=presentation-viewer-test"></script>
</body></html>"""

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

        def _dispatch(self, method):
            parsed = urlparse(self.path)
            path = parsed.path
            if path.startswith("/api/presentation"):
                if method == "POST":
                    if not routes._check_csrf(self):
                        return self._send(
                            403,
                            json.dumps({"error": routes._csrf_rejection_error(self)}).encode(),
                            "application/json",
                        )
                return presentation_http.handle_presentation(self, parsed, method)
            if method != "GET":
                return self._send(405, b"m", "text/plain")
            if path == "/":
                return self._send(200, html.encode(), "text/html; charset=utf-8")
            if path == "/static/biggy-brand.js":
                return self._send(200, brand_js, "application/javascript")
            if path == "/static/biggy-brand.css":
                return self._send(200, brand_css, "text/css")
            if path.startswith("/static/"):
                # Strip query is already done by urlparse.path
                rel = path[len("/static/") :]
                fpath = (ROOT / "static" / rel).resolve()
                if not str(fpath).startswith(str((ROOT / "static").resolve())) or not fpath.is_file():
                    return self._send(404, b"missing", "text/plain")
                ctype = "application/javascript" if fpath.suffix == ".js" else "text/css"
                if fpath.suffix == ".css":
                    ctype = "text/css"
                return self._send(
                    200,
                    fpath.read_bytes(),
                    ctype,
                    extra={"Content-Security-Policy": embed_csp},
                )
            if path.startswith("/api/"):
                return self._send(200, b"{}", "application/json")
            return self._send(404, b"missing", "text/plain")

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield {
            "origin": f"http://127.0.0.1:{server.server_address[1]}",
            "cookie": cookie,
            "cookie_name": auth.COOKIE_NAME,
            "dest": presentation_share["dest"],
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        auth._sessions.pop(raw, None)


def test_presentation_gui_mediarecorder_and_camera_anchor(presentation_gui_server):
    sp = _require_playwright()
    info = presentation_gui_server
    with sp() as p:
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
        # Real MediaRecorder via canvas stream (headless has no display picker).
        page.add_init_script(
            """
            (() => {
              const orig = navigator.mediaDevices.getDisplayMedia.bind(navigator.mediaDevices);
              navigator.mediaDevices.getDisplayMedia = async () => {
                const c = document.createElement('canvas');
                c.width = 320; c.height = 180;
                const ctx = c.getContext('2d');
                let i = 0;
                const draw = () => {
                  ctx.fillStyle = '#123';
                  ctx.fillRect(0,0,320,180);
                  ctx.fillStyle = '#0f8';
                  ctx.fillRect((i*3)%280, 40, 40, 40);
                  i += 1;
                };
                draw();
                const timer = setInterval(draw, 50);
                const stream = c.captureStream(20);
                const track = stream.getVideoTracks()[0];
                const stop = track.stop.bind(track);
                track.stop = () => { clearInterval(timer); stop(); };
                return stream;
              };
              navigator.mediaDevices.__origGetDisplayMedia = orig;
            })();
            """
        )
        page.goto(info["origin"], wait_until="domcontentloaded")

        # VISION→Camera opens settings (not a chrome-wrapped feed).
        page.get_by_test_id("biggy-vision").click()
        page.get_by_test_id("biggy-vision-camera").click()
        settings = page.get_by_test_id("biggy-td-camera-settings")
        expect(settings).to_be_visible(timeout=10000)
        expect(page.get_by_test_id("biggy-td-camera-overlay")).to_have_count(0)

        # Product default feed geometry vs real #composerBox (not full-width #composerWrap rail).
        page.evaluate(
            """() => {
              const api = window.BiggyTdCameraOverlay;
              api._test.ensureFeed();
              api._test.applyFeedRect(api._test.defaultFeedRect());
            }"""
        )
        overlay = page.get_by_test_id("biggy-td-camera-overlay")
        expect(overlay).to_be_visible()
        box = overlay.bounding_box()
        composer = page.locator("#composerBox").bounding_box()
        wrap = page.locator("#composerWrap").bounding_box()
        assert box and composer and wrap
        assert box["x"] < 200
        assert box["y"] > 400
        # No full-width forbidden strip at wrap.top: feed bottom may extend below wrap.top
        # when it does not AABB-overlap the real centered composerBox.
        overlaps_composer = not (
            box["x"] + box["width"] <= composer["x"]
            or box["x"] >= composer["x"] + composer["width"]
            or box["y"] + box["height"] <= composer["y"]
            or box["y"] >= composer["y"] + composer["height"]
        )
        if overlaps_composer:
            assert box["y"] + box["height"] <= composer["y"] + 2 or box["x"] + box["width"] <= composer["x"] + 2
        else:
            assert box["y"] + box["height"] > wrap["y"]
        # Settings Close must not tear down the feed.
        page.get_by_test_id("biggy-td-camera-close").click()
        expect(settings).to_have_count(0)
        expect(overlay).to_be_visible()
        page.evaluate("() => window.BiggyTdCameraOverlay.close({ restoreFocus: false })")
        expect(page.get_by_test_id("biggy-td-camera-overlay")).to_have_count(0)

        # Presentation panel — opening menu/panel does not capture.
        page.get_by_test_id("biggy-vision").click()
        page.get_by_test_id("biggy-vision-presentation").click()
        panel = page.get_by_test_id("biggy-presentation-panel")
        expect(panel).to_be_visible()
        page.wait_for_function(
            """() => {
              const t = document.querySelector('[data-testid="biggy-presentation-status"]');
              const d = document.querySelector('[data-testid="biggy-presentation-details-body"]');
              return !!(t && /Ready|share/i.test(t.textContent || '') && d && /max_duration_ms=/.test(d.textContent || ''));
            }""",
            timeout=10000,
        )
        assert list(info["dest"].glob("presentation-*/recording.*")) == []

        # Limits from status are applied into recorder Details before On.
        details = page.get_by_test_id("biggy-presentation-details-body").text_content() or ""
        assert "max_duration_ms=" in details
        assert "max_chunk_bytes=" in details

        page.get_by_test_id("biggy-presentation-on").click()
        page.wait_for_function(
            "() => !!(window.BiggyPresentation && window.BiggyPresentation.isRecording())",
            timeout=10000,
        )
        # Settings must disappear while recording so they are not in the capture.
        expect(page.get_by_test_id("biggy-presentation-panel")).to_have_count(0)
        assert page.evaluate("() => window.BiggyPresentation.phase()") == "recording"
        page.wait_for_timeout(2200)
        # Off via VISION→Presentation (reopen settings); Close must not be required to stop.
        page.get_by_test_id("biggy-vision").click()
        page.get_by_test_id("biggy-vision-presentation").click()
        expect(page.get_by_test_id("biggy-presentation-panel")).to_be_visible()
        assert page.evaluate("() => window.BiggyPresentation.isRecording()") is True
        page.get_by_test_id("biggy-presentation-off").click()
        page.wait_for_function(
            """() => {
              const t = document.querySelector('[data-testid="biggy-presentation-status"]');
              return !!(t && /Saved /i.test(t.textContent || ''));
            }""",
            timeout=20000,
        )
        files = list(info["dest"].glob("presentation-*/recording.*"))
        assert len(files) == 1
        assert files[0].stat().st_size > 500
        # Playable container magic
        head = files[0].read_bytes()[:4]
        assert head == b"\x1a\x45\xdf\xa3" or files[0].read_bytes()[4:8] == b"ftyp"
        status = page.get_by_test_id("biggy-presentation-status").inner_text()
        assert "Saved" in status
        assert any(ch.isdigit() for ch in status)

        page.get_by_test_id("biggy-presentation-open").click()
        expect(page.get_by_test_id("biggy-presentation-video")).to_be_visible(timeout=10000)
        dur = page.get_by_test_id("biggy-presentation-video").evaluate(
            """async (v) => {
              await new Promise((res, rej) => {
                if (v.readyState >= 1) return res();
                v.onloadedmetadata = () => res();
                v.onerror = () => rej(new Error('video error'));
              });
              return v.duration;
            }"""
        )
        assert isinstance(dur, (int, float)) and dur > 0

        # Close playback so Open saved controls stay reachable.
        page.locator(".biggy-document-close").click()
        expect(page.get_by_test_id("biggy-document-viewer")).to_have_count(0)

        # Stale viewer (no presentation support) must not silent-no-op Open saved.
        page.evaluate(
            """() => {
              window.BiggyDocumentViewer = {
                open: () => false
              };
            }"""
        )
        page.get_by_test_id("biggy-presentation-open").click()
        page.wait_for_function(
            """() => {
              const t = document.querySelector('[data-testid="biggy-presentation-status"]');
              return !!(t && /stale|rejected|unavailable|failed/i.test(t.textContent || ''));
            }""",
            timeout=5000,
        )
        # Cache-busted module must replace stale viewer and open video again.
        page.evaluate(
            """async () => {
              await import('/static/biggy-document-viewer.js?v=presentation-viewer-upgrade');
            }"""
        )
        page.wait_for_function(
            "() => !!(window.BiggyDocumentViewer && window.BiggyDocumentViewer.supportsPresentation)",
            timeout=5000,
        )
        page.get_by_test_id("biggy-presentation-open").click()
        expect(page.get_by_test_id("biggy-presentation-video").last).to_be_visible(timeout=10000)

        browser.close()


def test_brand_document_viewer_import_tracks_build_id():
    brand = (ROOT / "static" / "biggy-brand.js").read_text(encoding="utf-8")
    assert "biggy-document-viewer.js?v=20260912" not in brand
    assert "encodeURIComponent(BUILD_ID)" in brand
    assert "__biggyDocumentViewerReady" in brand
    viewer = (ROOT / "static" / "biggy-document-viewer.js").read_text(encoding="utf-8")
    assert "supportsPresentation" in viewer
    assert "presentationOk" in viewer
    recorder = (ROOT / "static" / "presentation" / "recorder.js").read_text(encoding="utf-8")
    assert "Viewer rejected" in recorder
    assert "supportsPresentation" in recorder


def test_embedded_webm_signatures_rejected(presentation_share):
    """Signatures mid-buffer must not pass — must start with EBML then Segment/Cluster."""
    owner = _owner("embed")
    sid = store.start_session(owner)["session_id"]
    webm = FIXTURE_WEBM.read_bytes()
    payload = b"NOTWEBM" + webm  # contains valid structure but wrong start
    store.receive_chunk(owner, sid, 0, payload)
    with pytest.raises(store.PresentationError) as ctx:
        store.finalize_session(
            owner, sid, mime="video/webm", duration_ms=500, total_chunks=1
        )
    assert ctx.value.code == "invalid_webm_magic"
    assert list(presentation_share["dest"].glob("presentation-*/recording.*")) == []


def test_finalize_streams_without_full_file_read(presentation_share, monkeypatch):
    """Finalize must not load the whole assembled recording via read_bytes()."""
    owner = _owner("stream")
    sid = store.start_session(owner)["session_id"]
    webm = FIXTURE_WEBM.read_bytes()
    store.receive_chunk(owner, sid, 0, webm)
    reads: list[str] = []
    orig = Path.read_bytes

    def spy(self, *a, **k):
        reads.append(self.name)
        return orig(self, *a, **k)

    monkeypatch.setattr(Path, "read_bytes", spy)
    meta = store.finalize_session(
        owner, sid, mime="video/webm", duration_ms=800, total_chunks=1
    )
    assert meta["state"] == "saved"
    assert not any(n.startswith("assembled") for n in reads)
    assert store.SAFE_REL_RECORDING_RE.match(meta["filename"])


def test_publish_collision_does_not_clobber(presentation_share, monkeypatch):
    owner = _owner("collide")
    sid = store.start_session(owner)["session_id"]
    webm = FIXTURE_WEBM.read_bytes()
    store.receive_chunk(owner, sid, 0, webm)
    monkeypatch.setattr(store.time, "strftime", lambda *a, **k: "20260101-000000")
    monkeypatch.setattr(store.secrets, "token_urlsafe", lambda n: "abcdefghijklmnop")
    # Exclusive recording dir: presentation-stamp-abcdefgh/
    pub_dir = presentation_share["dest"] / "presentation-20260101-000000-abcdefgh"
    pub_dir.mkdir()
    marker_file = pub_dir / "recording.webm"
    marker = b"ORIGINAL-DO-NOT-CLOBBER-" + os.urandom(32)
    marker_file.write_bytes(marker)
    with pytest.raises(store.PresentationError) as ctx:
        store.finalize_session(
            owner, sid, mime="video/webm", duration_ms=900, total_chunks=1
        )
    assert ctx.value.code == "final_name_collision"
    assert marker_file.read_bytes() == marker
    # No alternate final published beside the marker.
    assert list(pub_dir.glob("recording.webm.partial")) == []


def test_publish_short_write_retries_to_completion(presentation_share, monkeypatch):
    """os.write short counts must be drained; final name only after full bytes."""
    owner = _owner("short")
    sid = store.start_session(owner)["session_id"]
    webm = FIXTURE_WEBM.read_bytes()
    store.receive_chunk(owner, sid, 0, webm)
    real_write = os.write
    calls = {"n": 0}

    def short_then_real(fd, data):
        calls["n"] += 1
        view = memoryview(data)
        if calls["n"] == 1 and len(view) > 4:
            return real_write(fd, view[:3])  # deliberate short write
        return real_write(fd, data)

    monkeypatch.setattr(store.os, "write", short_then_real)
    meta = store.finalize_session(
        owner, sid, mime="video/webm", duration_ms=600, total_chunks=1
    )
    assert meta["state"] == "saved"
    assert calls["n"] >= 2
    path = presentation_share["dest"] / meta["filename"]
    assert path.read_bytes() == webm
    assert not path.with_name(path.name + ".partial").exists()


def test_publish_failure_leaves_partial_not_final(presentation_share, monkeypatch):
    """Interrupted staging must not present recording.webm as complete."""
    owner = _owner("half")
    sid = store.start_session(owner)["session_id"]
    webm = FIXTURE_WEBM.read_bytes()
    store.receive_chunk(owner, sid, 0, webm)
    monkeypatch.setattr(store.time, "strftime", lambda *a, **k: "20260102-010101")
    monkeypatch.setattr(store.secrets, "token_urlsafe", lambda n: "qrstuvwxyzabcdef")

    def boom(src, fd):
        # Write a few bytes then fail — simulates mid-publish I/O error.
        store._write_all(fd, b"PARTIAL")
        raise OSError("simulated smb write failure")

    monkeypatch.setattr(store, "_copy_file_fd", boom)
    with pytest.raises(store.PresentationError) as ctx:
        store.finalize_session(
            owner, sid, mime="video/webm", duration_ms=600, total_chunks=1
        )
    assert ctx.value.code == "publish_failed"
    pub_dir = presentation_share["dest"] / "presentation-20260102-010101-qrstuvwx"
    assert pub_dir.is_dir()
    assert not (pub_dir / "recording.webm").exists()
    # Recoverable staging partial retained (not a completed final).
    staging = pub_dir / "recording.webm.partial"
    assert staging.is_file()
    assert staging.read_bytes().startswith(b"PARTIAL")
    assert list(presentation_share["dest"].glob("presentation-*/recording.webm")) == []


def test_index_rebuild_after_publish_without_index(presentation_share, monkeypatch):
    owner = _owner("idx")
    sid = store.start_session(owner)["session_id"]
    webm = FIXTURE_WEBM.read_bytes()
    store.receive_chunk(owner, sid, 0, webm)
    writes = {"n": 0}
    real_write = store._write_index

    def flaky(root, meta):
        writes["n"] += 1
        if writes["n"] == 1:
            raise OSError("simulated index write failure")
        return real_write(root, meta)

    monkeypatch.setattr(store, "_write_index", flaky)
    meta = store.finalize_session(
        owner, sid, mime="video/webm", duration_ms=700, total_chunks=1, title="idx"
    )
    assert meta["state"] == "saved"
    assert meta.get("recovery") == "index_write_pending"
    final = presentation_share["dest"] / meta["filename"]
    assert final.is_file()
    idx = presentation_share["dest"] / ".index" / f"{meta['file_id']}.json"
    assert not idx.is_file()
    with store._lock:
        store._files.clear()
        store._index_loaded = False
    # Idempotent retry rebuilds index from finalized session + file.
    meta2 = store.finalize_session(
        owner, sid, mime="video/webm", duration_ms=700, total_chunks=1, title="idx"
    )
    assert meta2["file_id"] == meta["file_id"]
    assert meta2["state"] == "saved"
    assert meta2.get("recovery") == "rebuilt_index"
    assert idx.is_file()
    assert final.read_bytes() == webm
    assert store.SAFE_REL_RECORDING_RE.match(meta2["filename"])


def test_ordered_upload_small_chunks_delayed_and_duration_limit(presentation_gui_server, monkeypatch):
    """Overlapping dataavailable + tiny chunks + delayed uploads: exact byte order; duration limit saves."""
    sp = _require_playwright()
    info = presentation_gui_server
    # Tiny server chunks force split of each dataavailable event.
    monkeypatch.setattr(store, "MAX_CHUNK_BYTES", 200)

    # Delay chunk writes so overlapping events queue while consumer runs.
    orig_receive = store.receive_chunk

    def slow_receive(*a, **k):
        time.sleep(0.05)
        return orig_receive(*a, **k)

    monkeypatch.setattr(store, "receive_chunk", slow_receive)

    with sp() as p:
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
        page.add_init_script(
            """
            (() => {
              window.__presUploaded = [];
              const origFetch = window.fetch.bind(window);
              window.fetch = async (input, init = {}) => {
                const url = typeof input === 'string' ? input : (input && input.url) || '';
                const res = await origFetch(input, init);
                if (/\\/api\\/presentation\\/session\\/.*\\/chunk/.test(url) && init && init.body) {
                  const body = init.body;
                  let u8;
                  if (body instanceof ArrayBuffer) u8 = new Uint8Array(body);
                  else if (ArrayBuffer.isView(body)) u8 = new Uint8Array(body.buffer, body.byteOffset, body.byteLength);
                  else return res;
                  window.__presUploaded.push(Array.from(u8));
                }
                return res;
              };
              navigator.mediaDevices.getDisplayMedia = async () => {
                const c = document.createElement('canvas');
                c.width = 320; c.height = 180;
                const ctx = c.getContext('2d');
                let i = 0;
                const draw = () => {
                  ctx.fillStyle = '#214';
                  ctx.fillRect(0,0,320,180);
                  ctx.fillStyle = '#f80';
                  ctx.fillRect((i*5)%280, 30, 50, 50);
                  i += 1;
                };
                draw();
                const timer = setInterval(draw, 40);
                const stream = c.captureStream(20);
                const track = stream.getVideoTracks()[0];
                const stop = track.stop.bind(track);
                track.stop = () => { clearInterval(timer); stop(); };
                return stream;
              };
            })();
            """
        )
        page.goto(info["origin"], wait_until="domcontentloaded")
        page.get_by_test_id("biggy-vision").click()
        page.get_by_test_id("biggy-vision-presentation").click()
        panel = page.get_by_test_id("biggy-presentation-panel")
        expect(panel).to_be_visible()
        page.wait_for_function(
            """() => {
              const d = document.querySelector('[data-testid="biggy-presentation-details-body"]');
              return !!(d && /max_duration_ms=/.test(d.textContent || ''));
            }""",
            timeout=10000,
        )
        # Negotiate tiny client split size (server also capped via MAX_CHUNK_BYTES).
        page.evaluate("() => window.BiggyPresentation._test.setLimits({ max_chunk_bytes: 200, max_duration_ms: 1500 })")

        page.get_by_test_id("biggy-presentation-on").click()
        page.wait_for_function(
            "() => !!(window.BiggyPresentation && window.BiggyPresentation.isRecording())",
            timeout=10000,
        )
        expect(page.get_by_test_id("biggy-presentation-panel")).to_have_count(0)
        # Immediate Off while timeslice events still overlapping with delayed uploads.
        page.wait_for_timeout(600)
        page.get_by_test_id("biggy-vision").click()
        page.get_by_test_id("biggy-vision-presentation").click()
        expect(page.get_by_test_id("biggy-presentation-panel")).to_be_visible()
        page.get_by_test_id("biggy-presentation-off").click()
        page.wait_for_function(
            """() => {
              const t = document.querySelector('[data-testid="biggy-presentation-status"]');
              return !!(t && /Saved /i.test(t.textContent || ''));
            }""",
            timeout=30000,
        )
        files = list(info["dest"].glob("presentation-*/recording.*"))
        assert len(files) == 1
        saved = files[0].read_bytes()
        uploaded_parts = page.evaluate("() => window.__presUploaded")
        assert uploaded_parts and len(uploaded_parts) >= 2
        reconstructed = b"".join(bytes(part) for part in uploaded_parts)
        assert reconstructed == saved
        # Container may be WebM or MP4 depending on Chromium MediaRecorder support.
        assert saved.startswith(b"\x1a\x45\xdf\xa3") or saved[4:8] == b"ftyp"

        # Duration-limit path: accelerated max_duration must save (not false exceed).
        monkeypatch.setattr(store, "MAX_DURATION_MS", 800)
        page.evaluate(
            "() => window.BiggyPresentation._test.setLimits({ max_duration_ms: 800 })"
        )
        before = set(info["dest"].glob("presentation-*/recording.*"))
        page.get_by_test_id("biggy-presentation-on").click()
        page.wait_for_function(
            "() => !!(window.BiggyPresentation && window.BiggyPresentation.isRecording())",
            timeout=10000,
        )
        expect(page.get_by_test_id("biggy-presentation-panel")).to_have_count(0)
        page.wait_for_function(
            "() => window.BiggyPresentation.phase() === 'saved'",
            timeout=20000,
        )
        page.get_by_test_id("biggy-vision").click()
        page.get_by_test_id("biggy-vision-presentation").click()
        page.wait_for_function(
            """() => {
              const t = document.querySelector('[data-testid="biggy-presentation-status"]');
              const p = document.querySelector('[data-testid="biggy-presentation-panel"]');
              return !!(t && /Saved /i.test(t.textContent || '') && p && p.dataset.phase === 'saved');
            }""",
            timeout=10000,
        )
        after = set(info["dest"].glob("presentation-*/recording.*"))
        new_files = after - before
        assert len(new_files) == 1
        status = page.get_by_test_id("biggy-presentation-status").inner_text()
        assert "Saved" in status
        assert "exceeded" not in status.lower()

        browser.close()


def test_close_during_finalizing_preserves_generation(presentation_gui_server, monkeypatch):
    """Close while finalizing must not idle-race a new start over the pending save."""
    sp = _require_playwright()
    info = presentation_gui_server
    orig_finalize = store.finalize_session
    gate = threading.Event()
    started = threading.Event()

    def blocked_finalize(*a, **k):
        started.set()
        gate.wait(timeout=15)
        return orig_finalize(*a, **k)

    monkeypatch.setattr(store, "finalize_session", blocked_finalize)

    with sp() as p:
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
        page.add_init_script(
            """
            (() => {
              navigator.mediaDevices.getDisplayMedia = async () => {
                const c = document.createElement('canvas');
                c.width = 160; c.height = 90;
                const ctx = c.getContext('2d');
                const timer = setInterval(() => {
                  ctx.fillStyle = '#333'; ctx.fillRect(0,0,160,90);
                }, 50);
                const stream = c.captureStream(10);
                const track = stream.getVideoTracks()[0];
                const stop = track.stop.bind(track);
                track.stop = () => { clearInterval(timer); stop(); };
                return stream;
              };
            })();
            """
        )
        page.goto(info["origin"], wait_until="domcontentloaded")
        page.get_by_test_id("biggy-vision").click()
        page.get_by_test_id("biggy-vision-presentation").click()
        panel = page.get_by_test_id("biggy-presentation-panel")
        expect(panel).to_be_visible()
        page.wait_for_function(
            """() => {
              const d = document.querySelector('[data-testid="biggy-presentation-details-body"]');
              return !!(d && /max_duration_ms=/.test(d.textContent || ''));
            }""",
            timeout=10000,
        )
        page.get_by_test_id("biggy-presentation-on").click()
        page.wait_for_function(
            "() => !!(window.BiggyPresentation && window.BiggyPresentation.isRecording())",
            timeout=10000,
        )
        expect(page.get_by_test_id("biggy-presentation-panel")).to_have_count(0)
        page.wait_for_timeout(1200)
        page.get_by_test_id("biggy-vision").click()
        page.get_by_test_id("biggy-vision-presentation").click()
        expect(page.get_by_test_id("biggy-presentation-panel")).to_be_visible()
        page.get_by_test_id("biggy-presentation-off").click()
        # Wait until server entered finalize.
        assert started.wait(timeout=15)
        page.wait_for_function(
            "() => window.BiggyPresentation.phase() === 'finalizing'",
            timeout=10000,
        )
        page.get_by_test_id("biggy-presentation-close").click()
        page.wait_for_function(
            "() => !window.BiggyPresentation.isOpen()",
            timeout=5000,
        )
        assert page.evaluate("() => window.BiggyPresentation.phase()") == "finalizing"
        # Reopen — must not allow a new start while finalizing.
        page.get_by_test_id("biggy-vision").click()
        page.get_by_test_id("biggy-vision-presentation").click()
        expect(page.get_by_test_id("biggy-presentation-panel")).to_be_visible()
        assert page.evaluate("() => window.BiggyPresentation.phase()") == "finalizing"
        # On is disabled; force-invoke start to prove guard (no generation bump / no new session).
        before_gen = page.evaluate(
            """() => {
              const s = document.querySelector('[data-testid="biggy-presentation-status"]');
              return { phase: window.BiggyPresentation.phase(), status: (s && s.textContent) || '' };
            }"""
        )
        page.evaluate("() => window.BiggyPresentation.open() && document.querySelector('[data-testid=\"biggy-presentation-on\"]').click()")
        page.evaluate("""() => {
          const btn = document.querySelector('[data-testid="biggy-presentation-on"]');
          if (btn) btn.disabled = false;
          btn && btn.click();
        }""")
        page.wait_for_timeout(400)
        after = page.evaluate(
            """() => {
              const s = document.querySelector('[data-testid="biggy-presentation-status"]');
              return { phase: window.BiggyPresentation.phase(), status: (s && s.textContent) || '' };
            }"""
        )
        assert after["phase"] == "finalizing"
        assert "finalizing" in after["status"].lower()
        assert after["phase"] == before_gen["phase"]
        gate.set()
        page.wait_for_function(
            """() => {
              const ph = window.BiggyPresentation.phase();
              return ph === 'saved' || ph === 'failed';
            }""",
            timeout=20000,
        )
        assert page.evaluate("() => window.BiggyPresentation.phase()") == "saved"
        assert list(info["dest"].glob("presentation-*/recording.*"))
        browser.close()


def test_clean_ui_actual_layout_screenshots(presentation_gui_server):
    """Real Biggy composer layout harness — before/after evidence for clean UI."""
    sp = _require_playwright()
    info = presentation_gui_server
    out_dir = Path(
        "/Users/rick/Documents/Codex/2026-09-11/cursor-spark-handoff/outputs"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    with sp() as p:
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
        page.add_init_script(
            """
            (() => {
              navigator.mediaDevices.getDisplayMedia = async () => {
                const c = document.createElement('canvas');
                c.width = 320; c.height = 180;
                const ctx = c.getContext('2d');
                const timer = setInterval(() => {
                  ctx.fillStyle = '#124'; ctx.fillRect(0,0,320,180);
                  ctx.fillStyle = '#0c8'; ctx.fillRect(40,40,60,40);
                }, 50);
                const stream = c.captureStream(12);
                const track = stream.getVideoTracks()[0];
                const stop = track.stop.bind(track);
                track.stop = () => { clearInterval(timer); stop(); };
                return stream;
              };
            })();
            """
        )
        page.goto(info["origin"], wait_until="domcontentloaded")

        # BEFORE: settings chrome visible (owner complaint state class).
        page.get_by_test_id("biggy-vision").click()
        page.get_by_test_id("biggy-vision-camera").click()
        expect(page.get_by_test_id("biggy-td-camera-settings")).to_be_visible()
        page.screenshot(
            path=str(out_dir / "VISION_CLEAN_UI_before_settings_chrome.png"),
            full_page=False,
        )
        # Open Presentation settings (VISION menu dismisses Camera settings first).
        page.get_by_test_id("biggy-vision").click()
        page.get_by_test_id("biggy-vision-presentation").click()
        expect(page.get_by_test_id("biggy-presentation-panel")).to_be_visible()
        expect(page.get_by_test_id("biggy-td-camera-settings")).to_have_count(0)

        # Feed-only camera (product default geometry) + presentation recording hides settings.
        page.evaluate(
            """() => {
              const api = window.BiggyTdCameraOverlay;
              api.closeSettings();
              api._test.ensureFeed();
              api._test.applyFeedRect(api._test.defaultFeedRect());
              const c = document.querySelector('#biggy-td-camera-canvas');
              if (c) {
                c.hidden = false;
                const ctx = c.getContext('2d');
                ctx.fillStyle = '#062';
                ctx.fillRect(0,0,c.width,c.height);
                ctx.fillStyle = '#3d8';
                ctx.fillRect(40,40,120,80);
              }
            }"""
        )
        page.get_by_test_id("biggy-presentation-on").click()
        page.wait_for_function(
            "() => !!(window.BiggyPresentation && window.BiggyPresentation.isRecording())",
            timeout=10000,
        )
        expect(page.get_by_test_id("biggy-presentation-panel")).to_have_count(0)
        expect(page.get_by_test_id("biggy-td-camera-settings")).to_have_count(0)
        expect(page.get_by_test_id("biggy-td-camera-overlay")).to_be_visible()
        assert page.evaluate(
            "() => !!(document.getElementById('biggyVision') && "
            "document.getElementById('biggyVision').classList.contains('is-presentation-recording'))"
        )
        page.screenshot(
            path=str(out_dir / "VISION_CLEAN_UI_after_feed_only_recording.png"),
            full_page=False,
        )

        # Settings Close does not stop recording; Off does.
        page.get_by_test_id("biggy-vision").click()
        page.get_by_test_id("biggy-vision-presentation").click()
        expect(page.get_by_test_id("biggy-presentation-panel")).to_be_visible()
        page.get_by_test_id("biggy-presentation-close").click()
        expect(page.get_by_test_id("biggy-presentation-panel")).to_have_count(0)
        assert page.evaluate("() => window.BiggyPresentation.isRecording()") is True
        page.get_by_test_id("biggy-vision").click()
        page.get_by_test_id("biggy-vision-presentation").click()
        page.get_by_test_id("biggy-presentation-off").click()
        page.wait_for_function(
            "() => window.BiggyPresentation.phase() === 'saved'",
            timeout=20000,
        )
        browser.close()


def test_settings_hidden_before_mediarecorder_start_and_vision_error(presentation_gui_server):
    """First recorded frame must not include settings; hidden failures surface on Vision."""
    sp = _require_playwright()
    info = presentation_gui_server
    with sp() as p:
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
        page.add_init_script(
            """
            (() => {
              navigator.mediaDevices.getDisplayMedia = async () => {
                const c = document.createElement('canvas');
                c.width = 160; c.height = 90;
                const ctx = c.getContext('2d');
                const timer = setInterval(() => {
                  ctx.fillStyle = '#210'; ctx.fillRect(0,0,160,90);
                }, 40);
                const stream = c.captureStream(12);
                const track = stream.getVideoTracks()[0];
                const stop = track.stop.bind(track);
                track.stop = () => { clearInterval(timer); stop(); };
                return stream;
              };
              const origStart = MediaRecorder.prototype.start;
              MediaRecorder.prototype.start = function (...args) {
                const panel = document.querySelector('[data-testid="biggy-presentation-panel"]');
                window.__presAtRecorderStart = {
                  settingsPresent: !!panel,
                  settingsConnected: !!(panel && panel.isConnected),
                  phase: window.BiggyPresentation ? window.BiggyPresentation.phase() : null,
                };
                return origStart.apply(this, args);
              };
            })();
            """
        )
        page.goto(info["origin"], wait_until="domcontentloaded")
        page.get_by_test_id("biggy-vision").click()
        page.get_by_test_id("biggy-vision-presentation").click()
        expect(page.get_by_test_id("biggy-presentation-panel")).to_be_visible()
        page.wait_for_function(
            """() => {
              const d = document.querySelector('[data-testid="biggy-presentation-details-body"]');
              return !!(d && /max_duration_ms=/.test(d.textContent || ''));
            }""",
            timeout=10000,
        )
        page.get_by_test_id("biggy-presentation-on").click()
        page.wait_for_function(
            "() => !!(window.__presAtRecorderStart && window.BiggyPresentation.isRecording())",
            timeout=10000,
        )
        at_start = page.evaluate("() => window.__presAtRecorderStart")
        assert at_start["settingsPresent"] is False
        assert at_start["settingsConnected"] is False
        expect(page.get_by_test_id("biggy-presentation-panel")).to_have_count(0)

        # Hidden-settings upload failure must light Vision error chrome and retain status.
        page.evaluate(
            """() => {
              const gen = window.BiggyPresentation._test.getGeneration();
              window.BiggyPresentation._test.failUpload(new Error('chunk_upload_failed'), gen);
            }"""
        )
        page.wait_for_function(
            """() => {
              const v = document.getElementById('biggyVision');
              return !!(v && v.classList.contains('is-presentation-error')
                && window.BiggyPresentation.phase() === 'failed');
            }""",
            timeout=5000,
        )
        title = page.evaluate("() => document.getElementById('biggyVision').title || ''")
        assert "chunk_upload_failed" in title or "Upload failed" in title
        page.get_by_test_id("biggy-vision").click()
        page.get_by_test_id("biggy-vision-presentation").click()
        expect(page.get_by_test_id("biggy-presentation-panel")).to_be_visible()
        status = page.get_by_test_id("biggy-presentation-status").inner_text()
        assert "chunk_upload_failed" in status or "Upload failed" in status
        assert page.evaluate("() => window.BiggyPresentation.phase()") == "failed"
        browser.close()


def test_presentation_mic_opt_in_and_pause_excludes_duration(presentation_gui_server):
    """Mic stays off by default; synthetic mic+video can record; pause omitted from duration."""
    sp = _require_playwright()
    info = presentation_gui_server
    with sp() as p:
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
        page.add_init_script(
            """
            (() => {
              const makeVideo = () => {
                const c = document.createElement('canvas');
                c.width = 320; c.height = 180;
                const ctx = c.getContext('2d');
                let i = 0;
                const draw = () => {
                  ctx.fillStyle = '#234';
                  ctx.fillRect(0,0,320,180);
                  ctx.fillStyle = '#f80';
                  ctx.fillRect((i*4)%280, 50, 36, 36);
                  i += 1;
                };
                draw();
                const timer = setInterval(draw, 40);
                const stream = c.captureStream(20);
                const track = stream.getVideoTracks()[0];
                const stop = track.stop.bind(track);
                track.stop = () => { clearInterval(timer); stop(); };
                return stream;
              };
              const makeMic = () => {
                const ctx = new (window.AudioContext || window.webkitAudioContext)();
                const osc = ctx.createOscillator();
                const dest = ctx.createMediaStreamDestination();
                osc.frequency.value = 440;
                osc.connect(dest);
                osc.start();
                const track = dest.stream.getAudioTracks()[0];
                const stop = track.stop.bind(track);
                track.stop = () => { try { osc.stop(); } catch (_) {} try { ctx.close(); } catch (_) {} stop(); };
                return dest.stream;
              };
              navigator.mediaDevices.getDisplayMedia = async () => makeVideo();
              navigator.mediaDevices.getUserMedia = async (constraints) => {
                if (constraints && constraints.audio) return makeMic();
                throw new Error('unexpected getUserMedia');
              };
            })();
            """
        )
        page.goto(info["origin"], wait_until="domcontentloaded")
        page.get_by_test_id("biggy-vision").click()
        page.get_by_test_id("biggy-vision-presentation").click()
        panel = page.get_by_test_id("biggy-presentation-panel")
        expect(panel).to_be_visible()
        page.wait_for_function(
            """() => {
              const d = document.querySelector('[data-testid="biggy-presentation-details-body"]');
              return !!(d && /max_duration_ms=/.test(d.textContent || ''));
            }""",
            timeout=10000,
        )
        mic = page.get_by_test_id("biggy-presentation-mic")
        expect(mic).to_be_visible()
        assert mic.is_checked() is False
        expect(page.get_by_test_id("biggy-presentation-pause")).to_be_disabled()
        expect(page.get_by_test_id("biggy-presentation-mute")).to_be_disabled()
        mic.check()
        page.get_by_test_id("biggy-presentation-on").click()
        page.wait_for_function(
            "() => window.BiggyPresentation && window.BiggyPresentation.isRecording()",
            timeout=15000,
        )
        expect(page.get_by_test_id("biggy-presentation-panel")).to_have_count(0)
        page.get_by_test_id("biggy-vision").click()
        page.get_by_test_id("biggy-vision-presentation").click()
        expect(page.get_by_test_id("biggy-presentation-panel")).to_be_visible()
        expect(page.get_by_test_id("biggy-presentation-pause")).to_be_enabled()
        expect(page.get_by_test_id("biggy-presentation-mute")).to_be_enabled()
        page.get_by_test_id("biggy-presentation-pause").click()
        # Pause hides settings so the control chrome is not recorded.
        expect(page.get_by_test_id("biggy-presentation-panel")).to_have_count(0)
        page.wait_for_timeout(700)
        page.get_by_test_id("biggy-vision").click()
        page.get_by_test_id("biggy-vision-presentation").click()
        expect(page.get_by_test_id("biggy-presentation-panel")).to_be_visible()
        page.wait_for_function(
            """() => {
              const b = document.querySelector('[data-testid="biggy-presentation-pause"]');
              return !!(b && /Resume/i.test(b.textContent || ''));
            }""",
            timeout=5000,
        )
        page.get_by_test_id("biggy-presentation-pause").click()
        # Resume also hides settings before continuing capture.
        expect(page.get_by_test_id("biggy-presentation-panel")).to_have_count(0)
        page.wait_for_timeout(400)
        page.get_by_test_id("biggy-vision").click()
        page.get_by_test_id("biggy-vision-presentation").click()
        expect(page.get_by_test_id("biggy-presentation-panel")).to_be_visible()
        page.get_by_test_id("biggy-presentation-off").click()
        page.wait_for_function(
            """() => {
              const t = document.querySelector('[data-testid="biggy-presentation-status"]');
              return !!(t && /Saved|linked/i.test(t.textContent || ''));
            }""",
            timeout=20000,
        )
        files = list(info["dest"].glob("presentation-*/recording.*"))
        assert files, "expected saved recording with synthetic A/V"
        status = page.get_by_test_id("biggy-presentation-status").inner_text()
        assert "Saved" in status
        # Decode proof: Open saved and require video + audio track presence.
        page.get_by_test_id("biggy-presentation-open").click()
        expect(page.get_by_test_id("biggy-presentation-video")).to_be_visible(timeout=10000)
        av = page.get_by_test_id("biggy-presentation-video").evaluate(
            """async (v) => {
              await new Promise((res, rej) => {
                if (v.readyState >= 1) return res();
                v.onloadedmetadata = () => res();
                v.onerror = () => rej(new Error('video_error'));
                setTimeout(() => rej(new Error('meta_timeout')), 8000);
              });
              const hasAudio = !!(v.mozHasAudio || v.webkitAudioDecodedByteCount
                || (v.audioTracks && v.audioTracks.length > 0)
                || (typeof v.webkitAudioDecodedByteCount === 'number' && v.webkitAudioDecodedByteCount > 0));
              // Chromium headless: probe via captureStream when available.
              let capturedAudio = false;
              try {
                if (v.captureStream) {
                  const s = v.captureStream();
                  capturedAudio = s.getAudioTracks().length > 0;
                }
              } catch (_) {}
              return {
                duration: v.duration,
                videoWidth: v.videoWidth,
                hasAudio: hasAudio || capturedAudio,
                readyState: v.readyState,
              };
            }"""
        )
        assert av["videoWidth"] > 0
        assert av["hasAudio"] is True, av
        # Duration may be Infinity until fully demuxed in headless; prefer finite when available.
        if isinstance(av["duration"], (int, float)) and av["duration"] == av["duration"] and av["duration"] != float("inf"):
            assert av["duration"] > 0
            assert av["duration"] < 12.0
        else:
            # Fallback: saved file must be non-trivial and status reports seconds.
            assert files[0].stat().st_size > 1000
            assert any(ch.isdigit() for ch in status)
        browser.close()


def test_focus_guidance_panel_static_and_mount(presentation_gui_server):
    """Focus/Guidance panel mounts from VISION menu; freeze API is exported."""
    sp = _require_playwright()
    info = presentation_gui_server
    focus_js = (ROOT / "static" / "vision" / "focus-guidance.js").read_text(encoding="utf-8")
    assert "ingestFreeze" in focus_js
    assert '"params"' in focus_js or "params }" in focus_js or "params)," in focus_js
    assert "vision_evidence_save" in focus_js
    brand = (ROOT / "static" / "biggy-brand.js").read_text(encoding="utf-8")
    assert "ensureBiggyFocusGuidanceModule" in brand
    assert "window.openBiggyVisionSurface" in brand
    with sp() as p:
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
        page.get_by_test_id("biggy-vision").click()
        page.get_by_test_id("biggy-vision-focus").click()
        expect(page.get_by_test_id("biggy-focus-guidance")).to_be_visible(timeout=10000)
        expect(page.get_by_test_id("biggy-focus-capture")).to_be_visible()
        expect(page.get_by_test_id("biggy-guidance-ask")).to_be_visible()
        # Overview includes live Camera/Presentation rows.
        page.get_by_test_id("biggy-vision-close-surface").click()
        page.get_by_test_id("biggy-vision").click()
        page.get_by_test_id("biggy-vision-overview").click()
        expect(page.get_by_test_id("biggy-vision-overview-camera")).to_be_visible()
        expect(page.get_by_test_id("biggy-vision-overview-presentation")).to_be_visible()
        browser.close()



def test_finalize_success_link_network_fail_keeps_saved(presentation_gui_server):
    """Saved file stays saved/playable when optional task link throws."""
    sp = _require_playwright()
    info = presentation_gui_server
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
        page.add_init_script(
            """
            (() => {
              const makeVideo = () => {
                const c = document.createElement('canvas');
                c.width = 160; c.height = 90;
                const ctx = c.getContext('2d');
                let i = 0;
                const timer = setInterval(() => {
                  ctx.fillStyle = '#135'; ctx.fillRect(0,0,160,90);
                  ctx.fillStyle = '#0f8'; ctx.fillRect((i*2)%120, 20, 30, 30); i++;
                }, 40);
                const stream = c.captureStream(15);
                const track = stream.getVideoTracks()[0];
                const stop = track.stop.bind(track);
                track.stop = () => { clearInterval(timer); stop(); };
                return stream;
              };
              navigator.mediaDevices.getDisplayMedia = async () => makeVideo();
            })();
            """
        )
        page.goto(info["origin"], wait_until="domcontentloaded")
        page.get_by_test_id("biggy-vision").click()
        page.get_by_test_id("biggy-vision-presentation").click()
        page.wait_for_function(
            """() => /max_duration_ms=/.test((document.querySelector('[data-testid="biggy-presentation-details-body"]') || {}).textContent || '')""",
            timeout=10000,
        )
        # Force a task selection then break workspace commands after start.
        page.evaluate(
            """() => {
              const sel = document.querySelector('[data-testid="biggy-presentation-task"]');
              if (sel) {
                const o = document.createElement('option');
                o.value = 'task_link_fail';
                o.textContent = 'Link fail task';
                sel.appendChild(o);
                sel.value = 'task_link_fail';
                sel.dispatchEvent(new Event('change', { bubbles: true }));
              }
              const orig = window.fetch.bind(window);
              window.fetch = async (url, init) => {
                const u = String(url);
                if (u.includes('/biggy-workspace/api/v1/commands')) {
                  throw new TypeError('network_down_for_task_link');
                }
                return orig(url, init);
              };
            }"""
        )
        page.get_by_test_id("biggy-presentation-on").click()
        page.wait_for_function(
            "() => window.BiggyPresentation && window.BiggyPresentation.isRecording()",
            timeout=15000,
        )
        page.wait_for_timeout(600)
        page.get_by_test_id("biggy-vision").click()
        page.get_by_test_id("biggy-vision-presentation").click()
        page.evaluate(
            """() => {
              const sel = document.querySelector('[data-testid="biggy-presentation-task"]');
              let o = Array.from(sel.options).find(x => x.value === 'task_link_fail');
              if (!o) {
                o = document.createElement('option');
                o.value = 'task_link_fail';
                o.textContent = 'Link fail task';
                sel.appendChild(o);
              }
              sel.value = 'task_link_fail';
              sel.dispatchEvent(new Event('change', { bubbles: true }));
              window.BiggyPresentation._test.setLinkTaskId('task_link_fail');
              const orig = window.fetch.bind(window);
              window.fetch = async (url, init) => {
                const u = String(url);
                if (u.includes('/biggy-workspace/api/v1/commands')) {
                  throw new TypeError('network_down_for_task_link');
                }
                return orig(url, init);
              };
            }"""
        )
        page.get_by_test_id("biggy-presentation-off").click()
        page.wait_for_function(
            """() => {
              const ph = window.BiggyPresentation.phase();
              const t = (document.querySelector('[data-testid="biggy-presentation-status"]') || {}).textContent || '';
              return ph === 'saved' && /Saved/i.test(t);
            }""",
            timeout=20000,
        )
        status = page.get_by_test_id("biggy-presentation-status").inner_text()
        assert "Saved" in status
        assert "task link failed" in status.lower() or "network_down" in status.lower()
        assert page.evaluate("() => window.BiggyPresentation.phase()") == "saved"
        files = list(info["dest"].glob("presentation-*/recording.*"))
        assert files
        expect(page.get_by_test_id("biggy-presentation-open")).to_be_enabled()
        # Explicit none honored (clears latched task)
        page.select_option('[data-testid="biggy-presentation-task"]', "")
        assert page.evaluate("() => window.BiggyPresentation._test.getLinkTaskId()") == ""
        # Partial retry: evidence stage then attach fail once — no duplicate evidence keys
        page.evaluate(
            """() => {
              let attachAttempts = 0;
              const orig = window.fetch.bind(window);
              window.fetch = async (url, init) => {
                const u = String(url);
                if (u.includes('/biggy-workspace/api/v1/commands')) {
                  const body = JSON.parse(init.body || '{}');
                  if (body.command === 'vision_evidence_save') {
                    return new Response(JSON.stringify({ artifact: { id: 'ev_test' } }), {
                      status: 200, headers: { 'Content-Type': 'application/json' }
                    });
                  }
                  if (body.command === 'vision_attach') {
                    attachAttempts += 1;
                    if (attachAttempts === 1) {
                      return new Response(JSON.stringify({ error: 'attach_temp' }), {
                        status: 500, headers: { 'Content-Type': 'application/json' }
                      });
                    }
                    return new Response(JSON.stringify({ ok: true }), {
                      status: 200, headers: { 'Content-Type': 'application/json' }
                    });
                  }
                }
                return orig(url, init);
              };
              const sel = document.querySelector('[data-testid="biggy-presentation-task"]');
              const o = document.createElement('option');
              o.value = 'task_retry'; o.textContent = 'Retry';
              sel.appendChild(o); sel.value = 'task_retry';
              sel.dispatchEvent(new Event('change', { bubbles: true }));
              window.BiggyPresentation._test.setLinkTaskId('task_retry');
            }"""
        )
        # First retry fails attach after evidence staged
        page.evaluate("async () => { try { await window.BiggyPresentation.retryLinkSaved(); } catch (e) {} }")
        page.wait_for_function(
            "() => window.BiggyPresentation._test.getLinkedEvidenceKeys().length === 1",
            timeout=5000,
        )
        assert page.evaluate("() => window.BiggyPresentation._test.getLinkedKeys().length") == 0
        # Second retry completes attach without second evidence write
        page.evaluate("async () => { try { await window.BiggyPresentation.retryLinkSaved(); } catch (e) {} }")
        page.wait_for_function(
            "() => window.BiggyPresentation._test.getLinkedKeys().length === 1",
            timeout=5000,
        )
        assert page.evaluate("() => window.BiggyPresentation._test.getLinkedEvidenceKeys().length") == 1
        browser.close()
