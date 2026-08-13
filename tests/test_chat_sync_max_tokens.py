"""POST /api/chat per-request max_tokens override (PTT voice cap)."""

from __future__ import annotations

import json
import sys
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
    cfg = {
        "model": "gpt-5.6-sol",
        "provider": "openai-codex",
        "agent": {"reasoning_effort": "medium"},
    }
    monkeypatch.setattr(config, "get_config", lambda: cfg)
    monkeypatch.setattr(routes, "get_config", lambda: cfg)
    return tmp_path


def _make_session(tmp_path, session_id="sync_max_tokens_session"):
    session = Session(
        session_id=session_id,
        workspace=str(tmp_path),
        messages=[],
        context_messages=[],
        model="gpt-5.6-sol",
        model_provider="openai-codex",
    )
    session.save(touch_updated_at=False)
    return session


def _install_fake_agent(monkeypatch, *, capture: dict, accept_max_tokens: bool = True):
    class FakeAgent:
        instances: list[dict] = []

        def __init__(self, reasoning_config=None, max_tokens=None, **kwargs):
            if not accept_max_tokens:
                # Older agent builds omit max_tokens from the constructor.
                raise TypeError("unexpected keyword argument 'max_tokens'")
            self.kwargs = dict(kwargs)
            if reasoning_config is not None:
                self.kwargs["reasoning_config"] = reasoning_config
            if max_tokens is not None:
                self.kwargs["max_tokens"] = max_tokens
            FakeAgent.instances.append(self.kwargs)
            capture["kwargs"] = self.kwargs

        def run_conversation(self, **_kwargs):
            capture["run_kwargs"] = dict(_kwargs)
            return {
                "messages": [
                    {
                        "role": "user",
                        "content": _kwargs.get("persist_user_message", ""),
                    },
                    {"role": "assistant", "content": "ok"},
                ],
                "final_response": "ok",
                "completed": True,
            }

    if not accept_max_tokens:

        class FakeAgentNoMaxTokens:
            instances: list[dict] = []

            def __init__(self, reasoning_config=None, **kwargs):
                self.kwargs = dict(kwargs)
                if reasoning_config is not None:
                    self.kwargs["reasoning_config"] = reasoning_config
                FakeAgentNoMaxTokens.instances.append(self.kwargs)
                capture["kwargs"] = self.kwargs

            def run_conversation(self, **_kwargs):
                capture["run_kwargs"] = dict(_kwargs)
                return {
                    "messages": [
                        {
                            "role": "user",
                            "content": _kwargs.get("persist_user_message", ""),
                        },
                        {"role": "assistant", "content": "ok"},
                    ],
                    "final_response": "ok",
                    "completed": True,
                }

        FakeAgentNoMaxTokens.instances = []
        monkeypatch.setitem(
            sys.modules,
            "run_agent",
            SimpleNamespace(AIAgent=FakeAgentNoMaxTokens),
        )
        return FakeAgentNoMaxTokens

    FakeAgent.instances = []
    monkeypatch.setitem(sys.modules, "run_agent", SimpleNamespace(AIAgent=FakeAgent))
    return FakeAgent


def test_resolve_per_request_max_tokens_override_accepts_positive_int():
    assert config.resolve_per_request_max_tokens_override(180) == 180


@pytest.mark.parametrize("bad", [None, "180", 0, -1, True, 3.5, 128001])
def test_resolve_per_request_max_tokens_override_rejects_invalid(bad):
    with pytest.raises(ValueError):
        config.resolve_per_request_max_tokens_override(bad)


def test_sync_chat_max_tokens_override_wins(sync_chat_env, monkeypatch):
    tmp_path = sync_chat_env
    session = _make_session(tmp_path)
    capture: dict = {}
    _install_fake_agent(monkeypatch, capture=capture)

    handler = _FakePostHandler()
    routes._handle_chat_sync(
        handler,
        {
            "session_id": session.session_id,
            "message": "voice check",
            "workspace": str(tmp_path),
            "max_tokens": 180,
        },
    )

    assert handler.status == 200
    assert capture["kwargs"]["max_tokens"] == 180


def test_sync_chat_without_max_tokens_leaves_agent_default(sync_chat_env, monkeypatch):
    tmp_path = sync_chat_env
    session = _make_session(tmp_path, session_id="sync_no_max_tokens")
    capture: dict = {}
    _install_fake_agent(monkeypatch, capture=capture)

    handler = _FakePostHandler()
    routes._handle_chat_sync(
        handler,
        {
            "session_id": session.session_id,
            "message": "hello",
            "workspace": str(tmp_path),
        },
    )

    assert handler.status == 200
    assert "max_tokens" not in capture["kwargs"]


def test_sync_chat_invalid_max_tokens_fails_closed(sync_chat_env, monkeypatch):
    tmp_path = sync_chat_env
    session = _make_session(tmp_path, session_id="sync_bad_max_tokens")
    capture: dict = {}
    _install_fake_agent(monkeypatch, capture=capture)

    handler = _FakePostHandler()
    routes._handle_chat_sync(
        handler,
        {
            "session_id": session.session_id,
            "message": "voice check",
            "workspace": str(tmp_path),
            "max_tokens": 0,
        },
    )

    assert handler.status == 400
    assert "max_tokens" in handler.json_body()["error"]
    assert capture.get("kwargs") is None


def test_sync_chat_skips_max_tokens_when_agent_lacks_param(sync_chat_env, monkeypatch):
    tmp_path = sync_chat_env
    session = _make_session(tmp_path, session_id="sync_old_agent_max_tokens")
    capture: dict = {}
    _install_fake_agent(monkeypatch, capture=capture, accept_max_tokens=False)

    handler = _FakePostHandler()
    routes._handle_chat_sync(
        handler,
        {
            "session_id": session.session_id,
            "message": "voice check",
            "workspace": str(tmp_path),
            "max_tokens": 180,
        },
    )

    assert handler.status == 200
    assert "max_tokens" not in capture["kwargs"]
