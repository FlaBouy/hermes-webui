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
