"""Ingest sidebar cards: only current actionable failures; sidecar-indexed sources skip retry."""

from __future__ import annotations

import json
from pathlib import Path

import api.jarvis_rag_ingest_events as ingest
from tests.js_source_extract import extract_function

LIVE_EXT = (
    Path.home()
    / ".hermes"
    / "webui"
    / "extensions"
    / "smedley-engineering"
    / "smedley-engineering.v0.2.5.js"
)
REPO_EXT = (
    Path(__file__).resolve().parents[1]
    / "extensions"
    / "smedley-engineering"
    / "smedley-engineering.v0.2.5.js"
)


def _install_tmp(monkeypatch, tmp_path: Path):
    status_dir = tmp_path / "status"
    status_dir.mkdir()
    meta = tmp_path / "watch_meta.json"
    state = tmp_path / "watch_state.json"
    meta.write_text(json.dumps({"quarantine": {}, "hashes": {}, "bad_hashes": {}, "strikes": {}}))
    state.write_text("{}")
    monkeypatch.setattr(ingest, "STATUS_DIR", str(status_dir))
    monkeypatch.setattr(ingest, "LIBRARY_STATUS", str(status_dir / "library.json"))
    monkeypatch.setattr(ingest, "LEDGER_FILE", str(status_dir / "ingest_ledger.json"))
    monkeypatch.setattr(ingest, "WATCH_META", str(meta))
    monkeypatch.setattr(ingest, "WATCH_STATE", str(state))
    return meta, state


def test_193_indexed_via_sidecar_retry_does_not_enqueue(monkeypatch, tmp_path: Path):
    meta_path, state_path = _install_tmp(monkeypatch, tmp_path)
    pdf = tmp_path / "193-um015_-en-p.pdf"
    sidecar = tmp_path / "193-um015_-en-p.ocr.txt"
    pdf.write_bytes(b"%PDF-1.4 sidecar-indexed-source")
    sidecar.write_text("E300 analog module over level warning")
    pdf_sha = ingest.file_sha256(str(pdf))
    sidecar_sha = ingest.file_sha256(str(sidecar))
    meta = {
        "quarantine": {
            str(pdf): {"mtime": 1, "strikes": 1, "reason": "dup-of-bad: timeout", "first_seen": 1, "last_seen": 1}
        },
        "hashes": {sidecar_sha: str(sidecar)},
        "bad_hashes": {pdf_sha: "timeout"},
        "strikes": {},
    }
    meta_path.write_text(json.dumps(meta))
    state_path.write_text(json.dumps({str(pdf): 1}))
    result = ingest.retry_quarantine(str(pdf))
    assert result["queued"] is False
    assert result["status"] == "indexed_via_sidecar"
    saved = json.loads(meta_path.read_text())
    assert pdf_sha not in saved.get("bad_hashes", {})
    assert str(pdf) not in saved.get("quarantine", {})
    assert json.loads(state_path.read_text()).get(str(pdf)) == 1
    ledger = ingest.load_ledger()
    entry = ledger["files"][str(pdf)]
    assert entry["phase"] == "indexed_via_sidecar"
    assert not any(row.get("path") == str(pdf) for row in ingest.build_queue())


def test_1756_um001_duplicate_has_no_card(monkeypatch, tmp_path: Path):
    _install_tmp(monkeypatch, tmp_path)
    live = tmp_path / "1756-um001_-en-p.pdf"
    live.write_bytes(b"%PDF-1.4 um001")
    sha = ingest.file_sha256(str(live))
    ingest._save(
        ingest.WATCH_META,
        {"quarantine": {}, "hashes": {sha: str(live)}, "bad_hashes": {}, "strikes": {}},
    )
    ingest.record_file_event(
        str(live),
        "duplicate",
        sha256=sha,
        reconciliation_reason="canonical-path-reconcile",
    )
    queue = ingest.build_queue()
    assert queue == []
    entry = ingest.load_ledger()["files"][str(live)]
    assert entry["phase"] == "duplicate"
    assert entry["path"] == str(live)


def test_hidden_phases_do_not_render_cards(monkeypatch, tmp_path: Path):
    _install_tmp(monkeypatch, tmp_path)
    for name, phase in (
        ("a.pdf", "indexed"),
        ("b.pdf", "detected"),
        ("c.pdf", "duplicate"),
        ("d.pdf", "queued"),
        ("e.pdf", "extracting"),
        ("f.pdf", "idle"),
    ):
        path = tmp_path / name
        path.write_bytes(b"x")
        ingest.record_file_event(str(path), phase)
    assert ingest.build_queue() == []


def test_genuine_quarantine_renders_card(monkeypatch, tmp_path: Path):
    meta_path, _state = _install_tmp(monkeypatch, tmp_path)
    bad = tmp_path / "poison.pdf"
    bad.write_bytes(b"%PDF-1.4 not-indexed")
    meta_path.write_text(
        json.dumps(
            {
                "quarantine": {
                    str(bad): {
                        "mtime": 1,
                        "strikes": 1,
                        "reason": "timeout>600s",
                        "first_seen": 1,
                        "last_seen": 1,
                    }
                },
                "hashes": {},
                "bad_hashes": {},
                "strikes": {},
            }
        )
    )
    rows = ingest.build_queue()
    assert len(rows) == 1
    assert rows[0]["basename"] == "poison.pdf"
    assert rows[0]["phase"] == "quarantined"


def test_retry_clears_bad_hash_before_claiming_queued(monkeypatch, tmp_path: Path):
    meta_path, state_path = _install_tmp(monkeypatch, tmp_path)
    bad = tmp_path / "retry-me.pdf"
    bad.write_bytes(b"%PDF-1.4 genuine-fail")
    sha = ingest.file_sha256(str(bad))
    meta_path.write_text(
        json.dumps(
            {
                "quarantine": {str(bad): {"mtime": 1, "strikes": 1, "reason": "timeout", "first_seen": 1, "last_seen": 1}},
                "hashes": {},
                "bad_hashes": {sha: "timeout"},
                "strikes": {},
            }
        )
    )
    state_path.write_text(json.dumps({str(bad): 1}))
    result = ingest.retry_quarantine(str(bad))
    assert result["queued"] is True
    assert result["status"] == "queued"
    saved = json.loads(meta_path.read_text())
    assert sha not in saved.get("bad_hashes", {})
    assert str(bad) not in json.loads(state_path.read_text())


def test_requeue_reconciles_identical_content_instead_of_grinding_again(monkeypatch, tmp_path: Path):
    meta_path, _state_path = _install_tmp(monkeypatch, tmp_path)
    indexed = tmp_path / "Limit Amp Starter.pdf"
    duplicate = tmp_path / "CR194 Limit Amp Starter.pdf"
    indexed.write_bytes(b"%PDF-1.4 identical-content")
    duplicate.write_bytes(b"%PDF-1.4 identical-content")
    digest = ingest.file_sha256(str(indexed))
    meta_path.write_text(
        json.dumps({"quarantine": {}, "hashes": {digest: str(indexed)}, "bad_hashes": {}, "strikes": {}})
    )
    ingest.record_file_event(str(duplicate), "detected")

    result = ingest.requeue_ingest_source(str(duplicate))

    assert result["queued"] is False
    assert result["status"] == "duplicate"
    assert result["duplicate_of"] == indexed.name
    entry = ingest.load_ledger()["files"][str(duplicate)]
    assert entry["phase"] == "duplicate"
    assert "duplicate-content" in entry["reconciliation_reason"]
    assert ingest.build_queue() == []


def test_four_level_picker_source_untouched():
    live = LIVE_EXT.read_text(encoding="utf-8")
    repo = REPO_EXT.read_text(encoding="utf-8")
    for src in (live, repo):
        body = extract_function(src, "makeRightRail")
        assert "<span>FOLDER</span>" in body
        assert "<span>SUBFOLDER</span>" in body
        assert "<span>LEVEL 3</span>" in body
        assert "<span>LEVEL 4</span>" in body
        assert 'id="smedleyLibraryFolder"' in body
        assert 'id="smedleyLibrarySubfolder"' in body
        assert 'id="smedleyLibraryLevel3"' in body
        assert 'id="smedleyLibraryLevel4"' in body
        assert "refreshSubfolders" in body
        assert "refreshLevel3" in body
        assert "refreshLevel4" in body
        assert "subfolder.addEventListener('change',async()=>{await refreshLevel3()" in body
        assert "level3.addEventListener('change',async()=>{await refreshLevel4()" in body
        assert "status.queue||status.focus" not in body
        assert "isActionableIngestCard" in body
        queue_fn = extract_function(src, "isActionableIngestCard")
        assert "failed" in queue_fn and "quarantined" in queue_fn
        assert "detected" not in queue_fn
