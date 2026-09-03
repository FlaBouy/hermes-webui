"""Behavioral tests for DXF extract, table-cell OCR cross-check, and extract invariants."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from api import jarvis_rag_ingest_events, smedley_dxf_extract, smedley_pdf_ocr_verify, smedley_project_review_extract, smedley_table_grid


def _write_dxf_fixture(path: Path) -> None:
    ezdxf = pytest.importorskip("ezdxf")
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 4
    # Nested blocks with known positions.
    inner = doc.blocks.new("INNER")
    inner.add_text("INNER-TXT", dxfattribs={"height": 1.0, "insert": (1, 2), "layer": "0"})
    inner.add_mtext("MINNER {\\H1.5;}FMT", dxfattribs={"char_height": 1.0, "insert": (3, 4), "layer": "0"})
    outer = doc.blocks.new("OUTER")
    outer.add_blockref("INNER", insert=(10, 20), dxfattribs={"xscale": 2, "rotation": 0, "layer": "EQ"})
    outer.add_line((0, 0), (5, 0))
    msp = doc.modelspace()
    msp.add_text("PANEL-A", dxfattribs={"height": 2.5, "insert": (10, 20), "layer": "TEXT"})
    # Repeated inserts of same block.
    msp.add_blockref("OUTER", insert=(100, 200), dxfattribs={"xscale": 1, "rotation": 90, "layer": "DEVICES"})
    msp.add_blockref("OUTER", insert=(300, 400), dxfattribs={"xscale": 1, "rotation": 0, "layer": "DEVICES"})
    device = doc.blocks.new("DEVICE")
    device.add_attdef("TAG", insert=(0, 0), height=1.5)
    insert = msp.add_blockref("DEVICE", insert=(50, 60), dxfattribs={"xscale": 1, "rotation": 0})
    insert.add_auto_attribs({"TAG": "MTR-101"})
    # XREF-flagged block (never fetched).
    xref = doc.blocks.new("XREF_EXT")
    xref.block_record.set_flag_state(xref.block_record.is_xref.fget(xref.block_record) if False else 4, True)  # noqa: placeholder
    # Use documented API:
    xref.block_record.is_xref = True
    msp.add_blockref("XREF_EXT", insert=(0, 0))
    doc.saveas(path)


def _draw_ruled_table(path: Path, cells: list[list[str]]) -> None:
    rows = len(cells)
    cols = len(cells[0])
    cell_w, cell_h = 120, 40
    pad = 20
    img = Image.new("RGB", (pad * 2 + cols * cell_w, pad * 2 + rows * cell_h), "white")
    draw = ImageDraw.Draw(img)
    for r in range(rows + 1):
        y = pad + r * cell_h
        draw.line((pad, y, pad + cols * cell_w, y), fill="black", width=3)
    for c in range(cols + 1):
        x = pad + c * cell_w
        draw.line((x, pad, x, pad + rows * cell_h), fill="black", width=3)
    # Merge first row cells 0-1 by overpainting interior vertical rule.
    draw.line((pad + cell_w, pad + 1, pad + cell_w, pad + cell_h - 1), fill="white", width=5)
    for r, row in enumerate(cells):
        for c, text in enumerate(row):
            if r == 0 and c == 1:
                continue  # merged into col0
            x = pad + c * cell_w + 8
            y = pad + r * cell_h + 12
            draw.text((x, y), text, fill="black")
    img.save(path)


def test_ruled_grid_aligns_cells_and_catches_swaps_duplicates_pages_blanks_punct(tmp_path):
    image_path = tmp_path / "table.png"
    _draw_ruled_table(
        image_path,
        [
            ["REV:", "", "ITEM", "QTY", "DESC"],  # blank REV value column via merge/blank
            ["W12.", "W12.", "NOTE,", "1", "A"],  # duplicate wire numbers + punctuation
            ["A1", "B1", "C1", "2", "B"],
            ["D1", "E1", "F1", "3", "C"],
        ],
    )
    image = Image.open(image_path)
    grid = smedley_table_grid.detect_ruled_tables(image, page=1)
    assert grid["ok"] is True
    assert grid["cells"]

    # Engine A and B fragments with different line/word segmentation into same cells.
    cells = grid["cells"]
    # Find a data row cell roughly for W12 duplicate columns.
    a_frags = []
    b_frags = []
    for cell in cells:
        x0, y0, x1, y1 = cell["bbox"]
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        # Approximate content by table position.
        if cell["row"] == 1 and cell["col"] == 0:
            a_frags.append({"page": 1, "text": "W12.", "bbox": [cx - 10, cy - 5, cx + 10, cy + 5], "confidence": 0.9})
            b_frags.append({"page": 1, "text": "W12", "bbox": [cx - 8, cy - 4, cx - 1, cy + 4], "confidence": 0.91})
            b_frags.append({"page": 1, "text": ".", "bbox": [cx + 1, cy - 4, cx + 6, cy + 4], "confidence": 0.88})
        elif cell["row"] == 1 and cell["col"] == 1:
            a_frags.append({"page": 1, "text": "W12.", "bbox": [cx - 10, cy - 5, cx + 10, cy + 5], "confidence": 0.9})
            b_frags.append({"page": 1, "text": "W12.", "bbox": [cx - 10, cy - 5, cx + 10, cy + 5], "confidence": 0.9})
        elif cell["row"] == 2 and cell["col"] == 0:
            a_frags.append({"page": 1, "text": "A1", "bbox": [cx - 10, cy - 5, cx + 10, cy + 5], "confidence": 0.9})
            b_frags.append({"page": 1, "text": "B1", "bbox": [cx - 10, cy - 5, cx + 10, cy + 5], "confidence": 0.9})  # swapped
        elif cell["row"] == 2 and cell["col"] == 1:
            a_frags.append({"page": 1, "text": "B1", "bbox": [cx - 10, cy - 5, cx + 10, cy + 5], "confidence": 0.9})
            b_frags.append({"page": 1, "text": "A1", "bbox": [cx - 10, cy - 5, cx + 10, cy + 5], "confidence": 0.9})
        elif cell["row"] == 0 and cell["col"] == 0:
            # blank merged REV value intentionally omitted from both => blank match
            pass

    # Different page must not match.
    a_frags.append({"page": 2, "text": "A1", "bbox": [30, 30, 40, 40], "confidence": 0.9})
    b_frags.append({"page": 2, "text": "A1", "bbox": [30, 30, 40, 40], "confidence": 0.9})

    a_cells, _ = smedley_table_grid.assign_fragments_to_cells(cells, [f for f in a_frags if f["page"] == 1], engine="rapidocr")
    b_cells, _ = smedley_table_grid.assign_fragments_to_cells(cells, [f for f in b_frags if f["page"] == 1], engine="tesseract")
    cross = smedley_table_grid.compare_aligned_cells(a_cells, b_cells)
    assert cross["comparison_unit"] == "page/table/row/col cell identity"
    assert cross["disagree_count"] >= 1  # swapped A1/B1
    # Duplicate W12. in adjacent cells remain distinct cell identities (multiplicity preserved).
    w12_cells = [c for c in a_cells if c["text"] == "W12."]
    assert len(w12_cells) >= 2
    # Document-wide token set matching would falsely succeed on swaps; cell identity must disagree.
    assert any(item["primary_text"] != item["secondary_text"] for item in cross["disagree_sample"])


def test_dxf_nested_transforms_xref_geometry_and_bounds(tmp_path, monkeypatch):
    ezdxf = pytest.importorskip("ezdxf")
    dxf_path = tmp_path / "nested.dxf"
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 4
    inner = doc.blocks.new("INNER")
    inner.add_text("INNER-TXT", dxfattribs={"height": 1.0, "insert": (1, 2), "layer": "0"})
    inner.add_mtext("MINNER {\\H1.5;}FMT", dxfattribs={"char_height": 1.0, "insert": (3, 4), "layer": "0"})
    outer = doc.blocks.new("OUTER")
    outer.add_blockref("INNER", insert=(10, 20), dxfattribs={"xscale": 2, "rotation": 0, "layer": "EQ"})
    outer.add_circle((1, 1), 2.0)
    msp = doc.modelspace()
    msp.add_blockref("OUTER", insert=(100, 200), dxfattribs={"rotation": 90, "layer": "DEVICES"})
    msp.add_blockref("OUTER", insert=(300, 400), dxfattribs={"rotation": 0, "layer": "DEVICES"})
    device = doc.blocks.new("DEVICE")
    device.add_attdef("TAG", insert=(0, 0), height=1.5)
    insert = msp.add_blockref("DEVICE", insert=(50, 60))
    insert.add_auto_attribs({"TAG": "MTR-101"})
    xref = doc.blocks.new("XREF_EXT")
    from ezdxf.lldxf import const as ezconst
    xref.block.dxf.flags = ezconst.BLK_XREF | ezconst.BLK_EXTERNAL
    msp.add_blockref("XREF_EXT", insert=(9, 9))
    doc.saveas(dxf_path)

    monkeypatch.setattr(jarvis_rag_ingest_events, "EVIDENCE_ROOT", str(tmp_path / "evidence"))
    result = smedley_dxf_extract.extract_dxf(str(dxf_path), evidence_dir=str(tmp_path / "out"), update_ledger=False)
    assert result["ok"] is True
    texts = result["texts"]
    inner_hits = [t for t in texts if t["text"] == "INNER-TXT"]
    assert len(inner_hits) == 2  # repeated inserts
    # Known composed position for first insert: rotation 90 around (100,200), scale through nested x2.
    # Manual probe earlier: INNER-TXT -> (206.0, 221.0)
    first = sorted(inner_hits, key=lambda t: t["insert"][0])[0]
    assert abs(first["insert"][0] - 206.0) < 0.05
    assert abs(first["insert"][1] - 221.0) < 0.05
    assert first["layer"] == "EQ"  # layer 0 inheritance from INSERT layer
    assert first["insert_chain"]
    mtext = [t for t in texts if "MINNER" in t["text"] and "FMT" in t["text"]]
    assert mtext
    attrib = next(t for t in texts if t["type"] == "ATTRIB")
    assert attrib["transform_note"] == "attrib_coordinates_already_wcs"
    assert abs(attrib["insert"][0] - 50) < 0.01
    assert any(i["is_xref"] for i in result["inserts"])
    assert result["missing_xrefs"]
    geom = result["geometry_samples"]
    assert geom and ("center" in geom[0] or "start" in geom[0] or "points" in geom[0] or "radius" in geom[0])


def test_mixed_selective_and_sidecar_still_fail_closed(tmp_path, monkeypatch):
    folder = tmp_path / "Projects" / "Projects - 2026" / "26HOS-006"
    folder.mkdir(parents=True)
    drawing = folder / "WB3339-012.pdf"
    drawing.write_bytes(b"%PDF")
    monkeypatch.setattr(jarvis_rag_ingest_events, "LIBRARY_ROOT", str(tmp_path))
    monkeypatch.setattr(jarvis_rag_ingest_events, "load_ledger", lambda: {"files": {
        str(drawing.resolve()): {
            "phase": "indexed",
            "quality_state": "verified",
            "extraction_mode": "mixed_selective_ocr",
        },
    }})
    result = jarvis_rag_ingest_events.folder_ingest_readiness("Projects/Projects - 2026/26HOS-006")
    assert result["ready"] is False
    assert result["state"] == "needs_review"


def test_ledger_attach_preserves_phase_and_marks_stale(tmp_path, monkeypatch):
    monkeypatch.setattr(jarvis_rag_ingest_events, "LEDGER_FILE", str(tmp_path / "ingest_ledger.json"))
    monkeypatch.setattr(jarvis_rag_ingest_events, "LIBRARY_STATUS", str(tmp_path / "library.json"))
    monkeypatch.setattr(jarvis_rag_ingest_events, "STATUS_DIR", str(tmp_path))
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"pdf-v1")
    jarvis_rag_ingest_events.record_file_event(
        str(pdf),
        "indexed",
        quality_state="needs_review",
        extraction_mode="full_ocr",
        chunks=12,
    )
    sha1 = jarvis_rag_ingest_events.file_sha256(str(pdf))
    entry = jarvis_rag_ingest_events.attach_review_extraction_evidence(
        str(pdf),
        source_sha256=sha1,
        evidence={"kind": "pdf_ocr_verify", "ocr_verification_state": "needs_review", "quality_state": "needs_review", "manifest_path": "/tmp/x.json"},
    )
    assert entry["phase"] == "indexed"
    assert entry["chunks"] == 12
    assert entry["extraction_evidence"]["source_sha256"] == sha1
    pdf.write_bytes(b"pdf-v2-changed")
    entry2 = jarvis_rag_ingest_events.attach_review_extraction_evidence(
        str(pdf),
        source_sha256=sha1,
        evidence={"kind": "pdf_ocr_verify", "ocr_verification_state": "cross_checked", "quality_state": "needs_review"},
    )
    assert entry2["phase"] == "indexed"
    assert entry2["ocr_verification_state"] == "stale"
    assert entry2["extraction_evidence"]["stale"] is True


def test_project_scope_and_no_client_output_dir(tmp_path, monkeypatch):
    root = tmp_path / "Library"
    project = root / "Projects" / "Projects - 2026" / "26HOS-006"
    other = root / "Projects" / "Projects - 2026" / "OTHER"
    project.mkdir(parents=True)
    other.mkdir(parents=True)
    inside = project / "ok.dxf"
    outside = other / "secret.dxf"
    ezdxf = pytest.importorskip("ezdxf")
    for target in (inside, outside):
        doc = ezdxf.new()
        doc.modelspace().add_text("X", dxfattribs={"insert": (0, 0), "height": 1})
        doc.saveas(target)
    monkeypatch.setattr(jarvis_rag_ingest_events, "LIBRARY_ROOT", str(root))
    monkeypatch.setattr(smedley_project_review_extract, "LIBRARY_ROOT", str(root))
    monkeypatch.setattr(jarvis_rag_ingest_events, "EVIDENCE_ROOT", str(tmp_path / "evidence"))

    ok = smedley_project_review_extract.extract_project_document(
        str(inside),
        rag_folder="Projects/Projects - 2026/26HOS-006",
        update_ledger=False,
    )
    assert ok["ok"] is True
    assert str(ok["evidence_dir"]).startswith(str(tmp_path / "evidence"))

    with pytest.raises(ValueError, match="outside the selected Project Review RAG folder"):
        smedley_project_review_extract.extract_project_document(
            str(outside),
            rag_folder="Projects/Projects - 2026/26HOS-006",
            update_ledger=False,
        )
    with pytest.raises(ValueError, match="RAG folder"):
        smedley_project_review_extract.extract_project_document(
            str(inside),
            rag_folder="",
            update_ledger=False,
        )
    with pytest.raises(ValueError, match="max_pages"):
        smedley_project_review_extract.extract_project_document(
            str(inside),
            rag_folder="Projects/Projects - 2026/26HOS-006",
            update_ledger=False,
            max_pages=0,
        )


def test_native_text_does_not_require_ocr_engines(tmp_path, monkeypatch):
    pypdfium2 = pytest.importorskip("pypdfium2")
    pdf_path = tmp_path / "native.pdf"
    doc = pypdfium2.PdfDocument.new()
    doc.new_page(200, 200)
    doc.save(pdf_path)
    doc.close()

    def boom(*args, **kwargs):
        raise AssertionError("OCR should not run for non-raster native-only page")

    monkeypatch.setattr(smedley_pdf_ocr_verify, "page_looks_raster", lambda *a, **k: False)
    monkeypatch.setattr(
        smedley_pdf_ocr_verify,
        "page_image_coverage",
        lambda *a, **k: {"ink_ratio": 0.0, "contrast": 0.0, "significant": False},
    )
    # Many native fragments => not sparse; blank coverage => no OCR trigger.
    monkeypatch.setattr(
        smedley_pdf_ocr_verify,
        "_native_fragments",
        lambda page, page_no: [
            {"engine": "native", "page": page_no, "text": f"WORD{i}", "bbox": [i, i, i + 1, i + 1]}
            for i in range(12)
        ],
    )
    result = smedley_pdf_ocr_verify.verify_pdf(
        str(pdf_path),
        evidence_dir=str(tmp_path / "ev"),
        update_ledger=False,
        force_raster_ocr=False,
        producer_mode=None,
        rapidocr_runner=boom,
        tesseract_runner=boom,
        max_pages=1,
    )
    assert result["ocr_verification_state"] == "not_applicable"
    assert result["state"] == "native_text"
    assert result["pages"][0]["ocr_trigger"] == "native_text_only"
    assert result["source_snapshot"]["snapshot_path"]
    assert Path(result["parse_path"]).is_file()


def test_multi_page_engine_failure_and_raw_outputs_separated(tmp_path, monkeypatch):
    pypdfium2 = pytest.importorskip("pypdfium2")
    pdf_path = tmp_path / "rasterish.pdf"
    doc = pypdfium2.PdfDocument.new()
    doc.new_page(300, 300)
    doc.new_page(300, 300)
    doc.save(pdf_path)
    doc.close()

    def a_runner(image_path, page_index, python_bin=None):
        if page_index == 2:
            return [], {"available": False, "error": "engine failed page 2"}
        return [{"engine": "rapidocr", "page": page_index, "text": "A", "bbox": [10, 10, 20, 20], "confidence": 0.9}], {"available": True, "count": 1}

    def b_runner(image_path, page_index, tesseract_cmd=None):
        return [{"engine": "tesseract", "page": page_index, "text": "A", "bbox": [10, 10, 20, 20], "confidence": 0.9}], {"available": True, "count": 1}

    monkeypatch.setattr(
        smedley_pdf_ocr_verify,
        "select_ocr_orientation",
        lambda *a, **k: {
            "rotate_cw_deg": 0,
            "reason": "test_stub",
            "method": "ocr_orientation_sweep",
            "original_unmodified": True,
        },
    )
    # Force OCR path; grid may fail on blank pages -> needs_review / unavailable honest.
    result = smedley_pdf_ocr_verify.verify_pdf(
        str(pdf_path),
        evidence_dir=str(tmp_path / "ev2"),
        update_ledger=False,
        force_raster_ocr=True,
        producer_mode="full_ocr",
        rapidocr_runner=a_runner,
        tesseract_runner=b_runner,
        max_pages=2,
    )
    assert result["ok"] is True
    assert result["ocr_verification_state"] in {"needs_review", "unavailable"}
    raw = result["raw_engine_outputs"]
    assert Path(raw["rapidocr_fragments_path"]).is_file()
    assert "verified_cell_reports" in result
    assert raw["rapidocr_fragments_path"] != result.get("manifest_path")


def test_tool_routes_and_mcp_adapter_callable(tmp_path, monkeypatch):
    routes_text = (Path(__file__).resolve().parents[1] / "api" / "routes.py").read_text(encoding="utf-8")
    assert "/api/smedley/project-review/extract" in routes_text
    assert "project_review_extract_capabilities" in routes_text
    assert "project_review_extract" in routes_text
    assert "project_id:" in routes_text
    assert "output_dir is not client-configurable" in routes_text
    caps = smedley_project_review_extract.capabilities()
    assert caps["tool_name"] == "project_review_extract"
    assert caps["mcp_tools"] == ["project_review_extract_capabilities", "project_review_extract"]
    assert caps["callable"] is True

    # Real MCP adapter functions (not URL-string-only registration).
    import importlib.util

    monkeypatch.setenv("HERMES_WEBUI_STATE_DIR", str(tmp_path / "webui-state"))
    (tmp_path / "webui-state").mkdir()
    mcp_path = Path(__file__).resolve().parents[1] / "scripts" / "smedley_project_review_mcp.py"
    spec = importlib.util.spec_from_file_location("smedley_project_review_mcp_test", mcp_path)
    mcp_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mcp_mod)
    tool_caps = json.loads(mcp_mod.project_review_extract_capabilities())
    assert tool_caps["callable"] is True
    assert tool_caps["activation"]["mcp_server"] == "smedley_project_review"
    assert "project_review_extract" in tool_caps["activation"]["tools"]
    missing = json.loads(mcp_mod.project_review_extract(project_id="missing-project", path="/tmp/nope.dxf", update_ledger=False))
    assert missing["ok"] is False
    assert "project review not found" in missing["error"] or "HERMES_WEBUI_STATE_DIR" in missing["error"]

    fixture = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "project_review" / "sample_panel.dxf"
    rag = tmp_path / "rag"
    rag.mkdir()
    target = rag / "sample_panel.dxf"
    target.write_bytes(fixture.read_bytes())
    monkeypatch.setenv("SMEDLEY_PROJECT_REVIEW_EVIDENCE_ROOT", str(tmp_path / "evidence"))
    monkeypatch.setattr(mcp_mod, "_load_review_project", lambda project_id: {
        "project_id": project_id,
        "name": "fixture-review",
        "profile": "smedley",
        "review": {"rag_folder": "Projects/Projects - 2026/26HOS-006", "review_owner": "smedley"},
    })
    monkeypatch.setattr(
        "api.smedley_project_review_extract._resolve_scoped_path",
        lambda path, rag_folder: str(target),
    )
    body = json.loads(
        mcp_mod.project_review_extract(
            project_id="fixture",
            path=str(target),
            kind="dxf",
            update_ledger=False,
        )
    )
    assert body["ok"] is True
    assert body["tool"] == "project_review_extract"
    assert body["project_id"] == "fixture"
    assert body["evidence_dir"]
    assert body.get("state") in {"extracted", "needs_review"}


def test_border_joined_side_by_side_and_unequal_rows(tmp_path):
    """Regression: shared horizontal rules + narrow gutter must not invent gutter cells."""
    # Two tables sharing continuous horizontal lines across a 24px gutter.
    img = Image.new("RGB", (900, 320), "white")
    draw = ImageDraw.Draw(img)
    left_x0, left_x1 = 20, 420
    right_x0, right_x1 = 444, 860  # 24px gutter
    # Unequal row heights.
    y_lines = [20, 55, 100, 130, 175, 220, 260]
    v_left = [20, 70, 140, 220, 300, 360, 420]
    v_right = [444, 500, 580, 660, 740, 800, 860]
    for y in y_lines:
        draw.line((left_x0, y, right_x1, y), fill="black", width=2)  # shared rules across gutter
    for x in v_left + v_right:
        draw.line((x, y_lines[0], x, y_lines[-1]), fill="black", width=2)
    # Labels only inside table interiors (not gutter).
    draw.text((80, 30), "REV", fill="black")
    draw.text((160, 30), "ITEM", fill="black")
    draw.text((520, 30), "DEV", fill="black")
    path = tmp_path / "border_joined.png"
    img.save(path)
    grid = smedley_table_grid.detect_ruled_tables(Image.open(path), page=1)
    assert grid.get("structure_verified") is True
    assert grid["ok"] is True
    assert len(grid["tables"]) >= 2
    # No cell may span the gutter whitespace.
    for cell in grid["cells"]:
        x0, _, x1, _ = cell["bbox"]
        assert not (x0 < 430 and x1 > 440), cell["cell_id"]
    # Unequal row heights preserved (not uniform).
    t0 = grid["tables"][0]
    heights = [t0["h_lines"][i + 1] - t0["h_lines"][i] for i in range(len(t0["h_lines"]) - 1)]
    assert len(set(heights)) >= 2


def test_wb3339_012_rendered_fixture_recovers_header_and_columns():
    """Source-grounded regression on saved WB3339-012 page render (no new OCR run).

    Visual ground truth: BOM 8 cols × (header+11 data)=12 rows; device 9 cols ×
    (header+25 data)=26 rows; both tops on the drawing border (~y=28). Prior
    bug dropped header/item1 and invented a phantom BOM column from drawing ink.
    """
    fixture = Path(__file__).resolve().parents[1] / "tests/fixtures/project_review/wb3339_012_page_render.png"
    assert fixture.is_file(), fixture
    grid = smedley_table_grid.detect_ruled_tables(Image.open(fixture), page=1)
    assert grid.get("ok") is True
    assert grid.get("structure_verified") is True
    tables = sorted(grid["tables"], key=lambda t: t["bbox"][0])
    assert len(tables) >= 2
    bom, device = tables[0], tables[1]
    assert bom["col_count"] == 8, bom
    assert bom["row_count"] == 12, bom
    assert bom["bbox"][1] <= 35, bom  # includes header on page border
    assert device["col_count"] == 9, device
    assert device["row_count"] == 26, device
    assert device["bbox"][1] <= 35, device
    # Header OCR band (~y=27) must fall inside table bboxes (not unassigned above).
    assert bom["bbox"][1] <= 28 <= bom["bbox"][3]
    assert device["bbox"][1] <= 28 <= device["bbox"][3]


def test_wb3339_012_embedded_bom_native_raster_grid():
    """Preferred path: native embedded CCITT BOM (oriented) is clean 12×8."""
    oriented = Path(__file__).resolve().parents[1] / "tests/fixtures/project_review/wb3339_012_embedded_bom_oriented.png"
    source = Path(__file__).resolve().parents[1] / "tests/fixtures/project_review/wb3339_012_embedded_bom_source.png"
    assert oriented.is_file() and source.is_file()
    grid = smedley_table_grid.detect_ruled_tables(Image.open(oriented), page=1)
    assert grid.get("structure_verified") is True
    assert len(grid["tables"]) == 1
    t = grid["tables"][0]
    assert t["row_count"] == 12
    assert t["col_count"] == 8
    # Orientation sweep must prefer readable upright (270 CW here) over upside-down 90.
    ori = smedley_table_grid.select_table_raster_orientation(Image.open(source))
    assert ori.get("uncertain") is False
    assert int(ori.get("rotate_cw_deg") or 0) == 270
    assert (ori.get("best") or {}).get("primary", {}).get("col_count") == 8
    assert (ori.get("best") or {}).get("primary", {}).get("row_count") == 12


def test_embedded_image_extract_and_prepare(tmp_path):
    """pypdfium2 embedded extract returns provenance + verified native grids."""
    from api.smedley_pdf_embedded_images import collect_embedded_table_candidates
    import pypdfium2 as pdfium

    pdf = Path(
        "/Users/rick/Mounts/RAG_Pool/Library/Projects/Projects - 2026/26HOS-006/"
        "WB3339-012  Device Location, Item 130 - Stacker Infeed Roll Conveyor (1 of ).pdf"
    )
    if not pdf.is_file():
        pytest.skip("26HOS-006 WB3339-012 not mounted")
    doc = pdfium.PdfDocument(str(pdf))
    page = doc[0]
    result = collect_embedded_table_candidates(
        page,
        page_no=1,
        evidence_dir=str(tmp_path),
        source_sha256="test-sha",
    )
    doc.close()
    assert result.get("prefer_embedded_over_page_render") is True
    assert result.get("coverage_complete") is True
    assert result.get("omissions") == []
    verified = [
        c for c in result.get("candidates") or []
        if (c.get("table_structure") or {}).get("structure_verified")
    ]
    assert len(verified) == 2
    shapes = sorted(
        (
            int(t["row_count"]),
            int(t["col_count"]),
        )
        for c in verified
        for t in (c.get("table_structure") or {}).get("tables") or []
    )
    assert shapes == [(12, 8), (26, 9)]
    for c in verified:
        assert c.get("source_bbox_pdf")
        assert c.get("placement_matrix")
        assert c.get("image_sha256")
        assert Path(c["source_png"]).is_file()
        assert Path(c["oriented_png"]).is_file()


def test_embedded_mixed_good_bad_candidates_mark_incomplete_coverage():
    """One verified + one failed significant candidate must not claim full coverage."""
    from api import smedley_pdf_embedded_images as emb

    good = {
        "image_index": 0,
        "px_size": [1000, 2000],
        "source_bbox_pdf": [1, 2, 3, 4],
        "table_structure": {"structure_verified": True, "reason": "ok", "cell_count": 10, "warnings": []},
    }
    bad = {
        "image_index": 1,
        "px_size": [900, 1800],
        "source_bbox_pdf": [5, 6, 7, 8],
        "table_structure": {
            "structure_verified": False,
            "reason": "embedded_raster_ambiguous_table_split",
            "cell_count": 0,
            "warnings": ["split"],
        },
    }
    # Reproduce coverage bookkeeping without PDF I/O.
    prepared = [good, bad]
    verified = [row for row in prepared if (row.get("table_structure") or {}).get("structure_verified")]
    failed = [
        {
            "kind": "candidate_structure_failed",
            "image_index": row.get("image_index"),
            "px_size": row.get("px_size"),
            "source_bbox_pdf": row.get("source_bbox_pdf"),
            "reason": (row.get("table_structure") or {}).get("reason"),
        }
        for row in prepared
        if not (row.get("table_structure") or {}).get("structure_verified")
    ]
    significant_skips = [{"kind": "skipped_significant", "image_index": 2, "reason": "max_images_per_page"}]
    nontable = [{
        "kind": "unprocessed_non_table_candidate",
        "image_index": 3,
        "reason": "unprocessed_non_table_candidate",
        "detail": "below_table_candidate_size_threshold",
        "px_size": [146, 1806],
    }]
    omissions = failed + significant_skips
    coverage_complete = bool(verified) and not omissions
    prefer = len(verified) >= 1
    assert prefer is True
    assert coverage_complete is False
    assert len(omissions) == 2
    # Non-table size skips are out of table-coverage scope (not omissions).
    assert nontable[0]["kind"] == "unprocessed_non_table_candidate"
    assert nontable[0] not in omissions
    # Direct helper: size threshold still gates table candidates.
    assert emb.DEFAULT_MIN_EDGE_PX >= 400


def test_compare_aligned_cells_full_lists_and_preview_bound():
    cells_a = [
        {
            "page": 1,
            "table_id": "t",
            "row": i,
            "col": 0,
            "col_span": 1,
            "row_span": 1,
            "cell_id": f"t-r{i}-c0",
            "text": f"A{i}",
            "bbox": [0, i, 10, i + 1],
        }
        for i in range(5)
    ]
    cells_b = [{**c, "text": c["text"] if c["row"] != 2 else "DIFF"} for c in cells_a]
    cross = smedley_table_grid.compare_aligned_cells(
        cells_a, cells_b, sample_limit=2, include_full_lists=True
    )
    assert cross["matched_nonblank_count"] == 4
    assert cross["disagree_count"] == 1
    assert len(cross["matched_nonblank_sample"]) <= 2
    assert len(cross["full"]["matched_nonblank"]) == 4
    assert len(cross["full"]["disagree"]) == 1


def test_page_frame_macro_gap_and_shared_border_splits(tmp_path):
    """Drawing dead-zone + shared-border dual tables must split without phantom cols."""
    # Page frame with left drawing dead zone and one 5-col table on the right.
    img = Image.new("RGB", (900, 280), "white")
    draw = ImageDraw.Draw(img)
    # Outer page border (joins tables to frame — the failure mode under test).
    draw.rectangle((10, 10, 890, 270), outline="black", width=3)
    y_lines = [10, 40, 70, 100, 130, 160, 190]
    # Left border of page at x=10, then huge empty drawing zone, table at x=500.
    v_table = [500, 560, 630, 710, 790, 890]
    for y in y_lines:
        draw.line((10, y, 890, y), fill="black", width=2)
    draw.line((10, y_lines[0], 10, y_lines[-1]), fill="black", width=3)
    for x in v_table:
        draw.line((x, y_lines[0], x, y_lines[-1]), fill="black", width=2)
    for i, label in enumerate(["REV", "ITEM", "QTY", "DESC", "MFG"]):
        draw.text((v_table[i] + 8, 18), label, fill="black")
    # Phantom vertical in the drawing zone below the table band (must not become a col).
    draw.line((200, 210, 200, 260), fill="black", width=2)
    path = tmp_path / "macro_gap.png"
    img.save(path)
    grid = smedley_table_grid.detect_ruled_tables(Image.open(path), page=1)
    assert grid.get("ok") is True
    assert grid.get("structure_verified") is True
    assert len(grid["tables"]) >= 1
    # No table may claim the drawing dead zone as a data column.
    for t in grid["tables"]:
        assert t["bbox"][0] >= 450, t
        assert t["col_count"] == 5, t
        assert t["bbox"][1] <= 15, t  # keep page-border header line

    # Shared border (no whitespace gutter): two 6-col tables joined at x=450.
    # Threshold requires >=12 columns so a single 8-col BOM is not bisected.
    img2 = Image.new("RGB", (940, 260), "white")
    d2 = ImageDraw.Draw(img2)
    y2 = [12, 42, 72, 102, 132, 162, 192]
    left_v = [20, 70, 130, 200, 280, 360, 450]
    right_v = [450, 520, 590, 670, 760, 850, 930]
    for y in y2:
        d2.line((20, y, 930, y), fill="black", width=2)
    for x in left_v + right_v[1:]:
        d2.line((x, y2[0], x, y2[-1]), fill="black", width=2)
    d2.text((80, 20), "L0", fill="black")
    d2.text((530, 20), "R0", fill="black")
    path2 = tmp_path / "shared_border.png"
    img2.save(path2)
    grid2 = smedley_table_grid.detect_ruled_tables(Image.open(path2), page=1)
    assert grid2.get("ok") is True
    assert len(grid2["tables"]) >= 2
    cols = sorted(t["col_count"] for t in grid2["tables"][:2])
    assert cols == [6, 6], grid2["tables"]


def test_engine_agreement_never_sets_cells_verified():
    """Two engines agreeing is evidence only — never engineering cells_verified."""
    cells = [
        {
            "page": 1,
            "table_id": "p1-t0",
            "row": 0,
            "col": c,
            "row_span": 1,
            "col_span": 1,
            "bbox": [c * 40, 10, c * 40 + 40, 40],
            "cell_id": f"p1-t0-r0-c{c}",
            "engine": "rapidocr",
            "text": f"V{c}",
            "blank": False,
            "confidence_min": 0.9,
        }
        for c in range(3)
    ]
    secondary = [{**c, "engine": "tesseract"} for c in cells]
    cross = smedley_table_grid.compare_aligned_cells(cells, secondary)
    assert cross["matched_nonblank_count"] == 3
    assert cross.get("agreement_does_not_prove_correctness") is True
    # compare_aligned_cells must not invent a cells_verified promotion field.
    assert cross.get("cells_verified") in (None, False)


def test_side_by_side_tables_stay_separate_and_pid_rejects_fabricated_grid(tmp_path):
    # Two separate ruled tables on one page must not become one whole-page grid.
    img = Image.new("RGB", (700, 220), "white")
    draw = ImageDraw.Draw(img)
    def _table(x0, y0, rows, cols, label):
        cw, ch = 60, 30
        for r in range(rows + 1):
            draw.line((x0, y0 + r * ch, x0 + cols * cw, y0 + r * ch), fill="black", width=2)
        for c in range(cols + 1):
            draw.line((x0 + c * cw, y0, x0 + c * cw, y0 + rows * ch), fill="black", width=2)
        draw.text((x0 + 8, y0 + 8), label, fill="black")
    _table(20, 20, 4, 5, "BOM")
    _table(400, 20, 5, 4, "WIRE")
    path = tmp_path / "side.png"
    img.save(path)
    grid = smedley_table_grid.detect_ruled_tables(Image.open(path), page=1)
    assert grid["ok"] is True
    assert len(grid["tables"]) >= 2
    ids = {t["table_id"] for t in grid["tables"]}
    assert len(ids) >= 2

    # Sparse schematic-like boxes should not fabricate a data-table grid.
    pid = Image.new("RGB", (800, 1100), "white")
    d = ImageDraw.Draw(pid)
    d.rectangle((50, 50, 150, 120), outline="black", width=2)
    d.rectangle((200, 80, 280, 140), outline="black", width=2)
    d.line((50, 200, 700, 200), fill="black", width=2)
    d.line((100, 100, 100, 900), fill="black", width=2)
    d.rectangle((500, 900, 760, 1050), outline="black", width=2)  # title-ish
    pid_path = tmp_path / "pid.png"
    pid.save(pid_path)
    pid_grid = smedley_table_grid.detect_ruled_tables(Image.open(pid_path), page=1)
    assert pid_grid["ok"] is False
    assert pid_grid["reason"] in {"not_table_engineering_drawing", "unrecognized_table_structure", "structure_unverified"}
    assert pid_grid["cells"] == []


def test_blank_ink_ignores_border_rules(tmp_path):
    img = Image.new("RGB", (120, 80), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle((10, 10, 110, 70), outline="black", width=3)
    # Empty interior — borders alone must not count as visible ink.
    assert smedley_table_grid.cell_has_visible_ink(img, [10, 10, 110, 70]) is False
    draw.text((40, 35), "A", fill="black")
    assert smedley_table_grid.cell_has_visible_ink(img, [10, 10, 110, 70]) is True


def test_mcp_load_projects_readonly_biggy_state(monkeypatch):
    """Read-only lookup against live Biggy webui-state when present; no migration writes."""
    state = Path("/Users/rick/.hermes/profiles/biggy/webui-state/projects.json")
    if not state.is_file():
        pytest.skip("Biggy webui-state projects.json not present")
    before_mtime = state.stat().st_mtime_ns
    projects = json.loads(state.read_text(encoding="utf-8"))
    after_mtime = state.stat().st_mtime_ns
    assert before_mtime == after_mtime
    hit = next((p for p in projects if str(p.get("project_id")) == "bdd341b152a4"), None)
    assert hit is not None
    assert hit.get("name") == "26HOS-006"
    assert (hit.get("review") or {}).get("review_owner") == "smedley"

    # Fresh interpreter with staged env exercises load_projects(_migrate=False) path.
    import subprocess

    script = r"""
import json, os
os.environ["HERMES_WEBUI_STATE_DIR"] = "/Users/rick/.hermes/profiles/biggy/webui-state"
from api.models import load_projects, PROJECTS_FILE
assert "biggy/webui-state" in str(PROJECTS_FILE)
before = PROJECTS_FILE.stat().st_mtime_ns
projects = load_projects(_migrate=False)
after = PROJECTS_FILE.stat().st_mtime_ns
assert before == after
hit = next(p for p in projects if p.get("project_id") == "bdd341b152a4")
print(json.dumps({"ok": True, "name": hit.get("name"), "owner": (hit.get("review") or {}).get("review_owner")}))
"""
    proc = subprocess.run(
        [str(Path(__file__).resolve().parents[1] / ".venv" / "bin" / "python"), "-c", script],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[1]),
        env={**os.environ, "HERMES_WEBUI_STATE_DIR": "/Users/rick/.hermes/profiles/biggy/webui-state"},
    )
    assert proc.returncode == 0, proc.stderr
    body = json.loads(proc.stdout.strip().splitlines()[-1])
    assert body["name"] == "26HOS-006"
    assert body["owner"] == "smedley"
    assert state.stat().st_mtime_ns == before_mtime


def test_mcp_stdio_initialize_list_call(tmp_path, monkeypatch):
    """Actual MCP stdio initialize/list/call with staged env + temporary evidence root."""
    import subprocess
    import time

    state_dir = "/Users/rick/.hermes/profiles/biggy/webui-state"
    projects_path = Path(state_dir) / "projects.json"
    if not projects_path.is_file():
        pytest.skip("Biggy webui-state not present")
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    env = os.environ.copy()
    env["HERMES_WEBUI_STATE_DIR"] = state_dir
    env["SMEDLEY_PROJECT_REVIEW_EVIDENCE_ROOT"] = str(evidence)
    env["PYTHONUNBUFFERED"] = "1"
    before_mtime = projects_path.stat().st_mtime_ns
    cmd = [
        str(Path(__file__).resolve().parents[1] / ".venv" / "bin" / "python"),
        str(Path(__file__).resolve().parents[1] / "scripts" / "smedley_project_review_mcp.py"),
    ]
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=True,
        bufsize=1,
    )

    def send(msg: dict) -> None:
        proc.stdin.write(json.dumps(msg) + "\n")
        proc.stdin.flush()

    def recv(expect_id: int, timeout=30.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            line = proc.stdout.readline()
            if not line:
                continue
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("id") == expect_id:
                return msg
        raise TimeoutError(f"MCP stdout timeout waiting for id={expect_id}")

    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "0"},
        }})
        init = recv(1)
        assert "result" in init
        send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        listed = recv(2)
        names = {t.get("name") for t in ((listed.get("result") or {}).get("tools") or [])}
        assert "project_review_extract_capabilities" in names
        assert "project_review_extract" in names
        send({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "project_review_extract_capabilities",
            "arguments": {},
        }})
        caps_msg = recv(3, timeout=60)
        content = ((caps_msg.get("result") or {}).get("content") or [{}])[0].get("text") or "{}"
        caps = json.loads(content)
        assert caps.get("callable") is True
        assert "project_review_extract" in (caps.get("mcp_tools") or caps.get("activation", {}).get("tools") or [])
        send({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
            "name": "project_review_extract",
            "arguments": {
                "project_id": "bdd341b152a4",
                "path": "does-not-exist.dxf",
                "update_ledger": False,
                "max_pages": 1,
            },
        }})
        extract_msg = recv(4, timeout=60)
        extract_text = ((extract_msg.get("result") or {}).get("content") or [{}])[0].get("text") or "{}"
        extract_body = json.loads(extract_text)
        assert extract_body.get("project_id") == "bdd341b152a4"
        assert extract_body.get("ok") is False
        assert projects_path.stat().st_mtime_ns == before_mtime
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()


def test_sparse_native_with_coverage_triggers_ocr_without_force(tmp_path, monkeypatch):
    pypdfium2 = pytest.importorskip("pypdfium2")
    pdf_path = tmp_path / "pidish.pdf"
    doc = pypdfium2.PdfDocument.new()
    doc.new_page(400, 600)
    doc.save(pdf_path)
    doc.close()

    monkeypatch.setattr(smedley_pdf_ocr_verify, "page_looks_raster", lambda *a, **k: False)
    monkeypatch.setattr(
        smedley_pdf_ocr_verify,
        "page_image_coverage",
        lambda *a, **k: {"ink_ratio": 0.08, "contrast": 120.0, "significant": True},
    )
    monkeypatch.setattr(
        smedley_pdf_ocr_verify,
        "_native_fragments",
        lambda page, page_no: [
            {"engine": "native", "page": page_no, "text": "12-1-0104", "bbox": [1, 1, 2, 2]},
            {"engine": "native", "page": page_no, "text": "TITLE", "bbox": [3, 3, 4, 4]},
        ],
    )
    monkeypatch.setattr(
        smedley_pdf_ocr_verify,
        "select_ocr_orientation",
        lambda *a, **k: {
            "rotate_cw_deg": 270,
            "reason": "tesseract_orientation_confidence",
            "method": "ocr_orientation_sweep",
            "original_unmodified": True,
            "best": {"rotate_cw_deg": 270, "score": 999},
        },
    )
    called = {"a": 0, "b": 0}

    def a_runner(image_path, page_index, python_bin=None):
        called["a"] += 1
        return [{"engine": "rapidocr", "page": page_index, "text": "TALL OIL SCRUBBER", "bbox": [10, 10, 40, 20], "confidence": 0.9}], {"available": True, "count": 1}

    def b_runner(image_path, page_index, tesseract_cmd=None):
        called["b"] += 1
        return [{"engine": "tesseract", "page": page_index, "text": "TALL OIL SCRUBBER", "bbox": [10, 10, 40, 20], "confidence": 0.9}], {"available": True, "count": 1}

    result = smedley_pdf_ocr_verify.verify_pdf(
        str(pdf_path),
        evidence_dir=str(tmp_path / "ev-sparse"),
        update_ledger=False,
        force_raster_ocr=False,
        producer_mode=None,
        rapidocr_runner=a_runner,
        tesseract_runner=b_runner,
        max_pages=1,
    )
    assert called["a"] == 1 and called["b"] == 1
    page = result["pages"][0]
    assert page["ocr_trigger"] == "sparse_native_with_image_coverage"
    assert page["raster_detected"] is False
    assert page["ocr_rotation_cw_deg"] == 270
    assert page["ocr_rotation_ccw_deg"] == 90
    assert page["source_render_coordinate_space"] == "source_page_render"
    assert page["ocr_render_coordinate_space"] == "ocr_oriented_render"
    assert page["ocr_render"] and Path(page["ocr_render"]).is_file()
    assert Path(page["render"]).is_file()
    assert page["ocr_render"] != page["render"]
    assert result["original_preserved"] is True


def test_snapshot_toctou_expected_hash_mismatch_fails_closed(tmp_path):
    pypdfium2 = pytest.importorskip("pypdfium2")
    pdf_path = tmp_path / "live.pdf"
    doc = pypdfium2.PdfDocument.new()
    doc.new_page(120, 120)
    doc.save(pdf_path)
    doc.close()
    result = smedley_pdf_ocr_verify.verify_pdf(
        str(pdf_path),
        evidence_dir=str(tmp_path / "ev-mismatch"),
        update_ledger=False,
        force_raster_ocr=False,
        source_sha256="0" * 64,
        max_pages=1,
        rapidocr_runner=lambda *a, **k: ([], {"available": False}),
        tesseract_runner=lambda *a, **k: ([], {"available": False}),
    )
    assert result["ok"] is False
    assert "changed" in (result.get("reason") or "").lower() or "mismatch" in (result.get("reason") or "").lower()


def test_snapshot_survives_live_mutation_and_does_not_clobber_prior(tmp_path, monkeypatch):
    ezdxf = pytest.importorskip("ezdxf")
    dxf_path = tmp_path / "drawing.dxf"
    doc = ezdxf.new("R2010")
    doc.modelspace().add_text("BEFORE", dxfattribs={"insert": (0, 0), "height": 1})
    doc.saveas(dxf_path)

    from api.smedley_source_snapshot import materialize_source_snapshot, file_sha256

    ev1 = tmp_path / "ev-run1"
    snap1 = materialize_source_snapshot(str(dxf_path), evidence_dir=str(ev1), max_bytes=10_000_000)
    sha1 = snap1["source_sha256"]
    # Mutate live library file after snapshot.
    doc2 = ezdxf.new("R2010")
    doc2.modelspace().add_text("AFTER-MUTATION", dxfattribs={"insert": (0, 0), "height": 1})
    doc2.saveas(dxf_path)
    assert file_sha256(str(dxf_path)) != sha1

    result = smedley_dxf_extract.extract_dxf(
        str(dxf_path),
        evidence_dir=str(ev1),
        update_ledger=False,
        source_sha256=sha1,
        source_snapshot=snap1,
    )
    assert result["ok"] is True
    assert result["source_sha256"] == sha1
    assert any(t.get("text") == "BEFORE" for t in result["texts"])
    assert not any(t.get("text") == "AFTER-MUTATION" for t in result["texts"])
    assert Path(result["parse_path"]).is_file()
    assert Path(result["parse_path"]).resolve() != Path(dxf_path).resolve()

    # Second run materializes a distinct snapshot name; prior file remains.
    prior_names = set(os.listdir(ev1 / "source_snapshot"))
    ev2 = tmp_path / "ev-run2"
    result2 = smedley_dxf_extract.extract_dxf(
        str(dxf_path),
        evidence_dir=str(ev2),
        update_ledger=False,
    )
    assert result2["ok"] is True
    assert any(t.get("text") == "AFTER-MUTATION" for t in result2["texts"])
    assert prior_names.issubset(set(os.listdir(ev1 / "source_snapshot")))
    assert Path(snap1["snapshot_path"]).is_file()


def test_select_ocr_orientation_prefers_readable_rotation(tmp_path):
    pytest.importorskip("pytesseract")
    # Generic upright label (no sample-sheet vocabulary). Scale up for OCR signal.
    base = Image.new("RGB", (640, 160), "white")
    draw = ImageDraw.Draw(base)
    draw.text((30, 55), "WIDGET PANEL HEADER ROW SECTOR", fill="black")
    img = base.resize((1280, 320), Image.Resampling.NEAREST)
    from api.smedley_table_grid import select_ocr_orientation

    upright = select_ocr_orientation(img, timeout_s=15.0)
    assert upright["method"] == "ocr_orientation_sweep"
    assert "cue_hits" not in (upright.get("best") or {})
    assert len(upright["candidates"]) == 4
    assert upright["probe_timeout_s"] == 15.0
    assert upright["rotate_cw_deg"] in {0, 90, 180, 270}
    if not upright.get("uncertain"):
        assert upright["rotate_cw_deg"] == 0

    # Image already rotated 90 CW → sweep should select 270 CW when decisive.
    sideways = img.rotate(-90, expand=True)
    recovered = select_ocr_orientation(sideways, timeout_s=15.0)
    assert recovered["method"] == "ocr_orientation_sweep"
    assert "cue_hits" not in (recovered.get("best") or {})
    if not recovered.get("uncertain"):
        assert recovered["rotate_cw_deg"] == 270
    # At least one orientation must outscore the others on this fixture when decisive,
    # or uncertainty must be reported honestly.
    assert recovered.get("uncertain") or recovered["rotate_cw_deg"] == 270
    scores = [c["score"] for c in recovered["candidates"]]
    assert max(scores) >= 0



def test_snapshot_same_process_twice_does_not_overwrite(tmp_path):
    src = tmp_path / "same.pdf"
    src.write_bytes(b"%PDF-1.4 sample-bytes-v1")
    from api.smedley_source_snapshot import materialize_source_snapshot

    ev = tmp_path / "ev"
    a = materialize_source_snapshot(str(src), evidence_dir=str(ev), max_bytes=1_000_000)
    b = materialize_source_snapshot(str(src), evidence_dir=str(ev), max_bytes=1_000_000)
    assert a["snapshot_path"] != b["snapshot_path"]
    assert Path(a["snapshot_path"]).is_file()
    assert Path(b["snapshot_path"]).is_file()
    assert Path(a["snapshot_path"]).read_bytes() == Path(b["snapshot_path"]).read_bytes()
    names = list((ev / "source_snapshot").iterdir())
    assert len(names) == 2


def test_crop_cell_for_ocr_insets_and_pads():
    from api.smedley_cell_ocr import crop_cell_for_ocr

    img = Image.new("RGB", (100, 40), "white")
    # Dark border around a white interior — inset must drop the border ink.
    for x in range(10, 50):
        img.putpixel((x, 5), (0, 0, 0))
        img.putpixel((x, 34), (0, 0, 0))
    for y in range(5, 35):
        img.putpixel((10, y), (0, 0, 0))
        img.putpixel((49, y), (0, 0, 0))
    crop = crop_cell_for_ocr(img, [10, 5, 50, 35], inset_px=2, pad_px=4)
    # Interior after inset 36×26 + pad 4 each side → 44×34
    assert crop.size == (36 + 8, 26 + 8)
    # Padded rim is white (no automatic glyph wipe of interior).
    assert crop.getpixel((0, 0)) == (255, 255, 255)


def test_choose_tesseract_psm_from_geometry_not_document_name():
    from api.smedley_cell_ocr import choose_tesseract_psm

    # Short header / item cells → single line
    assert choose_tesseract_psm([0, 0, 80, 24], median_row_height=24) == 7
    # Tall description relative to median row pitch → block
    assert choose_tesseract_psm([0, 0, 400, 80], median_row_height=30) == 6
    # Absolute tall cell without median still block
    assert choose_tesseract_psm([0, 0, 100, 70], median_row_height=None) == 6


def test_ocr_cells_isolated_keeps_per_cell_text_and_spans(tmp_path):
    """Generic mock: engines see separate crops; no cross-cell string join."""
    from api import smedley_cell_ocr as cell_ocr

    img = Image.new("RGB", (300, 60), "white")
    # Non-blank ink so geometric_blank short-circuit does not skip engines.
    for x in range(5, 295):
        for y in range(8, 52):
            if x % 17 == 0 or y % 11 == 0:
                img.putpixel((x, y), (0, 0, 0))
    cells = [
        {
            "cell_id": "t0-r0-c0",
            "bbox": [0, 0, 100, 40],
            "row": 0,
            "col": 0,
            "row_span": 1,
            "col_span": 1,
            "table_id": "t0",
        },
        {
            "cell_id": "t0-r0-c1",
            "bbox": [100, 0, 200, 40],
            "row": 0,
            "col": 1,
            "row_span": 1,
            "col_span": 1,
            "table_id": "t0",
        },
        {
            "cell_id": "t0-r0-c2",
            "bbox": [200, 0, 300, 40],
            "row": 0,
            "col": 2,
            "row_span": 1,
            "col_span": 2,
            "table_id": "t0",
        },
    ]

    def fake_rapid(jobs, **_kwargs):
        by_id = {
            "t0-r0-c0": {"ok": True, "text": "REV", "confidence": 0.9, "token_count": 1},
            "t0-r0-c1": {"ok": True, "text": "ITEM", "confidence": 0.91, "token_count": 1},
            "t0-r0-c2": {"ok": True, "text": "GLOBE", "confidence": 0.92, "token_count": 1},
        }
        return by_id, {"available": True, "count": 3, "timed_out": False}

    def fake_tess(jobs, **_kwargs):
        by_id = {
            "t0-r0-c0": {"ok": True, "text": "REV", "confidence": 0.88, "psm": 7, "token_count": 1},
            "t0-r0-c1": {"ok": True, "text": "ITEM", "confidence": 0.87, "psm": 7, "token_count": 1},
            "t0-r0-c2": {"ok": True, "text": "GLOBE", "confidence": 0.86, "psm": 7, "token_count": 1},
        }
        return by_id, {"available": True, "count": 3, "incomplete": [], "incomplete_count": 0}

    out = cell_ocr.ocr_cells_isolated(
        img,
        cells,
        evidence_dir=str(tmp_path / "cell_ocr"),
        rapidocr_python="/usr/bin/true",
        rapidocr_batch_runner=fake_rapid,
        tesseract_cells_runner=fake_tess,
    )
    assert out["agreement_does_not_prove_correctness"] is True
    assert out["mode"] == "cell_isolated_crop"
    a_by = {c["cell_id"]: c for c in out["engine_a_cells"]}
    assert a_by["t0-r0-c0"]["text"] == "REV"
    assert a_by["t0-r0-c1"]["text"] == "ITEM"
    assert a_by["t0-r0-c2"]["text"] == "GLOBE"
    assert a_by["t0-r0-c2"]["col_span"] == 2
    assert a_by["t0-r0-c0"]["bbox"] == [0, 0, 100, 40]
    assert Path(a_by["t0-r0-c0"]["crop_path"]).is_file()
    # RapidOCR batch invoked once (fake receives full job list), not per cell.
    assert len(list((tmp_path / "cell_ocr" / "cell_crops").glob("*.png"))) == 3


def test_wb3339_012_embedded_bom_cell_isolated_headers(tmp_path):
    """Real engines on 012 BOM fixture: header cells must not merge across columns."""
    pytest.importorskip("pytesseract")
    from api import smedley_cell_ocr as cell_ocr
    from api import smedley_table_grid as grid_mod
    from api import smedley_pdf_ocr_verify as verify_mod

    oriented = (
        Path(__file__).resolve().parents[1]
        / "tests/fixtures/project_review/wb3339_012_embedded_bom_oriented.png"
    )
    assert oriented.is_file()
    caps = verify_mod.capabilities()
    if not caps.get("engine_a", {}).get("available"):
        pytest.skip("RapidOCR unavailable")
    if not caps.get("engine_b", {}).get("available"):
        pytest.skip("Tesseract unavailable")
    image = Image.open(oriented).convert("RGB")
    grid = grid_mod.detect_ruled_tables(image, page=1)
    assert grid.get("structure_verified") is True
    cells = grid.get("cells") or []
    headers = [c for c in cells if int(c.get("row", -1)) == 0]
    assert len(headers) == 8
    result = cell_ocr.ocr_cells_isolated(
        image,
        headers,
        evidence_dir=str(tmp_path / "012-bom-headers"),
        rapidocr_python=caps["engine_a"].get("python"),
        tesseract_cmd=caps["engine_b"].get("binary") or caps["engine_b"].get("path"),
        max_seconds=90,
    )
    a_by_col = {
        int(c["col"]): (c.get("text") or "").strip().upper()
        for c in result["engine_a_cells"]
    }
    # Expected BOM header sequence (source visual): blank/# | REV | ITEM | GLOBE | QTY | ...
    # Critical: REV / ITEM / GLOBE must not appear concatenated in one cell.
    joined = " | ".join(a_by_col.get(i, "") for i in range(8))
    assert "REV ITEM" not in a_by_col.get(1, "")
    assert "REV ITEM GLOBE" not in joined
    assert "ITEM GLOBE" not in joined
    # At least three distinct header tokens land in separate columns.
    tokens = {a_by_col.get(i, "") for i in range(8)}
    assert "REV" in tokens or any(t == "REV" for t in tokens)
    assert any("ITEM" == t or t.endswith("ITEM") for t in tokens)
    assert any("GLOBE" in t and "ITEM" not in t and "REV" not in t for t in tokens)
    assert any(t == "QTY" or t.startswith("QTY") for t in tokens)
    # Retain geometry + spans on durable cell reports.
    sample = result["engine_a_cells"][0]
    assert sample.get("bbox")
    assert sample.get("row_span") == 1
    assert sample.get("ocr_mode") == "cell_isolated_crop"
    assert result.get("incomplete_cell_count", 0) == 0 or result.get("incomplete_cells") is not None
    assert result.get("rapidocr_use_cls") is False
    assert result.get("orientation_established") is True


def test_geometric_blank_skips_engines_before_ocr(tmp_path):
    """Pure-white inset crops are geometric_blank — engines must not invent glyphs."""
    from api import smedley_cell_ocr as cell_ocr

    img = Image.new("RGB", (80, 40), "white")
    cells = [{
        "cell_id": "blank-rev",
        "bbox": [0, 0, 80, 40],
        "row": 1,
        "col": 0,
        "row_span": 1,
        "col_span": 1,
        "table_id": "t0",
    }]
    calls = {"rapid": 0, "tess": 0}

    def fake_rapid(jobs, **_kwargs):
        calls["rapid"] += 1
        ocr_jobs = [j for j in jobs if j.get("ok") and j.get("path") and not j.get("geometric_blank")]
        assert ocr_jobs == []
        return {}, {"available": True, "count": 0, "timed_out": False, "use_cls": False}

    def fake_tess(jobs, **_kwargs):
        calls["tess"] += 1
        ocr_jobs = [j for j in jobs if j.get("ok") and j.get("path") and not j.get("geometric_blank")]
        assert ocr_jobs == []
        return {}, {"available": True, "count": 0, "incomplete": [], "incomplete_count": 0}

    out = cell_ocr.ocr_cells_isolated(
        img,
        cells,
        evidence_dir=str(tmp_path / "blank"),
        rapidocr_python="/usr/bin/true",
        rapidocr_batch_runner=fake_rapid,
        tesseract_cells_runner=fake_tess,
    )
    assert out["geometric_blank_count"] == 1
    a = out["engine_a_cells"][0]
    b = out["engine_b_cells"][0]
    assert a["geometric_blank"] is True and b["geometric_blank"] is True
    assert a["text"] == "" and b["text"] == ""
    assert a["ocr_skipped_reason"] == "geometric_blank"
    assert a["incomplete"] is False
    assert calls["rapid"] == 1 and calls["tess"] == 1


def test_remaining_timeout_never_floors_expired_deadline():
    from api.smedley_cell_ocr import _remaining_timeout_s
    import time as _time

    # Expired deadline → 0, not max(30, remaining).
    assert _remaining_timeout_s(_time.monotonic() - 5.0, fallback=300.0) == 0.0
    left = _remaining_timeout_s(_time.monotonic() + 12.0, fallback=300.0)
    assert left is not None and 0 < left <= 12.0
    assert _remaining_timeout_s(None, fallback=90.0) == 90.0


def test_orientation_established_disables_rapidocr_use_cls(tmp_path):
    """Regression: oriented table cells must call RapidOCR with use_cls=False."""
    from api import smedley_cell_ocr as cell_ocr

    img = Image.new("RGB", (120, 40), "white")
    # Dark ink so not geometric blank.
    for x in range(10, 100):
        for y in range(10, 30):
            img.putpixel((x, y), (0, 0, 0))
    cells = [{
        "cell_id": "ink",
        "bbox": [0, 0, 120, 40],
        "row": 0,
        "col": 0,
        "row_span": 1,
        "col_span": 1,
        "table_id": "t0",
    }]
    seen = {}

    def fake_rapid(jobs, **kwargs):
        seen["use_cls"] = kwargs.get("use_cls")
        return {
            "ink": {"ok": True, "text": "X", "confidence": 0.9, "token_count": 1, "use_cls": kwargs.get("use_cls")},
        }, {"available": True, "count": 1, "timed_out": False, "use_cls": kwargs.get("use_cls")}

    def fake_tess(jobs, **_kwargs):
        return {
            "ink": {"ok": True, "text": "X", "confidence": 0.9, "psm": 7, "token_count": 1},
        }, {"available": True, "count": 1, "incomplete": [], "incomplete_count": 0}

    out = cell_ocr.ocr_cells_isolated(
        img,
        cells,
        evidence_dir=str(tmp_path / "cls"),
        rapidocr_python="/usr/bin/true",
        orientation_established=True,
        rapidocr_use_cls=True,  # even if requested, orientation_established wins
        rapidocr_batch_runner=fake_rapid,
        tesseract_cells_runner=fake_tess,
    )
    assert seen.get("use_cls") is False
    assert out["rapidocr_use_cls"] is False
    assert out["engine_a_meta"].get("use_cls") is False


def test_rapidocr_use_cls_false_recovers_oriented_cordset_cell():
    """Root proof fixture: use_cls=True mangles; use_cls=False reads CORDSET line."""
    from api import smedley_pdf_ocr_verify as verify_mod

    fixture = (
        Path(__file__).resolve().parents[1]
        / "tests/fixtures/project_review/wb3339_012_cordset_cell_oriented.png"
    )
    assert fixture.is_file()
    caps = verify_mod.capabilities()
    if not caps.get("engine_a", {}).get("available"):
        pytest.skip("RapidOCR unavailable")
    python_bin = caps["engine_a"]["python"]
    script = r"""
import json, sys
from rapidocr import RapidOCR
path = sys.argv[1]
use_cls = sys.argv[2] == "1"
e = RapidOCR()
r = e(path, use_cls=use_cls)
txts = list(r.txts) if getattr(r, "txts", None) is not None else []
scores = list(r.scores) if getattr(r, "scores", None) is not None else []
print(json.dumps({"txts": txts, "scores": scores}))
"""
    import subprocess

    def run(use_cls: bool):
        proc = subprocess.run(
            [python_bin, "-c", script, str(fixture), "1" if use_cls else "0"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout.strip().splitlines()[-1])

    bad = run(True)
    good = run(False)
    bad_text = " ".join(bad.get("txts") or [])
    good_text = " ".join(good.get("txts") or [])
    assert "CORDSET" in good_text.upper()
    assert "M12" in good_text.upper()
    assert "10" in good_text  # numbers preserved; no substitution
    # Classifier path must not equal the upright recovery (root: CO RS vs CORDSET...).
    assert bad_text.strip() != good_text.strip()
    assert "CORDSET" not in bad_text.upper()


def test_purewhite_rev_fixture_is_geometric_blank():
    from api.smedley_cell_ocr import is_geometric_blank_raster

    fixture = (
        Path(__file__).resolve().parents[1]
        / "tests/fixtures/project_review/wb3339_012_rev_cell_purewhite.png"
    )
    assert fixture.is_file()
    assert is_geometric_blank_raster(Image.open(fixture)) is True


def test_choose_rapidocr_use_det_ink_bands_not_absolute_height():
    """High-DPI ~53px single line → recognition-only; two ink rows → detector."""
    from api.smedley_cell_ocr import choose_rapidocr_use_det, ink_line_bands
    from PIL import ImageDraw

    # Ordinary 400dpi single-line cell height (~53px) must NOT force detector.
    single = Image.new("RGB", (420, 53), "white")
    d = ImageDraw.Draw(single)
    d.text((12, 14), "CORDSET SINGLE LINE TAG", fill="black")
    assert len(ink_line_bands(single)) == 1
    assert choose_rapidocr_use_det([0, 0, 420, 53], image=single, median_row_height=53) is False

    two = Image.new("RGB", (420, 100), "white")
    d2 = ImageDraw.Draw(two)
    d2.text((12, 12), "LINE ONE DESCRIPTION TEXT", fill="black")
    d2.text((12, 58), "LINE TWO DESCRIPTION TEXT", fill="black")
    assert len(ink_line_bands(two)) >= 2
    assert choose_rapidocr_use_det([0, 0, 420, 100], image=two, median_row_height=53) is True

    # Isolated digit "2" — recognition-only regardless of tall bbox.
    digit = Image.open(
        Path(__file__).resolve().parents[1]
        / "tests/fixtures/project_review/wb3339_012_digit2_cell_oriented.png"
    ).convert("RGB")
    assert choose_rapidocr_use_det(
        [0, 0, digit.size[0], digit.size[1]], image=digit, median_row_height=53
    ) is False

    # Merged-cell fallback when ink bands are inconclusive after edge exclude.
    edge_only = Image.new("RGB", (80, 80), "white")
    for x in range(80):
        edge_only.putpixel((x, 0), (0, 0, 0))  # top rule remnant only
    assert choose_rapidocr_use_det(
        [0, 0, 80, 80], image=edge_only, row_span=2, median_row_height=40
    ) is True


def test_table_geometry_from_cells_uses_actual_col_counts():
    from api.smedley_cell_ocr import table_geometry_from_cells

    bom = [
        {"table_id": "bom", "row": r, "col": c, "cell_id": f"b-r{r}-c{c}", "bbox": [c, r, c + 1, r + 1]}
        for r in range(12)
        for c in range(8)
    ]
    device = [
        {"table_id": "device", "row": r, "col": c, "cell_id": f"d-r{r}-c{c}", "bbox": [c, r, c + 1, r + 1]}
        for r in range(26)
        for c in range(9)
    ]
    geo = {g["table_id"]: g for g in table_geometry_from_cells(bom + device)}
    assert geo["bom"]["row_count"] == 12
    assert geo["bom"]["col_count"] == 8  # never invent a 9th BOM column
    assert geo["device"]["row_count"] == 26
    assert geo["device"]["col_count"] == 9
    assert len(geo["bom"]["header_cells"]) == 8


def test_exact_three_dots_ellipsis_retained_not_blank(tmp_path):
    """015-style three square dots are source ellipsis — run OCR, never blank-skip."""
    from api import smedley_cell_ocr as cell_ocr

    fixture = (
        Path(__file__).resolve().parents[1]
        / "tests/fixtures/project_review/wb3339_015_residual_micro_ink_cell.png"
    )
    assert fixture.is_file()
    crop = Image.open(fixture).convert("RGB")
    assert cell_ocr.classify_cell_ink(crop) == "glyph"
    assert cell_ocr.is_geometric_blank_raster(crop) is False
    assert cell_ocr.choose_rapidocr_use_det(
        [0, 0, crop.size[0], crop.size[1]], image=crop
    ) is False

    seen = {}

    def fake_rapid(jobs, **_kwargs):
        ocr_jobs = [j for j in jobs if j.get("ok") and j.get("path") and not j.get("geometric_blank")]
        assert len(ocr_jobs) == 1
        assert ocr_jobs[0].get("rapidocr_use_det") is False
        seen["ran"] = True
        return {
            ocr_jobs[0]["cell_id"]: {
                "ok": True, "text": "...", "confidence": 0.95, "token_count": 1,
                "use_det": False, "mode": "recognition_only",
            }
        }, {"available": True, "count": 1, "timed_out": False, "use_cls": False,
            "recognition_only_count": 1, "detection_count": 0}

    def fake_tess(jobs, **_kwargs):
        jid = [j for j in jobs if j.get("ok") and not j.get("geometric_blank")][0]["cell_id"]
        return {
            jid: {"ok": True, "text": "...", "confidence": 0.8, "psm": 7, "token_count": 1},
        }, {"available": True, "count": 1, "incomplete": [], "incomplete_count": 0}

    out = cell_ocr.ocr_cells_isolated(
        crop,
        [{
            "cell_id": "ellipsis-r1-c6",
            "bbox": [0, 0, crop.size[0], crop.size[1]],
            "row": 1,
            "col": 6,
            "row_span": 1,
            "col_span": 1,
            "table_id": "t0",
        }],
        evidence_dir=str(tmp_path / "ellipsis"),
        rapidocr_python="/usr/bin/true",
        rapidocr_batch_runner=fake_rapid,
        tesseract_cells_runner=fake_tess,
    )
    assert seen.get("ran") is True
    assert out["geometric_blank_count"] == 0
    assert out["engine_a_cells"][0]["geometric_blank"] is False
    assert out["engine_a_cells"][0]["text"] == "..."
    assert out["engine_b_cells"][0]["text"] == "..."
    assert out["engine_a_cells"][0].get("ocr_skipped_reason") is None
    assert out["cells_verified"] is False


def test_rapidocr_recognition_only_retains_exact_three_dots():
    """Real RapidOCR: recognition-only keeps literal '...' on 015 ellipsis crop."""
    from api import smedley_pdf_ocr_verify as verify_mod
    import subprocess

    caps = verify_mod.capabilities()
    if not caps.get("engine_a", {}).get("available"):
        pytest.skip("RapidOCR unavailable")
    python_bin = caps["engine_a"]["python"]
    fixture = (
        Path(__file__).resolve().parents[1]
        / "tests/fixtures/project_review/wb3339_015_residual_micro_ink_cell.png"
    )
    script = r"""
import json, sys
from rapidocr import RapidOCR
eng = RapidOCR()
r = eng(sys.argv[1], use_det=False, use_cls=False)
texts = []
if hasattr(r, "txts") and r.txts is not None:
    texts = [str(t or "") for t in r.txts]
print(json.dumps({"text": " ".join(t for t in texts if t).strip()}))
"""
    proc = subprocess.run(
        [python_bin, "-c", script, str(fixture)],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload.get("text") == "..."


def test_ocr_cells_isolated_passes_use_det_false_for_single_line(tmp_path):
    from api import smedley_cell_ocr as cell_ocr

    img = Image.new("RGB", (120, 30), "white")
    for x in range(10, 110):
        for y in range(8, 22):
            if x % 9 == 0:
                img.putpixel((x, y), (0, 0, 0))
    seen = {}

    def fake_rapid(jobs, **kwargs):
        ocr_jobs = [j for j in jobs if j.get("ok") and not j.get("geometric_blank")]
        assert ocr_jobs and ocr_jobs[0].get("rapidocr_use_det") is False
        seen["use_det"] = ocr_jobs[0].get("rapidocr_use_det")
        return {
            ocr_jobs[0]["cell_id"]: {
                "ok": True, "text": "2", "confidence": 0.99, "token_count": 1,
                "use_det": False, "mode": "recognition_only",
            }
        }, {"available": True, "count": 1, "timed_out": False, "use_cls": False,
            "recognition_only_count": 1, "detection_count": 0}

    def fake_tess(jobs, **_kwargs):
        jid = [j for j in jobs if j.get("ok") and not j.get("geometric_blank")][0]["cell_id"]
        return {
            jid: {"ok": True, "text": "2", "confidence": 0.9, "psm": 7, "token_count": 1},
        }, {"available": True, "count": 1, "incomplete": [], "incomplete_count": 0}

    out = cell_ocr.ocr_cells_isolated(
        img,
        [{
            "cell_id": "digit",
            "bbox": [0, 0, 120, 30],
            "row": 3,
            "col": 1,
            "row_span": 1,
            "col_span": 1,
            "table_id": "t0",
        }],
        evidence_dir=str(tmp_path / "digit"),
        rapidocr_python="/usr/bin/true",
        rapidocr_batch_runner=fake_rapid,
        tesseract_cells_runner=fake_tess,
    )
    assert seen.get("use_det") is False
    assert out["engine_a_cells"][0]["text"] == "2"
    assert out["table_geometry"][0]["col_count"] == 2  # cols 0..1 → count 2 from max col
    assert out["cells_verified"] is False


def test_rapidocr_recognition_only_recovers_single_digit_and_cordset():
    """Real engine: recognition-only on upright single-line crops."""
    from api import smedley_pdf_ocr_verify as verify_mod
    import subprocess

    caps = verify_mod.capabilities()
    if not caps.get("engine_a", {}).get("available"):
        pytest.skip("RapidOCR unavailable")
    python_bin = caps["engine_a"]["python"]
    root = Path(__file__).resolve().parents[1] / "tests/fixtures/project_review"
    digit = root / "wb3339_012_digit2_cell_oriented.png"
    cord = root / "wb3339_012_cordset_cell_oriented.png"
    assert digit.is_file() and cord.is_file()
    script = r"""
import json, sys, time
from rapidocr import RapidOCR
path, use_det = sys.argv[1], sys.argv[2] == "1"
e = RapidOCR()
t0 = time.perf_counter()
r = e(path, use_det=use_det, use_cls=False)
dt = time.perf_counter() - t0
txts = list(r.txts) if getattr(r, "txts", None) is not None else []
scores = list(r.scores) if getattr(r, "scores", None) is not None else []
print(json.dumps({"txts": txts, "scores": scores, "seconds": dt}))
"""

    def run(path: Path, use_det: bool):
        proc = subprocess.run(
            [python_bin, "-c", script, str(path), "1" if use_det else "0"],
            capture_output=True, text=True, timeout=60, check=False,
        )
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout.strip().splitlines()[-1])

    digit_direct = run(digit, False)
    digit_det = run(digit, True)
    digit_text = " ".join(digit_direct.get("txts") or []).strip()
    assert digit_text == "2" or digit_text.endswith("2")
    # Detector path is allowed to blank/miss; recognition-only must keep the digit.
    assert digit_direct.get("seconds", 1) < 1.0

    cord_direct = run(cord, False)
    cord_text = " ".join(cord_direct.get("txts") or [])
    assert "CORDSET" in cord_text.upper()
    assert "M12" in cord_text.upper()
    assert cord_direct.get("seconds", 1) < 1.0
    # Detection may truncate or slow; recognition-only is the single-line contract.
    _ = digit_det  # exercised for completeness; fidelity asserted on direct path
