"""Project-review dialog lifecycle stays honest across server-side turns."""

from __future__ import annotations

import threading
from types import SimpleNamespace

from api import config, jarvis_rag_ingest_events, routes


def _session(*, streaming: bool = False):
    return SimpleNamespace(
        session_id="review-session",
        messages=[{"role": "user", "content": "Owner message: What discrepancy is that?"}],
        is_streaming=streaming,
        active_stream_id="stream-1" if streaming else None,
    )


def test_project_review_dialog_surfaces_running_turn(monkeypatch):
    monkeypatch.setattr(routes, "SERVER_START_TIME", 1)
    monkeypatch.setattr(
        routes,
        "read_turn_journal",
        lambda _session_id: {
            "events": [
                {
                    "event": "worker_started",
                    "turn_id": "turn-1",
                    "stream_id": "stream-1",
                    "created_at": 2,
                }
            ]
        },
    )

    dialog = routes._biggy_project_review_dialog_payload(_session(streaming=True))

    assert dialog["is_streaming"] is True
    assert dialog["status"] == "running"
    assert "working" in dialog["status_message"].lower()


def test_project_review_dialog_surfaces_interrupted_orphan_after_restart(monkeypatch):
    monkeypatch.setattr(routes, "SERVER_START_TIME", 3)
    monkeypatch.setattr(
        routes,
        "read_turn_journal",
        lambda _session_id: {
            "events": [
                {
                    "event": "submitted",
                    "turn_id": "turn-1",
                    "stream_id": "stream-1",
                    "created_at": 1,
                },
                {
                    "event": "worker_started",
                    "turn_id": "turn-1",
                    "stream_id": "stream-1",
                    "created_at": 2,
                },
            ]
        },
    )

    dialog = routes._biggy_project_review_dialog_payload(_session(streaming=True))

    assert dialog["is_streaming"] is False
    assert dialog["status"] == "interrupted"
    assert "interrupted" in dialog["status_message"].lower()
    assert "retry" in dialog["status_message"].lower()


def test_project_review_retry_reconciles_stale_flags_without_losing_transcript(monkeypatch):
    saved = []
    messages = [
        {"role": "assistant", "content": "Original review findings"},
        {"role": "user", "content": "Owner message: What discrepancy is that?"},
    ]
    session = SimpleNamespace(
        session_id="review-session",
        profile="smedley",
        messages=list(messages),
        active_stream_id="stale-stream",
        is_streaming=True,
        pending_user_message=None,
        pending_attachments=[],
        pending_started_at=1,
        pending_user_source="project_review",
        save=lambda **kwargs: saved.append(kwargs),
    )
    monkeypatch.setattr(routes, "STREAMS", {})
    monkeypatch.setattr(routes, "STREAMS_LOCK", threading.RLock())
    monkeypatch.setattr(config, "ACTIVE_RUNS", {})
    monkeypatch.setattr(config, "ACTIVE_RUNS_LOCK", threading.RLock())

    assert routes._clear_stale_stream_state(session) is True

    assert session.active_stream_id is None
    assert session.pending_user_source is None
    assert session.messages == messages
    assert saved == [{"touch_updated_at": False}]


def test_project_review_dialog_completed_turn_has_no_failure_banner(monkeypatch):
    monkeypatch.setattr(
        routes,
        "read_turn_journal",
        lambda _session_id: {
            "events": [
                {
                    "event": "completed",
                    "turn_id": "turn-1",
                    "stream_id": "stream-1",
                    "created_at": 3,
                }
            ]
        },
    )

    dialog = routes._biggy_project_review_dialog_payload(_session())

    assert dialog["status"] == "completed"
    assert dialog["status_message"] == ""


def test_visible_fast_reply_supersedes_stale_nonterminal_journal(monkeypatch):
    session = _session(streaming=False)
    session.messages.append({
        "role": "assistant",
        "content": "DXF can be parsed after the governed parser is provisioned.",
        "timestamp": 20,
        "project_review_fast_route": True,
    })
    monkeypatch.setattr(routes, "SERVER_START_TIME", 30)
    monkeypatch.setattr(
        routes,
        "read_turn_journal",
        lambda _session_id: {
            "events": [{
                "event": "worker_started",
                "turn_id": "turn-stale",
                "stream_id": "stream-stale",
                "created_at": 10,
            }]
        },
    )

    dialog = routes._biggy_project_review_dialog_payload(session)

    assert dialog["status"] == "completed"
    assert dialog["status_message"] == ""


def test_project_review_readiness_fails_closed_until_every_document_is_verified(tmp_path, monkeypatch):
    folder = tmp_path / "Projects" / "Projects - 2026" / "26HOS-006"
    folder.mkdir(parents=True)
    first = folder / "drawing.pdf"
    second = folder / "schedule.pdf"
    first.write_bytes(b"pdf-one")
    second.write_bytes(b"pdf-two")
    monkeypatch.setattr(jarvis_rag_ingest_events, "LIBRARY_ROOT", str(tmp_path))
    monkeypatch.setattr(jarvis_rag_ingest_events, "load_ledger", lambda: {"files": {
        str(first.resolve()): {"phase": "indexed", "quality_state": "verified"},
        str(second.resolve()): {"phase": "needs_review", "quality_state": "needs_review",
                                "warnings": ["low OCR yield"]},
    }})

    result = jarvis_rag_ingest_events.folder_ingest_readiness(
        "Projects/Projects - 2026/26HOS-006"
    )

    assert result["ready"] is False
    assert result["state"] == "needs_review"
    assert result["counts"] == {
        "verified": 1, "processing": 0, "needs_review": 1,
        "failed": 0, "unverified": 0,
    }


def test_full_ocr_manifest_is_not_approval_grade_without_independent_verification(tmp_path, monkeypatch):
    folder = tmp_path / "Projects" / "Projects - 2026" / "ocr-review"
    folder.mkdir(parents=True)
    drawing = folder / "vendor-drawing.pdf"
    drawing.write_bytes(b"pdf")
    monkeypatch.setattr(jarvis_rag_ingest_events, "LIBRARY_ROOT", str(tmp_path))
    monkeypatch.setattr(jarvis_rag_ingest_events, "load_ledger", lambda: {"files": {
        str(drawing.resolve()): {
            "phase": "indexed",
            "quality_state": "verified",
            "extraction_mode": "full_ocr",
            "table_rows": 42,
        },
    }})

    result = jarvis_rag_ingest_events.folder_ingest_readiness(
        "Projects/Projects - 2026/ocr-review"
    )

    assert result["ready"] is False
    assert result["state"] == "needs_review"
    assert "independent" in result["reason"].lower()
    assert result["documents"][0]["state"] == "needs_review"


def test_cross_checked_full_ocr_manifest_can_pass_project_review_gate(tmp_path, monkeypatch):
    folder = tmp_path / "Projects" / "Projects - 2026" / "ocr-reviewed"
    folder.mkdir(parents=True)
    drawing = folder / "vendor-drawing.pdf"
    drawing.write_bytes(b"pdf")
    monkeypatch.setattr(jarvis_rag_ingest_events, "LIBRARY_ROOT", str(tmp_path))
    monkeypatch.setattr(jarvis_rag_ingest_events, "load_ledger", lambda: {"files": {
        str(drawing.resolve()): {
            "phase": "indexed",
            "quality_state": "verified",
            "extraction_mode": "full_ocr",
            "ocr_verification_state": "cross_checked",
        },
    }})

    result = jarvis_rag_ingest_events.folder_ingest_readiness(
        "Projects/Projects - 2026/ocr-reviewed"
    )

    assert result["ready"] is True
    assert result["state"] == "verified"


def _review_project(session_id="a09c02f318be"):
    return {
        "project_id": "bdd341b152a4",
        "name": "26HOS-006",
        "profile": "biggy",
        "review": {
            "review_owner": "smedley",
            "review_type": "internal-design",
            "rag_folder": "Projects/Projects - 2026/26HOS-006",
            "session_id": session_id,
            "state": "in_review",
            "sources": {
                "plant_specifications": "plant",
                "code_books": "nec",
                "design_package": "pkg",
            },
            "scope": "governance review",
        },
    }


class _DialogHandler:
    def __init__(self, payload: dict):
        import io
        import json as _json

        raw = _json.dumps(payload).encode("utf-8")
        self.rfile = io.BytesIO(raw)
        self.wfile = io.BytesIO()
        self.headers = {"Content-Type": "application/json", "Content-Length": str(len(raw))}
        self.status = None
        self.sent_headers = {}
        self.close_connection = False

    def send_response(self, status):
        self.status = status

    def send_header(self, key, value):
        self.sent_headers[key] = value

    def end_headers(self):
        pass

    def payload(self):
        import json as _json

        return _json.loads(self.wfile.getvalue().decode("utf-8"))


def _post_review_dialog(monkeypatch, *, message: str, session, capture: dict, readiness_check=None,
                        fast_reply=None, request_id=None):
    """ROUTING SIMULATION only — stubs start_session_turn; does not prove tool-loop completion."""
    from urllib.parse import urlparse

    project = _review_project(session.session_id)
    monkeypatch.setattr(routes, "load_projects", lambda: [project])
    monkeypatch.setattr(routes, "save_projects", lambda _projects: None)
    monkeypatch.setattr(routes, "get_session", lambda _sid: session)
    monkeypatch.setattr(routes, "_clear_stale_stream_state", lambda _session: False)
    monkeypatch.setattr(
        jarvis_rag_ingest_events,
        "folder_ingest_readiness",
        readiness_check or (lambda _folder: {"state": "needs_review", "reason": "OCR needs review", "ready": False}),
    )

    def _fast_reply(prompt, history=None, personality="smedley", system_context="", history_rows=4):
        capture["fast_calls"].append({
            "prompt": prompt,
            "system_context": system_context,
            "personality": personality,
            "history_len": len(history or []),
        })
        return {"reply": "Fast conversational answer about the transcript.", "model": "v6-test"}

    def _start_turn(session_id, message_text, source="project_review"):
        capture["governed_calls"].append(
            {"session_id": session_id, "message": message_text, "source": source}
        )
        # Do not fabricate tool results here — that is not tool-loop evidence.
        session.is_streaming = True
        session.active_stream_id = "stream-governed-sim"
        return {"ok": True, "_status": 200, "session_id": session_id, "stream_id": "stream-governed-sim"}

    import api.biggy_voice_route as voice

    monkeypatch.setattr(voice, "request_fast_voice_reply", fast_reply or _fast_reply)
    monkeypatch.setattr(routes, "start_session_turn", _start_turn)

    monkeypatch.setattr(
        routes,
        "_biggy_project_review_dialog_payload",
        lambda s: {
            "session_id": s.session_id,
            "messages": list(s.messages or []),
            "is_streaming": bool(getattr(s, "is_streaming", False)),
            "status": "running" if getattr(s, "is_streaming", False) else "completed",
            "status_message": "",
        },
    )

    handler = _DialogHandler({"project_id": "bdd341b152a4", "message": message,
                              "request_id": request_id})
    parsed = urlparse("/api/biggy/projects/reviews/dialog")
    routes.handle_post(handler, parsed)
    return handler, project


def test_sync_review_is_durable_before_execution_and_retry_is_idempotent(monkeypatch):
    import copy
    saved = []
    session = SimpleNamespace(session_id="durable-review", profile="smedley", messages=[],
                              is_streaming=False, active_stream_id=None)
    session.save = lambda **kw: saved.append(copy.deepcopy(session.messages))
    calls = []
    def execute(*args, **kwargs):
        calls.append(True)
        assert saved[-1][-1]["review_request_id"] == "durable-test-1"
        assert saved[-1][-1]["review_turn_state"] == "pending"
        return {"reply": "Answer", "model": "test"}
    for _ in range(2):
        handler, _ = _post_review_dialog(monkeypatch, message="What discrepancy is that?",
            session=session, capture={"fast_calls": [], "governed_calls": []},
            fast_reply=execute, request_id="durable-test-1")
        assert handler.status == 200
    assert calls == [True]
    assert [m["role"] for m in session.messages] == ["user", "assistant"]
    assert session.messages[0]["review_turn_state"] == "completed"


def test_readiness_only_runs_for_document_lane(monkeypatch):
    import api.project_review_electrical as electrical

    monkeypatch.setattr(electrical, "voltage_drop_reply", lambda *args: {"reply": "Calculator result"})
    for message, should_walk in [
        ("What discrepancy is that?", False),
        ("480V 3 phase 10hp motor 1200 ft voltage drop", False),
        ("Open the conduit fill tool", False),
        ("Re-run project review using new OCR tools", True),
    ]:
        walks = []
        def readiness_check(folder):
            walks.append(folder)
            return {"state": "needs_review", "ready": False, "reason": "Unverified evidence"}
        session = SimpleNamespace(session_id="lane-readiness-test", profile="smedley",
                                  messages=[], is_streaming=False, active_stream_id=None,
                                  save=lambda **kw: None)
        capture = {"fast_calls": [], "governed_calls": []}
        handler, _ = _post_review_dialog(monkeypatch, message=message, session=session,
                                        capture=capture, readiness_check=readiness_check)
        assert handler.status == 200
        assert len(walks) == int(should_walk), message
        if should_walk:
            assert "NEEDS_REVIEW" in capture["governed_calls"][0]["message"]
            assert handler.payload()["ingest_readiness"]["ready"] is False
        else:
            assert handler.payload()["ingest_readiness"] is None


def test_exact_rerun_request_enters_governed_tool_loop_not_fast_promise(monkeypatch):
    """ROUTING SIMULATION: proves lane selection + refreshed context; not tool-loop completion."""
    capture = {"fast_calls": [], "governed_calls": []}
    saved = []
    session = SimpleNamespace(
        session_id="a09c02f318be",
        profile="smedley",
        messages=[
            {"role": "user", "content": "Owner message: prior"},
            {"role": "assistant", "content": "prior reply"},
        ],
        is_streaming=False,
        active_stream_id=None,
        save=lambda **kwargs: saved.append(kwargs or True),
    )
    message = "OK, we upgraded the DXF and OCR tools. Re-run project review using new tools."
    handler, _project = _post_review_dialog(monkeypatch, message=message, session=session, capture=capture)

    assert handler.status == 200
    assert capture["fast_calls"] == []
    assert len(capture["governed_calls"]) == 1
    routed = capture["governed_calls"][0]["message"]
    assert "project_id: bdd341b152a4" in routed
    assert "project_review_extract" in routed
    assert "smedley_project_review" in routed
    assert "Owner message: " + message in routed
    assert routed.startswith("Project-review context")
    assert not any(m.get("project_review_fast_route") for m in session.messages)
    assert session.is_streaming is True
    assert session.active_stream_id == "stream-governed-sim"


def test_ordinary_clarification_stays_on_fast_lane(monkeypatch):
    capture = {"fast_calls": [], "governed_calls": []}
    saved = []
    session = SimpleNamespace(
        session_id="a09c02f318be",
        profile="smedley",
        messages=[{"role": "assistant", "content": "prior"}],
        is_streaming=False,
        active_stream_id=None,
        save=lambda **kwargs: saved.append(kwargs or True),
    )
    handler, _project = _post_review_dialog(
        monkeypatch,
        message="What discrepancy is that?",
        session=session,
        capture=capture,
    )
    assert handler.status == 200
    assert capture["governed_calls"] == []
    assert len(capture["fast_calls"]) == 1
    assert any(m.get("project_review_fast_route") for m in session.messages)
    assert "pending" not in session.messages[-1]["content"].lower()
    assert "will extract" not in session.messages[-1]["content"].lower()
    # Fast context must be dialogue intent — never GOVERNED EXECUTION / work-starting.
    prompt = capture["fast_calls"][0]["system_context"]
    assert "Turn intent: DIALOGUE ONLY" in prompt
    assert "Turn intent: GOVERNED EXECUTION" not in prompt
    assert "project_review_extract path=" not in prompt
    assert "Execution budget" not in prompt
    assert "Path forms for project_review_extract" not in prompt


def test_deferred_worksheet_dialogue_is_fast_not_governed_execute(monkeypatch):
    """Exact owner class: deferred-parameter worksheet ask must not start tools."""
    capture = {"fast_calls": [], "governed_calls": []}
    session = SimpleNamespace(
        session_id="a09c02f318be",
        profile="smedley",
        messages=[{"role": "assistant", "content": "prior ingest summary"}],
        is_streaming=False,
        active_stream_id=None,
        save=lambda **kwargs: None,
    )
    message = (
        "OK, Based on the new ingestions, can you create an independent Worksheet "
        "based on parameters that I will give you?"
    )
    handler, _ = _post_review_dialog(
        monkeypatch, message=message, session=session, capture=capture
    )
    assert handler.status == 200
    assert capture["governed_calls"] == []
    assert len(capture["fast_calls"]) == 1
    prompt = capture["fast_calls"][0]["system_context"]
    assert "Turn intent: DIALOGUE ONLY" in prompt
    assert "Planning mode:" in prompt
    assert "Do not enumerate source/table/row inventories" in prompt
    assert "project_review_extract path=" not in prompt
    assert "Execution budget" not in prompt
    assert "Turn intent: GOVERNED EXECUTION" not in prompt
    assert any(m.get("project_review_fast_route") for m in session.messages)
    assert session.messages[-1].get("project_review_dispatch_reason") == (
        "dialogue_capability_or_deferred"
    )


def test_fast_dialogue_failure_is_retryable_and_does_not_escalate(monkeypatch):
    capture = {"fast_calls": [], "governed_calls": []}
    prior = [{"role": "assistant", "content": "prior"}]
    session = SimpleNamespace(
        session_id="a09c02f318be",
        profile="smedley",
        messages=list(prior),
        is_streaming=False,
        active_stream_id=None,
        save=lambda **kwargs: None,
    )

    def _boom(*_args, **_kwargs):
        capture["fast_calls"].append({"boom": True})
        raise RuntimeError("v6 light model unavailable")

    from urllib.parse import urlparse
    import api.biggy_voice_route as voice

    project = _review_project(session.session_id)
    monkeypatch.setattr(routes, "load_projects", lambda: [project])
    monkeypatch.setattr(routes, "save_projects", lambda _projects: None)
    monkeypatch.setattr(routes, "get_session", lambda _sid: session)
    monkeypatch.setattr(routes, "_clear_stale_stream_state", lambda _session: False)
    monkeypatch.setattr(
        jarvis_rag_ingest_events,
        "folder_ingest_readiness",
        lambda _folder: {"state": "needs_review", "reason": "OCR needs review", "ready": False},
    )
    monkeypatch.setattr(voice, "request_fast_voice_reply", _boom)
    monkeypatch.setattr(
        routes,
        "start_session_turn",
        lambda *a, **k: capture["governed_calls"].append({"hit": True}) or {"ok": True, "_status": 200},
    )
    monkeypatch.setattr(
        routes,
        "_biggy_project_review_dialog_payload",
        lambda s: {"session_id": s.session_id, "messages": list(s.messages or [])},
    )
    handler = _DialogHandler(
        {
            "project_id": "bdd341b152a4",
            "message": "Can you create a worksheet once I give you the parameters?",
        }
    )
    routes.handle_post(handler, urlparse("/api/biggy/projects/reviews/dialog"))
    assert handler.status == 503
    body = handler.payload()
    assert body.get("retryable") is True
    assert body.get("lane") == "fast"
    assert "Heavy extraction was not started" in str(body.get("error") or "")
    assert capture["governed_calls"] == []
    assert session.messages[:-1] == prior
    assert session.messages[-1]["role"] == "user"
    assert session.messages[-1]["review_turn_state"] == "failed"
    assert session.is_streaming is False


def test_ambiguous_followup_is_not_accepted_as_fast_finished_promise(monkeypatch):
    capture = {"fast_calls": [], "governed_calls": []}
    session = SimpleNamespace(
        session_id="a09c02f318be",
        profile="smedley",
        messages=[{"role": "assistant", "content": "prior"}],
        is_streaming=False,
        active_stream_id=None,
        save=lambda **kwargs: None,
    )
    handler, _ = _post_review_dialog(
        monkeypatch,
        message="OK proceed.",
        session=session,
        capture=capture,
    )
    assert handler.status == 200
    assert capture["fast_calls"] == []
    assert len(capture["governed_calls"]) == 1
    # Governed execute context — not dialogue intent.
    routed = capture["governed_calls"][0]["message"]
    assert "Turn intent: GOVERNED EXECUTION" in routed
    assert "Turn intent: DIALOGUE / PLANNING ONLY." not in routed


def test_concurrent_request_returns_409_before_fast_or_governed(monkeypatch):
    capture = {"fast_calls": [], "governed_calls": []}
    prior_messages = [{"role": "assistant", "content": "prior"}]
    session = SimpleNamespace(
        session_id="a09c02f318be",
        profile="smedley",
        messages=list(prior_messages),
        is_streaming=True,
        active_stream_id="stream-live",
        save=lambda **kwargs: None,
    )
    # Even an informational question must not clear a live governed run via fast lane.
    handler, _ = _post_review_dialog(
        monkeypatch,
        message="What discrepancy is that?",
        session=session,
        capture=capture,
    )
    assert handler.status == 409
    assert capture["governed_calls"] == []
    assert capture["fast_calls"] == []
    assert session.messages == prior_messages
    assert session.is_streaming is True
    assert session.active_stream_id == "stream-live"
