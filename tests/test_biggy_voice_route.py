import json

from api.biggy_voice_route import (
    DEFAULT_MODEL,
    compact_voice_history,
    is_explicit_specialist_request,
    request_fast_voice_reply,
    resolve_fast_voice_personality,
    should_use_fast_voice_route,
    specialist_requires_governed_route,
)


class _Response:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self._body


def test_specialist_gate_accepts_ask_and_have_variants():
    for phrase in (
        "Ask Argus to map a route",
        "Have Argus check my calendar",
        "Ask Smedley to review this project",
        "Have Smedley pull the code book",
    ):
        assert is_explicit_specialist_request(phrase)


def test_general_topics_do_not_infer_a_heavy_route():
    for phrase in (
        "Tell me a story about a Marine",
        "What is on my calendar?",
        "Map a route to Auburn",
        "Explain grounding electrodes",
    ):
        assert not is_explicit_specialist_request(phrase)


def test_fast_voice_gate_requires_real_ptt_wrapper_and_no_specialist():
    wrapped = "hello\n\n[Voice PTT turn — operator channel: be concise]"
    assert should_use_fast_voice_route(message=wrapped, display_message="Hello Biggy")
    assert not should_use_fast_voice_route(message="Hello Biggy", display_message="Hello Biggy")
    assert not should_use_fast_voice_route(
        message=wrapped,
        display_message="Have Argus map a route",
    )


def test_fast_personality_selection_separates_identity_from_heavy_work():
    assert resolve_fast_voice_personality("Tell me a story", default="biggy") == "biggy"
    assert resolve_fast_voice_personality("Tell me a story", default="smedley") == "smedley"
    assert resolve_fast_voice_personality("Ask Smedley to tell me a joke") == "smedley"
    assert resolve_fast_voice_personality("Ask Argus what he thinks") == "argus"
    assert specialist_requires_governed_route("Ask Argus to check my calendar")
    assert specialist_requires_governed_route("Ask Smedley to review the project drawings")
    assert not specialist_requires_governed_route("Ask Smedley to tell me a story")


def test_nonheavy_smedley_voice_uses_fast_lane_but_review_stays_governed():
    wrapped = "voice\n\n[Voice PTT turn — operator channel: be concise]"
    assert should_use_fast_voice_route(
        message=wrapped,
        display_message="Ask Smedley to tell me a story",
        personality="smedley",
    )
    assert not should_use_fast_voice_route(
        message=wrapped,
        display_message="Ask Smedley to review the project drawings",
        personality="smedley",
    )


def test_compact_history_strips_voice_appendix_and_bounds_rows():
    history = []
    for i in range(5):
        history.extend(
            [
                {"role": "user", "content": f"question {i}\n[Voice PTT turn — appendix]"},
                {"role": "assistant", "content": f"answer {i}"},
            ]
        )
    result = compact_voice_history(history, max_rows=4)
    assert len(result) == 4
    assert result[0]["content"] == "question 3"
    assert all("Voice PTT" not in row["content"] for row in result)


def test_fast_voice_request_uses_one_light_model_call_and_story_budget():
    captured = {}

    def opener(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _Response({"choices": [{"message": {"content": "One complete story."}}]})

    result = request_fast_voice_reply(
        "Tell me a story about a Marine in a foxhole.",
        history=[{"role": "assistant", "content": "Prior context."}],
        opener=opener,
    )

    assert result == {"reply": "One complete story.", "model": DEFAULT_MODEL, "story": True}
    assert captured["url"].endswith("/v1/chat/completions")
    assert captured["payload"]["model"] == DEFAULT_MODEL
    assert captured["payload"]["max_tokens"] == 1500
    assert captured["payload"]["reasoning_effort"] == "none"
    assert captured["payload"]["stream"] is False
    assert captured["timeout"] == 55


def test_fast_voice_request_injects_selected_personality_prompt():
    captured = {}

    def opener(request, timeout):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _Response({"choices": [{"message": {"content": "Engineering answer."}}]})

    request_fast_voice_reply(
        "Give me the short version.",
        personality="smedley",
        opener=opener,
    )

    system = captured["payload"]["messages"][0]["content"]
    assert "You are Smedley" in system
    assert "senior engineer" in system
