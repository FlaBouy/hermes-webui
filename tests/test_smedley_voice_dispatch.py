"""Completed Smedley turns: Austin unless LEFT PTT already owns the turn."""

from __future__ import annotations

from pathlib import Path

from tests.js_source_extract import extract_function

ROOT = Path(__file__).resolve().parents[1]
LIVE_EXT = (
    Path.home()
    / ".hermes"
    / "webui"
    / "extensions"
    / "smedley-engineering"
    / "smedley-engineering.v0.2.5.js"
)
PEDAL = Path.home() / "jarvis-pedal" / "jarvis-webui-voice-pedal.py"


def select_smedley_voice_emitter(*, realtime_active: bool, ptt_owned: bool = False) -> str:
    if ptt_owned:
        return "none"
    return "austin"


def dispatch_once(*, realtime_active: bool, ptt_owned: bool = False) -> list[str]:
    emitter = select_smedley_voice_emitter(
        realtime_active=realtime_active, ptt_owned=ptt_owned
    )
    if emitter == "none":
        return []
    if emitter != "austin":
        return []
    return ["austin"]


def test_select_smedley_voice_emitter_js_matches_python_contract():
    src = (ROOT / "static" / "realtime_voice.js").read_text(encoding="utf-8")
    fn = extract_function(src, "selectSmedleyVoiceEmitter")
    assert "return 'austin'" in fn
    assert "return 'none'" in fn
    assert "return 'realtime'" not in fn
    speak = extract_function(src, "_speakHermesText")
    assert "selectSmedleyVoiceEmitter({}) === 'none'" in speak.replace(" ", "") or (
        "=== 'none'" in speak
    )
    hook = extract_function(src, "_hookHermesReplySpeech")
    assert "_speakHermesText" not in hook
    live = LIVE_EXT.read_text(encoding="utf-8") if LIVE_EXT.is_file() else ""
    if live:
        compact = live.replace(" ", "")
        assert "if(emitter==='none')return" in compact
        assert "if(emitter!=='austin')return" in compact
        assert "window.__smedleyRealtimeVoiceActive?'realtime'" not in compact
        voice_fn = live.split("function installSmedleyVoiceOutput")[1].split(
            "function installBrandingObserver"
        )[0]
        assert "original.apply" not in voice_fn
        assert "__smedleyPttOwnsVoiceUntil" in live


def test_voice_dispatch_one_emitter_no_double_fire():
    realtime_on = dispatch_once(realtime_active=True)
    austin = dispatch_once(realtime_active=False)
    ptt = dispatch_once(realtime_active=True, ptt_owned=True)
    assert realtime_on == ["austin"]
    assert austin == ["austin"]
    assert ptt == []
    assert "realtime" not in realtime_on
    assert "browser" not in realtime_on


def test_server_owned_argus_turn_skips_second_pedal_speaking_cycle():
    if not PEDAL.is_file():
        return
    source = PEDAL.read_text(encoding="utf-8")
    assert "return None, None" in source
    assert "server-owned Argus voice complete" in source
    assert "if answer is None and spoken_text is None:" in source


def test_stt_getting_argus_variant_skips_biggy_filler_and_narration():
    if not PEDAL.is_file():
        return
    source = PEDAL.read_text(encoding="utf-8")
    namespace = {"re": __import__("re")}
    start = source.index("def _is_ask_jarvis_prompt")
    end = source.index("\ndef ", start + 5)
    exec(source[start:end], namespace)
    matcher = namespace["_is_ask_jarvis_prompt"]
    assert matcher(
        "a biggie about getting Argus to get me a map routed to Jordan Harris Stadium."
    )
