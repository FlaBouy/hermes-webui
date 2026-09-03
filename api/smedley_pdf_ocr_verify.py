#!/usr/bin/env python3
"""Project Review PDF extraction evidence with table-cell OCR cross-check.

Native PDF text/layout via pypdfium2. Raster/engineering pages use ruled-grid
(or supplied) table structure; RapidOCR and Tesseract fragments are grouped into
the SAME cells, then compared one-to-one. Raw engine outputs stay separate from
verified cell reports. Agreement never proves correctness.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from typing import Any, Callable

from api.smedley_source_snapshot import materialize_source_snapshot
from api.smedley_pdf_embedded_images import collect_embedded_table_candidates
from api.smedley_cell_ocr import ocr_cells_isolated
from api.smedley_table_grid import (
    assign_fragments_to_cells,
    compare_aligned_cells,
    detect_ruled_tables,
    page_image_coverage,
    page_looks_raster,
    remove_grid_lines,
    select_ocr_orientation,
    _reject_page_footer_contamination,
)

SCHEMA = "smedley.pdf_ocr_verification.v2"
DEFAULT_MAX_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_PAGES = 8
DEFAULT_MAX_PIXELS = 25_000_000
DEFAULT_MAX_SECONDS = 180
DEFAULT_RENDER_SCALE = 2.0
DOCLING_VENV_PYTHON = "/Users/rick/jarvis-rag/docling-venv/bin/python"
HERMES_VENV_PYTHON = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".venv",
    "bin",
    "python",
)

OCR_MODES_NEEDING_VERIFICATION = {
    "full_ocr",
    "ocr",
    "mixed_ocr",
    "mixed_selective_ocr",
    "sidecar",
}


def _iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def file_sha256(path: str, *, max_bytes: int | None = None) -> str:
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if max_bytes is not None and size > max_bytes:
                raise ValueError("PDF exceeds bounded file size limit")
            digest.update(chunk)
    return digest.hexdigest()


def capabilities(
    *,
    rapidocr_python: str | None = None,
    tesseract_cmd: str | None = None,
) -> dict[str, Any]:
    native_ok = False
    native_detail = "pypdfium2 unavailable"
    try:
        import importlib.metadata as metadata
        import pypdfium2  # noqa: F401

        native_ok = True
        native_detail = f"pypdfium2 {metadata.version('pypdfium2')}"
    except Exception as exc:  # pragma: no cover
        native_detail = f"pypdfium2 unavailable: {exc}"

    tess_path = tesseract_cmd or shutil.which("tesseract")
    tess_ok = False
    tess_detail = "tesseract binary not found"
    if tess_path:
        try:
            proc = subprocess.run(
                [tess_path, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            line = (proc.stdout or proc.stderr or "").splitlines()[0] if (proc.stdout or proc.stderr) else ""
            tess_ok = proc.returncode == 0
            tess_detail = line or tess_path
        except Exception as exc:  # pragma: no cover
            tess_detail = f"tesseract probe failed: {exc}"

    rapid_python = rapidocr_python or os.environ.get("SMEDLEY_RAPIDOCR_PYTHON")
    if not rapid_python:
        for candidate in (HERMES_VENV_PYTHON, DOCLING_VENV_PYTHON, sys.executable):
            if candidate and os.path.isfile(candidate):
                rapid_python = candidate
                break
    rapid_ok = False
    rapid_detail = f"RapidOCR python not found: {rapid_python}"
    if rapid_python and os.path.isfile(rapid_python):
        try:
            proc = subprocess.run(
                [
                    rapid_python,
                    "-c",
                    "from rapidocr import RapidOCR; import importlib.metadata as m; import onnxruntime; print(m.version('rapidocr'))",
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if proc.returncode == 0:
                rapid_ok = True
                rapid_detail = f"rapidocr {(proc.stdout or '').strip()} via {rapid_python}"
            else:
                rapid_detail = f"rapidocr import failed: {(proc.stderr or proc.stdout or '')[:240]}"
        except Exception as exc:  # pragma: no cover
            rapid_detail = f"rapidocr probe failed: {exc}"

    independent_available = bool(native_ok and tess_ok and rapid_ok)
    blockers = []
    if not native_ok:
        blockers.append(native_detail)
    if not rapid_ok:
        blockers.append(rapid_detail)
    if not tess_ok:
        blockers.append(tess_detail)
    return {
        "schema": "smedley.pdf_ocr_capabilities.v2",
        "state": "available" if independent_available else "unavailable",
        "native_pdf_available": native_ok,
        "native_pdf_detail": native_detail,
        "engine_a": {"name": "rapidocr", "available": rapid_ok, "detail": rapid_detail, "python": rapid_python},
        "engine_b": {"name": "tesseract", "available": tess_ok, "detail": tess_detail, "binary": tess_path},
        "independent_cross_check_available": independent_available,
        "table_structure": "ruled_grid_local",
        "blockers": blockers,
        "notes": [
            "Cell verification compares page/table/row/col aligned cells, not document-wide token sets.",
            "Two reruns of the same engine are not independent.",
            "Agreement does not prove correctness.",
        ],
    }


def _native_fragments(page: Any, page_index: int) -> list[dict[str, Any]]:
    cells: list[dict[str, Any]] = []
    textpage = page.get_textpage()
    try:
        rect_count = 0
        try:
            rect_count = int(textpage.count_rects())
        except Exception:
            rect_count = 0
        if rect_count > 0:
            for idx in range(min(rect_count, 800)):
                try:
                    rect = textpage.get_rect(idx)
                    chunk = textpage.get_text_bounded(*rect)
                except Exception:
                    continue
                content = (chunk or "").strip()
                if not content:
                    continue
                cells.append({
                    "engine": "native_pdfium",
                    "page": page_index,
                    "text": content,
                    "bbox": [float(rect[0]), float(rect[1]), float(rect[2]), float(rect[3])],
                    "confidence": 1.0,
                    "provenance": "pypdfium2.textpage.rect",
                })
        else:
            page_text = textpage.get_text_bounded() or ""
            for line_idx, line in enumerate(page_text.splitlines()):
                content = line.strip()
                if not content:
                    continue
                cells.append({
                    "engine": "native_pdfium",
                    "page": page_index,
                    "text": content,
                    "bbox": None,
                    "confidence": 1.0,
                    "provenance": "pypdfium2.textpage.bounded",
                })
    finally:
        textpage.close()
    return cells


def _render_page_png(page: Any, path: str, *, scale: float, max_pixels: int) -> tuple[int, int, float]:
    width = float(page.get_width())
    height = float(page.get_height())
    pixels = width * height * (scale ** 2)
    used_scale = scale
    if pixels > max_pixels and width > 0 and height > 0:
        used_scale = max(0.5, (max_pixels / (width * height)) ** 0.5)
    bitmap = page.render(scale=used_scale)
    try:
        pil = bitmap.to_pil()
        pil.save(path, format="PNG")
        return pil.size[0], pil.size[1], used_scale
    finally:
        close = getattr(bitmap, "close", None)
        if callable(close):
            close()


def _rapidocr_fragments(image_path: str, page_index: int, *, python_bin: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    script = r"""
import json, sys
from PIL import Image
from rapidocr import RapidOCR
img_path = sys.argv[1]
side = max(Image.open(img_path).size)
# Default Global.max_side_len=2000 downsamples ~400DPI table rasters (~3–4k px).
# Raise only to the image's own max side, hard-capped for memory budget.
max_side = int(max(2000, min(side, 5000)))
engine = RapidOCR()
engine.max_side_len = max_side
result = engine(img_path)
boxes = []
if hasattr(result, "boxes") and result.boxes is not None:
    for idx, box in enumerate(result.boxes):
        text = str(result.txts[idx]) if result.txts is not None else ""
        score = float(result.scores[idx]) if result.scores is not None else None
        boxes.append({"text": text, "score": score, "box": [[float(x), float(y)] for x, y in box]})
elif isinstance(result, (list, tuple)) and result and result[0]:
    for item in result[0]:
        box, text, score = item[0], item[1], item[2]
        boxes.append({"text": str(text), "score": float(score) if score is not None else None,
                      "box": [[float(x), float(y)] for x, y in box]})
print(json.dumps({"ok": True, "boxes": boxes, "max_side_len": max_side, "image_max_side": side}))
"""
    proc = subprocess.run(
        [python_bin, "-c", script, image_path],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if proc.returncode != 0:
        return [], {"available": False, "error": (proc.stderr or proc.stdout or "rapidocr failed")[:400]}
    try:
        payload = json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception as exc:
        return [], {"available": False, "error": f"rapidocr parse failed: {exc}"}
    frags = []
    for item in payload.get("boxes") or []:
        text = str(item.get("text") or "")
        if text.strip() == "" and text != "":
            # preserve whitespace-only as empty after strip for blank detection at cell level
            pass
        box = item.get("box") or []
        xs = [float(pt[0]) for pt in box] if box else []
        ys = [float(pt[1]) for pt in box] if box else []
        bbox = [min(xs), min(ys), max(xs), max(ys)] if xs and ys else None
        score = item.get("score")
        frags.append({
            "engine": "rapidocr",
            "page": page_index,
            "text": text,
            "bbox": bbox,
            "confidence": float(score) if score is not None else None,
            "provenance": "rapidocr.subprocess",
        })
    return frags, {
        "available": True,
        "count": len(frags),
        "max_side_len": payload.get("max_side_len"),
        "image_max_side": payload.get("image_max_side"),
    }


def _tesseract_fragments(
    image_path: str,
    page_index: int,
    *,
    tesseract_cmd: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    try:
        import pytesseract
        from pytesseract import Output
        from PIL import Image
    except Exception as exc:  # pragma: no cover
        return [], {"available": False, "error": f"pytesseract/Pillow unavailable: {exc}"}
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    try:
        image = Image.open(image_path)
        data = pytesseract.image_to_data(image, output_type=Output.DICT)
    except Exception as exc:
        return [], {"available": False, "error": f"tesseract failed: {exc}"}
    frags = []
    n = len(data.get("text") or [])
    for idx in range(n):
        text = str(data["text"][idx] or "")
        if text == "":
            continue
        try:
            conf = float(data["conf"][idx])
        except Exception:
            conf = -1.0
        if conf < 0:
            continue
        left = int(data["left"][idx])
        top = int(data["top"][idx])
        width = int(data["width"][idx])
        height = int(data["height"][idx])
        frags.append({
            "engine": "tesseract",
            "page": page_index,
            "text": text,
            "bbox": [left, top, left + width, top + height],
            "confidence": conf / 100.0,
            "provenance": "tesseract.image_to_data",
        })
    return frags, {"available": True, "count": len(frags)}


# Back-compat export for older tests that imported cross_check_cells.
def cross_check_cells(primary, secondary, *, low_confidence: float = 0.55):
    return compare_aligned_cells(primary, secondary, low_confidence=low_confidence)


def _json_default(obj: Any):
    try:
        import numpy as np

        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
    except Exception:
        pass
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def verify_pdf(
    path: str,
    *,
    evidence_dir: str | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_pages: int = DEFAULT_MAX_PAGES,
    max_pixels: int = DEFAULT_MAX_PIXELS,
    max_seconds: int = DEFAULT_MAX_SECONDS,
    render_scale: float = DEFAULT_RENDER_SCALE,
    rapidocr_python: str | None = None,
    tesseract_cmd: str | None = None,
    update_ledger: bool = False,
    producer_mode: str | None = None,
    force_raster_ocr: bool | None = None,
    rapidocr_runner: Callable[..., tuple[list[dict[str, Any]], dict[str, Any]]] | None = None,
    tesseract_runner: Callable[..., tuple[list[dict[str, Any]], dict[str, Any]]] | None = None,
    source_sha256: str | None = None,
    source_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if max_pages is None or int(max_pages) < 1:
        raise ValueError("max_pages must be a positive integer")
    max_pages = int(max_pages)
    caps = capabilities(rapidocr_python=rapidocr_python, tesseract_cmd=tesseract_cmd)
    real = os.path.realpath(path)
    warnings: list[str] = []
    if not os.path.isfile(real):
        return {"schema": SCHEMA, "ok": False, "state": "failed", "reason": "PDF file not found", "capabilities": caps, "warnings": warnings}
    if os.path.splitext(real)[1].lower() != ".pdf":
        return {"schema": SCHEMA, "ok": False, "state": "unsupported", "reason": "verify_pdf requires a .pdf source", "capabilities": caps, "warnings": warnings}
    if not caps["native_pdf_available"]:
        return {
            "schema": SCHEMA, "ok": False, "state": "unavailable", "reason": caps["native_pdf_detail"],
            "ocr_verification_state": "unavailable", "capabilities": caps, "warnings": ["native PDF engine unavailable"],
        }

    from PIL import Image
    import pypdfium2 as pdfium

    started = time.time()
    out_dir = evidence_dir
    if not out_dir:
        raise ValueError("evidence_dir required (server-owned isolated evidence root)")
    os.makedirs(out_dir, exist_ok=True)
    try:
        if source_snapshot and source_snapshot.get("snapshot_path"):
            snapshot = dict(source_snapshot)
            snap_path = str(snapshot["snapshot_path"])
            if not os.path.isfile(snap_path):
                raise ValueError("supplied source_snapshot path missing")
            # Re-hash snapshot bytes; never reopen the live library path for parse.
            from api.smedley_source_snapshot import file_sha256 as _snap_hash
            got = _snap_hash(snap_path, max_bytes=max_bytes)
            if source_sha256 and str(source_sha256).lower() != got.lower():
                raise ValueError("supplied snapshot hash mismatch vs expected_sha256")
            if snapshot.get("source_sha256") and str(snapshot["source_sha256"]).lower() != got.lower():
                raise ValueError("supplied snapshot metadata hash mismatch vs snapshot bytes")
            snapshot["source_sha256"] = got
            snapshot["parse_path"] = snap_path
            snapshot["snapshot_path"] = snap_path
        else:
            snapshot = materialize_source_snapshot(
                real,
                evidence_dir=out_dir,
                max_bytes=max_bytes,
                expected_sha256=source_sha256,
            )
    except ValueError as exc:
        return {
            "schema": SCHEMA, "ok": False, "state": "failed", "reason": str(exc),
            "source": real, "source_sha256": source_sha256, "capabilities": caps, "warnings": warnings,
        }
    except Exception as exc:
        return {
            "schema": SCHEMA, "ok": False, "state": "failed",
            "reason": f"snapshot materialization failed: {exc}",
            "source": real, "capabilities": caps, "warnings": warnings,
        }
    source_sha = snapshot["source_sha256"]
    parse_path = snapshot["snapshot_path"]

    doc = pdfium.PdfDocument(parse_path)
    page_count = len(doc)
    pages_to_scan = min(page_count, max_pages)
    partial_coverage = page_count > max_pages
    if partial_coverage:
        warnings.append(f"partial_coverage: scanned {pages_to_scan}/{page_count} pages")
    render_dir = os.path.join(out_dir, "page_renders")
    os.makedirs(render_dir, exist_ok=True)
    raw_dir = os.path.join(out_dir, "raw_engine")
    os.makedirs(raw_dir, exist_ok=True)

    rapid_python = rapidocr_python or caps["engine_a"].get("python")
    tess_bin = tesseract_cmd or caps["engine_b"].get("binary")
    a_runner = rapidocr_runner or _rapidocr_fragments
    b_runner = tesseract_runner or _tesseract_fragments

    raw_native: list[dict[str, Any]] = []
    raw_a: list[dict[str, Any]] = []
    raw_b: list[dict[str, Any]] = []
    cell_reports_a: list[dict[str, Any]] = []
    cell_reports_b: list[dict[str, Any]] = []
    page_reports: list[dict[str, Any]] = []
    ambiguous: list[dict[str, Any]] = []
    visual_paths: list[str] = []
    engine_a_meta: dict[str, Any] = {"available": False}
    engine_b_meta: dict[str, Any] = {"available": False}
    raster_pages: list[int] = []
    native_only_pages: list[int] = []
    structure_failed_pages: list[int] = []
    timed_out = False

    producer_forces = str(producer_mode or "").lower() in OCR_MODES_NEEDING_VERIFICATION
    force = True if force_raster_ocr is None and producer_forces else bool(force_raster_ocr)

    with tempfile.TemporaryDirectory(prefix="smedley-ocr-") as tmp:
        for page_index in range(pages_to_scan):
            if time.time() - started > max_seconds:
                timed_out = True
                warnings.append(f"time bound reached after {page_index} page(s); marking partial coverage")
                partial_coverage = True
                break
            page = doc[page_index]
            page_no = page_index + 1
            page_native = _native_fragments(page, page_no)
            raw_native.extend(page_native)
            tmp_png = os.path.join(tmp, f"page-{page_no:03d}.png")
            width, height, used_scale = _render_page_png(page, tmp_png, scale=render_scale, max_pixels=max_pixels)
            render_path = os.path.join(render_dir, f"page-{page_no:03d}.png")
            shutil.copy2(tmp_png, render_path)
            visual_paths.append(render_path)
            image = Image.open(render_path)
            coverage = page_image_coverage(image)
            rasterish = page_looks_raster(image, native_fragment_count=len(page_native))
            sparse_native = len(page_native) <= 5
            need_ocr = bool(
                force
                or producer_forces
                or rasterish
                or (sparse_native and coverage.get("significant"))
            )
            ocr_reason = (
                "forced" if force or producer_forces else
                "raster_detected" if rasterish else
                "sparse_native_with_image_coverage" if (sparse_native and coverage.get("significant")) else
                "native_text_only"
            )
            orientation = {
                "rotate_cw_deg": 0,
                "reason": "not_applicable_native_only",
                "method": "none",
                "original_unmodified": True,
            }
            ocr_image = image
            ocr_png = tmp_png
            ocr_render_path = None
            rotate_cw = 0
            if need_ocr:
                try:
                    orientation = select_ocr_orientation(image, tesseract_cmd=tess_bin)
                except Exception as exc:
                    orientation = {
                        "rotate_cw_deg": 0,
                        "reason": f"orientation_sweep_failed:{exc}",
                        "method": "ocr_orientation_sweep",
                        "original_unmodified": True,
                    }
                    warnings.append(f"page {page_no}: OCR orientation sweep failed; using 0 deg")
                rotate_cw = int(orientation.get("rotate_cw_deg") or 0)
                if rotate_cw:
                    ocr_image = image.rotate(-rotate_cw, expand=True)  # PIL rotate is CCW
                    ocr_png = os.path.join(tmp, f"page-{page_no:03d}-rot{rotate_cw}cw.png")
                    ocr_image.save(ocr_png, format="PNG")
                    warnings.append(
                        f"page {page_no}: OCR render rotated {rotate_cw} deg CW "
                        f"(= {-rotate_cw % 360} CCW) via OCR confidence sweep; original PDF unmodified"
                    )
                ocr_dir = os.path.join(out_dir, "ocr_page_renders")
                os.makedirs(ocr_dir, exist_ok=True)
                ocr_render_path = os.path.join(
                    ocr_dir, f"page-{page_no:03d}-ocr-rot{rotate_cw}cw.png"
                )
                ocr_image.save(ocr_render_path, format="PNG")
            page_report: dict[str, Any] = {
                "page": page_no,
                "native_fragment_count": len(page_native),
                "render": render_path,
                "render_size": [width, height],
                "render_scale": used_scale,
                "source_render_coordinate_space": "source_page_render",
                "ocr_render": ocr_render_path,
                "ocr_render_coordinate_space": "ocr_oriented_render" if need_ocr else None,
                "raster_detected": rasterish,
                "image_coverage": coverage,
                "ocr_trigger": ocr_reason,
                "raster_ocr_attempted": False,
                "table_structure": None,
                "orientation": orientation,
                "ocr_rotation_cw_deg": rotate_cw,
                "ocr_rotation_ccw_deg": (-rotate_cw) % 360 if rotate_cw else 0,
            }
            if not need_ocr:
                native_only_pages.append(page_no)
                page_reports.append(page_report)
                continue

            raster_pages.append(page_no)
            page_report["raster_ocr_attempted"] = True

            # Preferred path: separate embedded CCITT/table rasters at native DPI.
            embedded = collect_embedded_table_candidates(
                page,
                page_no=page_no,
                evidence_dir=out_dir,
                source_sha256=source_sha,
                tesseract_cmd=tess_bin,
            )
            page_report["embedded_table_rasters"] = {
                "ok": embedded.get("ok"),
                "reason": embedded.get("reason"),
                "image_object_count": embedded.get("image_object_count"),
                "candidate_count": embedded.get("candidate_count"),
                "structure_verified_count": embedded.get("structure_verified_count"),
                "failed_candidate_count": embedded.get("failed_candidate_count"),
                "significant_skip_count": embedded.get("significant_skip_count"),
                "unprocessed_non_table_candidate_count": embedded.get(
                    "unprocessed_non_table_candidate_count"
                ),
                "ornament_skip_count": embedded.get("ornament_skip_count"),
                "coverage_complete": embedded.get("coverage_complete"),
                "coverage_scope": embedded.get("coverage_scope") or "detected_table_candidates",
                "omissions": embedded.get("omissions") or [],
                "unprocessed_non_table_candidates": embedded.get("unprocessed_non_table_candidates")
                or [],
                "prefer_embedded_over_page_render": embedded.get("prefer_embedded_over_page_render"),
                "candidates": [
                    {
                        "image_index": c.get("image_index"),
                        "px_size": c.get("px_size"),
                        "source_bbox_pdf": c.get("source_bbox_pdf"),
                        "placement_matrix": c.get("placement_matrix"),
                        "image_sha256": c.get("image_sha256"),
                        "source_png": c.get("source_png"),
                        "oriented_png": c.get("oriented_png"),
                        "rotate_cw_deg": c.get("rotate_cw_deg"),
                        "pad_px": c.get("pad_px"),
                        "table_structure": c.get("table_structure"),
                    }
                    for c in (embedded.get("candidates") or [])
                ],
                "skipped": embedded.get("skipped") or [],
            }

            if embedded.get("prefer_embedded_over_page_render"):
                coverage_complete = bool(embedded.get("coverage_complete"))
                omissions = list(embedded.get("omissions") or [])
                warnings.append(
                    f"page {page_no}: using {embedded.get('structure_verified_count')} embedded "
                    "table raster(s) for geometry (preferred over whole-page render)"
                )
                if omissions:
                    warnings.append(
                        f"page {page_no}: embedded coverage incomplete — "
                        f"{len(omissions)} significant omission(s); "
                        "structure_verified=false despite preserved good-raster evidence"
                    )
                page_tables = []
                emb_warns: list[str] = []
                for cand in embedded.get("candidates") or []:
                    ts = cand.get("table_structure") or {}
                    if not ts.get("structure_verified"):
                        emb_warns.append(
                            f"omitted img{cand.get('image_index')}: {ts.get('reason') or 'structure_failed'}"
                        )
                        continue
                    page_tables.extend(ts.get("tables") or [])
                    oriented_png = str(cand["oriented_png"])
                    oriented_image = Image.open(oriented_png).convert("RGB")
                    cells = list(cand.get("grid_cells") or [])
                    cell_evid = os.path.join(
                        out_dir,
                        "cell_ocr",
                        f"page-{page_no:03d}-img{int(cand['image_index']):03d}",
                    )
                    remaining = None
                    if max_seconds:
                        # Never floor an expired budget — 0 means skip/partial, not +30s.
                        remaining = max(0.0, float(max_seconds) - (time.time() - started))
                    isolated = ocr_cells_isolated(
                        oriented_image,
                        cells,
                        evidence_dir=cell_evid,
                        rapidocr_python=rapid_python,
                        tesseract_cmd=tess_bin,
                        max_seconds=remaining,
                        # Oriented embedded raster already fixed upright.
                        orientation_established=True,
                        rapidocr_use_cls=False,
                    )
                    engine_a_meta = {
                        **(isolated.get("engine_a_meta") or {}),
                        "mode": "cell_isolated_batch",
                        "embedded_image_index": cand.get("image_index"),
                    }
                    engine_b_meta = {
                        **(isolated.get("engine_b_meta") or {}),
                        "mode": "cell_isolated_psm",
                        "embedded_image_index": cand.get("image_index"),
                    }
                    a_cells = list(isolated.get("engine_a_cells") or [])
                    b_cells = list(isolated.get("engine_b_cells") or [])
                    for cell in a_cells:
                        cell["embedded_image_index"] = cand.get("image_index")
                        cell["coordinate_space"] = "embedded_oriented_raster_cell"
                    for cell in b_cells:
                        cell["embedded_image_index"] = cand.get("image_index")
                        cell["coordinate_space"] = "embedded_oriented_raster_cell"
                    cell_reports_a.extend(a_cells)
                    cell_reports_b.extend(b_cells)
                    # Retain raw per-engine cell text as fragment-shaped evidence rows.
                    for cell in a_cells:
                        raw_a.append({
                            "engine": "rapidocr",
                            "page": page_no,
                            "text": cell.get("text"),
                            "bbox": cell.get("bbox"),
                            "confidence": cell.get("confidence_mean"),
                            "provenance": "rapidocr.cell_isolated",
                            "cell_id": cell.get("cell_id"),
                            "embedded_image_index": cand.get("image_index"),
                        })
                    for cell in b_cells:
                        raw_b.append({
                            "engine": "tesseract",
                            "page": page_no,
                            "text": cell.get("text"),
                            "bbox": cell.get("bbox"),
                            "confidence": cell.get("confidence_mean"),
                            "provenance": "tesseract.cell_isolated",
                            "cell_id": cell.get("cell_id"),
                            "embedded_image_index": cand.get("image_index"),
                            "tesseract_psm": cell.get("tesseract_psm"),
                        })
                    for miss in isolated.get("incomplete_cells") or []:
                        ambiguous.append({
                            "engine": miss.get("engine") or "cell_isolated",
                            "fragment_text": None,
                            "bbox": miss.get("bbox"),
                            "reason": f"incomplete_cell:{miss.get('reason')}",
                            "cell_id": miss.get("cell_id"),
                            "embedded_image_index": cand.get("image_index"),
                        })
                    # Persist durable per-raster cell OCR package.
                    isolated_path = os.path.join(cell_evid, "cell_ocr_result.json")
                    os.makedirs(cell_evid, exist_ok=True)
                    with open(isolated_path, "w", encoding="utf-8") as handle:
                        json.dump(
                            {
                                "schema": "smedley.cell_isolated_ocr.v1",
                                "page": page_no,
                                "embedded_image_index": cand.get("image_index"),
                                "oriented_png": oriented_png,
                                "source_bbox_pdf": cand.get("source_bbox_pdf"),
                                "result": {
                                    k: isolated.get(k)
                                    for k in (
                                        "mode",
                                        "cell_count",
                                        "crop_dir",
                                        "inset_px",
                                        "pad_px",
                                        "median_row_height",
                                        "table_geometry",
                                        "engine_a_meta",
                                        "engine_b_meta",
                                        "incomplete_cell_count",
                                        "incomplete_cells",
                                        "elapsed_ms",
                                        "agreement_does_not_prove_correctness",
                                        "cells_verified",
                                    )
                                },
                                "engine_a_cells": a_cells,
                                "engine_b_cells": b_cells,
                            },
                            handle,
                            indent=2,
                            default=_json_default,
                        )
                        handle.write("\n")
                    emb_warns.append(
                        f"img{cand.get('image_index')}: cell_isolated incomplete="
                        f"{isolated.get('incomplete_cell_count') or 0}"
                    )
                if not coverage_complete:
                    structure_failed_pages.append(page_no)
                page_report["table_structure"] = {
                    "ok": bool(page_tables) and coverage_complete,
                    "reason": (
                        "embedded_table_rasters"
                        if coverage_complete
                        else "embedded_table_rasters_partial_coverage"
                    ),
                    "structure_verified": coverage_complete,
                    "structure_source": "embedded_raster",
                    "coverage_complete": coverage_complete,
                    "omissions": omissions,
                    "table_count": len(page_tables),
                    "cell_count": sum(
                        int((c.get("table_structure") or {}).get("cell_count") or 0)
                        for c in (embedded.get("candidates") or [])
                        if (c.get("table_structure") or {}).get("structure_verified")
                    ),
                    "warnings": emb_warns,
                    "structure_engine": "embedded_raster+opencv_morphology_gutter_split",
                    "tables": page_tables,
                }
                page_report["engine_a"] = engine_a_meta
                page_report["engine_b"] = engine_b_meta
                page_report["aligned_cell_count"] = page_report["table_structure"]["cell_count"]
                page_report["verification_mode"] = (
                    "embedded_cell_isolated_cross_check"
                    if coverage_complete
                    else "embedded_cell_isolated_cross_check_partial"
                )
                page_reports.append(page_report)
                continue

            # Fallback: whole-page render geometry (PDFs without separable table images).
            grid = detect_ruled_tables(ocr_image, page=page_no)
            # Refuse footer/title-block contamination on whole-page detects.
            kept_tables, footer_warns, footer_uncertain = _reject_page_footer_contamination(
                list(grid.get("tables") or []),
                tuple(ocr_image.size),
            )
            if footer_warns:
                warnings.extend(footer_warns)
                grid = {
                    **grid,
                    "warnings": list(grid.get("warnings") or []) + footer_warns,
                }
            if footer_uncertain:
                grid = {
                    **grid,
                    "ok": False,
                    "structure_verified": False,
                    "reason": "structure_unverified_footer_contamination",
                    "tables": kept_tables,
                    "cells": [],
                }
            # Near-native-empty engineering sheets (P&ID/schematic): do not fabricate
            # sparse title/equipment boxes into a data-table verification grid.
            if grid.get("ok") and len(page_native) <= 5:
                cell_n = len(grid.get("cells") or [])
                dense = [
                    t for t in (grid.get("tables") or [])
                    if int(t.get("col_count") or 0) >= 6 and int(t.get("row_count") or 0) >= 8
                ]
                if cell_n < 80 or not dense:
                    grid = {
                        **grid,
                        "ok": False,
                        "reason": "not_table_engineering_drawing",
                        "cells": [],
                        "warnings": list(grid.get("warnings") or [])
                        + [
                            "native-sparse sheet without dense BOM/device table; localized OCR only"
                        ],
                    }
            page_report["table_structure"] = {
                "ok": grid.get("ok"),
                "reason": grid.get("reason"),
                "structure_verified": bool(grid.get("structure_verified")),
                "structure_source": "whole_page_render_fallback",
                "table_count": len(grid.get("tables") or []),
                "cell_count": len(grid.get("cells") or []),
                "warnings": grid.get("warnings") or [],
                "structure_engine": grid.get("structure_engine"),
                "tables": [
                    {
                        "table_id": t.get("table_id"),
                        "bbox": t.get("bbox"),
                        "row_count": t.get("row_count"),
                        "col_count": t.get("col_count"),
                    }
                    for t in (grid.get("tables") or [])
                ],
            }
            # Deglitch OCR image by removing ruled lines on a copy.
            cleaned = remove_grid_lines(ocr_image)
            cleaned_png = os.path.join(tmp, f"page-{page_no:03d}-ocr.png")
            cleaned.save(cleaned_png, format="PNG")
            if not grid.get("ok"):
                structure_failed_pages.append(page_no)
                warnings.append(
                    f"page {page_no}: not recognized as table structure ({grid.get('reason')}); "
                    "retaining localized OCR evidence without fabricated grid"
                )
                if grid.get("reason") in {"structure_unverified", "structure_unverified_footer_contamination"}:
                    warnings.append(
                        "structure unverified — text agreements must not be treated as verified cells"
                    )
                a_frags, a_meta = a_runner(cleaned_png, page_no, python_bin=rapid_python)
                b_frags, b_meta = b_runner(cleaned_png, page_no, tesseract_cmd=tess_bin)
                engine_a_meta, engine_b_meta = a_meta, b_meta
                raw_a.extend(a_frags)
                raw_b.extend(b_frags)
                page_report["engine_a"] = a_meta
                page_report["engine_b"] = b_meta
                page_report["verification_mode"] = (
                    "structure_unverified_localized_ocr"
                    if "structure_unverified" in str(grid.get("reason") or "")
                    else "localized_ocr_not_table"
                )
                page_report["localized_ocr_sample"] = {
                    "rapidocr": [f.get("text") for f in a_frags[:40]],
                    "tesseract": [f.get("text") for f in b_frags[:40]],
                }
                page_reports.append(page_report)
                continue

            if grid.get("structure_verified") is False:
                structure_failed_pages.append(page_no)
                warnings.append(
                    f"page {page_no}: table geometry uncertain; refusing verified cell agreements"
                )
                a_frags, a_meta = a_runner(cleaned_png, page_no, python_bin=rapid_python)
                b_frags, b_meta = b_runner(cleaned_png, page_no, tesseract_cmd=tess_bin)
                engine_a_meta, engine_b_meta = a_meta, b_meta
                raw_a.extend(a_frags)
                raw_b.extend(b_frags)
                page_report["engine_a"] = a_meta
                page_report["engine_b"] = b_meta
                page_report["verification_mode"] = "structure_unverified_localized_ocr"
                page_report["localized_ocr_sample"] = {
                    "rapidocr": [f.get("text") for f in a_frags[:40]],
                    "tesseract": [f.get("text") for f in b_frags[:40]],
                }
                page_reports.append(page_report)
                continue

            # Prefer cell-isolated OCR when geometry is known (avoid cross-boundary joins).
            # Do not whole-image grid-wipe before crops — inset on each cell instead.
            cells = grid.get("cells") or []
            cell_evid = os.path.join(out_dir, "cell_ocr", f"page-{page_no:03d}-wholepage")
            remaining = None
            if max_seconds:
                remaining = max(0.0, float(max_seconds) - (time.time() - started))
            isolated = ocr_cells_isolated(
                ocr_image,
                cells,
                evidence_dir=cell_evid,
                rapidocr_python=rapid_python,
                tesseract_cmd=tess_bin,
                max_seconds=remaining,
                # Whole-page OCR path uses already-oriented page render when selected.
                orientation_established=True,
                rapidocr_use_cls=False,
            )
            engine_a_meta = {**(isolated.get("engine_a_meta") or {}), "mode": "cell_isolated_batch"}
            engine_b_meta = {**(isolated.get("engine_b_meta") or {}), "mode": "cell_isolated_psm"}
            for cell in isolated.get("engine_a_cells") or []:
                raw_a.append({
                    "engine": "rapidocr",
                    "page": page_no,
                    "text": cell.get("text"),
                    "bbox": cell.get("bbox"),
                    "confidence": cell.get("confidence_mean"),
                    "provenance": "rapidocr.cell_isolated",
                    "cell_id": cell.get("cell_id"),
                })
            for cell in isolated.get("engine_b_cells") or []:
                raw_b.append({
                    "engine": "tesseract",
                    "page": page_no,
                    "text": cell.get("text"),
                    "bbox": cell.get("bbox"),
                    "confidence": cell.get("confidence_mean"),
                    "provenance": "tesseract.cell_isolated",
                    "cell_id": cell.get("cell_id"),
                    "tesseract_psm": cell.get("tesseract_psm"),
                })
            cell_reports_a.extend(isolated.get("engine_a_cells") or [])
            cell_reports_b.extend(isolated.get("engine_b_cells") or [])
            for miss in isolated.get("incomplete_cells") or []:
                ambiguous.append({
                    "engine": miss.get("engine") or "cell_isolated",
                    "fragment_text": None,
                    "bbox": miss.get("bbox"),
                    "reason": f"incomplete_cell:{miss.get('reason')}",
                    "cell_id": miss.get("cell_id"),
                })
            page_report["engine_a"] = engine_a_meta
            page_report["engine_b"] = engine_b_meta
            page_report["aligned_cell_count"] = len(cells)
            page_report["verification_mode"] = "wholepage_cell_isolated_cross_check"
            isolated_path = os.path.join(cell_evid, "cell_ocr_result.json")
            os.makedirs(cell_evid, exist_ok=True)
            with open(isolated_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "schema": "smedley.cell_isolated_ocr.v1",
                        "page": page_no,
                        "structure_source": "whole_page_render_fallback",
                        "result": {
                            k: isolated.get(k)
                            for k in (
                                "mode",
                                "cell_count",
                                "crop_dir",
                                "inset_px",
                                "pad_px",
                                "median_row_height",
                                "table_geometry",
                                "engine_a_meta",
                                "engine_b_meta",
                                "incomplete_cell_count",
                                "incomplete_cells",
                                "elapsed_ms",
                                "agreement_does_not_prove_correctness",
                                "cells_verified",
                            )
                        },
                        "engine_a_cells": isolated.get("engine_a_cells") or [],
                        "engine_b_cells": isolated.get("engine_b_cells") or [],
                    },
                    handle,
                    indent=2,
                    default=_json_default,
                )
                handle.write("\n")
            page_reports.append(page_report)

    doc.close()

    raw_native_path = os.path.join(raw_dir, "native_fragments.json")
    raw_a_path = os.path.join(raw_dir, "rapidocr_fragments.json")
    raw_b_path = os.path.join(raw_dir, "tesseract_fragments.json")
    for path_out, payload in (
        (raw_native_path, raw_native),
        (raw_a_path, raw_a),
        (raw_b_path, raw_b),
    ):
        with open(path_out, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, default=_json_default)
            handle.write("\n")

    if not raster_pages:
        # Native-text-only PDF: do not require two OCR engines.
        state = "native_text"
        verification_state = "not_applicable"
        quality_state = "needs_review"
        extraction_mode = "native_text"
        reason = "Pages classified as native-text; dual OCR engines were not required."
        cross = {
            "schema": "smedley.table_cell_cross_check.v1",
            "matched_count": 0,
            "disagree_count": 0,
            "missing_in_primary_count": 0,
            "missing_in_secondary_count": 0,
            "blank_both_count": 0,
            "low_confidence_count": 0,
            "matched_sample": [],
            "disagree_sample": [],
            "comparison_unit": "not_applicable_native_text",
            "agreement_does_not_prove_correctness": True,
        }
    else:
        extraction_mode = "mixed_selective_ocr" if native_only_pages else "full_ocr"
        if producer_mode:
            warnings.append(f"producer_mode_hint={producer_mode}")
        independent_ok = bool(engine_a_meta.get("available") and engine_b_meta.get("available"))
        full_lists: dict[str, Any] = {}
        if structure_failed_pages and not cell_reports_a:
            state = "needs_review"
            verification_state = "structure_unverified" if any(
                (p.get("verification_mode") or "").startswith("structure_unverified")
                for p in page_reports
            ) else "needs_review"
            quality_state = "needs_review"
            reason = (
                "Raster OCR ran but table geometry is unverified or unrecognized; "
                "cell text agreements are not verified cells."
            )
            cross = compare_aligned_cells([], [])
            cross["cells_verified"] = False
            cross["note"] = "No verified cell agreements when structure is unverified."
        elif not independent_ok:
            state = "unavailable" if caps["state"] == "unavailable" else "needs_review"
            verification_state = "unavailable" if not (cell_reports_a or cell_reports_b) else "needs_review"
            quality_state = "needs_review"
            reason = (
                "Independent second OCR/extraction engine could not run locally "
                "or one engine failed; retaining durable per-cell outputs from engines that ran."
            )
            if engine_a_meta.get("error"):
                warnings.append(f"engine_a: {engine_a_meta['error']}")
            if engine_b_meta.get("error"):
                warnings.append(f"engine_b: {engine_b_meta['error']}")
            warnings.append("Do not fabricate cross-check scores when an engine is unavailable.")
            # Still compare whatever cell reports exist (may be empty / one-sided).
            cross = compare_aligned_cells(
                cell_reports_a, cell_reports_b, include_full_lists=True
            )
            full_lists = cross.pop("full", None) or {}
            cross["cells_verified"] = False
            cross["engine_pair_incomplete"] = True
        else:
            cross = compare_aligned_cells(
                cell_reports_a, cell_reports_b, include_full_lists=True
            )
            full_lists = cross.pop("full", None) or {}
            cross["ambiguous_assignment_count"] = len(ambiguous)
            cross["cells_verified"] = False
            page_structure_complete = not any(
                (p.get("table_structure") or {}).get("coverage_complete") is False
                or (
                    (p.get("verification_mode") or "").endswith("_partial")
                )
                for p in page_reports
            )
            cross["structure_verified"] = bool(
                page_structure_complete
                and not structure_failed_pages
                and any(
                    (p.get("table_structure") or {}).get("structure_verified")
                    for p in page_reports
                )
            )
            if structure_failed_pages and not cell_reports_a:
                # Already handled above, but keep explicit for mixed pages.
                pass
            problems = (
                cross.get("disagree_count")
                or cross.get("missing_in_primary_count")
                or cross.get("missing_in_secondary_count")
                or cross.get("low_confidence_count")
                or cross.get("both_missed_visible_ink_count")
                or ambiguous
                or structure_failed_pages
                or partial_coverage
                or timed_out
                or (not page_structure_complete)
                or (cross.get("matched_nonblank_count", 0) == 0 and cell_reports_a)
            )
            warnings.append(
                "blank_blank_matches=%d are reported separately and are not strong OCR evidence"
                % int(cross.get("matched_blank_count") or 0)
            )
            if problems:
                state = "needs_review"
                verification_state = "needs_review"
                quality_state = "needs_review"
                reason = (
                    "Aligned table-cell OCR comparison found disagreements, missed visible ink, "
                    "ambiguous boundary assignments, structure failures, weak nonblank agreement, "
                    "partial embedded coverage, or partial page coverage; owner verification required."
                )
            else:
                state = "cross_checked"
                verification_state = "cross_checked"
                quality_state = "needs_review"
                reason = (
                    "Independent engines agreed on aligned nonblank table cells for the scanned pages "
                    "under structure_verified geometry, but agreement does not prove correctness; "
                    "Project Review remains needs-review."
                )
                warnings.append("cross_checked is evidence state, not approval sign-off")
                cross["cells_verified"] = False  # never elevate agreement to verified cells
                cross["structure_verified"] = True

        # Durable full aligned reports survive either-engine failure (not only independent_ok).
        if cell_reports_a or cell_reports_b or ambiguous:
            aligned_dir = os.path.join(out_dir, "aligned_cell_reports")
            os.makedirs(aligned_dir, exist_ok=True)
            engine_a_path = os.path.join(aligned_dir, "engine_a_cells.json")
            engine_b_path = os.path.join(aligned_dir, "engine_b_cells.json")
            cross_full_path = os.path.join(aligned_dir, "cross_check_full.json")
            ambiguous_path = os.path.join(aligned_dir, "ambiguous_assignments.json")
            for path_out, payload_out in (
                (engine_a_path, cell_reports_a),
                (engine_b_path, cell_reports_b),
                (
                    cross_full_path,
                    {
                        "schema": "smedley.table_cell_cross_check.full.v1",
                        "counts": {
                            "matched_nonblank_count": cross.get("matched_nonblank_count"),
                            "matched_blank_count": cross.get("matched_blank_count"),
                            "disagree_count": cross.get("disagree_count"),
                            "missing_in_primary_count": cross.get("missing_in_primary_count"),
                            "missing_in_secondary_count": cross.get("missing_in_secondary_count"),
                            "both_missed_visible_ink_count": cross.get("both_missed_visible_ink_count"),
                            "low_confidence_count": cross.get("low_confidence_count"),
                            "ambiguous_assignment_count": len(ambiguous),
                        },
                        "lists": full_lists,
                        "agreement_does_not_prove_correctness": True,
                        "cells_verified": False,
                        "structure_verified": cross.get("structure_verified"),
                        "engine_pair_incomplete": bool(cross.get("engine_pair_incomplete")),
                    },
                ),
                (ambiguous_path, ambiguous),
            ):
                with open(path_out, "w", encoding="utf-8") as handle:
                    json.dump(payload_out, handle, indent=2, default=_json_default)
                    handle.write("\n")
            cross["full_reports"] = {
                "engine_a_cells_path": engine_a_path,
                "engine_b_cells_path": engine_b_path,
                "cross_check_full_path": cross_full_path,
                "ambiguous_assignments_path": ambiguous_path,
                "engine_a_cell_count": len(cell_reports_a),
                "engine_b_cell_count": len(cell_reports_b),
                "ambiguous_assignment_count": len(ambiguous),
            }

    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "ok": True,
        "state": state,
        "reason": reason,
        "source": real,
        "basename": os.path.basename(real),
        "source_sha256": source_sha,
        "page_count": page_count,
        "pages_scanned": pages_to_scan if not timed_out else len(page_reports),
        "partial_coverage": partial_coverage or timed_out,
        "extraction_mode": extraction_mode if raster_pages else "native_text",
        "quality_state": quality_state,
        "ocr_verification_state": verification_state,
        "raster_pages": raster_pages,
        "native_only_pages": native_only_pages,
        "structure_failed_pages": structure_failed_pages,
        "raw_engine_outputs": {
            "native_fragments_path": raw_native_path,
            "rapidocr_fragments_path": raw_a_path,
            "tesseract_fragments_path": raw_b_path,
            "native_fragment_count": len(raw_native),
            "rapidocr_fragment_count": len(raw_a),
            "tesseract_fragment_count": len(raw_b),
        },
        "verified_cell_reports": {
            "engine_a_cells": cell_reports_a[:40],
            "engine_b_cells": cell_reports_b[:40],
            "engine_a_cell_count": len(cell_reports_a),
            "engine_b_cell_count": len(cell_reports_b),
            "preview_limit": 40,
            "engine_a_cells_path": (cross.get("full_reports") or {}).get("engine_a_cells_path"),
            "engine_b_cells_path": (cross.get("full_reports") or {}).get("engine_b_cells_path"),
            "cross_check_full_path": (cross.get("full_reports") or {}).get("cross_check_full_path"),
            "ambiguous_assignments_path": (cross.get("full_reports") or {}).get(
                "ambiguous_assignments_path"
            ),
            "note": "Manifest carries bounded previews only; complete aligned cells live under aligned_cell_reports/",
        },
        "ambiguous_assignments": ambiguous[:40],
        "ambiguous_assignment_count": len(ambiguous),
        "cross_check": cross,
        "pages": page_reports,
        "visual_renders": visual_paths,
        "warnings": warnings,
        "capabilities": caps,
        "original_preserved": True,
        "source_snapshot": snapshot,
        "parse_path": parse_path,
        "extracted_at": _iso(),
        "elapsed_ms": int((time.time() - started) * 1000),
        "bounds": {
            "max_pages": max_pages,
            "max_pixels": max_pixels,
            "max_seconds": max_seconds,
        },
    }

    manifest_path = os.path.join(out_dir, f"{os.path.splitext(os.path.basename(real))[0]}.ocr-verify.json")
    tmp_manifest = manifest_path + f".tmp.{os.getpid()}"
    with open(tmp_manifest, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, default=_json_default)
        handle.write("\n")
    os.replace(tmp_manifest, manifest_path)
    payload["manifest_path"] = manifest_path

    if update_ledger:
        from api.jarvis_rag_ingest_events import attach_review_extraction_evidence

        attach_review_extraction_evidence(
            real,
            source_sha256=source_sha,
            evidence={
                "kind": "pdf_ocr_verify",
                "manifest_path": manifest_path,
                "ocr_verification_state": verification_state,
                "quality_state": quality_state,
                "extraction_mode": payload["extraction_mode"],
                "warnings": warnings,
                "partial_coverage": payload["partial_coverage"],
                "page_count": page_count,
                "pages_scanned": payload["pages_scanned"],
            },
        )
    return payload
