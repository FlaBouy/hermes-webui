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

from api.ask_jarvis_route import is_ask_jarvis_command


def test_leading_ask_jarvis_colon_matches():
    assert is_ask_jarvis_command("Ask Jarvis: get me a map route to Tallahassee, FL")


def test_embedded_ask_jarvis_matches():
    assert is_ask_jarvis_command(
        "Do you have access to ask Jarvis to get me a map route to Tallahassee?"
    )


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
    assert result["reply"].startswith("**Jarvis:**")
    assert "Tallahassee" in result["reply"]


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
