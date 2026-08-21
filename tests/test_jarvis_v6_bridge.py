"""Jarvis V6 bridge: loopback allowlist, honest offline/error, no secrets in tree."""

from __future__ import annotations

from pathlib import Path
from urllib.error import URLError

import api.jarvis_v6_bridge as bridge


ROOT = Path(__file__).resolve().parents[1]
BIGGY_JS = (ROOT / "static" / "biggy-brand.js").read_text(encoding="utf-8")
ROUTES = (ROOT / "api" / "routes.py").read_text(encoding="utf-8")


def test_allowlist_is_narrow():
    assert ("GET", "/api/model") in bridge.ALLOWED_UPSTREAM
    assert ("GET", "/api/status") in bridge.ALLOWED_UPSTREAM
    assert ("POST", "/chat") in bridge.ALLOWED_UPSTREAM
    assert ("POST", "/task") not in bridge.ALLOWED_UPSTREAM
    assert ("GET", "/api/inbox") not in bridge.ALLOWED_UPSTREAM


def test_non_loopback_base_is_rejected():
    jb = bridge.JarvisBridge(base_url="http://192.168.0.15:4719")
    payload, status = jb.health()
    assert status == 503
    assert payload["state"] == "error"
    assert "loopback" in str(payload["error"]).lower()


def test_health_offline_on_connection_refused(monkeypatch):
    def boom(*_a, **_k):
        raise URLError("Connection refused")

    monkeypatch.setattr(bridge, "urlopen", boom)
    jb = bridge.JarvisBridge(base_url="http://127.0.0.1:4719")
    payload, status = jb.health()
    assert status == 200
    assert payload["online"] is False
    assert payload["state"] == "offline"
    assert "unreachable" in str(payload["error"]).lower() or "offline" in str(payload["error"]).lower()


def test_chat_empty_question():
    payload, status = bridge.JarvisBridge().chat("   ")
    assert status == 400
    assert payload["ok"] is False


def test_slim_context_keeps_only_visible_envelope():
    out = bridge.slim_context(
        {
            "project_id": "p1",
            "display_name": "Brewton",
            "workspace_name": "Biggy",
            "synopsis": "visible",
            "vault_path": "/secret",
            "api_key": "nope",
            "files": ["a.py"],
        }
    )
    assert out == {
        "project_id": "p1",
        "display_name": "Brewton",
        "workspace_name": "Biggy",
        "synopsis": "visible",
    }


def test_browser_source_never_calls_v6_port_directly():
    assert "4719" not in BIGGY_JS
    assert "/api/biggy/v6/health" in BIGGY_JS
    assert "/api/biggy/v6/chat" in BIGGY_JS


def test_routes_wire_bridge_endpoints():
    assert "/api/biggy/v6/health" in ROUTES
    assert "/api/biggy/v6/chat" in ROUTES
    assert "JarvisBridge" in ROUTES


def test_gitignore_covers_local_bridge_config():
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "jarvis-v6-bridge.local.json" in gi
    assert "config.json" in gi
