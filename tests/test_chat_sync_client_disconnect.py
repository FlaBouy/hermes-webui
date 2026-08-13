"""POST /api/chat releases its provider slot when the caller hangs up.

A synchronous turn blocks for as long as the model takes. Without a liveness
check the handler only notices an abandoned client when it writes the response,
so the upstream generation keeps its slot until the Agent's own request timeout
expires. A few abandoned turns exhaust every parallel slot on a local model
server and the model stops answering anyone.
"""

from __future__ import annotations

import json
import socket
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

import api.agent_runtime as agent_runtime
import api.config as config
import api.models as models
import api.routes as routes
from api.helpers import client_connection_lost
from api.models import Session


class _FakePostHandler:
    def __init__(self, connection=None):
        self.status = None
        self.headers = {}
        self.body = bytearray()
        self.wfile = self
        self.connection = connection

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
    # Keep the disconnect poll far below the test timeouts.
    monkeypatch.setattr(agent_runtime, "CLIENT_DISCONNECT_POLL_SECONDS", 0.02)
    monkeypatch.setattr(agent_runtime, "INTERRUPT_GRACE_SECONDS", 2.0)
    return tmp_path


def _make_session(tmp_path, session_id):
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


def _socketpair(request, *, close_client: bool):
    """Return a live server-side socket, optionally with the peer hung up."""
    client, server = socket.socketpair()
    request.addfinalizer(server.close)
    if close_client:
        client.close()
    else:
        request.addfinalizer(client.close)
    return server


def _install_blocking_agent(monkeypatch, *, supports_interrupt: bool, release):
    """Install an agent whose turn only ends when interrupted (or released)."""

    class BlockingAgent:
        latest = None

        def __init__(self, **kwargs):
            self.kwargs = dict(kwargs)
            self.interrupted = None
            self.started = threading.Event()
            BlockingAgent.latest = self

        def run_conversation(self, **kwargs):
            self.started.set()
            if not release.wait(10):
                raise AssertionError("agent turn was never released")
            return {
                "messages": [
                    {"role": "user", "content": kwargs.get("persist_user_message", "")},
                    {"role": "assistant", "content": "ok"},
                ],
                "final_response": "ok",
                "completed": True,
            }

        if supports_interrupt:

            def interrupt(self, reason=None):
                self.interrupted = reason
                release.set()

    monkeypatch.setitem(
        sys.modules, "run_agent", SimpleNamespace(AIAgent=BlockingAgent)
    )
    return BlockingAgent


# ── the primitive ──────────────────────────────────────────────────────────


def test_client_connection_lost_detects_a_closed_peer(request):
    assert client_connection_lost(_FakePostHandler(_socketpair(request, close_client=True)))


def test_client_connection_lost_is_false_for_a_live_peer(request):
    assert not client_connection_lost(
        _FakePostHandler(_socketpair(request, close_client=False))
    )


def test_client_connection_lost_is_false_without_a_socket():
    assert not client_connection_lost(_FakePostHandler())


def test_client_connection_lost_is_false_for_a_pipelined_request(request):
    client, server = socket.socketpair()
    request.addfinalizer(server.close)
    request.addfinalizer(client.close)
    client.sendall(b"POST /api/chat HTTP/1.1\r\n")
    # Readable, but with data rather than EOF: the caller is still there.
    assert not client_connection_lost(_FakePostHandler(server))


# ── the endpoint ───────────────────────────────────────────────────────────


def test_sync_chat_interrupts_the_agent_when_the_client_hangs_up(
    sync_chat_env, monkeypatch, request
):
    tmp_path = sync_chat_env
    session = _make_session(tmp_path, "sync_disconnect_session")
    release = threading.Event()
    agent_cls = _install_blocking_agent(
        monkeypatch, supports_interrupt=True, release=release
    )

    handler = _FakePostHandler(_socketpair(request, close_client=True))
    routes._handle_chat_sync(
        handler,
        {
            "session_id": session.session_id,
            "message": "voice check",
            "workspace": str(tmp_path),
        },
    )

    # Before the disconnect guard the turn ran to its own completion and the
    # provider slot stayed busy; the interrupt is the whole point of the fix.
    assert agent_cls.latest.interrupted == "Client disconnected"


def test_sync_chat_does_not_interrupt_a_connected_client(
    sync_chat_env, monkeypatch, request
):
    tmp_path = sync_chat_env
    session = _make_session(tmp_path, "sync_connected_session")
    release = threading.Event()
    release.set()  # a live client's turn finishes on its own
    agent_cls = _install_blocking_agent(
        monkeypatch, supports_interrupt=True, release=release
    )

    handler = _FakePostHandler(_socketpair(request, close_client=False))
    routes._handle_chat_sync(
        handler,
        {
            "session_id": session.session_id,
            "message": "typed chat",
            "workspace": str(tmp_path),
        },
    )

    assert handler.status == 200
    assert agent_cls.latest.interrupted is None


def test_sync_chat_runs_inline_without_a_client_socket(sync_chat_env, monkeypatch):
    tmp_path = sync_chat_env
    session = _make_session(tmp_path, "sync_inline_session")
    release = threading.Event()
    release.set()
    agent_cls = _install_blocking_agent(
        monkeypatch, supports_interrupt=True, release=release
    )

    handler = _FakePostHandler()
    routes._handle_chat_sync(
        handler,
        {
            "session_id": session.session_id,
            "message": "in-process caller",
            "workspace": str(tmp_path),
        },
    )

    assert handler.status == 200
    assert agent_cls.latest.interrupted is None


def test_sync_chat_fails_closed_when_the_agent_cannot_be_interrupted(
    sync_chat_env, monkeypatch, request
):
    tmp_path = sync_chat_env
    session = _make_session(tmp_path, "sync_no_interrupt_session")
    release = threading.Event()
    request.addfinalizer(release.set)  # let the abandoned worker unwind
    _install_blocking_agent(monkeypatch, supports_interrupt=False, release=release)

    handler = _FakePostHandler(_socketpair(request, close_client=True))
    routes._handle_chat_sync(
        handler,
        {
            "session_id": session.session_id,
            "message": "voice check",
            "workspace": str(tmp_path),
        },
    )

    assert handler.status == 499
    assert handler.json_body()["error"] == "client disconnected"
