"""POST /api/chat optional display_message (PTT visible-user-turn seam)."""

from __future__ import annotations

import json
import sys
import uuid
from types import SimpleNamespace

import pytest

import api.config as config
import api.models as models
import api.routes as routes
from api.models import Session


class _FakePostHandler:
    def __init__(self):
        self.status = None
        self.headers = {}
        self.body = bytearray()
        self.wfile = self

    def send_response(self, status):
        self.status = status

    def send_header(self, name, value):
        self.headers[name] = value

    def end_headers(self):
        pass

    def write(self, data):
        self.body.extend(data)

    def json_body(self):
        return json.loads(bytes(self.body).decode("utf-8"))


@pytest.fixture
def sync_chat_env(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    session_dir = state_dir / "sessions"
    session_dir.mkdir(parents=True)
    monkeypatch.setattr(models, "SESSION_DIR", session_dir)
    monkeypatch.setattr(models, "SESSION_INDEX_FILE", state_dir / "session_index.json")
    monkeypatch.setattr(routes, "SESSION_INDEX_FILE", state_dir / "session_index.json")
    monkeypatch.setattr(routes, "get_session", models.get_session)
    monkeypatch.setattr(routes, "title_from", models.title_from)
    monkeypatch.setattr(routes, "resolve_trusted_workspace", lambda value: tmp_path)
    monkeypatch.setattr(routes, "load_settings", lambda: {})
    monkeypatch.setattr(routes, "_resolve_cli_toolsets", lambda: [])
    models.SESSIONS.clear()
    monkeypatch.setattr(
        config,
        "get_config",
        lambda: {
            "model": "gpt-5.6-sol",
            "provider": "openai-codex",
            "agent": {"reasoning_effort": "medium"},
        },
    )
    monkeypatch.setattr(
        routes,
        "get_config",
        lambda: {
            "model": "gpt-5.6-sol",
            "provider": "openai-codex",
            "agent": {"reasoning_effort": "medium"},
        },
    )
    return tmp_path


def _make_session(tmp_path, *, session_id=None, model="gpt-5.6-sol", provider="openai-codex"):
    session = Session(
        session_id=session_id or f"sync_display_{uuid.uuid4().hex[:10]}",
        workspace=str(tmp_path),
        messages=[],
        context_messages=[],
        model=model,
        model_provider=provider,
        title="Untitled",
    )
    session.save(touch_updated_at=False)
    return session


def _install_fake_agent(monkeypatch, *, capture: dict):
    class FakeAgent:
        instances: list[dict] = []

        def __init__(self, reasoning_config=None, **kwargs):
            self.kwargs = dict(kwargs)
            if reasoning_config is not None:
                self.kwargs["reasoning_config"] = reasoning_config
            FakeAgent.instances.append(self.kwargs)
            capture["kwargs"] = self.kwargs

        def run_conversation(self, **kwargs):
            capture["run_kwargs"] = kwargs
            persist = kwargs.get("persist_user_message") or ""
            return {
                "messages": [
                    {"role": "user", "content": persist},
                    {"role": "assistant", "content": "ok"},
                ],
                "final_response": "ok",
                "completed": True,
            }

    FakeAgent.instances = []
    monkeypatch.setitem(sys.modules, "run_agent", SimpleNamespace(AIAgent=FakeAgent))
    return FakeAgent


def test_sync_chat_without_display_message_preserves_message_for_save(sync_chat_env, monkeypatch):
    tmp_path = sync_chat_env
    session = _make_session(tmp_path)
    capture: dict = {}
    _install_fake_agent(monkeypatch, capture=capture)

    handler = _FakePostHandler()
    routes._handle_chat_sync(
        handler,
        {
            "session_id": session.session_id,
            "message": "typed hello",
            "workspace": str(tmp_path),
        },
    )

    assert handler.status == 200
    assert capture["run_kwargs"]["user_message"].endswith("typed hello")
    assert capture["run_kwargs"]["persist_user_message"] == "typed hello"
    saved = models.get_session(session.session_id)
    user_rows = [m for m in saved.messages if m.get("role") == "user"]
    assert user_rows
    assert user_rows[0]["content"] == "typed hello"
    assert saved.title == "typed hello"


def test_sync_chat_display_message_splits_agent_input_from_visible_turn(
    sync_chat_env, monkeypatch
):
    tmp_path = sync_chat_env
    session = _make_session(tmp_path)
    capture: dict = {}
    _install_fake_agent(monkeypatch, capture=capture)
    augmented = (
        "What is NEC 250.122?\n\n"
        "———— library matches (cite the filename if you use one) ————\n"
        "- nec.pdf — sizing table\n\n"
        "[Voice PTT turn: Answer naturally and directly.]"
    )

    handler = _FakePostHandler()
    routes._handle_chat_sync(
        handler,
        {
            "session_id": session.session_id,
            "message": augmented,
            "display_message": "What is NEC 250.122?",
            "workspace": str(tmp_path),
            "reasoning_effort": "low",
        },
    )

    assert handler.status == 200
    assert "library matches" in capture["run_kwargs"]["user_message"]
    assert "Voice PTT turn" in capture["run_kwargs"]["user_message"]
    assert "What is NEC 250.122?" in capture["run_kwargs"]["user_message"]
    assert capture["run_kwargs"]["persist_user_message"] == "What is NEC 250.122?"
    assert capture["kwargs"]["reasoning_config"] == {"enabled": True, "effort": "low"}

    saved = models.get_session(session.session_id)
    user_rows = [m for m in saved.messages if m.get("role") == "user"]
    assert len(user_rows) == 1
    assert user_rows[0]["content"] == "What is NEC 250.122?"
    assert "library matches" not in user_rows[0]["content"]
    assert "Voice PTT" not in user_rows[0]["content"]
    assert saved.title == "What is NEC 250.122?"

    body = handler.json_body()
    visible = [m for m in body["session"]["messages"] if m.get("role") == "user"]
    assert visible[0]["content"] == "What is NEC 250.122?"


def test_sync_voice_appendix_cannot_steal_ordinary_biggy_story(
    sync_chat_env, monkeypatch
):
    """The raw owner story uses one V6 light call, never the Argus hard bind."""
    import api.biggy_voice_route as voice_route

    tmp_path = sync_chat_env
    session = _make_session(tmp_path)
    capture: dict = {}
    _install_fake_agent(monkeypatch, capture=capture)
    monkeypatch.setattr(
        voice_route,
        "request_fast_voice_reply",
        lambda prompt, history=None: {
            "reply": "A complete story with one ending.",
            "model": voice_route.DEFAULT_MODEL,
            "story": True,
        },
    )
    monkeypatch.setattr(
        routes,
        "_handle_argus_sync_hard_bind",
        lambda *_a, **_k: pytest.fail("ordinary Biggy story was stolen by Argus"),
    )
    owner = "Hey Biggy, tell me a story about a Marine in a foxhole."
    wrapped = (
        owner
        + "\n\n[Voice PTT turn — Never say Jarvis online, never recite host IP. "
        + "Open as Smedley in natural voice.]"
    )

    handler = _FakePostHandler()
    routes._handle_chat_sync(
        handler,
        {
            "session_id": session.session_id,
            "message": wrapped,
            "display_message": owner,
            "workspace": str(tmp_path),
        },
    )

    assert handler.status == 200
    body = handler.json_body()
    assert body["biggy_fast_voice_route"] is True
    assert body["provider_calls"] == 1
    assert body["answer"] == "A complete story with one ending."
    assert "run_kwargs" not in capture
    saved = models.get_session(session.session_id)
    assert [row["role"] for row in saved.messages] == ["user", "assistant"]
    assert saved.messages[0]["content"] == owner
    assert saved.messages[1]["tts_owner"] == "biggy_pedal_austin"


def test_sync_explicit_new_argus_map_beats_stale_travel_destination(
    sync_chat_env, monkeypatch
):
    """A new Jordan-Hare command must not continue a Grand Canyon card."""
    tmp_path = sync_chat_env
    session = _make_session(tmp_path)
    session.messages = [
        {
            "role": "assistant",
            "ask_jarvis_hard_bind": True,
            "map_view_model": {
                "destination": {"label": "Grand Canyon National Park, Arizona"}
            },
        }
    ]
    session.save(touch_updated_at=False)
    captured = {}

    def _hard_bind(handler, _session, objective):
        captured["objective"] = objective
        return routes.j(handler, {"ok": True, "objective": objective})

    monkeypatch.setattr(routes, "_handle_argus_sync_hard_bind", _hard_bind)
    owner = "Hey Biggy, have Argus pull me a map to Jordan-Hare Stadium."
    handler = _FakePostHandler()
    routes._handle_chat_sync(
        handler,
        {
            "session_id": session.session_id,
            "message": owner + "\n\n[Voice PTT turn]",
            "display_message": owner,
            "workspace": str(tmp_path),
        },
    )

    assert handler.status == 200
    assert captured["objective"] == owner
    assert "Grand Canyon" not in captured["objective"]


def test_sync_stt_vargas_map_is_repaired_and_hard_bound_fresh(
    sync_chat_env, monkeypatch
):
    tmp_path = sync_chat_env
    session = _make_session(tmp_path)
    session.messages = [
        {
            "role": "assistant",
            "ask_jarvis_hard_bind": True,
            "map_view_model": {
                "destination": {"label": "Grand Canyon National Park, Arizona"}
            },
        }
    ]
    session.save(touch_updated_at=False)
    captured = {}

    def _hard_bind(handler, _session, objective):
        captured["objective"] = objective
        return routes.j(handler, {"ok": True, "objective": objective})

    monkeypatch.setattr(routes, "_handle_argus_sync_hard_bind", _hard_bind)
    owner = "Hey Biggie, have Vargas pull a map to Jordan-Hare Stadium."
    handler = _FakePostHandler()
    routes._handle_chat_sync(
        handler,
        {
            "session_id": session.session_id,
            "message": owner + "\n\n[Voice PTT turn]",
            "display_message": owner,
            "workspace": str(tmp_path),
        },
    )

    assert handler.status == 200
    assert captured["objective"] == (
        "Hey Biggy, have Argus pull a map to Jordan-Hare Stadium."
    )
    assert "Grand Canyon" not in captured["objective"]


@pytest.mark.parametrize(
    "display_message",
    ["", "   ", None, 123, ["not", "a", "string"]],
)
def test_sync_chat_invalid_display_message_returns_400_before_agent(
    sync_chat_env, monkeypatch, display_message
):
    tmp_path = sync_chat_env
    session = _make_session(tmp_path)
    FakeAgent = _install_fake_agent(monkeypatch, capture={})

    handler = _FakePostHandler()
    routes._handle_chat_sync(
        handler,
        {
            "session_id": session.session_id,
            "message": "full agent payload",
            "display_message": display_message,
            "workspace": str(tmp_path),
        },
    )

    assert handler.status == 400
    assert FakeAgent.instances == []


def test_sync_chat_oversized_display_message_returns_400_before_agent(
    sync_chat_env, monkeypatch
):
    tmp_path = sync_chat_env
    session = _make_session(tmp_path)
    FakeAgent = _install_fake_agent(monkeypatch, capture={})
    too_long = "x" * (config.SYNC_DISPLAY_MESSAGE_MAX_CHARS + 1)

    handler = _FakePostHandler()
    routes._handle_chat_sync(
        handler,
        {
            "session_id": session.session_id,
            "message": "full agent payload",
            "display_message": too_long,
            "workspace": str(tmp_path),
        },
    )

    assert handler.status == 400
    assert FakeAgent.instances == []


def test_sync_chat_ptt_owned_tts_stamps_assistant(sync_chat_env, monkeypatch):
    tmp_path = sync_chat_env
    session = _make_session(tmp_path)
    _install_fake_agent(monkeypatch, capture={})
    handler = _FakePostHandler()
    routes._handle_chat_sync(
        handler,
        {
            "session_id": session.session_id,
            "message": "What is NEC 250.122?\n\n[Voice PTT turn]",
            "display_message": "What is NEC 250.122?",
            "ptt_owned_tts": True,
            "workspace": str(tmp_path),
        },
    )
    assert handler.status == 200
    body = handler.json_body()
    assert body.get("ptt_owned_tts") is True
    saved = models.get_session(session.session_id)
    asst = [m for m in saved.messages if m.get("role") == "assistant"][-1]
    assert asst.get("ptt_owned_tts") is True
    assert asst.get("tts_owner") == "pedal_austin"


def test_sync_chat_without_voice_owner_queues_server_austin(sync_chat_env, monkeypatch):
    tmp_path = sync_chat_env
    session = _make_session(tmp_path)
    _install_fake_agent(monkeypatch, capture={})
    spoken = []
    monkeypatch.setattr(routes, "_server_speak_smedley", spoken.append)

    handler = _FakePostHandler()
    routes._handle_chat_sync(
        handler,
        {
            "session_id": session.session_id,
            "message": "Tell me something useful.",
            "display_message": "Tell me something useful.",
            "workspace": str(tmp_path),
        },
    )

    assert handler.status == 200
    assert spoken == ["ok"]
    assert handler.json_body()["ptt_owned_tts"] is True
    saved = models.get_session(session.session_id)
    assistant = [m for m in saved.messages if m.get("role") == "assistant"][-1]
    assert assistant["tts_owner"] == "server_austin"
    assert assistant["ptt_owned_tts"] is True


def test_sync_argus_document_result_is_server_owned_alistar(sync_chat_env, monkeypatch):
    """A direct RAG result must never fall through to the pedal's Austin TTS."""
    tmp_path = sync_chat_env
    session = _make_session(tmp_path)

    import api.argus_route as ask_route
    import api.smedley_document_route as doc_route

    source = "Vendor Data/Honeywell/Honeywell Edge UIO/User-manual.pdf"
    monkeypatch.setattr(routes, "_request_base_url", lambda _handler: "http://127.0.0.1:8790")
    monkeypatch.setattr(ask_route, "is_argus_command", lambda _text: True)
    monkeypatch.setattr(doc_route, "is_document_request", lambda *_a, **_k: True)
    monkeypatch.setattr(
        doc_route,
        "try_document_route",
        lambda *_a, **_k: {
            "handled": True,
            "reply": "I found the Honeywell manual.",
            "spoken_reply": "I found the Honeywell manual.",
            "active_document": {"source": source},
            "retrieval_receipt": {"source": source},
        },
    )
    monkeypatch.setattr(ask_route, "mint_correlation_id", lambda: "corr-honeywell")
    monkeypatch.setattr(ask_route, "timing_path_for", lambda _corr: tmp_path / "timing.json")
    queued = {}

    def _queue(text, **kwargs):
        queued.update(text=text, **kwargs)
        return {"queued": True}

    monkeypatch.setattr(ask_route, "queue_argus_smedley_tts", _queue)
    monkeypatch.setattr(
        ask_route,
        "wait_final_playback_complete",
        lambda _corr, timeout_s: {"ok": True},
    )

    handler = _FakePostHandler()
    routes._handle_chat_sync(
        handler,
        {
            "session_id": session.session_id,
            "message": "Ask Argus for the Honeywell 900A16-0103 manual",
            "display_message": "Ask Argus for the Honeywell 900A16-0103 manual",
            "workspace": str(tmp_path),
        },
    )

    assert handler.status == 200
    body = handler.json_body()
    assert body["tts_server_handled"] is True
    assert body["tts_final_queued"] is True
    assert body["tts_voice_profile"] == "argus_alistar"
    assert body["retrieval_receipt"]["source"] == source
    assert queued["voice_id"] == "rvugSNzdY0NcpG2PKe4B"
    saved = models.get_session(session.session_id)
    final = [m for m in saved.messages if m.get("role") == "assistant"][-1]
    assert final["_correlation_id"] == "corr-honeywell"
    assert final["_tts_final_server_queued"] is True
