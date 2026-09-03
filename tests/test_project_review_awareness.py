"""Fresh clock and indexed corpus orientation without per-turn NAS scans."""

import json
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from api import project_review_awareness as awareness
from api.biggy_project_review_runtime import build_canonical_project_context, build_dialogue_project_context


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps({"files": {
        "a": {"source": "Projects/Projects - 2026/26HOS-006/a.pdf"},
        "b": {"source": "Projects/Projects - 2026/26OTHER-001/b.pdf"},
        "c": {"source": "Electrical Resources/Standards/code.pdf"},
        "d": {"source": "/Users/rick/Mounts/RAG_Pool/Library/Vendor Data/Manuals/c.pdf"},
        "e": {"source": "../outside/secret.pdf"},
    }}))
    monkeypatch.setattr(awareness, "resolve_rag_ingest_ledger", lambda: path)
    monkeypatch.setattr(awareness, "load_world_config", lambda: {"rag_library_root": "/corpus/Library"})
    monkeypatch.setattr(awareness, "_CACHE", None)
    return path


def test_clock_refreshes_including_date_rollover_timezone_and_offset(ledger):
    review = {"rag_folder": "Projects/Projects - 2026/26HOS-006"}
    first = awareness.build_review_awareness(review, now=datetime(2026, 9, 3, 23, 59, 59, tzinfo=ZoneInfo("America/Chicago")))
    second = awareness.build_review_awareness(review, now=datetime(2026, 9, 4, 0, 0, 1, tzinfo=ZoneInfo("America/Chicago")))
    assert "2026-09-03T23:59:59-05:00" in first
    assert "2026-09-04T00:00:01-05:00" in second
    assert "timezone: CDT" in second
    assert "2026-09-04T05:00:01+00:00" in second
    winter = awareness.build_review_awareness(review, now=datetime(2026, 12, 4, 12, tzinfo=ZoneInfo("America/Chicago")))
    assert "12:00:00-06:00" in winter and "timezone: CST" in winter


@pytest.mark.parametrize("builder", [build_canonical_project_context, build_dialogue_project_context])
@pytest.mark.parametrize("project", ["26HOS-006", "26OTHER-001"])
def test_shared_across_projects_and_both_lanes(ledger, builder, project):
    text = builder(project={"project_id": project}, review={"rag_folder": f"Projects/Projects - 2026/{project}"}, readiness={})
    assert "Current local date/time:" in text
    assert f'/corpus/Library/Projects/Projects - 2026/{project}' in text
    assert '"Electrical Resources"' in text and '"Vendor Data"' in text
    assert "Current project folder present in index: True" in text
    assert '"outside"' not in text
    assert "NOT a live mount check" in text


def test_snapshot_cached_but_ledger_replacement_is_detected(ledger, monkeypatch):
    original = Path.read_text
    reads = []

    def read(path, *args, **kwargs):
        reads.append(path)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    monkeypatch.setattr(Path, "rglob", lambda *_: pytest.fail("must not scan NAS"))
    monkeypatch.setattr(Path, "iterdir", lambda *_: pytest.fail("must not enumerate folders"))
    awareness.build_review_awareness({})
    awareness.build_review_awareness({})
    assert reads == [ledger]
    replacement = ledger.with_suffix(".new")
    replacement.write_text(json.dumps({"files": {"new": {"source": "New Folder/new.pdf"}}}))
    replacement.replace(ledger)
    text = awareness.build_review_awareness({})
    assert '"New Folder"' in text and '"Vendor Data"' not in text
    assert reads == [ledger, ledger]


def test_missing_and_corrupt_index_do_not_claim_empty_or_serve_old_snapshot(ledger):
    awareness.build_review_awareness({})
    ledger.write_text("broken json")
    text = awareness.build_review_awareness({})
    assert "directory knowledge unavailable" in text and "corpus is empty" in text
    assert '"Vendor Data"' not in text
    ledger.unlink()
    assert "directory knowledge unavailable" in awareness.build_review_awareness({})


def test_absolute_project_binding_and_truncation_are_explicit(ledger, monkeypatch):
    monkeypatch.setattr(awareness, "_TREE_CHAR_LIMIT", 20)
    text = awareness.build_review_awareness({"rag_folder": "/corpus/Library/Projects/Projects - 2026/26HOS-006"})
    assert "Current project folder present in index: True" in text
    assert "omitted 0" not in text
    assert "never invent omitted paths" in text
    assert "no valid library-relative folder binding" in awareness.build_review_awareness({"rag_folder": "../escape"})


def test_naive_clock_rejected(ledger):
    with pytest.raises(ValueError, match="timezone-aware"):
        awareness.build_review_awareness({}, now=datetime(2026, 9, 3))
