"""Isolated Vision core Playwright: intake → analyze → save → reload → reopen.

Uses synthetic auth/data only. Task is pre-seeded in the isolated DB (no production
writes). Owner login uses the real password UI — authentication is not weakened.
Exercises real app.js discard/replace while analyze is pending, and shared
BiggyDocumentViewer fullscreen without a new browser tab.
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

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


def _tiny_png_bytes(*, label: str = "A") -> bytes:
    try:
        from PIL import Image, ImageDraw

        img = Image.new("RGB", (96, 64), color=(30, 60, 90) if label == "A" else (90, 30, 60))
        draw = ImageDraw.Draw(img)
        draw.rectangle([10, 10, 50, 50], fill=(220, 40, 40) if label == "A" else (40, 220, 40))
        draw.text((55, 20), label, fill=(255, 255, 0))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        )


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    if not (WORKSPACE / "biggy_workspace/app.py").is_file():
        pytest.skip("Set BIGGY_WORKSPACE_REPO to run Vision UI integration")
    sys.path.insert(0, str(WORKSPACE))
    from biggy_workspace.app import AppState, serve

    monkeypatch.setenv("BIGGY_WORKSPACE_RAG_RETRIEVE_URL", "fixture://workspace-rag")
    monkeypatch.delenv("BIGGY_WORKSPACE_LOCAL_INFERENCE_URL", raising=False)

    state = AppState(
        db_path=tmp_path / "vision-test.db",
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


def _inject_viewer(page) -> None:
    if not os.getenv("BIGGY_VIEWER_BASELINE"):
        page.add_script_tag(path=str(ROOT / "static/biggy-document-viewer.js"))


def _login(page, workspace_url: str) -> None:
    # Exact same login sequence as tests/test_biggy_document_viewer.py.
    page.goto(workspace_url)
    page.get_by_label("Owner password", exact=True).fill("synthetic-test-owner-password")
    page.get_by_role("button", name="Sign in", exact=True).click()
    # #app uses .planner-shell { display:flex }, which overrides the HTML hidden
    # attribute for Playwright visibility — wait on the IDL .hidden flag instead.
    page.wait_for_function(
        "() => {"
        "  const app = document.getElementById('app');"
        "  const auth = document.getElementById('auth-panel');"
        "  return !!(app && !app.hidden && auth && auth.hidden);"
        "}",
        timeout=15000,
    )


def _create_synthetic_task_via_capture(page, title: str) -> str:
    """Create an unscheduled synthetic task through the authenticated capture UI."""
    close_btn = page.locator("#close-senses-drawer")
    if close_btn.count() and close_btn.is_visible():
        close_btn.click()
    page.locator("#capture-title").fill(title)
    page.locator("#capture-form button[type='submit']").click()
    expect(page.locator("#capture-title")).to_have_value("", timeout=10000)
    # Open senses drawer so focus-task is populated and readable.
    page.locator("#open-senses-drawer").click()
    expect(page.locator("#focus-task")).to_be_visible()
    expect(page.locator("#focus-task option")).not_to_have_count(0, timeout=15000)
    options = page.locator("#focus-task option")
    task_id = None
    for i in range(options.count()):
        if title in options.nth(i).inner_text():
            task_id = options.nth(i).get_attribute("value")
            break
    assert task_id, f"capture task {title!r} not in focus-task"
    return task_id


def _open_vision(page, workspace_url: str) -> None:
    page.goto(f"{workspace_url}/?panel=vision")
    page.wait_for_function(
        "() => {"
        "  const app = document.getElementById('app');"
        "  return !!(app && !app.hidden);"
        "}",
        timeout=15000,
    )
    if not page.locator("#vision-panel").is_visible():
        page.locator("#open-senses-drawer").click(force=True)
        page.locator("#vision-panel").scroll_into_view_if_needed()
    expect(page.locator("#vision-panel")).to_be_visible()


def test_vision_intake_analyze_save_reload_reopen_fullscreen(workspace, tmp_path):
    sp = _require_playwright()
    workspace_url = workspace
    png_a = _tiny_png_bytes(label="A")
    png_b = _tiny_png_bytes(label="B")
    file_a = tmp_path / "intake-a.png"
    file_b = tmp_path / "intake-b.png"
    file_a.write_bytes(png_a)
    file_b.write_bytes(png_b)

    with sp() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        _login(page, workspace_url)
        task_id = _create_synthetic_task_via_capture(
            page, "Vision synthetic evidence task"
        )
        _open_vision(page, workspace_url)
        _inject_viewer(page)
        expect(page.locator(f'#focus-task option[value="{task_id}"]')).to_be_attached(
            timeout=15000
        )
        page.locator("#focus-task").select_option(task_id)
        assert page.locator("#focus-task").input_value() == task_id

        # Sync Playwright cannot sleep inside a route handler (deadlocks the test thread).
        pending_analyze: list = []
        analyze_payload = {
            "available": True,
            "state": "ok",
            "text": "synthetic-vision-analysis-ok",
            "message": None,
            "provenance": {
                "source": "image_intake",
                "host": "test",
                "captured_at": "2026-09-12T16:00:00Z",
                "model": "fixture-vlm",
                "endpoint_kind": "local",
                "endpoint_host": "127.0.0.1",
                "route": "v1/chat/completions",
            },
        }

        def handle_analyze(route):
            pending_analyze.append(route)

        def wait_pending(n: int, timeout: float = 8.0):
            deadline = time.time() + timeout
            while len(pending_analyze) < n and time.time() < deadline:
                page.wait_for_timeout(50)
            assert len(pending_analyze) >= n, (
                f"expected {n} analyze routes, got {len(pending_analyze)}; "
                f"error={page.locator('#error').inner_text()!r}"
            )

        def fulfill_next():
            route = pending_analyze.pop(0)
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(analyze_payload),
            )

        page.route("**/api/v1/vision/analyze", handle_analyze)
        page.route(
            "**/api/v1/vision/capability",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "capability": {
                            "image_support": "configured_unverified",
                            "verified": False,
                            "detail": "fixture",
                            "endpoint_kind": "local_chat_completions",
                            "endpoint_host": "127.0.0.1",
                            "model": "fixture-vlm",
                            "original_max_bytes": 1_500_000,
                            "inference_max_bytes": 400_000,
                        }
                    }
                ),
            ),
        )

        # --- replace while analyze pending ---
        page.set_input_files("#vision-file", str(file_a))
        expect(page.locator("#vision-preview")).to_be_visible()
        expect(page.locator("#vision-analyze")).to_be_enabled()
        page.locator("#vision-analyze").click(force=True)
        wait_pending(1)
        page.set_input_files("#vision-file", str(file_b))
        expect(page.locator("#vision-preview")).to_be_visible()
        fulfill_next()  # stale analyze for frame A
        page.wait_for_timeout(200)
        page.locator("#vision-analyze").click(force=True)
        wait_pending(1)
        fulfill_next()
        expect(page.locator("#vision-text")).to_be_visible()
        expect(page.locator("#vision-text")).to_contain_text("synthetic-vision-analysis-ok")

        # --- discard while analyze pending ---
        page.set_input_files("#vision-file", str(file_a))
        expect(page.locator("#vision-analyze")).to_be_enabled()
        page.locator("#vision-analyze").click(force=True)
        wait_pending(1)
        page.locator("#vision-discard").click(force=True)
        expect(page.locator("#vision-meta")).to_contain_text("discarded")
        fulfill_next()  # late response must not resurrect discarded preview
        page.wait_for_timeout(200)
        expect(page.locator("#vision-text")).to_be_hidden()

        # --- successful intake → analyze → save ---
        page.set_input_files("#vision-file", str(file_a))
        expect(page.locator("#vision-analyze")).to_be_enabled()
        page.locator("#vision-analyze").click(force=True)
        wait_pending(1)
        fulfill_next()
        expect(page.locator("#vision-text")).to_contain_text("synthetic-vision-analysis-ok")
        page.locator("#vision-save").click(force=True)
        expect(page.locator("#vision-meta")).to_contain_text("Saved")
        expect(page.locator("#vision-evidence-items li")).to_have_count(1)
        expect(page.get_by_role("button", name="Reopen original", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="Reopen analysis", exact=True)).to_be_visible()

        # Reload and reopen both original + analysis via shared viewer.
        page.reload()
        # Session cookie usually keeps the app unlocked; only sign in if auth is shown.
        try:
            expect(page.locator("#app")).to_be_visible(timeout=5000)
        except Exception:
            page.get_by_label("Owner password", exact=True).fill(
                "synthetic-test-owner-password"
            )
            page.get_by_role("button", name="Sign in", exact=True).click()
            expect(page.locator("#app")).to_be_visible()
        _open_vision(page, workspace_url)
        _inject_viewer(page)
        expect(page.locator(f'#focus-task option[value="{task_id}"]')).to_be_attached(
            timeout=15000
        )
        page.locator("#focus-task").select_option(task_id)
        expect(page.get_by_role("button", name="Reopen original", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="Reopen analysis", exact=True)).to_be_visible()

        page.evaluate(
            "() => document.documentElement.requestFullscreen()"
        )
        assert page.evaluate("!!document.fullscreenElement")

        page.get_by_role("button", name="Reopen original", exact=True).click(force=True)
        dialog = page.get_by_role("dialog", name="Document viewer", exact=True)
        expect(dialog).to_be_visible()
        assert len(page.context.pages) == 1
        assert page.evaluate("!!document.fullscreenElement")
        page.get_by_role("button", name="Close document", exact=True).click(force=True)
        expect(dialog).to_have_count(0)
        assert page.evaluate("!!document.fullscreenElement")
        assert len(page.context.pages) == 1

        page.get_by_role("button", name="Reopen analysis", exact=True).click(force=True)
        expect(dialog).to_be_visible()
        assert len(page.context.pages) == 1
        assert page.evaluate("!!document.fullscreenElement")
        frame = page.frame_locator(".biggy-document-frame")
        expect(frame.get_by_text("synthetic-vision-analysis-ok")).to_be_visible()
        page.get_by_role("button", name="Close document", exact=True).click(force=True)
        assert len(page.context.pages) == 1
        assert not errors, errors
        browser.close()


def test_tablet_intake_survives_session_failure_and_analyzes(workspace, tmp_path):
    """Android-like tablet: no getDisplayMedia; intake works when mint/session fails."""
    sp = _require_playwright()
    workspace_url = workspace
    png = _tiny_png_bytes(label="T")
    file_path = tmp_path / "tablet-intake.png"
    file_path.write_bytes(png)

    with sp() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 900, "height": 1400},
            user_agent=(
                "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
            ),
        )
        # Display capture absent (tablet / Chromium without getDisplayMedia).
        context.add_init_script(
            """
            Object.defineProperty(Navigator.prototype, 'mediaDevices', {
              configurable: true,
              get() {
                return { getUserMedia: undefined };
              },
            });
            """
        )
        page = context.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))

        _login(page, workspace_url)
        _open_vision(page, workspace_url)
        # Wait until affordance sync runs (showApp → syncVisionCaptureAffordances).
        try:
            page.wait_for_function(
                """() => {
                  const btn = document.getElementById('vision-capture');
                  const label = document.querySelector('label.vision-file-label');
                  return !!(
                    btn && btn.disabled === true &&
                    label && label.classList.contains('is-enabled')
                  );
                }""",
                timeout=10000,
            )
        except Exception:
            diag = page.evaluate(
                """() => ({
                  gdmType: typeof (navigator.mediaDevices && navigator.mediaDevices.getDisplayMedia),
                  disabled: document.getElementById('vision-capture') &&
                    document.getElementById('vision-capture').disabled,
                  title: document.getElementById('vision-capture') &&
                    document.getElementById('vision-capture').title,
                  label: document.querySelector('label.vision-file-label') &&
                    document.querySelector('label.vision-file-label').className,
                  appHidden: document.getElementById('app') && document.getElementById('app').hidden,
                  errors: window.__unused,
                })"""
            )
            raise AssertionError(f"capture affordance sync failed: {diag}; pageerrors={errors}")

        expect(page.locator("#vision-capture")).to_be_disabled()
        expect(page.locator("label.vision-file-label")).to_have_class(
            re.compile(r"\bis-enabled\b")
        )
        assert page.locator("#vision-file").is_enabled()
        intake_bg = page.locator("label.vision-file-label").evaluate(
            "el => getComputedStyle(el).backgroundColor"
        )
        # Accent green path — not the muted disabled gray (#2a4258 ≈ rgb(42,66,88)).
        assert intake_bg not in {"rgba(0, 0, 0, 0)", "transparent", "rgb(42, 66, 88)"}, intake_bg

        mint_body = json.dumps({"error": "bridge_mint_failed"})

        def fail_ack(route):
            try:
                payload = route.request.post_data_json or {}
            except Exception:
                payload = {}
            if payload.get("command") == "capture_preview_ack":
                route.fulfill(
                    status=503,
                    content_type="application/json",
                    body=mint_body,
                )
            else:
                route.continue_()

        def fail_planner(route):
            route.fulfill(
                status=503,
                content_type="application/json",
                body=mint_body,
            )

        page.route("**/api/v1/commands", fail_ack)
        page.route("**/api/v1/planner*", fail_planner)

        analyze_payload = {
            "available": True,
            "state": "ok",
            "text": "tablet-analyze-ok-independent",
            "message": None,
            "provenance": {
                "source": "image_intake",
                "host": "test",
                "captured_at": "2026-09-12T17:00:00Z",
                "model": "fixture-vlm",
                "endpoint_kind": "local",
                "endpoint_host": "127.0.0.1",
                "route": "v1/chat/completions",
            },
        }
        page.route(
            "**/api/v1/vision/analyze",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(analyze_payload),
            ),
        )
        page.route(
            "**/api/v1/vision/capability",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(
                    {
                        "capability": {
                            "image_support": "configured_unverified",
                            "verified": False,
                            "detail": "fixture",
                            "owner_summary": "Local analysis fixture",
                            "endpoint_kind": "local_chat_completions",
                            "model": "fixture-vlm",
                            "original_max_bytes": 1_500_000,
                            "inference_max_bytes": 400_000,
                        }
                    }
                ),
            ),
        )

        page.set_input_files("#vision-file", str(file_path))
        expect(page.locator("#vision-preview")).to_be_visible(timeout=10000)
        expect(page.locator("#vision-analyze")).to_be_enabled()
        expect(page.locator("#vision-save")).to_be_enabled()
        err = page.locator("#error")
        expect(err).to_be_visible()
        err_text = err.inner_text()
        assert "bridge_mint_failed" not in err_text, err_text
        assert "Workspace session could not be established" in err_text
        assert "Your image is still loaded" in err_text
        assert "reopen" not in err_text.lower()

        meta_before = page.locator("#vision-meta").inner_text()
        assert "not retained until save" in meta_before or "image_intake" in meta_before.lower() or "B raw" in meta_before

        page.locator("#vision-analyze").click(force=True)
        expect(page.locator("#vision-text")).to_contain_text(
            "tablet-analyze-ok-independent", timeout=15000
        )
        expect(page.locator("#vision-preview")).to_be_visible()
        expect(page.locator("#vision-analyze")).to_be_enabled()
        # Results preserved after independent analyze despite session mint failure.
        assert "tablet-analyze-ok-independent" in page.locator("#vision-text").inner_text()
        assert not errors, errors
        browser.close()
