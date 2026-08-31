import json

from api.biggy_voice_route import (
    DEFAULT_MODEL,
    compact_voice_history,
    is_explicit_specialist_request,
    request_fast_voice_reply,
    should_use_fast_voice_route,
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
