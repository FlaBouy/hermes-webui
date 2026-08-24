"""Biggy Room / Headset / Mute control and shared speech-sink contract."""

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROUTE_STATE = Path.home() / "bin" / "ptt_audio_route.py"
RAG_API = Path.home() / "bin" / "smedley-rag-api.py"
PEDAL = Path.home() / "jarvis-pedal" / "jarvis-webui-voice-pedal.py"


def _load_route_module():
    spec = importlib.util.spec_from_file_location("biggy_test_ptt_audio_route", ROUTE_STATE)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_mute_persists_without_losing_physical_route(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_PTT_AUDIO_ROUTE_STATE", str(tmp_path / "route.json"))
    route = _load_route_module()

    route.set_desired_route("headset")
    muted = route.set_output_muted(True)
    status = route.build_public_route_status(
        active_route="headset", headset_available=True
    )

    assert muted["desired_route"] == "headset"
    assert muted["output_muted"] is True
    assert status["active_route"] == "headset"
    assert status["desired_route"] == "headset"
    assert status["output_muted"] is True

    unmuted = route.set_desired_route("room")
    assert unmuted["output_muted"] is False
    assert route.get_output_muted() is False


def test_biggy_control_cycles_room_headset_mute_and_marks_mute():
    source = (ROOT / "static" / "biggy-brand.js").read_text(encoding="utf-8")
    css = (ROOT / "static" / "biggy-brand.css").read_text(encoding="utf-8")

    assert "const muted = !!status.output_muted" in source
    assert "active === 'headset' ? 'mute' : 'headset'" in source
    assert "muted ? 'room'" in source
    assert "routeBtn.textContent = muted ? 'MUTE'" in source
    assert "Biggy and A.R.G.U.S. speech muted." in source
    assert ".biggy-brand-controls button.muted" in css


def test_shared_speech_planes_fail_silent_while_muted():
    rag = RAG_API.read_text(encoding="utf-8")
    pedal = PEDAL.read_text(encoding="utf-8")

    assert 'if get_output_muted():' in rag
    assert '{"status": "muted"' in rag
    assert 'if route == "mute":' in rag
    assert "stop_speak_async()" in rag
    assert "if speech_cancelled.is_set() or _output_muted():" in pedal
    assert "output_muted_before_playback" in pedal
    assert "playback_stop.set()" in pedal
