"""Contracts for Biggy's Google-primary, Twilio-fallback phone cockpit."""

import json
from pathlib import Path

import pytest

from api import biggy_phone


ROOT = Path(__file__).resolve().parents[1]
BRAND = (ROOT / "static" / "biggy-brand.js").read_text(encoding="utf-8")


def _config(tmp_path: Path, **overrides) -> Path:
    payload = {
        "device_label": "Galaxy S25 Ultra",
        "carrier": "Verizon",
        "account_sid": "AC1234567890",
        "auth_token": "secret-token",
        "from_number": "+18505550100",
        "twilio_sms_enabled": True,
        "voice_url": "https://example.invalid/twiml",
        "bridge_device_number": "+18505550199",
    }
    payload.update(overrides)
    path = tmp_path / "biggy-phone.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_phone_is_disconnected_without_profile_config(tmp_path, monkeypatch):
    monkeypatch.setattr(biggy_phone, "_PROFILE_CONFIG", tmp_path / "missing.json")
    monkeypatch.setattr("api.google_messages_bridge.google_messages_status", lambda: {"ready": False, "paired": False, "connected": False, "detail": "not paired"})
    status = biggy_phone.phone_status()
    assert status["state"] == "disconnected"
    assert status["connected"] is False
    assert status["device_label"] == "Galaxy S25 Ultra"
    assert status["carrier"] == "Verizon"
    assert "auth_token" not in json.dumps(status)


def test_phone_status_never_exposes_twilio_secret(tmp_path, monkeypatch):
    monkeypatch.setattr(biggy_phone, "_PROFILE_CONFIG", _config(tmp_path, contacts={
        "EGS": [{"name": "Dispatch", "number": "(850) 555-0102"}],
        "Personal": [{"name": "Rick", "number": "+18505550103"}],
    }))
    monkeypatch.setattr("api.google_messages_bridge.google_messages_status", lambda: {"ready": True, "paired": True, "connected": True, "detail": "connected"})
    status = biggy_phone.phone_status()
    rendered = json.dumps(status)
    assert status["state"] == "ready"
    assert status["connected"] is True
    assert status["sms_primary"] == "google_messages"
    assert status["sms_transport"] == "google_messages"
    assert status["twilio_fallback_ready"] is True
    assert "secret-token" not in rendered
    assert "account_sid" not in rendered
    assert status["contacts"] == {
        "EGS": [{"name": "Dispatch", "number": "+18505550102"}],
        "Personal": [{"name": "Rick", "number": "+18505550103"}],
    }


def test_sms_requires_explicit_confirmation(tmp_path, monkeypatch):
    monkeypatch.setattr(biggy_phone, "_PROFILE_CONFIG", _config(tmp_path))
    with pytest.raises(PermissionError, match="confirmation"):
        biggy_phone.send_sms({"to": "+18505550101", "body": "Test", "confirmed": False})


def test_call_requires_explicit_confirmation(tmp_path, monkeypatch):
    monkeypatch.setattr(biggy_phone, "_PROFILE_CONFIG", _config(tmp_path))
    with pytest.raises(PermissionError, match="confirmation"):
        biggy_phone.start_call({"to": "+18505550101", "confirmed": False})


def test_confirmed_sms_uses_google_messages_primary(tmp_path, monkeypatch):
    monkeypatch.setattr(biggy_phone, "_PROFILE_CONFIG", _config(tmp_path))
    captured = {}

    def fake_google(to, body):
        captured.update(to=to, body=body)
        return {"ok": True, "transport": "google_messages", "status": "submitted"}

    monkeypatch.setattr("api.google_messages_bridge.send_google_message", fake_google)
    result = biggy_phone.send_sms({"to": "(850) 555-0101", "body": "Test", "confirmed": True})

    assert result == {"schema": "biggy.phone.sms.v1", "ok": True, "transport": "google_messages", "status": "submitted"}
    assert captured == {"to": "+18505550101", "body": "Test"}


def test_confirmed_sms_falls_back_to_twilio(tmp_path, monkeypatch):
    monkeypatch.setattr(biggy_phone, "_PROFILE_CONFIG", _config(tmp_path))
    captured = {}

    def failed_google(_to, _body):
        raise RuntimeError("not paired")

    def fake_request(cfg, resource, *, method="GET", data=None):
        captured.update(resource=resource, method=method, data=data)
        return {"sid": "SM123", "status": "queued"}

    monkeypatch.setattr("api.google_messages_bridge.send_google_message", failed_google)
    monkeypatch.setattr(biggy_phone, "_twilio_request", fake_request)
    result = biggy_phone.send_sms({"to": "(850) 555-0101", "body": "Test", "confirmed": True})

    assert result == {
        "schema": "biggy.phone.sms.v1",
        "ok": True,
        "transport": "twilio_fallback",
        "sid": "SM123",
        "status": "queued",
        "primary_error": "not paired",
    }
    assert captured == {
        "resource": "Messages.json",
        "method": "POST",
        "data": {"To": "+18505550101", "From": "+18505550100", "Body": "Test"},
    }


def test_twilio_fallback_is_blocked_until_carrier_registration_is_active(tmp_path, monkeypatch):
    monkeypatch.setattr(biggy_phone, "_PROFILE_CONFIG", _config(
        tmp_path,
        twilio_sms_enabled=False,
        twilio_sms_block_reason="A2P registration pending (Twilio 30034).",
    ))
    monkeypatch.setattr("api.google_messages_bridge.google_messages_status", lambda: {
        "ready": False, "paired": False, "connected": False, "detail": "not paired",
    })

    def failed_google(_to, _body):
        raise RuntimeError("not paired")

    monkeypatch.setattr("api.google_messages_bridge.send_google_message", failed_google)
    status = biggy_phone.phone_status()
    assert status["sms_ready"] is False
    assert status["voice_ready"] is True
    assert status["twilio_configured"] is True
    assert status["twilio_fallback_ready"] is False
    assert "30034" in status["twilio_fallback_detail"]
    with pytest.raises(RuntimeError, match="fallback is blocked"):
        biggy_phone.send_sms({"to": "+18505550101", "body": "Test", "confirmed": True})


def test_confirmed_call_uses_click_to_call_bridge(tmp_path, monkeypatch):
    monkeypatch.setattr(biggy_phone, "_PROFILE_CONFIG", _config(tmp_path))
    captured = {}

    def fake_request(cfg, resource, *, method="GET", data=None):
        captured.update(resource=resource, method=method, data=data)
        return {"sid": "CA123", "status": "queued"}

    monkeypatch.setattr(biggy_phone, "_twilio_request", fake_request)
    result = biggy_phone.start_call({"to": "+18505550101", "confirmed": True})

    assert result == {"schema": "biggy.phone.call.v1", "ok": True, "transport": "twilio_click_to_call", "sid": "CA123", "status": "queued"}
    assert captured == {
        "resource": "Calls.json",
        "method": "POST",
        "data": {
            "To": "+18505550199",
            "From": "+18505550100",
            "Twiml": '<Response><Say>Connecting your call.</Say><Dial callerId="+18505550100"><Number>+18505550101</Number></Dial></Response>',
        },
    }


def test_phone_rail_sits_directly_below_filter():
    categories = BRAND[BRAND.index("const TRAVEL_CATEGORIES"):]
    assert categories.index("'Filter'") < categories.index("'Phone'") < categories.index("'Travel'")
    assert 'data-biggy-operator-panel="phone"' in BRAND
    assert "/api/biggy/phone/status" in BRAND
    assert "/api/biggy/phone/history" in BRAND
    assert "/api/biggy/phone/sms/send" in BRAND
    assert "/api/biggy/phone/call/start" in BRAND
    assert "Galaxy S25 Ultra" in BRAND
    assert "Verizon" in BRAND
    assert "window.confirm(`Send this text" in BRAND
    assert "window.confirm(`Call ${to}" in BRAND
    assert "renderPhoneContacts(panel, phone, [sms, call])" in BRAND
    assert "['EGS', 'Personal']" in BRAND
    assert "openPhoneContactCard(panel, label, contacts, forms)" in BRAND
    assert "biggy-phone-contact-card" in BRAND
    assert "Back to Phone" in BRAND
    assert "Google Messages is primary" in BRAND
    assert "Twilio fallback" in BRAND
    assert "const primaryView = Array.from(panel.childNodes)" in BRAND
