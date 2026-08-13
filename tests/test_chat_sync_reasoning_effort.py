"""POST /api/chat per-request reasoning_effort override (PTT-only seam)."""

from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import api.config as config
import api.models as models
import api.routes as routes
from api.models import Session

REPO_ROOT = Path(__file__).parent.parent.resolve()


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


def _make_session(tmp_path, *, model="gpt-5.6-sol", provider="openai-codex"):
    session = Session(
        session_id="sync_reasoning_session",
        workspace=str(tmp_path),
        messages=[],
        context_messages=[],
        model=model,
        model_provider=provider,
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

    FakeAgent.instances = []
    monkeypatch.setitem(sys.modules, "run_agent", SimpleNamespace(AIAgent=FakeAgent))
    return FakeAgent


def test_sync_chat_without_override_preserves_agent_defaults(sync_chat_env, monkeypatch):
  tmp_path = sync_chat_env
  session = _make_session(tmp_path)
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
  assert capture["kwargs"]["reasoning_config"] == {"enabled": True, "effort": "medium"}


def test_sync_chat_request_override_wins_over_agent_default(sync_chat_env, monkeypatch):
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
          "reasoning_effort": "none",
      },
  )

  assert handler.status == 200
  assert capture["kwargs"]["reasoning_config"] == {"enabled": False}


def test_sync_chat_applies_minimal_override_to_single_agent(sync_chat_env, monkeypatch):
  tmp_path = sync_chat_env
  session = _make_session(tmp_path)
  capture: dict = {}
  _install_fake_agent(monkeypatch, capture=capture)

  handler = _FakePostHandler()
  routes._handle_chat_sync(
      handler,
      {
          "session_id": session.session_id,
          "message": "hello",
          "workspace": str(tmp_path),
          "reasoning_effort": "minimal",
      },
  )

  assert handler.status == 200
  assert capture["kwargs"]["reasoning_config"] == {"enabled": True, "effort": "minimal"}


def test_sync_chat_applies_low_override_to_single_agent(sync_chat_env, monkeypatch):
  tmp_path = sync_chat_env
  session = _make_session(tmp_path)
  capture: dict = {}
  _install_fake_agent(monkeypatch, capture=capture)

  handler = _FakePostHandler()
  routes._handle_chat_sync(
      handler,
      {
          "session_id": session.session_id,
          "message": "grounded question",
          "workspace": str(tmp_path),
          "reasoning_effort": "low",
      },
  )

  assert handler.status == 200
  assert capture["kwargs"]["reasoning_config"] == {"enabled": True, "effort": "low"}


def test_sync_chat_display_message_hides_augmented_agent_payload(sync_chat_env, monkeypatch):
  tmp_path = sync_chat_env
  session = _make_session(tmp_path)
  capture: dict = {}
  _install_fake_agent(monkeypatch, capture=capture)
  augmented = (
      "What is NEC 250.122?\n\n———— library matches ————\n"
      "- NEC.pdf — hidden grounded excerpt\n\n"
      "[Voice PTT turn: hidden instruction]"
  )

  handler = _FakePostHandler()
  routes._handle_chat_sync(
      handler,
      {
          "session_id": session.session_id,
          "message": augmented,
          "display_message": "What is NEC 250.122?",
          "workspace": str(tmp_path),
      },
  )

  assert handler.status == 200
  assert augmented in capture["run_kwargs"]["user_message"]
  assert capture["run_kwargs"]["persist_user_message"] == "What is NEC 250.122?"
  saved = models.get_session(session.session_id)
  visible_user_messages = [m["content"] for m in saved.messages if m.get("role") == "user"]
  assert visible_user_messages[-1] == "What is NEC 250.122?"
  assert augmented not in visible_user_messages
  assert "library matches" not in saved.title


@pytest.mark.parametrize("display_message", [None, "", "   ", 123, "x" * 8001])
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
          "message": "full internal payload",
          "display_message": display_message,
          "workspace": str(tmp_path),
      },
  )

  assert handler.status == 400
  assert FakeAgent.instances == []


def test_sync_chat_without_display_message_preserves_normal_visible_turn(
    sync_chat_env, monkeypatch
):
  tmp_path = sync_chat_env
  session = _make_session(tmp_path)
  capture: dict = {}
  _install_fake_agent(monkeypatch, capture=capture)
  handler = _FakePostHandler()

  routes._handle_chat_sync(
      handler,
      {
          "session_id": session.session_id,
          "message": "normal typed message",
          "workspace": str(tmp_path),
      },
  )

  assert handler.status == 200
  assert capture["run_kwargs"]["persist_user_message"] == "normal typed message"
  saved = models.get_session(session.session_id)
  visible_user_messages = [m["content"] for m in saved.messages if m.get("role") == "user"]
  assert visible_user_messages[-1] == "normal typed message"


def test_sync_chat_invalid_effort_returns_400_before_agent(sync_chat_env, monkeypatch):
  tmp_path = sync_chat_env
  session = _make_session(tmp_path)
  FakeAgent = _install_fake_agent(monkeypatch, capture={})

  handler = _FakePostHandler()
  routes._handle_chat_sync(
      handler,
      {
          "session_id": session.session_id,
          "message": "hello",
          "workspace": str(tmp_path),
          "reasoning_effort": "garbage",
      },
  )

  assert handler.status == 400
  assert FakeAgent.instances == []


def test_sync_chat_override_does_not_write_global_config(sync_chat_env, monkeypatch, tmp_path):
  session = _make_session(sync_chat_env)
  _install_fake_agent(monkeypatch, capture={})
  cfg_path = tmp_path / "config.yaml"
  cfg_path.write_text("agent:\n  reasoning_effort: medium\n", encoding="utf-8")
  monkeypatch.setattr(config, "_get_config_path", lambda: cfg_path)

  handler = _FakePostHandler()
  routes._handle_chat_sync(
      handler,
      {
          "session_id": session.session_id,
          "message": "hello",
          "workspace": str(sync_chat_env),
          "reasoning_effort": "minimal",
      },
  )

  assert handler.status == 200
  assert cfg_path.read_text(encoding="utf-8") == "agent:\n  reasoning_effort: medium\n"


def test_sync_chat_uses_session_model_for_capability_coercion(sync_chat_env, monkeypatch):
  tmp_path = sync_chat_env
  session = _make_session(tmp_path, model="gpt-5", provider="openai-codex")
  calls: list[tuple] = []
  original = config.resolve_per_request_reasoning_effort_override
  monkeypatch.setattr(
      routes,
      "_resolve_compatible_session_model_state",
      lambda model, provider, **kwargs: (model, provider, kwargs.get("profile_config")),
  )
  monkeypatch.setattr(
      config,
      "resolve_model_provider",
      lambda model, **kwargs: ("gpt-5", "openai-codex", None),
  )

  def _spy(effort, *, model_id=None, provider_id=None, base_url=None):
      calls.append((effort, model_id, provider_id, base_url))
      return original(
          effort,
          model_id=model_id,
          provider_id=provider_id,
          base_url=base_url,
      )

  monkeypatch.setattr(config, "resolve_per_request_reasoning_effort_override", _spy)
  _install_fake_agent(monkeypatch, capture={})

  handler = _FakePostHandler()
  routes._handle_chat_sync(
      handler,
      {
          "session_id": session.session_id,
          "message": "hello",
          "workspace": str(tmp_path),
          "reasoning_effort": "low",
      },
  )

  assert handler.status == 200
  assert calls
  assert calls[0][1:] == ("gpt-5", "openai-codex", None)


def test_browser_streaming_path_does_not_accept_per_request_reasoning_override():
    messages_src = (REPO_ROOT / "static" / "messages.js").read_text(encoding="utf-8")
    start_idx = messages_src.find("api('/api/chat/start'")
    assert start_idx >= 0
    start_block = messages_src[start_idx : start_idx + 2500]
    assert "reasoning_effort" not in start_block
    routes_src = inspect.getsource(routes._handle_chat_start)
    assert "reasoning_effort" not in routes_src
