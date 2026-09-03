"""Actual Project Review tool-loop verification (not routing-only simulations).

Distinguishes:
- Deterministic regression: scripted model transport + real start_session_turn +
  real streaming runner + real MCP ``project_review_extract_capabilities``.
- Opt-in local-model smoke (``HERMES_WEBUI_LOCAL_MODEL_SMOKE=1``): same path
  against LM Studio, pinned to the live review model ``qwen/qwen3.8-27b`` with
  ``provider=lmstudio``. Normal CI must not invoke local LMs.

Routing-only dialog tests that mock ``start_session_turn`` live elsewhere and
are labeled ROUTING SIMULATION — they do not prove tool-loop completion.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

import api.config as config
import api.models as models
import api.profiles as profiles
import api.routes as routes

CAPABILITIES_TOOL = "mcp__smedley_project_review__project_review_extract_capabilities"
MCP_SERVER = "smedley_project_review"
LIVE_REVIEW_MODEL = "qwen/qwen3.8-27b"
LIVE_REVIEW_PROVIDER = "lmstudio"
DEFAULT_LM_BASE = "http://127.0.0.1:1234/v1"
LOCAL_SMOKE_ENV = "HERMES_WEBUI_LOCAL_MODEL_SMOKE"

REPO_ROOT = Path(__file__).resolve().parents[1]


def _discover_agent_dir() -> Path | None:
    try:
        from tests.conftest import HERMES_AGENT
        if HERMES_AGENT and Path(HERMES_AGENT).is_dir():
            return Path(HERMES_AGENT)
    except Exception:
        pass
    candidates = [
        os.getenv("HERMES_WEBUI_AGENT_DIR", ""),
        str(Path.home() / ".hermes" / "hermes-agent"),
        str(REPO_ROOT.parent / "hermes-agent"),
    ]
    for raw in candidates:
        if not raw:
            continue
        path = Path(raw).expanduser()
        if path.is_dir() and (path / "run_agent.py").is_file():
            return path.resolve()
    return None


def _discover_webui_python() -> Path:
    explicit = os.getenv("HERMES_WEBUI_PYTHON", "").strip()
    if explicit:
        return Path(explicit).expanduser()
    for sub, name in (("bin", "python"), ("Scripts", "python.exe")):
        candidate = REPO_ROOT / ".venv" / sub / name
        if candidate.is_file():
            return candidate
    return Path(sys.executable)


AGENT_DIR = _discover_agent_dir()
WEBUI_PYTHON = _discover_webui_python()
MCP_SCRIPT = REPO_ROOT / "scripts" / "smedley_project_review_mcp.py"


def _agent_site_packages(agent_dir: Path) -> list[Path]:
    """Prefer ``venv`` over ``.venv``; keep packages matching a working openai import."""
    found: list[Path] = []
    for venv_name in ("venv", ".venv"):
        for site in sorted((agent_dir / venv_name / "lib").glob("python*/site-packages")):
            found.append(site)
    if not found:
        return []
    # Prefer the first site-packages that can import openai without ABI errors.
    for site in found:
        probe = [
            sys.executable,
            "-c",
            "import sys; sys.path.insert(0, sys.argv[1]); import openai",
            str(site),
        ]
        try:
            import subprocess

            completed = subprocess.run(probe, capture_output=True, text=True, timeout=20)
            if completed.returncode == 0:
                return [site]
        except Exception:
            continue
    return [found[0]]


def _ensure_agent_site_packages() -> None:
    """WebUI .venv may lack openai/hermes_logging; pin agent runtime on sys.path."""
    if AGENT_DIR is None:
        return
    agent_home = str(AGENT_DIR)
    if agent_home in sys.path:
        sys.path.remove(agent_home)
    sys.path.insert(0, agent_home)
    # Drop any previously injected agent site-packages that may be ABI-incompatible.
    for entry in list(sys.path):
        if "/hermes-agent/" in entry.replace("\\", "/") and entry.endswith("site-packages"):
            try:
                sys.path.remove(entry)
            except ValueError:
                pass
    for idx, site in enumerate(_agent_site_packages(AGENT_DIR)):
        path = str(site)
        if path in sys.path:
            sys.path.remove(path)
        sys.path.insert(1 + idx, path)


_ensure_agent_site_packages()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _sse_chunks(events: list[dict]) -> bytes:
    parts = [f"data: {json.dumps(event)}\n\n".encode("utf-8") for event in events]
    parts.append(b"data: [DONE]\n\n")
    return b"".join(parts)


class _ScriptedOpenAIHandler(BaseHTTPRequestHandler):
    """Minimal OpenAI-compatible chat completions for deterministic tool loops."""

    server_version = "ScriptedOpenAI/1.0"
    calls: list

    def log_message(self, format, *args):  # noqa: A003
        return

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/v1/models"):
            body = json.dumps({"data": [{"id": "scripted-tool-model", "object": "model"}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def _has_tool_result(self, messages: list) -> bool:
        for m in messages:
            if str(m.get("role") or "") == "tool":
                return True
            content = m.get("content")
            if isinstance(content, str) and "callable" in content.lower():
                return True
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") in {
                        "tool_result",
                        "function_call_output",
                    }:
                        return True
        return False

    def _write_json(self, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _write_sse(self, events: list[dict]) -> None:
        body = _sse_chunks(events)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            payload = {}
        type(self).calls.append({"path": self.path, "payload": payload})
        if not self.path.startswith("/v1/chat/completions"):
            self.send_response(404)
            self.end_headers()
            return

        messages = payload.get("messages") or []
        tools = payload.get("tools") or []
        stream = bool(payload.get("stream"))
        has_tool_result = self._has_tool_result(messages)

        if not tools:
            text = "scripted-title"
            if stream:
                self._write_sse([
                    {
                        "id": "chatcmpl-scripted-aux",
                        "object": "chat.completion.chunk",
                        "choices": [{"index": 0, "delta": {"role": "assistant", "content": text}, "finish_reason": None}],
                    },
                    {
                        "id": "chatcmpl-scripted-aux",
                        "object": "chat.completion.chunk",
                        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                    },
                ])
            else:
                self._write_json({
                    "id": "chatcmpl-scripted-aux",
                    "object": "chat.completion",
                    "choices": [{
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": text},
                    }],
                })
            return

        if not has_tool_result:
            if stream:
                self._write_sse([
                    {
                        "id": "chatcmpl-scripted-1",
                        "object": "chat.completion.chunk",
                        "choices": [{
                            "index": 0,
                            "delta": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [{
                                    "index": 0,
                                    "id": "call_capabilities_1",
                                    "type": "function",
                                    "function": {"name": CAPABILITIES_TOOL, "arguments": ""},
                                }],
                            },
                            "finish_reason": None,
                        }],
                    },
                    {
                        "id": "chatcmpl-scripted-1",
                        "object": "chat.completion.chunk",
                        "choices": [{
                            "index": 0,
                            "delta": {
                                "tool_calls": [{
                                    "index": 0,
                                    "function": {"arguments": "{}"},
                                }],
                            },
                            "finish_reason": None,
                        }],
                    },
                    {
                        "id": "chatcmpl-scripted-1",
                        "object": "chat.completion.chunk",
                        "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
                    },
                ])
            else:
                self._write_json({
                    "id": "chatcmpl-scripted-1",
                    "object": "chat.completion",
                    "choices": [{
                        "index": 0,
                        "finish_reason": "tool_calls",
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [{
                                "id": "call_capabilities_1",
                                "type": "function",
                                "function": {"name": CAPABILITIES_TOOL, "arguments": "{}"},
                            }],
                        },
                    }],
                })
            return

        final = (
            "Capabilities tool returned callable=true for "
            "project_review_extract_capabilities; no extraction performed."
        )
        if stream:
            self._write_sse([
                {
                    "id": "chatcmpl-scripted-2",
                    "object": "chat.completion.chunk",
                    "choices": [{
                        "index": 0,
                        "delta": {"role": "assistant", "content": final},
                        "finish_reason": None,
                    }],
                },
                {
                    "id": "chatcmpl-scripted-2",
                    "object": "chat.completion.chunk",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                },
            ])
        else:
            self._write_json({
                "id": "chatcmpl-scripted-2",
                "object": "chat.completion",
                "choices": [{
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": final},
                }],
            })


def _start_scripted_server():
    port = _free_port()
    _ScriptedOpenAIHandler.calls = []
    server = ThreadingHTTPServer(("127.0.0.1", port), _ScriptedOpenAIHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{port}/v1"


def _write_smedley_profile_home(
    base: Path,
    *,
    base_url: str,
    model: str,
    provider: str,
    state_dir: Path,
) -> Path:
    """Create ``base/profiles/smedley`` so named-profile resolution stays isolated."""
    home = base / "profiles" / "smedley"
    home.mkdir(parents=True)
    config_doc = {
        "model": {
            "provider": provider,
            "default": model,
            "base_url": base_url,
            "api_key": "local-test-key",
        },
        "mcp_servers": {
            MCP_SERVER: {
                "command": str(WEBUI_PYTHON),
                "args": [str(MCP_SCRIPT)],
                "env": {
                    "HERMES_WEBUI_STATE_DIR": str(state_dir),
                },
                "connect_timeout": 45.0,
                "enabled": True,
                "tools": {
                    "include": ["project_review_extract_capabilities"],
                    "resources": False,
                    "prompts": False,
                },
            }
        },
        "platform_toolsets": {
            "cli": [MCP_SERVER],
        },
        "agent": {
            "enabled_toolsets": [MCP_SERVER],
        },
    }
    if provider == "custom":
        config_doc["providers"] = {
            "custom": {"base_url": base_url, "api_key": "local-test-key"},
        }
    (home / "config.yaml").write_text(yaml.safe_dump(config_doc), encoding="utf-8")
    (home / ".env").write_text("OPENAI_API_KEY=local-test-key\n", encoding="utf-8")
    return home


def _bind_isolated_smedley_home(
    monkeypatch,
    tmp_path,
    *,
    base_url: str,
    model: str,
    provider: str,
):
    state = tmp_path / "webui-state"
    sessions = state / "sessions"
    sessions.mkdir(parents=True)
    biggy_state = tmp_path / "biggy-webui-state"
    biggy_state.mkdir()
    (biggy_state / "projects.json").write_text("[]", encoding="utf-8")

    base = tmp_path / ".hermes"
    hermes_home = _write_smedley_profile_home(
        base,
        base_url=base_url,
        model=model,
        provider=provider,
        state_dir=biggy_state,
    )

    monkeypatch.setenv("HERMES_BASE_HOME", str(base))
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    if AGENT_DIR is not None:
        monkeypatch.setenv("HERMES_WEBUI_AGENT_DIR", str(AGENT_DIR))
    monkeypatch.setenv("HERMES_WEBUI_STATE_DIR", str(state))
    monkeypatch.setenv("OPENAI_API_KEY", "local-test-key")
    monkeypatch.setattr(profiles, "_DEFAULT_HERMES_HOME", base)
    monkeypatch.setattr(models, "SESSION_DIR", sessions)
    monkeypatch.setattr(models, "SESSION_INDEX_FILE", state / "session_index.json")
    monkeypatch.setattr(routes, "SESSION_INDEX_FILE", state / "session_index.json")
    monkeypatch.setattr(routes, "get_session", models.get_session)
    models.SESSIONS.clear()

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(routes, "resolve_trusted_workspace", lambda value: str(workspace))
    monkeypatch.setattr(config, "ACTIVE_RUNS", {})
    monkeypatch.setattr(config, "ACTIVE_RUNS_LOCK", threading.RLock())

    return {
        "base": base,
        "hermes_home": hermes_home,
        "state": state,
        "workspace": workspace,
        "model": model,
        "provider": provider,
        "base_url": base_url,
    }


@pytest.fixture
def isolated_review_runtime(tmp_path, monkeypatch):
    _ensure_agent_site_packages()
    if AGENT_DIR is None or not AGENT_DIR.is_dir():
        pytest.skip("hermes-agent checkout not discovered (set HERMES_WEBUI_AGENT_DIR)")
    if not MCP_SCRIPT.is_file():
        pytest.skip(f"MCP script missing at {MCP_SCRIPT}")

    server, base_url = _start_scripted_server()
    model = "scripted-tool-model"
    bound = _bind_isolated_smedley_home(
        monkeypatch,
        tmp_path,
        base_url=base_url,
        model=model,
        provider="custom",
    )

    session = models.Session(
        session_id=f"followthrough_{uuid.uuid4().hex[:10]}",
        workspace=str(bound["workspace"]),
        messages=[],
        context_messages=[],
        model=model,
        model_provider="custom",
        title="Smedley review tool-loop",
        profile="smedley",
    )
    session.enabled_toolsets = [MCP_SERVER]
    session.save(touch_updated_at=False)

    yield {
        "session": session,
        "server": server,
        **bound,
    }
    server.shutdown()


def _wait_session_idle(session_id: str, *, timeout_s: float = 120.0) -> models.Session:
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        last = models.get_session(session_id)
        streaming = bool(getattr(last, "is_streaming", False))
        active = getattr(last, "active_stream_id", None)
        if not streaming and not active:
            return last
        time.sleep(0.25)
    raise TimeoutError(
        f"session {session_id} still busy after {timeout_s}s "
        f"streaming={getattr(last, 'is_streaming', None)} active={getattr(last, 'active_stream_id', None)}"
    )


def _is_capabilities_tool_name(name: str) -> bool:
    value = str(name or "").strip()
    return value == CAPABILITIES_TOOL or value.endswith("project_review_extract_capabilities")


def _tool_result_succeeded(content: str) -> bool:
    text = str(content or "")
    lowered = text.lower()
    if not text.strip():
        return False
    if lowered.startswith("**error") or '"error"' in lowered:
        if "callable" not in lowered:
            return False
    # Capabilities payload is JSON-ish and should affirm callable tooling.
    return "callable" in lowered or '"ok"' in lowered or "project_review_extract" in lowered


def _capabilities_success_index(messages) -> int | None:
    """Index of successful role=tool capabilities result, or None."""
    for idx, m in enumerate(messages or []):
        if not isinstance(m, dict) or str(m.get("role") or "") != "tool":
            continue
        name = str(m.get("name") or m.get("tool_name") or "")
        if not _is_capabilities_tool_name(name):
            continue
        if _tool_result_succeeded(str(m.get("content") or "")):
            return idx
    return None


def _final_assistant_after(messages, after_idx: int) -> dict | None:
    for m in (messages or [])[after_idx + 1 :]:
        if not isinstance(m, dict):
            continue
        if str(m.get("role") or "") != "assistant":
            continue
        if m.get("_error") or m.get("tool_only"):
            continue
        if m.get("tool_calls"):
            continue
        content = str(m.get("content") or "").strip()
        if content:
            return m
    return None


def _message_roles_summary(messages) -> list[dict]:
    rows = []
    for m in messages or []:
        if not isinstance(m, dict):
            continue
        tool_names = []
        for tc in m.get("tool_calls") or []:
            if isinstance(tc, dict):
                fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
                tool_names.append(str(fn.get("name") or tc.get("name") or ""))
        rows.append({
            "role": m.get("role"),
            "name": m.get("name") or m.get("tool_name"),
            "tool_call_id": m.get("tool_call_id"),
            "tool_calls": tool_names,
            "error": bool(m.get("_error")),
            "content_prefix": str(m.get("content") or "")[:160],
        })
    return rows


def _assert_capabilities_tool_loop(messages, *, context: str) -> dict:
    roles = _message_roles_summary(messages)
    tool_idx = _capabilities_success_index(messages)
    assert tool_idx is not None, (
        f"{context}: missing successful role=tool capabilities result\nroles={roles}"
    )
    final = _final_assistant_after(messages, tool_idx)
    assert final is not None, (
        f"{context}: missing final assistant after capabilities tool result\nroles={roles}"
    )
    return {
        "tool_index": tool_idx,
        "final_excerpt": str(final.get("content") or "")[:240],
        "roles": roles,
    }


def test_start_session_turn_real_mcp_capabilities_tool_loop(isolated_review_runtime):
    """ACTUAL check: start_session_turn → runner → agent tool select → MCP capabilities → persist."""
    runtime = isolated_review_runtime
    session = runtime["session"]

    resolved = profiles.get_hermes_home_for_profile("smedley")
    assert Path(resolved) == Path(runtime["hermes_home"]), (
        f"profile home leaked outside isolation: {resolved} vs {runtime['hermes_home']}"
    )

    message = (
        "Project-review context for this reply:\n"
        "project_id: bdd341b152a4\n"
        "Configured Smedley MCP server name: smedley_project_review.\n"
        "Call project_review_extract_capabilities now. Do not extract files.\n\n"
        "Owner message: Call project_review_extract_capabilities only."
    )
    started = time.time()
    result = routes.start_session_turn(session.session_id, message, source="project_review")
    assert int(result.get("_status", 200) or 200) < 400, result

    finished = _wait_session_idle(session.session_id, timeout_s=180.0)
    duration_s = round(time.time() - started, 3)
    proof = _assert_capabilities_tool_loop(
        finished.messages,
        context="deterministic scripted tool-loop",
    )
    assert any(row["n_tools"] > 0 for row in [
        {"n_tools": len((c.get("payload") or {}).get("tools") or [])}
        for c in _ScriptedOpenAIHandler.calls
        if str(c.get("path") or "").startswith("/v1/chat/completions")
    ]), "scripted transport saw no tools on chat completions"
    # Evidence for report/log readers.
    print(
        "TOOL_LOOP_EVIDENCE "
        f"model={runtime['model']} provider={runtime['provider']} "
        f"base_url={runtime['base_url']} duration_s={duration_s} "
        f"tool_ok=true final_excerpt={proof['final_excerpt']!r}"
    )


def test_start_session_turn_review_context_budget_on_scripted_transport(isolated_review_runtime):
    """ACTUAL streaming: long review history outbound is evidence-summary only under budget."""
    from api.biggy_project_review_runtime import (
        REVIEW_CONTEXT_MAX_CHARS,
        REVIEW_MAX_ITERATIONS,
        build_review_agent_context_messages,
    )

    runtime = isolated_review_runtime
    session = runtime["session"]
    history = []
    for i in range(12):
        history.append({"role": "user", "content": f"Owner message: decision {i}"})
        history.append(
            {
                "role": "assistant",
                "content": "",
                "reasoning_content": "r" * 12000,
                "tool_calls": [
                    {
                        "id": f"id{i}a",
                        "type": "function",
                        "function": {
                            "name": "project_review_extract",
                            "arguments": json.dumps({"path": f"a{i}.pdf", "pad": "x" * 3000}),
                        },
                    },
                    {
                        "id": f"id{i}b",
                        "type": "function",
                        "function": {
                            "name": "project_review_extract",
                            "arguments": json.dumps({"path": f"b{i}.pdf", "pad": "y" * 3000}),
                        },
                    },
                ],
            }
        )
        history.append(
            {
                "role": "tool",
                "tool_call_id": f"id{i}a",
                "name": "project_review_extract",
                "content": json.dumps(
                    {
                        "ok": True,
                        "source": f"/p/a{i}.pdf",
                        "cells_verified": False,
                        "ocr_verification_state": "needs_review",
                    }
                ),
            }
        )
        history.append(
            {
                "role": "tool",
                "tool_call_id": f"id{i}b",
                "name": "project_review_extract",
                "content": json.dumps(
                    {"ok": False, "error": "source file not found", "source": f"/p/b{i}.pdf"}
                ),
            }
        )
    saved_messages = list(history)
    session.messages = list(saved_messages)
    # One-shot review binding (matches dialog path) — do not poison durable context.
    from api.biggy_project_review_runtime import set_project_review_turn_binding

    set_project_review_turn_binding(
        session.session_id,
        context_messages=build_review_agent_context_messages(saved_messages),
        max_iterations=REVIEW_MAX_ITERATIONS,
    )
    session.save(touch_updated_at=False)
    assert session.messages == saved_messages

    captured_agent = {}
    try:
        import run_agent as _run_agent

        real_init = _run_agent.AIAgent.__init__

        def _capture_init(self, *args, **kwargs):
            captured_agent["max_iterations"] = kwargs.get("max_iterations")
            return real_init(self, *args, **kwargs)

        _run_agent.AIAgent.__init__ = _capture_init
    except Exception:
        _run_agent = None
        real_init = None

    _ScriptedOpenAIHandler.calls = []
    try:
        message = (
            "Project-review context for this reply (CANONICAL):\n"
            "project_id: bdd341b152a4\n"
            "Configured Smedley MCP server name: smedley_project_review.\n"
            "Call project_review_extract_capabilities now. Do not extract files.\n\n"
            "Owner message: Call project_review_extract_capabilities only."
        )
        result = routes.start_session_turn(session.session_id, message, source="project_review")
        assert int(result.get("_status", 200) or 200) < 400, result
        finished = _wait_session_idle(session.session_id, timeout_s=180.0)

        # Full saved history preserved as prefix of display transcript.
        assert any(
            isinstance(m, dict) and m.get("content") == "Owner message: decision 0"
            for m in finished.messages
        ), finished.messages[:3]
        assert any(
            isinstance(m, dict) and m.get("content") == "Owner message: decision 11"
            for m in finished.messages
        )

        completion_calls = [
            c
            for c in _ScriptedOpenAIHandler.calls
            if str(c.get("path") or "").startswith("/v1/chat/completions")
        ]
        assert completion_calls, "expected scripted chat completions"
        first_payload = completion_calls[0].get("payload") or {}
        outbound = first_payload.get("messages") or []
        serialized = json.dumps(outbound, default=str)
        assert "r" * 1000 not in serialized
        assert "id0a" not in serialized
        assert "Prior tool evidence" in serialized or "cells_verified=False" in serialized
        assert len(serialized) < max(REVIEW_CONTEXT_MAX_CHARS * 3, 200_000)
        if captured_agent.get("max_iterations") is not None:
            assert int(captured_agent["max_iterations"]) <= REVIEW_MAX_ITERATIONS
        _assert_capabilities_tool_loop(finished.messages, context="budgeted long-history tool-loop")
    finally:
        if _run_agent is not None and real_init is not None:
            _run_agent.AIAgent.__init__ = real_init


def test_empty_profile_provider_does_not_route_live_review_model_to_openrouter():
    """Failing-before class: null provider + qwen/ slash id must not invent OpenRouter."""
    old = dict(config.cfg)
    try:
        config.cfg["model"] = {}
        resolved_model, resolved_provider, resolved_base = config.resolve_model_provider(LIVE_REVIEW_MODEL)
    finally:
        config.cfg.clear()
        config.cfg.update(old)
    assert resolved_model == LIVE_REVIEW_MODEL
    assert resolved_provider != "openrouter", (
        f"empty model.provider selected paid path: provider={resolved_provider!r} base_url={resolved_base!r}"
    )
    assert resolved_provider in (None, ""), resolved_provider
    assert resolved_base in (None, ""), resolved_base


def test_local_model_smoke_capabilities_or_report_blocker(tmp_path, monkeypatch):
    """BOUNDED SMOKE: opt-in only; pinned live review model + lmstudio; no fallback model."""
    import urllib.request

    _ensure_agent_site_packages()
    if os.getenv(LOCAL_SMOKE_ENV, "").strip() not in {"1", "true", "yes", "on"}:
        pytest.skip(
            f"local-model smoke disabled (set {LOCAL_SMOKE_ENV}=1 to opt in; "
            "CI must not opportunistically invoke local LMs)"
        )

    lm_base = (os.getenv("HERMES_WEBUI_LOCAL_MODEL_BASE_URL") or DEFAULT_LM_BASE).rstrip("/")
    try:
        with urllib.request.urlopen(f"{lm_base}/models", timeout=3) as resp:
            models_payload = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        pytest.fail(
            f"local smoke opted in but endpoint unavailable: base_url={lm_base} "
            f"{type(exc).__name__}: {exc}"
        )

    ids = [row.get("id") for row in (models_payload.get("data") or []) if isinstance(row, dict)]
    if LIVE_REVIEW_MODEL not in ids:
        pytest.fail(
            f"local smoke opted in but pinned model {LIVE_REVIEW_MODEL!r} is not loaded; "
            f"base_url={lm_base}; available={ids[:20]!r}"
        )

    if AGENT_DIR is None or not AGENT_DIR.is_dir():
        pytest.fail(f"local smoke opted in but hermes-agent not discovered")
    if not MCP_SCRIPT.is_file():
        pytest.fail(f"local smoke opted in but MCP script missing: {MCP_SCRIPT}")

    # Prove resolver keeps lmstudio for the live review model under isolated profile config.
    bound = _bind_isolated_smedley_home(
        monkeypatch,
        tmp_path,
        base_url=lm_base,
        model=LIVE_REVIEW_MODEL,
        provider=LIVE_REVIEW_PROVIDER,
    )
    old_cfg = dict(config.cfg)
    try:
        config.cfg.clear()
        config.cfg.update(yaml.safe_load((Path(bound["hermes_home"]) / "config.yaml").read_text()) or {})
        rm, rp, rbase = config.resolve_model_provider(LIVE_REVIEW_MODEL)
    finally:
        config.cfg.clear()
        config.cfg.update(old_cfg)
    assert rp == LIVE_REVIEW_PROVIDER, (
        f"resolver did not keep lmstudio for live review model: model={rm} provider={rp} base={rbase}"
    )
    assert rbase == lm_base or (rbase or "").rstrip("/") == lm_base, (
        f"resolver base_url mismatch: got={rbase!r} expected={lm_base!r}"
    )
    assert rp != "openrouter"

    session = models.Session(
        session_id=f"smoke_{uuid.uuid4().hex[:10]}",
        workspace=str(bound["workspace"]),
        messages=[],
        model=LIVE_REVIEW_MODEL,
        model_provider=LIVE_REVIEW_PROVIDER,  # live session has null; smoke pins intended local path
        title="smoke capabilities live-review model",
        profile="smedley",
    )
    session.enabled_toolsets = [MCP_SERVER]
    session.save(touch_updated_at=False)

    # Also cover null provider under profile that HAS lmstudio model block (post-remediation shape).
    # The session above pins provider explicitly to match intended local settings after remediation.
    prompt = (
        f"Call {CAPABILITIES_TOOL} exactly once with empty arguments, then stop. "
        "Do not call get_prompt, list_prompts, list_resources, or project_review_extract. "
        "Do not write files."
    )
    started = time.time()
    result = routes.start_session_turn(session.session_id, prompt, source="project_review")
    if int(result.get("_status", 200) or 200) >= 400:
        pytest.fail(
            f"start_session_turn failed for local smoke: model={LIVE_REVIEW_MODEL} "
            f"provider={LIVE_REVIEW_PROVIDER} base_url={lm_base} result={result}"
        )

    try:
        finished = _wait_session_idle(session.session_id, timeout_s=300.0)
    except TimeoutError as exc:
        pytest.fail(
            f"local-model smoke timed out: model={LIVE_REVIEW_MODEL} "
            f"provider={LIVE_REVIEW_PROVIDER} base_url={lm_base}: {exc}"
        )

    duration_s = round(time.time() - started, 3)
    proof = _assert_capabilities_tool_loop(
        finished.messages,
        context=(
            f"local smoke model={LIVE_REVIEW_MODEL} provider={LIVE_REVIEW_PROVIDER} "
            f"base_url={lm_base}"
        ),
    )
    print(
        "LOCAL_SMOKE_EVIDENCE "
        f"model={LIVE_REVIEW_MODEL} provider={LIVE_REVIEW_PROVIDER} "
        f"base_url={lm_base} duration_s={duration_s} tool_ok=true "
        f"final_excerpt={proof['final_excerpt']!r}"
    )
