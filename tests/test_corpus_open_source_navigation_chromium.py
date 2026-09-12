"""Chromium regression: Workspace Open-source link provenance for corpus docs.

Owner failure (release workspace-rag-20260912-134447): target=_blank with
rel=noopener noreferrer → no Referer, Sec-Fetch-Site:same-origin → sidecar
proxy 403 Cross-origin mismatch.

Fix: rel=noopener + referrerPolicy=same-origin so same-origin Referer is sent.
Does not weaken routes._check_same_origin_browser_request.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest

try:
    from playwright.sync_api import sync_playwright
except Exception:  # pragma: no cover
    sync_playwright = None

DOC_PATH = (
    "/api/extensions/smedley-engineering/sidecar/doc/"
    "Vendor%20Data/Allen%20Bradley/1756/1756-um001_-en-p.pdf"
)
PDF_BYTES = b"%PDF-1.4 chromium-open-source-fixture"


def _require_playwright():
    if sync_playwright is None:
        pytest.skip("playwright is unavailable; install chromium for this regression")
    return sync_playwright


def _wait_status(server: "_ProvenanceDocServer", timeout_sec: float = 8.0) -> int | None:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if server.last_doc_status is not None:
            return server.last_doc_status
        time.sleep(0.05)
    return server.last_doc_status


class _ProvenanceDocServer:
    """Minimal same-origin host: workspace page + sidecar doc gated like Hermes."""

    def __init__(self) -> None:
        self.last_doc_headers: dict[str, str] = {}
        self.last_doc_status: int | None = None
        self._lock = threading.Lock()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args):  # noqa: N802
                return

            def do_GET(self):  # noqa: N802
                parsed = urlparse(self.path)
                if parsed.path in {"/", "/biggy-workspace/", "/biggy-workspace"}:
                    body = owner._page_html().encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    # Match Hermes embed: strict-origin must still allow same-origin Referer.
                    self.send_header("Referrer-Policy", "strict-origin")
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if parsed.path == DOC_PATH.split("#", 1)[0]:
                    from api import routes

                    hdrs = {
                        "Host": self.headers.get("Host", ""),
                        "Origin": self.headers.get("Origin", ""),
                        "Referer": self.headers.get("Referer", ""),
                        "Sec-Fetch-Site": self.headers.get("Sec-Fetch-Site", ""),
                    }
                    handler = SimpleNamespace(headers=hdrs)
                    ok = routes._check_same_origin_browser_request(
                        handler, require_provenance=True
                    )
                    with owner._lock:
                        owner.last_doc_headers = dict(hdrs)
                    if not ok:
                        payload = json.dumps(
                            {"error": routes._csrf_rejection_error(handler)}
                        ).encode("utf-8")
                        with owner._lock:
                            owner.last_doc_status = 403
                        self.send_response(403)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Content-Length", str(len(payload)))
                        self.end_headers()
                        self.wfile.write(payload)
                        return
                    with owner._lock:
                        owner.last_doc_status = 200
                    self.send_response(200)
                    self.send_header("Content-Type", "application/pdf")
                    self.send_header("Content-Length", str(len(PDF_BYTES)))
                    self.end_headers()
                    self.wfile.write(PDF_BYTES)
                    return
                self.send_response(404)
                self.end_headers()

        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.origin = f"http://127.0.0.1:{self._httpd.server_address[1]}"
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)

    def reset_doc(self) -> None:
        with self._lock:
            self.last_doc_headers = {}
            self.last_doc_status = None

    def _page_html(self) -> str:
        # Mirrors Workspace app.js Open-source attributes after the provenance fix.
        return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>open-source provenance</title></head>
<body>
<a class="rag-open-source"
   href="{DOC_PATH}"
   target="_blank"
   rel="noopener"
   referrerpolicy="same-origin">Open source</a>
<a class="rag-open-source-broken"
   href="{DOC_PATH}"
   target="_blank"
   rel="noopener noreferrer">Broken noreferrer</a>
</body></html>"""

    def start(self) -> str:
        self._thread.start()
        return self.origin

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=2)


def test_chromium_open_source_link_sends_same_origin_referer():
    sp = _require_playwright()
    server = _ProvenanceDocServer()
    origin = server.start()
    try:
        with sp() as pw:
            browser = pw.chromium.launch(
                headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
            try:
                ctx = browser.new_context()
                page = ctx.new_page()
                page.goto(f"{origin}/biggy-workspace/", wait_until="domcontentloaded")
                server.reset_doc()
                with page.expect_popup(timeout=10_000) as pop_info:
                    page.click("a.rag-open-source")
                popup = pop_info.value
                status = _wait_status(server)
                assert status == 200, (
                    status,
                    server.last_doc_headers,
                    getattr(popup, "url", None),
                )
                referer = server.last_doc_headers.get("Referer", "")
                assert referer.startswith(f"{origin}/"), server.last_doc_headers
                popup.close()
            finally:
                browser.close()
    finally:
        server.stop()


def test_chromium_noreferrer_open_source_still_fails_provenance():
    """Keep the failure mode documented: noreferrer must not become accepted."""
    sp = _require_playwright()
    server = _ProvenanceDocServer()
    origin = server.start()
    try:
        with sp() as pw:
            browser = pw.chromium.launch(
                headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
            try:
                ctx = browser.new_context()
                page = ctx.new_page()
                page.goto(f"{origin}/biggy-workspace/", wait_until="domcontentloaded")
                server.reset_doc()
                with page.expect_popup(timeout=10_000) as pop_info:
                    page.click("a.rag-open-source-broken")
                popup = pop_info.value
                status = _wait_status(server)
                # Chromium+noreferrer often yields Sec-Fetch-Site:same-origin with no
                # Referer — the exact owner 403 path. If a build sends Site:none instead,
                # provenance would allow; fail the test only when headers match the
                # documented failure profile or when status is 403.
                site = (server.last_doc_headers.get("Sec-Fetch-Site") or "").lower()
                referer = server.last_doc_headers.get("Referer") or ""
                origin_hdr = server.last_doc_headers.get("Origin") or ""
                if site == "same-origin" and not referer and not origin_hdr:
                    assert status == 403, server.last_doc_headers
                else:
                    assert status == 403, (
                        "expected noreferrer navigation to fail provenance; "
                        f"got status={status} headers={server.last_doc_headers}"
                    )
                popup.close()
            finally:
                browser.close()
    finally:
        server.stop()


def test_chromium_hostile_origin_navigation_rejected():
    sp = _require_playwright()
    victim = _ProvenanceDocServer()
    victim_origin = victim.start()

    class Evil(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args):  # noqa: N802
            return

        def do_GET(self):  # noqa: N802
            html = (
                f'<!doctype html><a id="atk" href="{victim_origin}{DOC_PATH}" '
                'target="_blank" rel="noopener" referrerpolicy="unsafe-url">go</a>'
            )
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    evil_httpd = ThreadingHTTPServer(("127.0.0.1", 0), Evil)
    evil_thread = threading.Thread(target=evil_httpd.serve_forever, daemon=True)
    evil_thread.start()
    evil_origin = f"http://127.0.0.1:{evil_httpd.server_address[1]}"
    try:
        with sp() as pw:
            browser = pw.chromium.launch(
                headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
            try:
                ctx = browser.new_context()
                page = ctx.new_page()
                page.goto(f"{evil_origin}/", wait_until="domcontentloaded")
                victim.reset_doc()
                with page.expect_popup(timeout=10_000) as pop_info:
                    page.click("#atk")
                popup = pop_info.value
                status = _wait_status(victim)
                assert status == 403, victim.last_doc_headers
                popup.close()
            finally:
                browser.close()
    finally:
        evil_httpd.shutdown()
        evil_httpd.server_close()
        evil_thread.join(timeout=2)
        victim.stop()
