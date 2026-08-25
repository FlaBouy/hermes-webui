"""Weather-card contracts for Biggy's persistent PA rail."""

from pathlib import Path

import pytest

from api import biggy_pa_sources as sources


ROOT = Path(__file__).resolve().parents[1]
BRAND = (ROOT / "static" / "biggy-brand.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "biggy-brand.css").read_text(encoding="utf-8")
ROUTES = (ROOT / "api" / "routes.py").read_text(encoding="utf-8")


def _clear_weather_state() -> None:
    with sources._LOCK:
        sources._CACHE.clear()
        sources._WEATHER_LAST_GOOD.clear()


def test_default_zip_uses_the_same_normalized_hal_weather_feed(monkeypatch):
    _clear_weather_state()

    def fake_json(url, **_kwargs):
        assert url == sources._HAL_WEATHER_URL
        return {
            "updated": "2026-08-25T08:00:00-05:00",
            "location": "Lynn Haven, FL",
            "current": {"temp": 76, "cond": "Clear"},
            "forecast": [
                {"day": day, "hi": 90, "lo": 72, "pop": 20, "short": "Sunny"}
                for day in ("Tue", "Wed", "Thu", "Fri", "Sat")
            ],
        }

    monkeypatch.setattr(sources, "_weather_json", fake_json)
    payload = sources.weather_snapshot()

    assert payload["ok"] is True
    assert payload["zip"] == "32444"
    assert payload["location"] == "Lynn Haven, FL"
    assert len(payload["forecast"]) == 5
    assert "HAL weather feed" in payload["source"]


def test_weather_snapshot_rejects_non_zip_input():
    with pytest.raises(ValueError, match="five digits"):
        sources.weather_snapshot("Auburn")


def test_refresh_failure_returns_last_good_forecast_instead_of_blank(monkeypatch):
    _clear_weather_state()
    good = {
        "schema": "biggy.pa.weather.v1",
        "ok": True,
        "zip": "32444",
        "location": "Lynn Haven, FL",
        "source": "test",
        "updated": "now",
        "current": {"temp_f": 75},
        "forecast": [{"day": "Tue", "high_f": 88, "low_f": 70, "summary": "Clear"}],
        "stale": False,
        "warning": "",
    }
    with sources._LOCK:
        sources._WEATHER_LAST_GOOD["32444"] = good
    monkeypatch.setattr(sources, "_weather_json", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("offline")))
    monkeypatch.setattr(sources, "_nws_weather", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("offline")))

    payload = sources.weather_snapshot("32444")

    assert payload["ok"] is True
    assert payload["stale"] is True
    assert payload["forecast"]
    assert "last good forecast" in payload["warning"]


def test_weather_card_is_persistent_with_zip_and_myradar_controls():
    assert "const BIGGY_DEFAULT_WEATHER_ZIP = '32444'" in BRAND
    assert 'id="biggyWeatherZip"' in BRAND
    assert 'id="biggyWeatherForecast"' in BRAND
    assert 'href="radar://open"' in BRAND
    assert "/api/biggy/pa/weather?zip=" in BRAND
    assert "renderArgusWeatherBriefing" in BRAND
    assert ".biggy-weather-forecast" in CSS


def test_weather_route_is_same_origin_and_validated_server_side():
    assert 'parsed.path == "/api/biggy/pa/weather"' in ROUTES
    assert "weather_snapshot(zip_code)" in ROUTES
