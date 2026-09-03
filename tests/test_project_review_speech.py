import json
import subprocess
from pathlib import Path

import pytest

from tests.js_source_extract import extract_function


def test_review_reply_has_a_voice_policy():
    from api.project_review_speech import review_speech_candidate, prepare_review_speech
    dialog = {"session_id": "s1", "messages": [
        {"role": "user", "content": "Morning."},
        {"role": "assistant", "content": "Morning, Rick. The drawings haven't improved themselves.", "project_review_fast_route": True},
    ]}
    candidate = review_speech_candidate(dialog)
    assert candidate["mode"] == "conversation"
    assert prepare_review_speech(candidate, summarize=lambda *_: pytest.fail("ordinary conversation must not require a second model call"))["text"] == dialog["messages"][-1]["content"]


def test_heavy_reply_speaks_summary_not_tables_or_code():
    from api.project_review_speech import review_speech_candidate, prepare_review_speech
    raw = 'Two criteria need owner review. Values remain unverified.\n\n| Item | Value |\n|---|---|\n| 1 | 100 |\n```json\n{"command":"execute_code"}\n```'
    candidate = review_speech_candidate({"session_id": "s", "messages": [{"role": "assistant", "content": raw}]})
    calls = []
    def summarize(text):
        calls.append(text)
        return "Two criteria need your review. The extracted values remain unverified."
    result = prepare_review_speech(candidate, summarize=summarize)
    assert result["mode"] == "summary" and len(calls) == 1
    assert "unverified" in result["text"]
    assert "execute_code" not in calls[0] and "|" not in calls[0]
    assert "100" not in result["text"]


@pytest.mark.parametrize("extra", [{"is_streaming": True}, {"status": "interrupted"}, {"status": "cancelled"}])
def test_partial_cancelled_and_interrupted_replies_never_speak(extra):
    from api.project_review_speech import review_speech_candidate
    assert review_speech_candidate({"session_id": "s", "messages": [{"role": "assistant", "content": "I will start..."}], **extra}) is None


@pytest.mark.parametrize("row", [
    {"role": "tool", "content": "secret output"},
    {"role": "assistant", "content": '{"todos": []}'},
    {"role": "assistant", "content": "Starting now", "tool_calls": [{"id": "t"}]},
    {"role": "user", "content": "new question"},
    {"role": "assistant", "content": "hidden", "_hidden": True},
    {"role": "assistant", "content": "pending", "_pending": True},
])
def test_no_tool_or_old_reply_fallback(row):
    from api.project_review_speech import review_speech_candidate
    assert review_speech_candidate({"session_id": "s", "messages": [{"role": "assistant", "content": "old"}, row]}) is None


def test_summary_failure_is_not_full_readout():
    from api.project_review_speech import prepare_review_speech
    def failed(_):
        raise RuntimeError("offline")
    with pytest.raises(RuntimeError):
        prepare_review_speech({"id": "id", "mode": "summary", "content": "Long details. " * 100}, summarize=failed)


def test_voice_lifecycle_once_only_and_no_history_replay():
    src = (Path(__file__).resolve().parents[1] / "static/biggy-brand.js").read_text()
    helper = extract_function(src, "createProjectReviewSpeechGate")
    script = helper + '''
const assert = require('assert');
const gate = createProjectReviewSpeechGate();
const old = {id:'old'};
assert.strictEqual(gate.take(old), null); // opening history
gate.arm('project-a', 'old');
assert.strictEqual(gate.take(old), null);
const next = {id:'next'};
const ticket = gate.take(next);
assert(ticket && gate.valid(ticket));
assert.strictEqual(gate.take(next), null); // repeated polls
gate.reset(); // close, switch, cancel
assert(!gate.valid(ticket));
assert.strictEqual(gate.take({id:'later'}), null);
gate.arm('project-b','baseline');
const second = gate.take({id:'new'});
assert(gate.valid(second) && second.projectId === 'project-b');
gate.arm('project-b','new'); // newer send invalidates queued audio
assert(!gate.valid(second));
'''
    subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)


def test_speech_endpoint_validates_owner_and_reply_and_keeps_history(monkeypatch):
    from types import SimpleNamespace
    from urllib.parse import urlparse
    from api import routes
    from api.project_review_speech import review_speech_candidate
    from tests.test_biggy_project_review_lifecycle import _DialogHandler, _review_project

    messages = [{"role": "user", "content": "Hello"}, {"role": "assistant", "content": "Morning, Rick.", "project_review_fast_route": True}]
    session = SimpleNamespace(session_id="a09c02f318be", profile="smedley", project_id="bdd341b152a4", messages=messages, is_streaming=False, active_stream_id=None)
    monkeypatch.setattr(routes, "load_projects", lambda: [_review_project()])
    monkeypatch.setattr(routes, "get_session", lambda *args, **kw: session)
    monkeypatch.setattr(routes, "_get_active_profile_name", lambda: "biggy")
    monkeypatch.setattr(routes, "_biggy_project_review_live_stream_id", lambda _: None)
    monkeypatch.setattr(routes, "read_turn_journal", lambda _: {"events": []})
    dialog = routes._biggy_project_review_dialog_payload(session)
    assert dialog["speech"]["mode"] == "conversation"
    reply_id = review_speech_candidate(dialog)["id"]
    before = json.dumps(messages)
    handler = _DialogHandler({"project_id": session.project_id, "reply_id": reply_id})
    routes.handle_post(handler, urlparse("/api/biggy/projects/reviews/dialog/speech"))
    assert handler.status == 200 and handler.payload()["speech"]["text"] == "Morning, Rick."
    assert handler.payload()["speech"]["voice_id"] == "c6SfcYrb2t09NHXiT80T"
    assert handler.payload()["speech"]["voice_name"] == "Jarnathan"
    assert json.dumps(messages) == before
    handler = _DialogHandler({"project_id": session.project_id, "reply_id": "stale"})
    routes.handle_post(handler, urlparse("/api/biggy/projects/reviews/dialog/speech"))
    assert handler.status == 409
    monkeypatch.setattr(routes, "_get_active_profile_name", lambda: "unrelated")
    handler = _DialogHandler({"project_id": session.project_id, "reply_id": reply_id})
    routes.handle_post(handler, urlparse("/api/biggy/projects/reviews/dialog/speech"))
    assert handler.status == 403


def test_review_sink_does_not_inherit_argus_voice_and_rechecks_queue():
    src = (Path(__file__).resolve().parents[1] / "static/biggy-brand.js").read_text()
    helper = extract_function(src, "speakOnSmedley", prefix="async function")
    script = '''
const assert = require('assert');
let smedleySpeechTail = Promise.resolve();
const bodies = [];
const requests = [];
const stripForSmedleySpeak = x => x;
const splitSmedleySpeech = x => [x];
const resolveArgusVoiceId = () => 'argus-voice';
const proxyJson = async (path, opts) => { requests.push(opts); bodies.push(JSON.parse(opts.body)); };
''' + helper + '''
(async () => {
 assert(await speakOnSmedley('Morning.', {personality:'smedley',voice_id:'c6SfcYrb2t09NHXiT80T', canSpeak:()=>true}));
 assert.strictEqual(bodies[0].voice_id,'c6SfcYrb2t09NHXiT80T'); // documented Jarnathan, not Austin/Argus
 assert.strictEqual(requests[0].timeoutMs,190000); // exceeds server's playback budget
 assert.strictEqual(requests[0].retries,0); // lost acknowledgement must not repeat speech
 assert.strictEqual(bodies[0].assistant_identity,'smedley');
 assert.strictEqual(await speakOnSmedley('Missing identity.', {personality:'smedley'}), false);
 assert.strictEqual(await speakOnSmedley('Malformed identity.', {personality:'smedley',voice_id:'bad/id'}), false);
 assert.strictEqual(await speakOnSmedley('Stale.', {personality:'smedley',voice_id:'c6SfcYrb2t09NHXiT80T', canSpeak:()=>false}), false);
 assert.strictEqual(bodies.length,1);
 await speakOnSmedley('Argus.', {});
 assert.strictEqual(bodies[1].voice_id,'argus-voice'); // other callers unchanged
 await speakOnSmedley('Review summary.', {personality:'smedley',voice_id:'c6SfcYrb2t09NHXiT80T'});
 assert.strictEqual(bodies[2].voice_id,'c6SfcYrb2t09NHXiT80T');
 await speakOnSmedley('Explicit voice.', {personality:'smedley',voice_id:'explicit-voice'});
 assert.strictEqual(bodies[3].voice_id,'explicit-voice');
})().catch(e => { console.error(e); process.exit(1); });
'''
    subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)


def test_media_paths_are_not_spoken_or_summarized():
    from api.project_review_speech import prepare_review_speech
    result = prepare_review_speech({"id": "x", "mode": "conversation", "content":
        "Understood.\n\nMEDIA:/private/cache/audio.mp3"})
    assert result["text"] == "Understood."
