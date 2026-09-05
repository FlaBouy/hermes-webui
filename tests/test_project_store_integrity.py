import json

import pytest

from api import models
from api.project_store import ProjectStoreError, ProjectConflict


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = tmp_path / "projects.json"
    path.write_text(json.dumps([{"project_id": "one", "profile": "biggy", "name": "Original",
                                 "review": {"session_id": "keep", "custom": [1, 2]}}]))
    monkeypatch.setattr(models, "PROJECTS_FILE", path)
    monkeypatch.setattr(models, "_projects_migrated", True)
    return path


def test_malformed_projects_are_visible_and_not_overwritten(store):
    store.write_text("[{broken")
    with pytest.raises(ProjectStoreError):
        models.load_projects()
    with pytest.raises(ProjectStoreError):
        models.save_projects([])
    assert store.read_text() == "[{broken"


def test_stale_project_writer_cannot_erase_newer_metadata(store):
    first = models.load_projects()
    stale = models.load_projects()
    first[0]["review"]["session_id"] = "new-session"
    models.save_projects(first)
    stale[0]["name"] = "Stale rename"
    with pytest.raises(ProjectConflict):
        models.save_projects(stale)
    assert models.load_projects()[0]["review"]["session_id"] == "new-session"


def test_failed_atomic_replace_preserves_original(store, monkeypatch):
    before = store.read_bytes()
    projects = models.load_projects()
    projects[0]["name"] = "Changed"
    def fail(*args):
        raise OSError("injected replace failure")
    monkeypatch.setattr("os.replace", fail)
    with pytest.raises(OSError):
        models.save_projects(projects)
    assert store.read_bytes() == before


def _competing_writer(path, barrier, queue, label):
    from api.project_store import read_projects, write_projects, ProjectConflict
    snapshot = read_projects(path)
    snapshot[0]["name"] = label
    barrier.wait(timeout=15)
    try:
        write_projects(path, snapshot)
        queue.put("saved")
    except ProjectConflict:
        queue.put("conflict")


def test_concurrent_processes_cannot_silently_overwrite_each_other(store):
    import multiprocessing
    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(2)
    queue = ctx.Queue()
    workers = [ctx.Process(target=_competing_writer, args=(store, barrier, queue, label))
               for label in ("first", "second")]
    try:
        for worker in workers:
            worker.start()
        outcomes = [queue.get(timeout=20), queue.get(timeout=20)]
        for worker in workers:
            worker.join(timeout=10)
            assert worker.exitcode == 0
        assert sorted(outcomes) == ["conflict", "saved"]
        assert models.load_projects()[0]["review"] == {"session_id": "keep", "custom": [1, 2]}
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
                worker.join(timeout=5)


def test_restore_valid_data_recovers_without_schema_changes(store):
    original = store.read_bytes()
    store.write_text("null")
    with pytest.raises(ProjectStoreError):
        models.load_projects()
    store.write_bytes(original)
    projects = models.load_projects()
    projects[0]["name"] = "Recovered"
    models.save_projects(projects)
    assert isinstance(json.loads(store.read_text()), list)
    assert models.load_projects()[0]["review"]["custom"] == [1, 2]


@pytest.mark.parametrize("method,error_type,status", [("GET", ProjectStoreError, 503),
                                                     ("POST", ProjectConflict, 409)])
def test_http_storage_errors_are_explicit_and_recoverable(monkeypatch, method, error_type, status):
    import server
    from tests.test_biggy_project_review_lifecycle import _DialogHandler
    handler = _DialogHandler({})
    handler.path = "/api/projects"
    handler.command = method
    handler._safe_webui_print = lambda *args: None
    monkeypatch.setattr(server, "reset_trusted_auth_request_state", lambda h: None)
    monkeypatch.setattr(server, "get_profile_cookie", lambda h: None)
    monkeypatch.setattr(server, "check_auth", lambda *args: True)
    def fail(*args):
        raise error_type("Preserved original; reload or restore validated data.")
    if method == "GET":
        monkeypatch.setattr(server, "handle_get", fail)
        server.Handler.do_GET(handler)
    else:
        server.Handler._handle_write(handler, fail)
    assert handler.status == status
    assert handler.payload()["recoverable"] is True
    assert "Preserved original" in handler.payload()["error"]
