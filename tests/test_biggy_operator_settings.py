from __future__ import annotations

import json
from pathlib import Path

from api import biggy_operator_settings as settings


def test_operator_settings_are_bounded_and_durable(tmp_path, monkeypatch):
    path = tmp_path / "biggy-operator-settings.json"
    monkeypatch.setattr(settings, "_SETTINGS_PATH", path)

    assert settings.read_operator_settings()["speech_sync_gain"] == 1.1
    saved = settings.write_operator_settings({
        "speech_sync_gain": 1.37,
        "speech_sync_lead_ms": -999,
    })

    assert saved["speech_sync_gain"] == 1.37
    assert saved["speech_sync_lead_ms"] == -250
    assert settings.read_operator_settings() == saved
    assert json.loads(path.read_text(encoding="utf-8"))["schema"] == "biggy.operator_settings.v1"


def test_biggy_sync_controls_use_server_and_browser_persistence():
    root = Path(__file__).resolve().parents[1]
    brand = (root / "static" / "biggy-brand.js").read_text(encoding="utf-8")
    routes = (root / "api" / "routes.py").read_text(encoding="utf-8")

    assert "operatorFetch('/api/biggy/operator-settings')" in brand
    assert "speech_sync_gain: argusSpeechPulseGain" in brand
    assert 'parsed.path == "/api/biggy/operator-settings"' in routes
