from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from api import biggy_pa_sources


def test_google_reader_uses_the_running_biggy_python(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.delenv("PYTHON", raising=False)
    script = tmp_path / "skills" / "productivity" / "google-workspace" / "scripts" / "google_api.py"
    script.parent.mkdir(parents=True)
    script.write_text("", encoding="utf-8")
    (tmp_path / "google_token.json").write_text("{}", encoding="utf-8")
    captured = {}

    def fake_run(command, **_kwargs):
        captured["command"] = command
        return SimpleNamespace(returncode=0, stdout="[]", stderr="")

    monkeypatch.setattr(biggy_pa_sources.subprocess, "run", fake_run)
    assert biggy_pa_sources._run_google(["gmail", "search", "in:inbox"]) == []
    assert captured["command"][0] == biggy_pa_sources.sys.executable


def test_google_sources_fail_closed_without_profile_token(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    biggy_pa_sources._CACHE.clear()
    mail = biggy_pa_sources.mail_snapshot()
    calendar = biggy_pa_sources.calendar_snapshot()
    assert mail["connected"] is False
    assert mail["messages"] == []
    assert calendar["connected"] is False
    assert calendar["events"] == []


def test_google_source_routes_include_guarded_write_contracts():
    routes = Path("api/routes.py").read_text(encoding="utf-8")
    assert 'parsed.path == "/api/biggy/pa/mail"' in routes
    assert 'parsed.path == "/api/biggy/pa/calendar"' in routes
    assert "mail_snapshot()" in routes
    assert "calendar_snapshot()" in routes
    for path in (
        "/api/biggy/pa/mail/draft",
        "/api/biggy/pa/mail/send",
        "/api/biggy/pa/mail/discard",
        "/api/biggy/pa/calendar/create",
        "/api/biggy/pa/calendar/update",
        "/api/biggy/pa/calendar/delete",
    ):
        assert path in routes


def _write_token(tmp_path: Path) -> None:
    (tmp_path / "google_token.json").write_text(
        '{"scopes":["https://www.googleapis.com/auth/gmail.readonly",'
        '"https://www.googleapis.com/auth/gmail.compose",'
        '"https://www.googleapis.com/auth/calendar.events"]}',
        encoding="utf-8",
    )


class _Execute:
    def __init__(self, result):
        self.result = result

    def execute(self):
        return self.result


class _Drafts:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(("create", kwargs))
        return _Execute({"id": "draft_123"})

    def send(self, **kwargs):
        self.calls.append(("send", kwargs))
        return _Execute({"id": "message_123", "threadId": "thread_123"})

    def delete(self, **kwargs):
        self.calls.append(("delete", kwargs))
        return _Execute({})


class _Gmail:
    def __init__(self):
        self.drafts_api = _Drafts()

    def users(self):
        return self

    def drafts(self):
        return self.drafts_api


class _Events:
    def __init__(self):
        self.calls = []

    def insert(self, **kwargs):
        self.calls.append(("insert", kwargs))
        return _Execute({"id": "event_123", "summary": kwargs["body"]["summary"]})

    def patch(self, **kwargs):
        self.calls.append(("patch", kwargs))
        return _Execute({"id": kwargs["eventId"], "summary": kwargs["body"].get("summary", "")})

    def delete(self, **kwargs):
        self.calls.append(("delete", kwargs))
        return _Execute({})


class _Calendar:
    def __init__(self):
        self.events_api = _Events()

    def events(self):
        return self.events_api


def test_mail_is_draft_first_and_send_requires_confirmation(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_token(tmp_path)
    gmail = _Gmail()
    monkeypatch.setattr(biggy_pa_sources, "_google_service", lambda *_args: gmail)

    drafted = biggy_pa_sources.create_mail_draft({
        "to": "owner@example.com",
        "subject": "Schedule review",
        "body": "Please review the attached schedule.",
    })
    assert drafted["status"] == "drafted"
    assert [name for name, _kwargs in gmail.drafts_api.calls] == ["create"]

    with pytest.raises(ValueError, match="confirmation"):
        biggy_pa_sources.send_mail_draft({"draft_id": "draft_123"})
    assert [name for name, _kwargs in gmail.drafts_api.calls] == ["create"]

    sent = biggy_pa_sources.send_mail_draft({"draft_id": "draft_123", "confirmed": True})
    assert sent["status"] == "sent"
    assert [name for name, _kwargs in gmail.drafts_api.calls] == ["create", "send"]


def test_calendar_create_update_and_confirmed_delete(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_token(tmp_path)
    calendar = _Calendar()
    monkeypatch.setattr(biggy_pa_sources, "_google_service", lambda *_args: calendar)
    base = {
        "summary": "Auburn football",
        "start": "2026-09-19T12:00:00-05:00",
        "end": "2026-09-19T16:00:00-05:00",
        "location": "Auburn, Alabama",
    }

    created = biggy_pa_sources.create_calendar_event(base)
    assert created["status"] == "created"
    updated = biggy_pa_sources.update_calendar_event({"event_id": "event_123", "summary": "Auburn vs Florida"})
    assert updated["status"] == "updated"

    with pytest.raises(ValueError, match="confirmation"):
        biggy_pa_sources.delete_calendar_event({"event_id": "event_123"})
    assert [name for name, _kwargs in calendar.events_api.calls] == ["insert", "patch"]

    deleted = biggy_pa_sources.delete_calendar_event({"event_id": "event_123", "confirmed": True})
    assert deleted["status"] == "deleted"
    assert [name for name, _kwargs in calendar.events_api.calls] == ["insert", "patch", "delete"]


def test_calendar_update_requires_start_and_end_together(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_token(tmp_path)
    with pytest.raises(ValueError, match="start and end"):
        biggy_pa_sources.update_calendar_event({
            "event_id": "event_123",
            "start": "2026-09-19T12:00:00-05:00",
        })


def test_write_actions_fail_closed_without_upgraded_scopes(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    (tmp_path / "google_token.json").write_text(
        '{"scopes":["https://www.googleapis.com/auth/gmail.readonly",'
        '"https://www.googleapis.com/auth/calendar.readonly"]}',
        encoding="utf-8",
    )
    with pytest.raises(PermissionError, match="upgraded"):
        biggy_pa_sources.create_mail_draft({"to": "owner@example.com", "subject": "x", "body": "y"})
    with pytest.raises(PermissionError, match="upgraded"):
        biggy_pa_sources.create_calendar_event({})


@pytest.mark.parametrize(
    "payload, message",
    [
        ({"to": "not-an-email", "subject": "x", "body": "y"}, "invalid to"),
        ({"to": "owner@example.com", "subject": "", "body": "y"}, "subject is required"),
        ({"to": "owner@example.com", "subject": "x", "body": ""}, "body is required"),
    ],
)
def test_mail_draft_rejects_invalid_input(monkeypatch, tmp_path: Path, payload, message):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    _write_token(tmp_path)
    with pytest.raises(ValueError, match=message):
        biggy_pa_sources.create_mail_draft(payload)
