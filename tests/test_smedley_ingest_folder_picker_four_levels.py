"""Current live RAG Ingest picker must expose four dependent hierarchy levels."""

from __future__ import annotations

from pathlib import Path

from tests.js_source_extract import extract_function

LIVE_EXT = (
    Path.home()
    / ".hermes"
    / "webui"
    / "extensions"
    / "smedley-engineering"
    / "smedley-engineering.v0.2.5.js"
)


def test_ingest_folder_picker_has_four_dependent_levels():
    src = LIVE_EXT.read_text(encoding="utf-8")
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
    assert "subfolder.addEventListener('change',refreshLevel3)" in body
    assert "level3.addEventListener('change',refreshLevel4)" in body
    assert "INGEST STATUS" in body
    assert "smedleyIngestQueue" in body
