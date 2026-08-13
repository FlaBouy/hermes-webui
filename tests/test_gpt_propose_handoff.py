"""Local GPT Voice → Biggy propose-only handoff (loopback gateway proxy)."""

from __future__ import annotations

import io
import json
from urllib.error import HTTPError, URLError

import api.gpt_propose_handoff as handoff
from api.routes import _handle_gpt_propose_status, _handle_gpt_propose_task


class _FakeHandler:
    def __init__(self, command="GET", body=b"{}"):
        self.command = command
        self.rfile = io.BytesIO(body)
        self.wfile = io.BytesIO()
        self.headers = {
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
        }
        self.status = None
        self.sent_headers = {}

    def send_response(self, status):
        self.status = status

    def send_header(self, key, value):
        self.sent_headers[key] = value

    def end_headers(self):
        pass

    def payload(self):
        return json.loads(self.wfile.getvalue().decode("utf-8"))


def test_gateway_status_ready_when_healthy(monkeypatch, tmp_path):
    token_file = tmp_path / "tok"
    token_file.write_text("test-token\n", encoding="utf-8")
    monkeypatch.setenv("GPT_BIGGY_PROPOSE_TOKEN_FILE", str(token_file))

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(
                {"ok": True, "propose_only": True, "service": "gpt-biggy-propose-only"}
            ).encode("utf-8")

    monkeypatch.setattr(handoff.urllib.request, "urlopen", lambda *a, **k: _Resp())
    status = handoff.gateway_status()
    assert status["ready"] is True
    assert status["token_configured"] is True
    assert "test-token" not in json.dumps(status)


def test_propose_strips_dispose_fields_and_returns_speak(monkeypatch, tmp_path):
    token_file = tmp_path / "tok"
    token_file.write_text("test-token\n", encoding="utf-8")
    monkeypatch.setenv("GPT_BIGGY_PROPOSE_TOKEN_FILE", str(token_file))
    captured = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(
                {
                    "ok": True,
                    "pending_owner_ack": True,
                    "proposal_id": "ACK-TEST-1",
                    "status": "pending_owner_ack",
                    "speak": "Staged for Owner approval. Nothing has started.",
                    "confirmation": "Staged for Owner approval. Nothing has started.",
                    "lane": "cursor",
                    "target_machine": "THUNDERDOME",
                }
            ).encode("utf-8")

    def _urlopen(req, timeout=45):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.headers)
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _Resp()

    monkeypatch.setattr(handoff.urllib.request, "urlopen", _urlopen)
    out = handoff.propose_task(
        {
            "title": "lifecycle smoke",
            "prompt": "harmless tracking test",
            "lane": "cursor",
            "approve": True,
            "reject": False,
            "enqueue": True,
            "start_worker": True,
        }
    )
    assert out["ok"] is True
    assert out["pending_owner_ack"] is True
    assert out["proposal_id"] == "ACK-TEST-1"
    assert "Nothing has started" in out["speak"]
    assert "approve" not in captured["body"]
    assert "enqueue" not in captured["body"]
    assert "start_worker" not in captured["body"]
    assert "test-token" not in json.dumps(out)


def test_propose_fails_closed_when_gateway_down(monkeypatch, tmp_path):
    token_file = tmp_path / "tok"
    token_file.write_text("test-token\n", encoding="utf-8")
    monkeypatch.setenv("GPT_BIGGY_PROPOSE_TOKEN_FILE", str(token_file))

    def _boom(*a, **k):
        raise URLError("connection refused")

    monkeypatch.setattr(handoff.urllib.request, "urlopen", _boom)
    try:
        handoff.propose_task(
            {"title": "x", "prompt": "y", "lane": "cursor"}
        )
        assert False, "expected ProposeHandoffError"
    except handoff.ProposeHandoffError as exc:
        assert "not staged" in str(exc).lower()


def test_propose_fails_closed_without_token(monkeypatch, tmp_path):
    missing = tmp_path / "missing.token"
    monkeypatch.setenv("GPT_BIGGY_PROPOSE_TOKEN_FILE", str(missing))
    try:
        handoff.propose_task(
            {"title": "x", "prompt": "y", "lane": "cursor"}
        )
        assert False, "expected ProposeHandoffError"
    except handoff.ProposeHandoffError as exc:
        assert "not staged" in str(exc).lower()


def test_route_propose_returns_202(monkeypatch):
    monkeypatch.setattr(
        "api.routes._realtime_voice_auth_ok",
        lambda handler: True,
    )
    monkeypatch.setattr(
        "api.gpt_propose_handoff.propose_task",
        lambda body: {
            "ok": True,
            "pending_owner_ack": True,
            "proposal_id": "ACK-1",
            "speak": "Staged. Nothing started.",
            "confirmation": "Staged. Nothing started.",
            "message": "awaiting Owner ACK",
        },
    )
    body = json.dumps(
        {"title": "t", "prompt": "p", "lane": "cursor"}
    ).encode("utf-8")
    h = _FakeHandler(command="POST", body=body)
    assert _handle_gpt_propose_task(h) is True
    assert h.status == 202
    assert h.payload()["pending_owner_ack"] is True


def test_route_propose_503_fail_closed(monkeypatch):
    monkeypatch.setattr(
        "api.routes._realtime_voice_auth_ok",
        lambda handler: True,
    )

    def _fail(body):
        raise handoff.ProposeHandoffError("Propose gateway unavailable. Task was not staged.")

    monkeypatch.setattr("api.gpt_propose_handoff.propose_task", _fail)
    body = json.dumps(
        {"title": "t", "prompt": "p", "lane": "cursor"}
    ).encode("utf-8")
    h = _FakeHandler(command="POST", body=body)
    assert _handle_gpt_propose_task(h) is True
    assert h.status == 503
    payload = h.payload()
    assert payload["ok"] is False
    assert "not staged" in payload["speak"].lower()


def test_route_status_unauthorized(monkeypatch):
    monkeypatch.setattr(
        "api.routes._realtime_voice_auth_ok",
        lambda handler: False,
    )
    h = _FakeHandler(command="GET")
    _handle_gpt_propose_status(h)
    assert h.status == 401
    assert "unauthorized" in str(h.payload().get("error", "")).lower()


def test_http_error_401_mapped(monkeypatch, tmp_path):
    token_file = tmp_path / "tok"
    token_file.write_text("bad\n", encoding="utf-8")
    monkeypatch.setenv("GPT_BIGGY_PROPOSE_TOKEN_FILE", str(token_file))

    def _urlopen(req, timeout=45):
        raise HTTPError(req.full_url, 401, "unauthorized", hdrs=None, fp=io.BytesIO(b"{}"))

    monkeypatch.setattr(handoff.urllib.request, "urlopen", _urlopen)
    try:
        handoff.propose_task({"title": "t", "prompt": "p", "lane": "cursor"})
        assert False, "expected ProposeHandoffError"
    except handoff.ProposeHandoffError as exc:
        assert "not staged" in str(exc).lower()
