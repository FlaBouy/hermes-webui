"""Biggy Voice browser wiring stays on the Jarvis V6 local lane."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_biggy_controller_posts_transcript_to_local_v6_chat_lane():
    source = (ROOT / "static" / "biggy-brand.js").read_text(encoding="utf-8")
    start = source.index("function installBiggyV6VoiceController")
    controller = source[start : source.index("function smedleyWebUiUrl", start)]
    submit_start = source.index("async function submitBiggyV6Voice")
    submit = source[submit_start:start]

    assert "window.__biggyV6VoiceController = controller" in controller
    assert "window.__biggyV6VoiceSubmit = submitBiggyV6Voice" in controller
    assert "biggyVoicePath = 'jarvis-v6-local'" in controller
    assert "jsonPost('/api/chat'" in submit
    assert "biggy_local_voice: true" in submit
    assert "display_message: spoken" in submit
    assert "[Voice PTT turn — browser-local Biggy Voice" in submit
    assert "_biggy_voice_optimistic: true" in submit
    assert "delete lane.dataset.homeHidden" in submit
    assert "renderArgusConversationLane()" in submit
    assert "/api/realtime/session" not in controller + submit


def test_ptt_completion_reveals_new_dialog_after_home_hid_old_history():
    source = (ROOT / "static" / "biggy-brand.js").read_text(encoding="utf-8")
    hydrate_start = source.index("async function hydratePttSessionMessages")
    hydrate_end = source.index("async function refreshPttProgress", hydrate_start)
    hydrate = source[hydrate_start:hydrate_end]
    reconcile_start = source.index("async function reconcileActiveBiggySessionCompletion")
    reconcile_end = source.index("window.__biggyReconcileActiveSessionCompletion", reconcile_start)
    reconcile = source[reconcile_start:reconcile_end]

    assert "delete lane.dataset.homeHidden" in hydrate
    assert "delete lane.dataset.homeHidden" in reconcile


def test_dictation_and_voice_controls_delegate_to_biggy_local_controller():
    boot = (ROOT / "static" / "boot.js").read_text(encoding="utf-8")
    realtime = (ROOT / "static" / "realtime_voice.js").read_text(encoding="utf-8")

    assert "window.__biggyV6VoiceSubmit(String(committed||ta.value||''))" in boot
    assert "function _biggyV6VoiceController()" in realtime
    assert "local.beginTalk()" in realtime
    assert "local.endTalk()" in realtime
    assert "return local.start()" in realtime
    assert "return local.toggle()" in realtime


def test_biggy_voice_prefers_live_stt_without_changing_normal_dictation():
    boot = (ROOT / "static" / "boot.js").read_text(encoding="utf-8")
    start = boot.index("function _biggyV6PrefersLiveStt")
    end = boot.index("async function _transcribeBlob", start)
    preference = boot[start:end]
    capture_start = boot.index("async function _startMicCapture")
    capture_end = boot.index("async function _toggleMicCapture", capture_start)
    capture = boot[capture_start:capture_end]

    assert "window.__biggyV6VoicePending" in preference
    assert "SpeechRecognition" in preference
    assert "const biggyLiveStt=_biggyV6PrefersLiveStt()" in capture
    assert "if(biggyLiveStt&&!recognition)" in capture
    assert "(biggyLiveStt||!_forceMediaRecorder)" in capture
    assert "_forceMediaRecorder=true" not in preference


def test_biggy_controller_is_installed_and_describes_no_realtime_session():
    source = (ROOT / "static" / "biggy-brand.js").read_text(encoding="utf-8")

    assert source.count("installBiggyV6VoiceController();") >= 2
    assert "Biggy Voice (Jarvis V6)" in source
    assert "it does not open an OpenAI Realtime session" in source
