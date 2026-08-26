"""Biggy Room / Headset / Mute control and shared speech-sink contract."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess

from tests.js_source_extract import extract_function


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


def test_argus_orb_status_tracks_server_owned_alistar_playback():
    rag = RAG_API.read_text(encoding="utf-8")
    speaker = (Path.home() / "bin" / "speak_on_smedley.py").read_text(encoding="utf-8")
    brand = (ROOT / "static" / "biggy-brand.js").read_text(encoding="utf-8")

    assert "def get_public_ptt_status():" in rag
    assert "get_argus_speech_meter(" in rag
    assert 'p == "/ptt/speech-meter"' in rag
    assert 'status["phase"] = "speaking"' in rag
    assert 'status["ptt_instance"] = "biggy"' in rag
    assert 'status["speech_owner"] = "argus"' in rag
    assert 'self._json(200, get_public_ptt_status())' in rag
    assert "build_argus_audio_envelope" in speaker
    assert "on_playback_started" in speaker
    assert "clear_argus_speech_telemetry" in speaker
    assert "pollArgusSpeechMeter" in brand
    assert "requestAnimationFrame(renderArgusSpeechFrame)" in brand
    assert "setInterval(() => { pollArgusSpeechMeter().catch(() => {}); }, 400)" in brand
    assert "argusSpeechSyncGain" in brand
    assert "argusSpeechSyncLead" in brand
    assert "ARGUS_SYNC_STORAGE_KEY" in brand
    assert "status.speech_meter" not in brand
    assert "word.length / 28" not in brand


def test_argus_orb_ring_motion_remains_continuous():
    css = (ROOT / "static" / "biggy-brand.css").read_text(encoding="utf-8")
    assert "#j-orb .rot-a{animation:hudCCW 64s linear infinite;}" in css
    assert "#j-orb .rot-radar{animation:hudCW 6s linear infinite;}" in css
    assert "#j-orb .rot-a{animation-timing-function:steps" not in css


def test_argus_orb_renders_measured_audio_level_and_cleans_up():
    source = (ROOT / "static" / "biggy-brand.js").read_text(encoding="utf-8")
    functions = "\n".join(
        extract_function(source, name)
        for name in (
            "stopArgusSpeechPulse",
            "renderArgusSpeechFrame",
            "startArgusSpeechPulse",
        )
    )
    script = f"""
const vm = require('vm');
let now = 100000;
const style = {{values: {{}}, setProperty(k, v) {{ this.values[k] = String(v); }}}};
const orb = {{style}};
let frames = [];
const sandbox = {{
  console,
  Date: {{now: () => now}},
  Number,
  Math,
  Array,
  document: {{getElementById: (id) => id === 'j-orb' ? orb : null}},
  requestAnimationFrame: (fn) => {{ frames.push(fn); return frames.length; }},
  cancelAnimationFrame: () => {{}},
  argusOrbFlight: true,
  pollArgusHealth: () => Promise.resolve(),
  argusSpeechPulseFrame: null,
  argusSpeechPulseSignature: '',
  argusSpeechPulseEnvelope: [],
  argusSpeechPulseStartedAt: 0,
  argusSpeechPulseSampleMs: 40,
  argusSpeechPulseGain: 1.5,
  argusSpeechPulseLeadMs: 40,
}};
vm.createContext(sandbox);
vm.runInContext({json.dumps(functions)}, sandbox);
vm.runInContext(`startArgusSpeechPulse({{
  generation: 'speech-1', started_at: 100, sample_ms: 40,
  envelope: [0, 0.5, 1.0]
}})`, sandbox);
now = 100000;
frames.shift()();
const during = {{...style.values}};
now = 100200;
frames.shift()();
const after = {{...style.values}};
process.stdout.write(JSON.stringify({{during, after}}));
"""
    completed = subprocess.run(
        ["node", "-e", script],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)
    assert float(result["during"]["--beat"]) == 0.615
    assert float(result["during"]["--orb-scale"]) == 1.021
    assert result["after"]["--beat"] == "0"
    assert result["after"]["--orb-scale"] == "1"
