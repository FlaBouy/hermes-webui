"""Contracts for Biggy's profile-local Twilio phone cockpit."""

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
        "voice_url": "https://example.invalid/twiml",
    }
    payload.update(overrides)
    path = tmp_path / "biggy-phone.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_phone_is_disconnected_without_profile_config(tmp_path, monkeypatch):
    monkeypatch.setattr(biggy_phone, "_PROFILE_CONFIG", tmp_path / "missing.json")
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
    status = biggy_phone.phone_status()
    rendered = json.dumps(status)
    assert status["state"] == "ready"
    assert status["connected"] is True
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


def test_confirmed_sms_uses_twilio_seam(tmp_path, monkeypatch):
    monkeypatch.setattr(biggy_phone, "_PROFILE_CONFIG", _config(tmp_path))
    captured = {}

    def fake_request(cfg, resource, *, method="GET", data=None):
        captured.update(resource=resource, method=method, data=data)
        return {"sid": "SM123", "status": "queued"}

    monkeypatch.setattr(biggy_phone, "_twilio_request", fake_request)
    result = biggy_phone.send_sms({"to": "(850) 555-0101", "body": "Test", "confirmed": True})

    assert result == {"schema": "biggy.phone.sms.v1", "ok": True, "sid": "SM123", "status": "queued"}
    assert captured == {
        "resource": "Messages.json",
        "method": "POST",
        "data": {"To": "+18505550101", "From": "+18505550100", "Body": "Test"},
    }


def test_confirmed_call_uses_configured_twiml_url(tmp_path, monkeypatch):
    monkeypatch.setattr(biggy_phone, "_PROFILE_CONFIG", _config(tmp_path))
    captured = {}

    def fake_request(cfg, resource, *, method="GET", data=None):
        captured.update(resource=resource, method=method, data=data)
        return {"sid": "CA123", "status": "queued"}

    monkeypatch.setattr(biggy_phone, "_twilio_request", fake_request)
    result = biggy_phone.start_call({"to": "+18505550101", "confirmed": True})

    assert result == {"schema": "biggy.phone.call.v1", "ok": True, "sid": "CA123", "status": "queued"}
    assert captured == {
        "resource": "Calls.json",
        "method": "POST",
        "data": {
            "To": "+18505550101",
            "From": "+18505550100",
            "Url": "https://example.invalid/twiml",
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
    assert "const primaryView = Array.from(panel.childNodes)" in BRAND
