import json

from api.biggy_voice_route import (
    BIGGY_SYSTEM_PROMPT,
    DEFAULT_MODEL,
    compact_voice_history,
    is_explicit_specialist_request,
    request_fast_voice_reply,
    resolve_fast_voice_personality,
    should_use_fast_conversation_route,
    should_use_fast_project_review_route,
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

    def __iter__(self):
        content = json.loads(self._body.decode("utf-8"))["choices"][0]["message"]["content"]
        yield ("data: " + json.dumps({"choices": [{"delta": {"content": content}}]}) + "\n").encode()
        yield b"data: [DONE]\n"


def test_project_context_is_one_system_message_not_owner_text():
    captured = {}

    def opener(request, timeout):
        captured.update(json.loads(request.data.decode("utf-8")))
        return _Response({"choices": [{"message": {"content": "Send the columns and layout."}}]})

    request_fast_voice_reply(
        "Which parameters do you need?",
        personality="smedley",
        system_context="Drafts may flag uncertainty; approval requires verification.",
        opener=opener,
    )
    systems = [m for m in captured["messages"] if m["role"] == "system"]
    assert len(systems) == 1  # Local chat templates need one leading system role.
    assert "Drafts may flag uncertainty" in systems[0]["content"]
    assert captured["messages"][-1] == {"role": "user", "content": "Which parameters do you need?"}


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


def test_nonheavy_argus_voice_uses_fast_lane_but_live_pa_work_stays_governed():
    wrapped = "voice\n\n[Voice PTT turn — operator channel: be concise]"
    assert should_use_fast_voice_route(
        message=wrapped,
        display_message="Ask Argus what he thinks about paperwork",
        personality="argus",
    )
    assert not should_use_fast_voice_route(
        message=wrapped,
        display_message="Have Argus check my calendar",
        personality="argus",
    )


def test_typed_conversation_uses_light_lane_without_stealing_governed_work():
    assert should_use_fast_conversation_route("How is your morning?", profile="biggy")
    assert should_use_fast_conversation_route(
        "Ask Argus what he thinks about bureaucracy", profile="biggy"
    )
    assert should_use_fast_conversation_route(
        "Ask Smedley to tell me a joke", profile="biggy"
    )
    assert not should_use_fast_conversation_route(
        "Have Argus check my calendar", profile="biggy"
    )
    assert not should_use_fast_conversation_route(
        "Ask Smedley to review the project drawings", profile="biggy"
    )
    assert not should_use_fast_conversation_route(
        "Fix the API code in this repository", profile="biggy"
    )
    assert not should_use_fast_conversation_route(
        "Tell me what this is", profile="biggy", has_attachments=True
    )
    assert not should_use_fast_conversation_route("/model", profile="biggy")


def test_biggy_opinion_and_story_phrases_are_quick_lane_intents():
    assert should_use_fast_conversation_route(
        "What's your opinion of the Auburn versus Baylor game this weekend?",
        profile="biggy",
    )
    assert should_use_fast_conversation_route(
        "Tell me a story about the Auburn versus Baylor game this weekend.",
        profile="biggy",
    )


def test_project_review_questions_are_fast_but_evidence_actions_stay_governed():
    from api.biggy_voice_route import plan_project_review_turn

    # Explicit current execute / continuation → governed.
    for msg in (
        "Can you do that?",
        "Please proceed?",
        "Could you run it again?",
        "What should we extract next, and please run it?",
        "OK, we upgraded the DXF and OCR tools. Re-run project review using new tools.",
        "Re-run project review using new tools.",
        "Please extract the DXF with the new tools.",
        "Run project_review_extract on the interconnects DXF.",
        "OK proceed.",
        "Continue.",
        "Continue",
        "Go ahead",
        "But run the extraction now",
        "Create the worksheet now using the ingested files",
        "Sure, go ahead and generate the report from the PDFs",
        "Please extract the BOM now",
        "Go ahead and run the extraction",
        "Before you run anything, can we discuss the layout? But run the extraction now",
        # Plain present imperatives (create/build/make/read) — not deferred/hypo
        "Create the request workbook with columns REV, ITEM, and QTY.",
        "Build the worksheet.",
        "Make the changes we just agreed to.",
        "Can you read the DXF now?",
    ):
        plan = plan_project_review_turn(msg)
        assert plan["lane"] == "governed", (msg, plan)
        assert not should_use_fast_project_review_route(msg)

    # Capability / hypothetical / future-dependent / discussion-only → dialogue.
    for msg in (
        "If I handed you the CAD drawings, could you read them?",
        "Could you generate a worksheet once I send the column definitions?",
        "Can you build a worksheet from the PDFs once I give you the requirements?",
        "Before you run anything, can we discuss the layout?",
        "I want to discuss the review, not run another extraction.",
        "OK, Based on the new ingestions, can you create an independent Worksheet based on parameters that I will give you?",
        "Can you create a worksheet once I give you the parameters?",
        "I'd like an independent worksheet — I'll provide the parameters.",
        "Based on parameters I will give you, can you build a workbook?",
        "Sounds good — what do you need from me first?",
        "What discrepancy is that?",
        "What capability do we need to overcome the OCR weakness?",
        "Can you summarize what we discussed so far?",
    ):
        plan = plan_project_review_turn(msg)
        assert plan["lane"] == "fast", (msg, plan)
        assert should_use_fast_project_review_route(msg)

    # Ambiguity defaults to dialogue clarification — not a tool loop.
    amb = plan_project_review_turn("Hmm, interesting.")
    assert amb["lane"] == "fast"
    assert amb["reason"] == "dialogue_default_clarify"

    cont = plan_project_review_turn("Continue.")
    assert cont["lane"] == "governed"
    assert cont["reason"] == "explicit_continuation"

    status = plan_project_review_turn("Have you ran the re-tests?")
    assert status["lane"] == "status"
    assert status["reason"] == "status_inquiry_report_prior"
    assert plan_project_review_turn("Have you run the re-tests?")["lane"] == "status"
    assert plan_project_review_turn(
        "Have you run the re-tests? Status only; do not rerun extraction."
    )["lane"] == "status"
    assert plan_project_review_turn("Have you run the OCR on sheet 3?")["lane"] == "status"
    assert plan_project_review_turn("Please delete source or Have you finished and verify")["lane"] == "governed"
    assert plan_project_review_turn("Have you run the re-tests? If not, run them now")["lane"] == "governed"
    assert plan_project_review_turn("What is the status? Please verify the source")["lane"] == "governed"
    assert plan_project_review_turn("Do not just report status, rerun the extraction")["lane"] == "governed"



def test_review_restrictions_are_not_execution_requests():
    from api.biggy_voice_route import plan_project_review_turn
    for message in (
        "We wired in voice response. Natural voice for general chat and voice response on heavy technical returns via summary response. Read no docs or tables unless specifically asked.",
        "Read no documents.", "Run nothing until I ask.",
        "Extract only when explicitly requested.",
        "Only scan documents when I request it.",
        "Do not read docs; keep replies conversational.",
    ):
        assert plan_project_review_turn(message)["lane"] == "fast", message
    for message in (
        "Read only the specified drawing now.",
        "Run only the voltage-drop calculation now.",
        "Read no docs. Calculate voltage drop now.",
    ):
        assert plan_project_review_turn(message)["lane"] == "governed", message


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
    assert captured["payload"]["stream"] is True
    assert captured["payload"]["max_tokens"] == 128


def test_one_sentence_request_discards_batched_extra_sentence():
    def opener(request, timeout):
        return _Response({"choices": [{"message": {"content": "First answer. Extra answer."}}]})

    result = request_fast_voice_reply(
        "Give me one dry sentence about paperwork.",
        opener=opener,
    )

    assert result["reply"] == "First answer."


def test_biggy_system_prompt_owner_and_history_guardrails():
    prompt = BIGGY_SYSTEM_PROMPT
    assert "current user is Rick" in prompt
    assert "never tell him to ask Rick" in prompt
    assert "Do not invent interface diagnoses without telemetry" in prompt
    assert "When conversation history is absent" in prompt
    assert "physical-archive" in prompt or "physical-archive claims" in prompt
    assert "no hostility" in prompt or "no hostility" in prompt.lower()
    # Must remain a spoken-lane prompt, not a broad history-search redesign.
    assert "search your archives" not in prompt.lower()
    assert "/no_think" in prompt
