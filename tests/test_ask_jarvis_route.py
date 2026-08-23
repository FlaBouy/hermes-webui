"""Ask-Jarvis hard-bind trigger detection and chat-bubble attribution.

Regression coverage for two 2026-08-18 reports:
  - "I need Jarvis to get me a map routing to Tallahassee, Florida" fell
    through to ordinary chat instead of hard-binding to Jarvis (missing verb
    form in the embedded trigger regex).
  - A completed Ask-Jarvis turn rendered in the chat bubble with no visible
    attribution, so it read as if the host assistant (Smedley/Biggy) had
    answered when Jarvis actually did.
"""

from __future__ import annotations

from api.ask_jarvis_route import argus_voice_id, is_ask_jarvis_command


def test_argus_voice_is_alistar():
    assert argus_voice_id() == "rvugSNzdY0NcpG2PKe4B"


def test_stt_wake_homophone_is_repaired_only_at_leading_address():
    from api.routes import _normalize_biggy_wake_name

    assert _normalize_biggy_wake_name("Hey Piggy, ask Argus for a map") == (
        "Hey Biggy, ask Argus for a map"
    )
    assert _normalize_biggy_wake_name("Hey Biggie, good morning") == "Hey Biggy, good morning"
    assert _normalize_biggy_wake_name(
        "a biggie about getting Argus to get me a map routed to Jordan Harris Stadium."
    ) == (
        "Hey Biggy about getting Argus to get me a map routed to Jordan-Hare Stadium."
    )
    assert _normalize_biggy_wake_name("Open my piggy bank note") == "Open my piggy bank note"


def _jarvis_session_for_followup_tests():
    from types import SimpleNamespace

    return SimpleNamespace(
        messages=[
            {"role": "user", "content": "Ask Jarvis for the PM20-520 manual."},
            {
                "role": "assistant",
                "content": "**Jarvis:** I could not verify that page yet.",
                "assistant_identity": "jarvis",
                "ask_jarvis_hard_bind": True,
                "ask_jarvis_pending": False,
            },
        ]
    )


def _argus_travel_session_for_followup_tests():
    from types import SimpleNamespace

    return SimpleNamespace(
        messages=[
            {
                "role": "assistant",
                "content": "A.R.G.U.S. mapped the route.",
                "assistant_identity": "jarvis",
                "ask_jarvis_hard_bind": True,
                "map_view_model": {
                    "destination": {
                        "label": (
                            "Jordan-Hare Stadium, 251 South Donahue Drive, "
                            "Auburn, Alabama 36849, United States"
                        )
                    }
                },
            }
        ]
    )


def test_leading_ask_jarvis_colon_matches():
    assert is_ask_jarvis_command("Ask Jarvis: get me a map route to Tallahassee, FL")


def test_embedded_ask_jarvis_matches():
    assert is_ask_jarvis_command(
        "Do you have access to ask Jarvis to get me a map route to Tallahassee?"
    )


def test_embedded_ask_argus_matches():
    assert is_ask_jarvis_command(
        "Hey Biggy, ask Argus to map us a route to Jordan-Hare Stadium."
    )


def test_stt_getting_argus_map_variant_stays_hard_bound():
    assert is_ask_jarvis_command(
        "Hey Biggy about getting Argus to get me a map routed to Jordan-Hare Stadium."
    )


def test_leading_ask_argus_colon_matches():
    assert is_ask_jarvis_command("Ask Argus: map a route to Tallahassee, FL")


def test_need_jarvis_to_matches():
    assert is_ask_jarvis_command(
        "I need Jarvis to get me a map routing to Tallahassee, Florida"
    )


def test_need_jarvis_for_matches():
    assert is_ask_jarvis_command("I need Jarvis for a weather update")


def test_unrelated_mention_of_jarvis_does_not_match():
    assert not is_ask_jarvis_command(
        "That is untrue. Jarvis has been providing maps for a week now."
    )


def test_jarvis_manual_location_followup_stays_hard_bound():
    from api.routes import _jarvis_active_followup_objective

    objective = _jarvis_active_followup_objective(
        _jarvis_session_for_followup_tests(),
        "Take a look in the Vendor Data folder under Honeywell - TDC3000",
    )

    assert objective is not None
    assert objective.startswith("Ask Argus:")
    assert "Honeywell - TDC3000" in objective


def test_jarvis_numbered_selection_stays_hard_bound():
    from api.routes import _jarvis_active_followup_objective

    objective = _jarvis_active_followup_objective(
        _jarvis_session_for_followup_tests(), "Selection 1"
    )

    assert objective is not None
    assert "Selection 1" in objective


def test_explicit_biggy_address_releases_jarvis_followup_binding():
    from api.routes import _jarvis_active_followup_objective

    assert (
        _jarvis_active_followup_objective(
            _jarvis_session_for_followup_tests(), "Hey Biggy, change subjects."
        )
        is None
    )


def test_argus_event_venue_clarification_stays_in_active_travel_lane():
    from api.routes import _jarvis_active_followup_objective

    objective = _jarvis_active_followup_objective(
        _argus_travel_session_for_followup_tests(),
        "The Auburn and Florida game is going to be played September the 19th at Jordan-Hare.",
    )

    assert objective is not None
    assert "owner-confirmed destination exactly as Jordan-Hare Stadium" in objective
    assert "Owner request: The Auburn and Florida game" in objective
    assert "five-day forecast" in objective


def test_argus_multi_category_travel_retry_uses_prior_verified_destination():
    from api.routes import _jarvis_active_followup_objective

    objective = _jarvis_active_followup_objective(
        _argus_travel_session_for_followup_tests(),
        (
            "Ask Argus: map a route to the Auburn versus Florida game on September 19 "
            "and get weather, meals, and lodging."
        ),
    )

    assert objective is not None
    assert "Do not replace that destination with an event phrase" in objective
    assert "route, lodging, meal, fuel, and weather" in objective


def test_argus_travel_recovery_discards_injected_library_matches():
    from api.routes import _jarvis_active_followup_objective

    objective = _jarvis_active_followup_objective(
        _argus_travel_session_for_followup_tests(),
        (
            "The game is at Jordan-Hare.\n\n"
            "———— library matches ————\n"
            "Electrical OCR excerpt that must never enter the PA objective."
        ),
    )

    assert objective is not None
    assert "The game is at Jordan-Hare" in objective
    assert "Electrical OCR" not in objective


def test_travel_language_without_prior_argus_map_is_not_auto_bound():
    from types import SimpleNamespace
    from api.routes import _jarvis_active_followup_objective

    assert (
        _jarvis_active_followup_objective(
            SimpleNamespace(messages=[]),
            "The game is going to be played September 19 at Jordan-Hare.",
        )
        is None
    )


def test_ask_jarvis_reply_is_attributed_in_chat_bubble(monkeypatch):
    """The chat-bubble ``reply`` text must name Jarvis as the answerer.

    The window/session label may stay on the host profile (Smedley/Biggy),
    but the per-message text must not silently pass off Jarvis's answer as
    the host's own — that is the mislabeling Rick flagged as unacceptable.
    """
    import pathlib
    import subprocess

    import api.ask_jarvis_route as ajr

    fake_payload = {
        "speak": "Route to Tallahassee is 285 miles, about 4.5 hours.",
        "citations": [],
        "correlation_id": "test-corr-1",
    }

    class _FakeProc:
        stdout = __import__("json").dumps(fake_payload)
        stderr = ""
        returncode = 0

    monkeypatch.setattr(pathlib.Path, "is_file", lambda self: True)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeProc())

    result = ajr.try_ask_jarvis("Ask Jarvis: get me a map route to Tallahassee, FL")
    assert result is not None
    assert result["reply"].startswith("**A.R.G.U.S.:**")
    assert "Tallahassee" in result["reply"]


def test_legacy_backend_name_is_rebranded_in_public_reply(monkeypatch):
    import json
    import pathlib
    import subprocess

    import api.ask_jarvis_route as ajr

    class _FakeProc:
        stdout = json.dumps({"speak": "Jarvis has mapped the route.", "citations": []})
        stderr = ""
        returncode = 0

    monkeypatch.setattr(pathlib.Path, "is_file", lambda self: True)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeProc())

    result = ajr.try_ask_jarvis("Ask Argus: map the route")
    assert result is not None
    assert result["reply"] == "**A.R.G.U.S.:** Argus has mapped the route."


def test_pa_core_carries_biggy_session_id_for_short_term_memory(monkeypatch):
    """A follow-up must retain its chat identity, never a request correlation."""
    import json

    import api.ask_jarvis_route as ajr
    import api.jarvis_pa_conversation_memory as conversation_memory
    import api.jarvis_pa_strategy_memory as strategy_memory

    captured = {}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"status":"COMPLETED","spokenText":"I found the manual.","citations":[]}'

    def _urlopen(request, timeout):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return _Response()

    monkeypatch.setenv("GPT_BIGGY_PROPOSE_TOKEN", "test-token")
    monkeypatch.setattr(ajr.urllib.request, "urlopen", _urlopen)
    monkeypatch.setattr(strategy_memory, "record_outcome", lambda **_kwargs: None)
    monkeypatch.setattr(
        conversation_memory,
        "recent_context",
        lambda _session_id: [{"objective": "Prior manual request", "status": "COMPLETED", "summary": "Prior turn", "tools": ["rag_core"]}],
    )
    monkeypatch.setattr(conversation_memory, "record_turn", lambda *_args, **_kwargs: None)

    result = ajr.try_jarvis_ii_pa_core(
        "Find the 1756-IB32 manual.",
        correlation_id="request-123",
        session_id="biggy-chat-456",
    )

    assert result["ok"] is True
    assert captured["payload"]["session_id"] == "biggy-chat-456"
    assert captured["payload"]["correlation_id"] == "request-123"
    assert captured["payload"]["conversation_context"][0]["objective"] == "Prior manual request"


def test_short_term_pa_context_is_bounded_and_session_scoped():
    """The continuity window is transient and cannot cross from one Biggy chat to another."""
    from api.jarvis_pa_conversation_memory import record_turn, recent_context

    session_id = "test-short-term-pa-context"
    for number in range(12):
        record_turn(
            session_id,
            objective=f"Manual request {number}",
            status="PLANNED",
            spoken_summary="Checking the library.",
            tools=["rag_core"],
        )

    turns = recent_context(session_id)
    assert len(turns) == 10
    assert turns[0]["objective"] == "Manual request 2"
    assert recent_context("another-biggy-chat") == []


def test_jarvis_identity_and_server_tts_guard_are_durable():
    """Every UI shell must receive an explicit Jarvis identity and avoid a second TTS pass."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    routes = (root / "api" / "routes.py").read_text(encoding="utf-8")
    ui = (root / "static" / "ui.js").read_text(encoding="utf-8")
    messages = (root / "static" / "messages.js").read_text(encoding="utf-8")

    assert '"assistant_identity": "jarvis"' in routes
    assert "message.assistant_identity" in ui
    assert "startData.tts_final_queued" in messages


def test_explicit_ask_jarvis_does_not_default_to_legacy_document_shortcut():
    """Hard-bound PA/RAG delegation must win unless an operator opts into legacy routing."""
    from pathlib import Path

    routes = (Path(__file__).resolve().parents[1] / "api" / "routes.py").read_text(
        encoding="utf-8"
    )
    assert "HERMES_WEBUI_ASK_JARVIS_DOCUMENT_FAST_PATH" in routes
    assert "_ask_jarvis_document_fast_path\n                        and _is_aj_document" in routes
