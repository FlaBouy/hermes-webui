"""VISION→Gestures observational integration (Human hand-only).

Proves: disabled default, shared lease/no extra polls, Off mid-load,
source-loss discard, browser model load + fixture inference (isolated fixture;
not shipped), cleanUI camera still feed-only.
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_TESTS_DIR = Path(__file__).resolve().parent
if str(_TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR))

POC_FIXTURE = Path(
    "/Users/rick/Documents/Codex/2026-09-11/cursor-spark-handoff/"
    "work/vision-gestures/fixtures/handtrack-egohands.jpg"
)
OUT_DIR = Path(
    "/Users/rick/Documents/Codex/2026-09-11/cursor-spark-handoff/outputs"
)

# Reuse the TD cockpit fixture (auth + lease + brand) from the camera suite.
pytest_plugins = ["test_vision_cockpit_entry_chromium"]

try:
    from playwright.sync_api import expect, sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None
    expect = None


def _require_playwright():
    if sync_playwright is None:
        pytest.skip("playwright not installed")
    return sync_playwright


def _open_authed(page, info):
    origin = info["origin"]
    page.goto(origin, wait_until="domcontentloaded")
    assert page.evaluate(
        "() => !!(window.__HERMES_CONFIG__ && window.__HERMES_CONFIG__.csrfToken)"
    )


def _open_gestures(page):
    vision = page.get_by_test_id("biggy-vision")
    expect(vision).to_be_visible(timeout=15000)
    vision.click()
    page.get_by_test_id("biggy-vision-gestures").click()
    expect(page.get_by_test_id("biggy-gestures-host")).to_be_visible(timeout=15000)
    expect(page.get_by_test_id("biggy-gestures-panel")).to_be_visible(timeout=20000)


def test_gestures_disabled_by_default_and_no_camera_activation(cockpit_td_embed_server):
    sp = _require_playwright()
    info = cockpit_td_embed_server
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
        _open_authed(page, info)
        _open_gestures(page)

        expect(page.get_by_test_id("biggy-gestures-state")).to_have_text("Off")
        expect(page.get_by_test_id("biggy-gestures-pose")).to_have_text("—")
        assert info["state"]["snaps"] == 0
        assert page.locator('[data-testid="biggy-td-camera-overlay"]').count() == 0
        # Diagnostics live under Details, not main flow.
        page.get_by_test_id("biggy-gestures-details").locator("summary").click()
        details = page.get_by_test_id("biggy-gestures-details-body").inner_text()
        assert "model_loaded=no" in details
        assert "hand_detected=no" in details

        ready = page.evaluate(
            """() => {
              const g = window.BiggyGestures && window.BiggyGestures.readiness();
              return g && {
                gesturesEnabled: g.gesturesEnabled,
                modelLoaded: g.modelLoaded,
                realHandDetected: g.realHandDetected,
                realCameraAccepted: g.realCameraAccepted,
                interpreterEnabled: g.interpreterEnabled,
                openIndependentLease: g.openIndependentLease,
                increaseRelayTraffic: g.increaseRelayTraffic,
              };
            }"""
        )
        assert ready["gesturesEnabled"] is False
        assert ready["modelLoaded"] is False
        assert ready["realHandDetected"] is False
        assert ready["realCameraAccepted"] is False
        assert ready["interpreterEnabled"] is False
        assert ready["openIndependentLease"] is False
        assert ready["increaseRelayTraffic"] is False
        browser.close()


def test_gestures_shared_lease_no_extra_polls_and_stop_clears(cockpit_td_embed_server):
    sp = _require_playwright()
    info = cockpit_td_embed_server
    with sp() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--use-gl=angle", "--use-angle=swiftshader-webgl"],
        )
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
        _open_authed(page, info)

        # Start camera first (authorized lease owner).
        page.get_by_test_id("biggy-vision").click()
        page.get_by_test_id("biggy-vision-camera").click()
        expect(page.get_by_test_id("biggy-td-camera-settings")).to_be_visible(timeout=15000)
        page.get_by_test_id("biggy-td-camera-start").click()
        expect(page.get_by_test_id("biggy-td-camera-overlay")).to_be_visible(timeout=45000)
        page.wait_for_timeout(800)
        snaps_before = info["state"]["snaps"]
        assert snaps_before >= 1
        stats_before = page.evaluate("() => window.BiggyTdCameraOverlay.frameStats()")
        assert stats_before["leaseActive"] is True
        assert stats_before["subscriberCount"] == 0

        # Open Gestures Enable — must subscribe, not open a second lease.
        page.get_by_test_id("biggy-vision").click()
        page.get_by_test_id("biggy-vision-gestures").click()
        expect(page.get_by_test_id("biggy-gestures-panel")).to_be_visible(timeout=20000)
        page.get_by_test_id("biggy-gestures-enable").click()
        page.wait_for_function(
            """() => {
              const g = window.BiggyGestures && window.BiggyGestures.readiness();
              return !!(g && g.gesturesEnabled);
            }""",
            timeout=120000,
        )
        page.wait_for_timeout(900)
        snaps_after = info["state"]["snaps"]
        stats_after = page.evaluate("() => window.BiggyTdCameraOverlay.frameStats()")
        # Traffic must not jump discontinuously (same ~5fps poll). Allow normal growth.
        assert snaps_after - snaps_before <= 12
        assert stats_after["subscriberCount"] >= 1
        assert stats_after["openIndependentLease"] is False
        assert stats_after["increaseRelayTraffic"] is False

        # Camera Stop clears gesture source without requiring Gestures Off.
        page.get_by_test_id("biggy-vision").click()
        page.get_by_test_id("biggy-vision-camera").click()
        expect(page.get_by_test_id("biggy-td-camera-settings")).to_be_visible(timeout=10000)
        page.get_by_test_id("biggy-td-camera-stop").click()
        page.wait_for_timeout(400)
        # Re-open gestures surface (still enabled) and confirm cameraAccepted cleared.
        page.get_by_test_id("biggy-vision").click()
        page.get_by_test_id("biggy-vision-gestures").click()
        page.wait_for_function(
            """() => {
              const g = window.BiggyGestures && window.BiggyGestures.readiness();
              return !!(g && g.gesturesEnabled && !g.realCameraAccepted);
            }""",
            timeout=10000,
        )
        browser.close()


def test_gestures_off_during_model_load_discards(cockpit_td_embed_server):
    sp = _require_playwright()
    info = cockpit_td_embed_server
    with sp() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--use-gl=angle", "--use-angle=swiftshader-webgl"],
        )
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
        _open_authed(page, info)
        _open_gestures(page)
        page.get_by_test_id("biggy-gestures-enable").click()
        # Immediately Off while load may still be in flight.
        page.get_by_test_id("biggy-gestures-off").click()
        page.wait_for_timeout(1500)
        ready = page.evaluate(
            """() => {
              const g = window.BiggyGestures && window.BiggyGestures.readiness();
              return g && {
                gesturesEnabled: g.gesturesEnabled,
                modelLoaded: g.modelLoaded,
                loading: g.loading,
                realHandDetected: g.realHandDetected,
              };
            }"""
        )
        assert ready["gesturesEnabled"] is False
        assert ready["loading"] is False
        assert ready["realHandDetected"] is False
        # modelLoaded may race to true then unload; final must be false after Off.
        assert ready["modelLoaded"] is False
        browser.close()


def test_gestures_browser_fixture_inference_and_screenshots(cockpit_td_embed_server):
    """Real browser Human inference on isolated fixture (not shipped to production).

    Distinguishes backend / modelLoaded / realHandDetected.
    Fixture has EgoHands content-rights caveat — test-only path.
    """
    if not POC_FIXTURE.is_file():
        pytest.skip("isolated POC fixture missing")
    sp = _require_playwright()
    info = cockpit_td_embed_server
    fixture_b64 = base64.b64encode(POC_FIXTURE.read_bytes()).decode("ascii")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with sp() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--use-gl=angle", "--use-angle=swiftshader-webgl"],
        )
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
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        _open_authed(page, info)
        _open_gestures(page)

        page.get_by_test_id("biggy-gestures-enable").click()
        page.wait_for_function(
            """() => {
              const g = window.BiggyGestures && window.BiggyGestures.readiness();
              return !!(g && g.gesturesEnabled && g.modelLoaded && !g.loading);
            }""",
            timeout=180000,
        )

        result = page.evaluate(
            """async (b64) => {
              const bin = atob(b64);
              const bytes = new Uint8Array(bin.length);
              for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
              const blob = new Blob([bytes], { type: 'image/jpeg' });
              const url = URL.createObjectURL(blob);
              const img = new Image();
              img.src = url;
              await img.decode();
              const canvas = document.createElement('canvas');
              // Keep near-native resolution — aggressive downscale drops EgoHands collage hands below detector threshold.
              canvas.width = img.naturalWidth;
              canvas.height = img.naturalHeight;
              canvas.getContext('2d').drawImage(img, 0, 0);
              URL.revokeObjectURL(url);
              const out = await window.BiggyGestures.submitTestImage(canvas, {
                label: 'poc_fixture_egohands_test_only',
              });
              const r = window.BiggyGestures.readiness();
              const obs = (out && out.observation) || (r && r.lastObservation) || {};
              return {
                accepted: out.accepted,
                reason: out.reason,
                backend: r.backend,
                modelLoaded: r.modelLoaded,
                realHandDetected: !!(obs.handCount > 0) || !!r.realHandDetected,
                realCameraAccepted: r.realCameraAccepted,
                pose: obs.primaryPose,
                confidence: obs.primaryConfidence,
                landmarkCount: obs.landmarkCount,
                status: obs.status,
                pageErrors: [],
              };
            }""",
            fixture_b64,
        )
        result["pageErrors"] = errors[:5]
        (OUT_DIR / "VISION_GESTURES_BROWSER_INFERENCE_20260912.json").write_text(
            json.dumps(
                {
                    **result,
                    "fixture": str(POC_FIXTURE),
                    "fixture_rights": (
                        "HandTrack repo MIT covers repository packaging; "
                        "EgoHands image content rights are separate — "
                        "fixture not shipped to production"
                    ),
                    "realOwnerCameraAccepted": False,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        assert result["modelLoaded"] is True
        assert result["backend"] in {"webgl", "wasm", "cpu", "tensorflow"}
        assert result["realHandDetected"] is True
        assert result["realCameraAccepted"] is False  # fixture path, not live lease
        assert result["landmarkCount"] == 21
        assert result["accepted"] is True

        # Desktop screenshot of Gestures surface (on-demand).
        page.locator('[data-testid="biggy-gestures-status-grid"]').scroll_into_view_if_needed()
        page.wait_for_timeout(100)
        page.screenshot(
            path=str(OUT_DIR / "VISION_GESTURES_desktop_20260912.png"),
            full_page=False,
        )
        # Narrow
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(200)
        page.locator('[data-testid="biggy-gestures-panel"]').scroll_into_view_if_needed()
        page.screenshot(
            path=str(OUT_DIR / "VISION_GESTURES_narrow_20260912.png"),
            full_page=False,
        )
        browser.close()


def test_gestures_preserve_clean_ui_camera_feed_only(cockpit_td_embed_server):
    """Camera Start still hides settings; gestures UI stays off the feed."""
    sp = _require_playwright()
    info = cockpit_td_embed_server
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
        _open_authed(page, info)
        page.get_by_test_id("biggy-vision").click()
        page.get_by_test_id("biggy-vision-camera").click()
        page.get_by_test_id("biggy-td-camera-start").click()
        expect(page.get_by_test_id("biggy-td-camera-overlay")).to_be_visible(timeout=45000)
        expect(page.get_by_test_id("biggy-td-camera-settings")).to_have_count(0)
        # Gestures panel must not inject controls onto the feed overlay.
        assert page.locator('#biggyTdCameraFeed [data-testid="biggy-gestures-panel"]').count() == 0
        assert page.locator('#biggyTdCameraFeed .biggy-gestures-controls').count() == 0
        browser.close()


def test_gestures_static_assets_no_fixtures_shipped():
    gestures = ROOT / "static" / "td-camera" / "gestures"
    assert (gestures / "gestures-panel.js").is_file()
    assert (gestures / "vendor" / "human-3.3.6" / "dist" / "human.esm.js").is_file()
    for name in (
        "handtrack.json",
        "handtrack.bin",
        "handlandmark-lite.json",
        "handlandmark-lite.bin",
    ):
        assert (gestures / "models" / name).is_file()
    assert not (gestures / "fixtures").exists()
    notice = (gestures / "notices" / "MODELS_NOTICE.md").read_text(encoding="utf-8")
    assert "face" in notice.lower() or "Face" in notice
