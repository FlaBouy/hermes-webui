"""Owner-ACK proxy contracts + Biggy must not render Approvals UI."""

from __future__ import annotations

import re
from pathlib import Path

import api.owner_ack_proxy as proxy


ROOT = Path(__file__).resolve().parents[1]
BIGGY_JS = (ROOT / "static" / "biggy-brand.js").read_text(encoding="utf-8")
BIGGY_CSS = (ROOT / "static" / "biggy-brand.css").read_text(encoding="utf-8")
ROUTES = (ROOT / "api" / "routes.py").read_text(encoding="utf-8")


def test_bridge_base_defaults_loopback(monkeypatch):
    monkeypatch.delenv("HERMES_WEBUI_OWNER_ACK_BRIDGE_URL", raising=False)
    monkeypatch.delenv("OWNER_ACK_BRIDGE_URL", raising=False)
    assert proxy.bridge_base_url() == "http://127.0.0.1:8791"


def test_bridge_url_rejects_public_host(monkeypatch):
    monkeypatch.setenv("HERMES_WEBUI_OWNER_ACK_BRIDGE_URL", "http://example.com:8791")
    status = proxy.bridge_status()
    assert status["ok"] is False
    assert "not loopback/private" in status["error"]


def test_upstream_path_allowlist():
    assert proxy._upstream_path("/api/owner-ack/health") == "/v1/health"
    assert proxy._upstream_path("/v1/health") == "/v1/health"
    assert proxy._upstream_path("/v1/owner-ack") == "/v1/owner-ack"
    assert proxy._upstream_path("/v1/owner-ack/abc/approve") == "/v1/owner-ack/abc/approve"
    assert proxy._upstream_path("/v1/admin") is None
    assert proxy._upstream_path("/api/owner-ack/../secret") is None


def test_proxy_request_fail_closed_on_bad_url(monkeypatch):
    monkeypatch.setenv("HERMES_WEBUI_OWNER_ACK_BRIDGE_URL", "http://8.8.8.8:8791")
    code, body = proxy.proxy_request(method="GET", path="/v1/health")
    assert code == 503
    assert body["ok"] is False


def test_routes_wire_owner_ack_proxy_for_non_gui_consumers():
    # Server proxy remains for propose/handoff tooling; Biggy GUI must not poll it.
    assert 'parsed.path == "/api/owner-ack"' in ROUTES
    assert "_handle_owner_ack_proxy" in ROUTES


def test_biggy_feature_config_disables_approvals():
    assert "approvalsEnabled: false" in BIGGY_JS
    assert "const FEATURES = Object.freeze({" in BIGGY_JS
    assert "__BIGGY_FEATURES__" in BIGGY_JS


def test_biggy_source_has_no_approvals_widget_or_polling():
    forbidden = [
        "installOwnerAckPanel",
        "ensureOwnerAckPanel",
        "refreshOwnerAckPanel",
        "ownerAckFetch",
        "OWNER_ACK_PROXY",
        "OWNER ACK REQUIRED",
        "No approvals pending",
        "/api/owner-ack",
        "127.0.0.1:8791",
        "setInterval(() => { refreshOwnerAckPanel",
        "biggy-owner-ack-title",
        "biggy-owner-ack-count",
        "biggy-owner-ack-bridge",
    ]
    for token in forbidden:
        assert token not in BIGGY_JS, f"Biggy still contains approvals token: {token}"
    # Creation markup must not exist (legacy purge may still name the old id).
    assert "OWNER ACK REQUIRED" not in BIGGY_JS
    assert ">Approvals<" not in BIGGY_JS
    assert "No approvals pending" not in BIGGY_JS
    assert "purgeOwnerAckArtifacts" in BIGGY_JS
    assert "biggy-owner-ack" not in BIGGY_CSS
    # Must not poll/fetch approvals.
    assert re.search(r"fetch\([^)]*owner-ack", BIGGY_JS, re.I) is None
    assert re.search(r"api\([^)]*owner-ack", BIGGY_JS, re.I) is None


def test_biggy_dom_contract_no_approval_widget_markup():
    """Static DOM contract: Biggy brand never emits approval/ack widget markup."""
    # No live widget copy or create-path markup.
    assert "OWNER ACK REQUIRED" not in BIGGY_JS
    assert "No approvals pending" not in BIGGY_JS
    assert "bridge ok:" not in BIGGY_JS
    assert "ensureOwnerAckPanel" not in BIGGY_JS
    assert "innerHTML =" not in BIGGY_JS or "biggy-owner-ack-head" not in BIGGY_JS
    assert "biggy-owner-ack-head" not in BIGGY_JS
    assert "data-approval-widget" not in BIGGY_JS or "purgeOwnerAckArtifacts" in BIGGY_JS
    # Coordinator surfaces that must remain.
    assert "installPttBridge" in BIGGY_JS
    assert "Biggy Voice" in BIGGY_JS
    assert "biggyPtt" in BIGGY_JS
    assert "approvalsEnabled: false" in BIGGY_JS


def test_smedley_approvals_config_is_independent():
    smedley = Path.home() / ".hermes/webui/extensions/smedley-engineering/smedley-engineering.v0.2.5.js"
    if not smedley.exists():
        return
    text = smedley.read_text(encoding="utf-8", errors="ignore")
    assert "__SMEDLEY_FEATURES__" in text
    assert "approvalsEnabled" in text
    # No Biggy Approvals panel leaked into Smedley.
    assert "biggyOwnerAckPanel" not in text
    assert "No approvals pending" not in text
