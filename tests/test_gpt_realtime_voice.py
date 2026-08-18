"""GPT Realtime Voice — ephemeral session minting (Hermes remains chat authority)."""

from __future__ import annotations

import io
import json
from urllib.error import HTTPError

import api.realtime_voice as realtime_voice


class _FakeHandler:
    def __init__(self, command="GET", body=b"{}"):
        self.command = command
        self.rfile = io.BytesIO(body)
        self.wfile = io.BytesIO()
        self.headers = {"Content-Type": "application/json", "Content-Length": str(len(body))}
        self.status = None
        self.sent_headers = {}

    def send_response(self, status):
        self.status = status

    def send_header(self, key, value):
        self.sent_headers[key] = value

    def end_headers(self):
        pass

    def payload(self):
        return json.loads(self.wfile.getvalue().decode("utf-8"))


def test_realtime_status_reports_disabled_without_key(monkeypatch):
    monkeypatch.delenv("HERMES_WEBUI_GPT_REALTIME_VOICE", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("VOICE_TOOLS_OPENAI_KEY", raising=False)
    monkeypatch.delenv("HERMES_OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(realtime_voice, "resolve_openai_api_key", lambda: "")
    status = realtime_voice.realtime_voice_status()
    assert status["ok"] is True
    assert status["enabled"] is False
    assert status["api_key_configured"] is False
    assert "value" not in status


def test_realtime_status_enabled_when_key_present(monkeypatch):
    monkeypatch.delenv("HERMES_WEBUI_GPT_REALTIME_VOICE", raising=False)
    monkeypatch.setattr(realtime_voice, "resolve_openai_api_key", lambda: "sk-test")
    status = realtime_voice.realtime_voice_status()
    assert status["enabled"] is True
    assert status["api_key_configured"] is True


def test_env_kill_switch_disables_feature(monkeypatch):
    monkeypatch.setenv("HERMES_WEBUI_GPT_REALTIME_VOICE", "0")
    monkeypatch.setattr(realtime_voice, "resolve_openai_api_key", lambda: "sk-test")
    assert realtime_voice.realtime_voice_env_enabled() is False
    status = realtime_voice.realtime_voice_status()
    assert status["enabled"] is False
    assert status["env_enabled"] is False


def test_create_ephemeral_fails_closed_without_key(monkeypatch):
    monkeypatch.delenv("HERMES_WEBUI_GPT_REALTIME_VOICE", raising=False)
    monkeypatch.setattr(realtime_voice, "resolve_openai_api_key", lambda: "")
    try:
        realtime_voice.create_ephemeral_client_secret()
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "API key" in str(exc)


def test_create_ephemeral_returns_value_only(monkeypatch):
    monkeypatch.delenv("HERMES_WEBUI_GPT_REALTIME_VOICE", raising=False)
    monkeypatch.setattr(realtime_voice, "resolve_openai_api_key", lambda: "sk-permanent-secret")

    class _Resp:
        status = 200

        def read(self):
            return json.dumps(
                {
                    "value": "ek_ephemeral_only",
                    "expires_at": 123,
                    "session": {"type": "realtime", "model": "gpt-realtime"},
                }
            ).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    captured = {}

    def _urlopen(req, timeout=20):
        captured["url"] = req.full_url
        headers = {k.lower(): v for k, v in req.header_items()}
        captured["auth"] = headers.get("authorization")
        captured["safety"] = headers.get("openai-safety-identifier")
        body = req.data.decode("utf-8")
        captured["body"] = json.loads(body)
        return _Resp()

    monkeypatch.setattr(realtime_voice.urllib.request, "urlopen", _urlopen)
    out = realtime_voice.create_ephemeral_client_secret(safety_seed="cookie.sig")
    assert out["ok"] is True
    assert out["value"] == "ek_ephemeral_only"
    assert out["expires_at"] == 123
    assert "sk-permanent-secret" not in json.dumps(out)
    assert captured["url"].endswith("/v1/realtime/client_secrets")
    assert captured["auth"] == "Bearer sk-permanent-secret"
    assert captured["safety"]
    session = captured["body"]["session"]
    assert session["type"] == "realtime"
    # GA schema nests turn detection under audio.input; a top-level
    # session.turn_detection is rejected with unknown_parameter.
    assert "turn_detection" not in session
    turn_detection = session["audio"]["input"]["turn_detection"]
    assert turn_detection["type"] == "server_vad"
    assert turn_detection["create_response"] is False
    assert turn_detection["silence_duration_ms"] == 10000
    assert session["audio"]["input"]["transcription"]["model"] == "gpt-4o-mini-transcribe"
    assert "Hermes" in session["instructions"]


def test_create_ephemeral_maps_upstream_http_error(monkeypatch):
    monkeypatch.delenv("HERMES_WEBUI_GPT_REALTIME_VOICE", raising=False)
    monkeypatch.setattr(realtime_voice, "resolve_openai_api_key", lambda: "sk-test")

    def _urlopen(req, timeout=20):
        raise HTTPError(req.full_url, 500, "nope", hdrs=None, fp=io.BytesIO(b'{"error":"bad"}'))

    monkeypatch.setattr(realtime_voice.urllib.request, "urlopen", _urlopen)
    try:
        realtime_voice.create_ephemeral_client_secret()
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "failed" in str(exc).lower()
        assert realtime_voice.error_category(exc) == "session"


def test_upstream_400_reports_configuration_category(monkeypatch):
    """A rejected session config is an operator config problem, not a retry."""
    monkeypatch.delenv("HERMES_WEBUI_GPT_REALTIME_VOICE", raising=False)
    monkeypatch.setattr(realtime_voice, "resolve_openai_api_key", lambda: "sk-test")

    body = json.dumps(
        {"error": {"message": "Unknown parameter: 'session.turn_detection'."}}
    ).encode("utf-8")

    def _urlopen(req, timeout=20):
        raise HTTPError(req.full_url, 400, "bad", hdrs=None, fp=io.BytesIO(body))

    monkeypatch.setattr(realtime_voice.urllib.request, "urlopen", _urlopen)
    try:
        realtime_voice.create_ephemeral_client_secret()
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert realtime_voice.error_category(exc) == "configuration"
        assert "Unknown parameter" in str(exc)


def test_missing_key_reports_configuration_category(monkeypatch):
    monkeypatch.delenv("HERMES_WEBUI_GPT_REALTIME_VOICE", raising=False)
    monkeypatch.setattr(realtime_voice, "resolve_openai_api_key", lambda: "")
    try:
        realtime_voice.create_ephemeral_client_secret()
        assert False, "expected ValueError"
    except ValueError as exc:
        assert realtime_voice.error_category(exc) == "configuration"


def test_routes_status_and_session_gate(monkeypatch):
    from api import routes
    import api.config as config_mod
    import api.realtime_voice as rv_mod

    monkeypatch.setattr(routes, "_realtime_voice_auth_ok", lambda handler: True)
    monkeypatch.setattr(
        rv_mod,
        "realtime_voice_status",
        lambda: {"ok": True, "enabled": False, "api_key_configured": False},
    )

    handler = _FakeHandler("GET")
    routes._handle_realtime_voice_status(handler)
    assert handler.status == 200
    assert handler.payload()["enabled"] is False

    monkeypatch.setattr(config_mod, "load_settings", lambda: {"gpt_realtime_voice": False})
    handler2 = _FakeHandler("POST")
    routes._handle_realtime_voice_session(handler2)
    assert handler2.status == 403
    assert handler2.payload()["category"] == "configuration"

    monkeypatch.setattr(config_mod, "load_settings", lambda: {"gpt_realtime_voice": True})
    monkeypatch.setattr(
        rv_mod,
        "create_ephemeral_client_secret",
        lambda **kwargs: {"ok": True, "value": "ek_test"},
    )
    handler3 = _FakeHandler("POST")
    routes._handle_realtime_voice_session(handler3)
    assert handler3.status == 200
    assert handler3.payload()["value"] == "ek_test"
    assert "sk-" not in json.dumps(handler3.payload())


def test_session_route_forwards_failure_category(monkeypatch):
    """A failed mint must name the failing layer, not just 'error'."""
    from api import routes
    import api.config as config_mod
    import api.realtime_voice as rv_mod

    monkeypatch.setattr(routes, "_realtime_voice_auth_ok", lambda handler: True)
    monkeypatch.setattr(config_mod, "load_settings", lambda: {"gpt_realtime_voice": True})

    def _raise_config(**kwargs):
        raise rv_mod.RealtimeConfigError("OpenAI API key not configured")

    monkeypatch.setattr(rv_mod, "create_ephemeral_client_secret", _raise_config)
    handler = _FakeHandler("POST")
    routes._handle_realtime_voice_session(handler)
    assert handler.status == 503
    assert handler.payload()["category"] == "configuration"

    def _raise_upstream(**kwargs):
        raise rv_mod.RealtimeUpstreamError("OpenAI Realtime session create failed (500)")

    monkeypatch.setattr(rv_mod, "create_ephemeral_client_secret", _raise_upstream)
    handler2 = _FakeHandler("POST")
    routes._handle_realtime_voice_session(handler2)
    assert handler2.status == 502
    assert handler2.payload()["category"] == "session"


def test_client_reports_error_categories():
    """The browser client must label failures by category and use showToast."""
    js = open("static/realtime_voice.js", encoding="utf-8").read()
    for category in ("configuration", "permission", "session", "webrtc"):
        assert f"'{category}'" in js or f'"{category}"' in js
    # showToast is the real global in this codebase; a bare toast() is a no-op.
    assert "showToast" in js
    assert "typeof toast === 'function'" not in js
    # An error must still render after teardown sets active=false.
    assert "phase !== 'error'" in js
    assert "connectionstatechange" in js


def _voice_client_js():
    return open("static/realtime_voice.js", encoding="utf-8").read()


def test_insecure_origin_is_reported_before_capability_probe():
    """Browsers delete navigator.mediaDevices on http:// origins.

    Probing capability first misreports a plain-HTTP page (for example a
    Tailscale IP) as an unsupported browser, sending the operator to debug the
    wrong layer.
    """
    js = _voice_client_js()
    secure_at = js.index("if (!window.isSecureContext)")
    probe_at = js.index("if (!_webrtcSupported())")
    assert secure_at < probe_at
    # The message names the offending origin so the fix is obvious.
    assert "location.origin" in js
    assert "gpt_voice_insecure_context" in js


def test_mic_constraints_request_echo_cancellation():
    js = _voice_client_js()
    assert "echoCancellation: true" in js
    assert "noiseSuppression: true" in js
    assert "autoGainControl: true" in js


def test_playback_guard_blocks_self_reply_loop():
    """Playback must never be re-captured as a new Hermes turn.

    Without the guard the model hears its own spoken reply, transcribes it,
    and drives an endless self-reply loop.
    """
    js = _voice_client_js()
    # Mic is hard-muted at the track level rather than merely ignored.
    assert "getAudioTracks" in js
    assert "track.enabled" in js
    # Speaking closes the capture window before any audio is emitted.
    assert "_closeCapture();\n    _setPhase('speaking');" in js
    # Transcripts arriving outside an open window are dropped, and playback and
    # Hermes processing are both excluded explicitly.
    assert "if (!STATE.captureOpen) return;" in js
    assert "if (STATE.phase === 'speaking' || STATE.phase === 'processing') return;" in js
    # Buffered input is invalidated when playback or processing begins.
    assert (
        "if (phase === 'speaking' || phase === 'processing' || !STATE.active) _closeCapture();"
        in js
    )
    # Re-arm is deferred so speaker decay cannot retrigger VAD.
    assert "MIC_REARM_MS" in js


def test_only_one_submission_per_voice_turn():
    js = _voice_client_js()
    assert "if (STATE.turnSubmitted) return;" in js
    assert "STATE.turnSubmitted = true;" in js
    # The guard re-arms only when entering listening from a non-listening phase.
    assert "if (phase === 'listening' && prev !== 'listening') STATE.turnSubmitted = false;" in js


def test_push_to_talk_is_the_default_mode():
    """Hands-free VAD must stay opt-in until echo handling is proven."""
    js = _voice_client_js()
    assert "HANDS_FREE_KEY = 'hermes-gpt-voice-handsfree'" in js
    # Default is false: only an explicit 'true' opts in.
    assert "localStorage.getItem(HANDS_FREE_KEY) === 'true'" in js
    # The mic arms only for hands-free or an active hold.
    assert "(_handsFree() || STATE.talking)" in js
    assert "function beginTalk()" in js
    assert "function endTalk()" in js
    # A release keeps the window open briefly so the final transcript lands.
    assert "CAPTURE_GRACE_MS" in js
    # Hold must survive button-bound drift; release only on real pointer end.
    assert "setPointerCapture" in js
    assert "lostpointercapture" in js
    bind = js.split("function _bindTalkControl()")[1].split("function ")[0]
    assert "addEventListener('pointerleave'" not in bind
    assert 'addEventListener("pointerleave"' not in bind
    assert "addEventListener('pointercancel'" not in bind
    assert 'addEventListener("pointercancel"' not in bind
    # Mid-hold VAD must not clear talking / submit.
    assert "if (!_handsFree() && STATE.talking)" in js
    assert "submit_blocked_while_talking" in js
    assert "input_audio_buffer.commit" in js
    assert "gpt-4o-mini-transcribe" in js
    assert "ptt_vad_long_silence" in js
    # Must not wipe transcription with a bare turn_detection:null update.
    assert "turn_detection: null" not in js
    # Live mic must not pulse-mute on re-entrant listening (spoken cutout bug).
    assert "mic_gate_keep_live" in js
    assert "HANDS_FREE_SILENCE_MS" in js
    assert "audio_replace_gate_ready" in js
    assert "sender_replace" in js
    assert "STATE.micTrack" in js
    assert "STATE.silentTrack" in js


def test_barge_in_is_intentional_only():
    js = _voice_client_js()
    # Holding Talk during playback cancels it.
    assert "if (STATE.phase === 'speaking' || STATE.pendingSpeak) _stopPlayback();" in js
    # Leaked playback must not be treated as operator barge-in.
    assert "if (!STATE.micLive) return;" in js


def test_stop_control_halts_playback_mic_and_run():
    js = _voice_client_js()
    html = open("static/index.html", encoding="utf-8").read()
    assert 'id="btnGptVoiceStop"' in html
    assert 'id="btnGptVoiceTalk"' in html
    # Stop silences playback, tears down capture, and cancels the Hermes run.
    assert "_stopPlayback();" in js
    assert "cancelStream('gpt-voice-stop')" in js
    assert "stopGptVoice({ cancelRun: true })" in js


def test_echo_protection_status_is_visible():
    js = _voice_client_js()
    html = open("static/index.html", encoding="utf-8").read()
    i18n = open("static/i18n.js", encoding="utf-8").read()
    assert 'id="gptVoiceGuard"' in html
    assert "gpt_voice_echo_guard" in i18n
    # Shown exactly while the mic is muted for playback or processing.
    assert "const guarded = phase === 'processing' || phase === 'speaking';" in js
    assert "guard.style.display = guarded ? '' : 'none';" in js


def test_composer_markup_has_gpt_voice_button():
    html = open("static/index.html", encoding="utf-8").read()
    assert 'id="btnGptVoice"' in html
    assert 'id="settingsGptRealtimeVoice"' in html
    assert "static/realtime_voice.js" in html
    assert 'data-i18n-title="gpt_voice_toggle"' in html


def test_reply_speech_hook_does_not_steal_completed_turns():
    """Completed Hermes turns stay on Austin. Realtime must not speak replies."""
    js = _voice_client_js()
    ui = open("static/ui.js", encoding="utf-8").read()
    selector = '.msg-row[data-role="assistant"], .assistant-segment[data-raw-text]'
    assert selector in ui, "ui.js changed the assistant DOM contract"
    hook_start = js.index("function _hookHermesReplySpeech")
    hook_end = js.index("function _unhookHermesReplySpeech")
    hook = js[hook_start:hook_end]
    assert "_speakHermesText" not in hook
    assert "_origAutoRead.apply" in hook
    emitter_start = js.index("function selectSmedleyVoiceEmitter")
    emitter = js[emitter_start : js.index("window.selectSmedleyVoiceEmitter")]
    assert "return 'austin'" in emitter
    assert "return 'none'" in emitter
    assert "return 'realtime'" not in emitter


def test_finished_turn_always_returns_to_ready():
    js = _voice_client_js()
    # Empty or unspeakable replies still end the turn.
    assert js.count("if (STATE.active) _setPhase('listening');") >= 2
    # Watchdog recovers if the run ends without any speech hook firing.
    assert "_startRunWatch" in js and "_stopRunWatch" in js
    assert "S.busy || S.activeStreamId" in js
    assert "idleTicks >= RUN_IDLE_TICKS" in js
    # It must only fire while stuck in processing, never mid-reply.
    assert "STATE.phase !== 'processing' || _hermesRunActive()" in js


def test_stop_interrupts_the_turn_before_it_disconnects():
    js = _voice_client_js()
    # Mid-turn Stop cancels the response and stays connected.
    assert "function stopCurrentResponse()" in js
    assert "cancelStream('gpt-voice-stop-response')" in js
    assert (
        "if (STATE.phase === 'processing' || STATE.phase === 'speaking') {\n"
        "        stopCurrentResponse();\n"
        "      } else {\n"
        "        stopGptVoice({ cancelRun: true });"
    ) in js
    # The control says which job it will do.
    i18n = open("static/i18n.js", encoding="utf-8").read()
    assert "gpt_voice_end:" in i18n
    assert "gpt_voice_end_hint:" in i18n
    assert "? _t('gpt_voice_stop', 'Stop')" in js
    assert ": _t('gpt_voice_end', 'End');" in js


def test_csp_allows_openai_connect():
    from api.helpers import _build_csp_enforced_policy

    policy = _build_csp_enforced_policy("")
    assert "https://api.openai.com" in policy
