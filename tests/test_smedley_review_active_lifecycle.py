"""Active project-review dialog lifecycle must keep polling genuine work.

Covers presentation ownership in ``_biggy_project_review_dialog_payload`` only.
Does not exercise dispatch classification or model/provider smoke.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace

from api import config, routes


def _session(
    *,
    streaming: bool = False,
    stream_id: str | None = None,
    messages: list | None = None,
    pending_user_message: str | None = None,
):
    sid = stream_id if stream_id is not None else ("stream-live" if streaming else None)
    return SimpleNamespace(
        session_id="review-active-lifecycle",
        messages=list(messages or [{"role": "user", "content": "Owner message: proceed"}]),
        is_streaming=streaming,
        active_stream_id=sid,
        pending_user_message=pending_user_message,
    )


def _install_live_stream(monkeypatch, stream_id: str, *, via: str = "STREAMS"):
    """Mark ``stream_id`` as process-live (authoritative ownership)."""
    monkeypatch.setattr(config, "STREAMS_LOCK", threading.RLock())
    monkeypatch.setattr(config, "ACTIVE_RUNS_LOCK", threading.RLock())
    if via == "STREAMS":
        monkeypatch.setattr(config, "STREAMS", {stream_id: object()})
        monkeypatch.setattr(config, "ACTIVE_RUNS", {})
    elif via == "ACTIVE_RUNS":
        monkeypatch.setattr(config, "STREAMS", {})
        monkeypatch.setattr(
            config,
            "ACTIVE_RUNS",
            {stream_id: {"stream_id": stream_id, "session_id": "review-active-lifecycle"}},
        )
    else:
        raise AssertionError(f"unknown live path {via}")
    # routes imports STREAMS/ACTIVE_RUNS by name — keep module attrs aligned
    monkeypatch.setattr(routes, "STREAMS", config.STREAMS)
    monkeypatch.setattr(routes, "STREAMS_LOCK", config.STREAMS_LOCK)
    monkeypatch.setattr(routes, "ACTIVE_RUNS", config.ACTIVE_RUNS)
    monkeypatch.setattr(routes, "ACTIVE_RUNS_LOCK", config.ACTIVE_RUNS_LOCK)


def test_interim_assistant_text_during_active_stream_keeps_running(monkeypatch):
    """Interim prose must not stop dialog polling while the worker is live."""
    monkeypatch.setattr(routes, "SERVER_START_TIME", 1)
    _install_live_stream(monkeypatch, "stream-live")
    session = _session(
        streaming=True,
        stream_id="stream-live",
        messages=[
            {"role": "user", "content": "Owner message: re-run project review", "timestamp": 5},
            {
                "role": "assistant",
                "content": "I will run the governed extract tools now.",
                "timestamp": 20,
            },
        ],
    )
    monkeypatch.setattr(
        routes,
        "read_turn_journal",
        lambda _session_id: {
            "events": [
                {
                    "event": "worker_started",
                    "turn_id": "turn-live",
                    "stream_id": "stream-live",
                    "created_at": 10,
                }
            ]
        },
    )

    dialog = routes._biggy_project_review_dialog_payload(session)

    assert dialog["is_streaming"] is True
    assert dialog["status"] == "running"
    assert "working" in dialog["status_message"].lower()


def test_prior_completed_journal_does_not_hide_new_active_stream(monkeypatch):
    """A settled prior turn must not stop polling a different live stream."""
    monkeypatch.setattr(routes, "SERVER_START_TIME", 1)
    _install_live_stream(monkeypatch, "stream-new", via="ACTIVE_RUNS")
    session = _session(streaming=True, stream_id="stream-new")
    monkeypatch.setattr(
        routes,
        "read_turn_journal",
        lambda _session_id: {
            "events": [
                {
                    "event": "completed",
                    "turn_id": "turn-old",
                    "stream_id": "stream-old",
                    "created_at": 50,
                }
            ]
        },
    )

    dialog = routes._biggy_project_review_dialog_payload(session)

    assert dialog["is_streaming"] is True
    assert dialog["status"] == "running"
    assert dialog["status_message"]


def test_matching_completed_turn_settles_final(monkeypatch):
    monkeypatch.setattr(routes, "SERVER_START_TIME", 1)
    monkeypatch.setattr(config, "STREAMS", {})
    monkeypatch.setattr(config, "ACTIVE_RUNS", {})
    monkeypatch.setattr(routes, "STREAMS", {})
    monkeypatch.setattr(routes, "ACTIVE_RUNS", {})
    session = _session(streaming=False, stream_id=None)
    session.messages.append(
        {
            "role": "assistant",
            "content": "Final review findings for the package.",
            "timestamp": 40,
        }
    )
    monkeypatch.setattr(
        routes,
        "read_turn_journal",
        lambda _session_id: {
            "events": [
                {
                    "event": "worker_started",
                    "turn_id": "turn-1",
                    "stream_id": "stream-1",
                    "created_at": 10,
                },
                {
                    "event": "completed",
                    "turn_id": "turn-1",
                    "stream_id": "stream-1",
                    "created_at": 30,
                },
            ]
        },
    )

    dialog = routes._biggy_project_review_dialog_payload(session)

    assert dialog["is_streaming"] is False
    assert dialog["status"] == "completed"
    assert dialog["status_message"] == ""


def test_interrupted_and_stale_restart_settle_without_trusting_flags(monkeypatch):
    monkeypatch.setattr(routes, "SERVER_START_TIME", 100)
    monkeypatch.setattr(config, "STREAMS", {})
    monkeypatch.setattr(config, "ACTIVE_RUNS", {})
    monkeypatch.setattr(routes, "STREAMS", {})
    monkeypatch.setattr(routes, "ACTIVE_RUNS", {})
    # Persisted flags claim a live run, but the process has no live stream and
    # the journal predates this server start — fail closed to interrupted.
    session = _session(streaming=True, stream_id="stream-orphan")
    monkeypatch.setattr(
        routes,
        "read_turn_journal",
        lambda _session_id: {
            "events": [
                {
                    "event": "worker_started",
                    "turn_id": "turn-orphan",
                    "stream_id": "stream-orphan",
                    "created_at": 40,
                }
            ]
        },
    )

    dialog = routes._biggy_project_review_dialog_payload(session)

    assert dialog["is_streaming"] is False
    assert dialog["status"] == "interrupted"
    assert "interrupted" in dialog["status_message"].lower()


def test_failed_interrupted_journal_settles(monkeypatch):
    monkeypatch.setattr(routes, "SERVER_START_TIME", 1)
    monkeypatch.setattr(config, "STREAMS", {})
    monkeypatch.setattr(config, "ACTIVE_RUNS", {})
    monkeypatch.setattr(routes, "STREAMS", {})
    monkeypatch.setattr(routes, "ACTIVE_RUNS", {})
    session = _session(streaming=False, stream_id=None)
    monkeypatch.setattr(
        routes,
        "read_turn_journal",
        lambda _session_id: {
            "events": [
                {
                    "event": "interrupted",
                    "turn_id": "turn-fail",
                    "stream_id": "stream-fail",
                    "created_at": 12,
                }
            ]
        },
    )

    dialog = routes._biggy_project_review_dialog_payload(session)

    assert dialog["is_streaming"] is False
    assert dialog["status"] == "interrupted"
    assert "retry" in dialog["status_message"].lower()


def test_later_settled_fast_reply_supersedes_old_journal(monkeypatch):
    """Nonstreaming fast reply after a stale worker journal must settle completed."""
    session = _session(streaming=False, stream_id=None)
    session.messages.append(
        {
            "role": "assistant",
            "content": "That discrepancy is the feeder ampacity mismatch on sheet E-2.",
            "timestamp": 20,
            "project_review_fast_route": True,
        }
    )
    monkeypatch.setattr(routes, "SERVER_START_TIME", 30)
    monkeypatch.setattr(config, "STREAMS", {})
    monkeypatch.setattr(config, "ACTIVE_RUNS", {})
    monkeypatch.setattr(routes, "STREAMS", {})
    monkeypatch.setattr(routes, "ACTIVE_RUNS", {})
    monkeypatch.setattr(
        routes,
        "read_turn_journal",
        lambda _session_id: {
            "events": [
                {
                    "event": "worker_started",
                    "turn_id": "turn-stale",
                    "stream_id": "stream-stale",
                    "created_at": 10,
                }
            ]
        },
    )

    dialog = routes._biggy_project_review_dialog_payload(session)

    assert dialog["is_streaming"] is False
    assert dialog["status"] == "completed"
    assert dialog["status_message"] == ""


def test_active_run_payload_includes_pending_owner_message_without_mutating_store(monkeypatch):
    """Pending lives outside messages; live poll must still present the owner turn."""
    monkeypatch.setattr(routes, "SERVER_START_TIME", 1)
    _install_live_stream(monkeypatch, "stream-live")
    pending = (
        "Project-review context for this reply:\n"
        "  project_id: bdd341b152a4\n\n"
        "Owner message: Have you run the re-tests? Status only; do not rerun extraction."
    )
    stored = [
        {"role": "assistant", "content": "Prior findings.", "timestamp": 1},
    ]
    session = _session(
        streaming=True,
        stream_id="stream-live",
        messages=stored,
        pending_user_message=pending,
    )
    monkeypatch.setattr(
        routes,
        "read_turn_journal",
        lambda _session_id: {
            "events": [
                {
                    "event": "worker_started",
                    "turn_id": "turn-live",
                    "stream_id": "stream-live",
                    "created_at": 10,
                }
            ]
        },
    )

    dialog = routes._biggy_project_review_dialog_payload(session)

    assert dialog["is_streaming"] is True
    assert dialog["status"] == "running"
    assert len(dialog["messages"]) == 2
    tail = dialog["messages"][-1]
    assert tail["role"] == "user"
    assert tail.get("_pending") is True
    assert tail["content"] == pending
    assert "Owner message: Have you run the re-tests?" in tail["content"]
    # Stored transcript unchanged — presentation-only append.
    assert session.messages == stored
    assert session.pending_user_message == pending
    assert not any(m.get("_pending") for m in session.messages if isinstance(m, dict))


def test_pending_owner_message_not_duplicated_when_already_in_transcript(monkeypatch):
    monkeypatch.setattr(routes, "SERVER_START_TIME", 1)
    _install_live_stream(monkeypatch, "stream-live")
    pending = (
        "Project-review context for this reply:\n"
        "Owner message: Have you run the re-tests?"
    )
    stored = [
        {"role": "user", "content": "Owner message: Have you run the re-tests?", "timestamp": 5},
    ]
    session = _session(
        streaming=True,
        stream_id="stream-live",
        messages=stored,
        pending_user_message=pending,
    )

    dialog = routes._biggy_project_review_dialog_payload(session)

    assert len(dialog["messages"]) == 1
    assert dialog["messages"][0]["content"] == "Owner message: Have you run the re-tests?"
    assert session.messages == stored


def test_interrupted_stale_pending_still_presented(monkeypatch):
    """Cancelling/orphan path: pending must remain visible with interrupted status."""
    monkeypatch.setattr(routes, "SERVER_START_TIME", 3)
    monkeypatch.setattr(config, "STREAMS", {})
    monkeypatch.setattr(config, "ACTIVE_RUNS", {})
    monkeypatch.setattr(routes, "STREAMS", {})
    monkeypatch.setattr(routes, "ACTIVE_RUNS", {})
    pending = (
        "Project-review context for this reply:\n"
        "Owner message: Continue the voltage-drop check."
    )
    stored = [{"role": "assistant", "content": "Earlier reply.", "timestamp": 1}]
    session = _session(
        streaming=True,
        stream_id="stream-orphan",
        messages=stored,
        pending_user_message=pending,
    )
    monkeypatch.setattr(
        routes,
        "read_turn_journal",
        lambda _session_id: {
            "events": [
                {
                    "event": "worker_started",
                    "turn_id": "turn-1",
                    "stream_id": "stream-orphan",
                    "created_at": 1,
                }
            ]
        },
    )

    dialog = routes._biggy_project_review_dialog_payload(session)

    assert dialog["is_streaming"] is False
    assert dialog["status"] == "interrupted"
    assert dialog["messages"][-1]["content"] == pending
    assert dialog["messages"][-1].get("_pending") is True
    assert session.messages == stored
