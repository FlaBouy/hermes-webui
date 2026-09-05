import json
from types import SimpleNamespace

import pytest

from api.project_review_turns import ReviewTurnError, run_sync_review, sync_turn_status


def disk_session(tmp_path):
    path = tmp_path / "session.json"
    session = SimpleNamespace(session_id="isolated", messages=[])
    session.save = lambda: path.write_text(json.dumps(session.messages))
    return session, path


def test_reload_preserves_completed_identity_and_result(tmp_path):
    session, path = disk_session(tmp_path)
    def execute():
        assert json.loads(path.read_text())[0]["review_turn_state"] == "pending"
        assert sync_turn_status(session)["is_streaming"]
        assert sync_turn_status(session)["cancel_stream_id"] is None
        return {"reply": "Done", "tool_action": {"id": "voltage-drop"}}
    first = run_sync_review(session, message="calculate", request_id="one", lane="electrical", execute=execute)
    session.messages = json.loads(path.read_text())
    repeated = run_sync_review(session, message="calculate", request_id="one", lane="electrical",
                               execute=lambda: pytest.fail("duplicate execution"))
    assert repeated == first
    assert len(session.messages) == 2
    with pytest.raises(ReviewTurnError, match="different message"):
        run_sync_review(session, message="changed", request_id="one", lane="fast", execute=execute)


def test_failed_and_interrupted_requests_are_not_silently_reexecuted(tmp_path):
    session, path = disk_session(tmp_path)
    with pytest.raises(ReviewTurnError):
        run_sync_review(session, message="hello", request_id="one", lane="fast",
                        execute=lambda: (_ for _ in ()).throw(RuntimeError("model failed")))
    assert json.loads(path.read_text())[0]["review_turn_state"] == "failed"
    assert sync_turn_status(session)["status"] == "failed"
    session.messages[0]["review_turn_state"] = "pending"
    session.save()
    session.messages = json.loads(path.read_text())
    assert sync_turn_status(session)["status"] == "interrupted"
    with pytest.raises(ReviewTurnError):
        run_sync_review(session, message="hello", request_id="one", lane="fast",
                        execute=lambda: pytest.fail("unsafe recovery execution"))


def test_acceptance_failure_never_computes(tmp_path):
    session, _ = disk_session(tmp_path)
    session.save = lambda: (_ for _ in ()).throw(OSError("disk unavailable"))
    with pytest.raises(ReviewTurnError, match="execution was not started"):
        run_sync_review(session, message="hello", request_id="one", lane="fast",
                        execute=lambda: pytest.fail("not durable"))
    assert session.messages == []


def test_completion_save_failure_never_replays_memory_only_success(tmp_path):
    session, path = disk_session(tmp_path)
    saved = session.save
    def save():
        if len(session.messages) > 1:
            raise OSError("completion save failed")
        saved()
    session.save = save
    with pytest.raises(ReviewTurnError, match="Reply could not be saved"):
        run_sync_review(session, message="hello", request_id="one", lane="fast",
                        execute=lambda: {"reply": "unpersisted"})
    assert len(json.loads(path.read_text())) == 1
    assert sync_turn_status(session)["status"] == "failed"
    with pytest.raises(ReviewTurnError):
        run_sync_review(session, message="hello", request_id="one", lane="fast",
                        execute=lambda: pytest.fail("duplicate"))


def test_native_governed_stream_wins_over_prior_sync_completion(tmp_path):
    session, _ = disk_session(tmp_path)
    run_sync_review(session, message="hi", request_id="one", lane="fast", execute=lambda: {"reply": "hi"})
    session.active_stream_id = "governed"
    assert sync_turn_status(session) is None


def test_native_session_json_preserves_request_identity(tmp_path, monkeypatch):
    from api import models
    monkeypatch.setattr(models, "SESSION_DIR", tmp_path)
    monkeypatch.setattr(models, "_write_session_index", lambda **kw: None)
    session = models.Session(workspace=str(tmp_path), profile="smedley")
    def execute():
        persisted = models.Session.load(session.session_id)
        assert persisted.messages[-1]["review_turn_state"] == "pending"
        return {"reply": "Native storage answer"}
    run_sync_review(session, message="hello", request_id="native", lane="fast", execute=execute)
    restored = models.Session.load(session.session_id)
    run_sync_review(restored, message="hello", request_id="native", lane="fast",
                    execute=lambda: pytest.fail("duplicate native execution"))
    assert len(restored.messages) == 2
    assert restored.messages[0]["review_turn_state"] == "completed"
