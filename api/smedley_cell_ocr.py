#!/usr/bin/env python3
"""Cell-isolated OCR under known ruled-table geometry.

Whole-table OCR often merges adjacent headers/columns. This module crops each
detected (possibly merged) cell with a modest border inset + white pad, then
runs RapidOCR (one loaded engine per batch subprocess) and Tesseract (PSM
chosen from cell geometry) independently. No document-name hardcoding and no
post-OCR string substitutions.

Orientation-established table cells disable RapidOCR's angle classifier
(`use_cls=False`) so upright crops are not re-rotated. Single-line cells use
recognition-only (`use_det=False`) based on horizontal ink-line bands (not
absolute cell height / DPI); genuine multiline ink keeps the detector.
Only pure zero-ink rasters are geometric_blank — ellipsis / dashes / small
punctuation are content and must reach both engines.
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import subprocess
import tempfile
import time
from typing import Any, Callable

from PIL import Image

DEFAULT_INSET_PX = 2
DEFAULT_PAD_PX = 6
DEFAULT_TESS_WORKERS = 4
DEFAULT_CELL_TIMEOUT_S = 3.0
DEFAULT_RAPID_BATCH_TIMEOUT_S = 300.0
DEFAULT_MAX_SIDE_CAP = 5000
# Dark-pixel threshold / count for geometric blank on inset crop (pre-pad).
GEOMETRIC_BLANK_THRESHOLD = 200
GEOMETRIC_BLANK_MAX_DARK = 0
# Ink-line band detection (after excluding edge rule remnants).
INK_BAND_EDGE_EXCLUDE_PX = 2
INK_BAND_MAX_GAP_MERGE = 2
INK_BAND_MIN_HEIGHT = 2
INK_BAND_MIN_DARK = 8
INK_BAND_WEAK_VS_PEAK = 0.08


def crop_cell_for_ocr(
    image: Image.Image,
    bbox: list[float] | list[int],
    *,
    inset_px: int = DEFAULT_INSET_PX,
    pad_px: int = DEFAULT_PAD_PX,
    fill: str | tuple[int, int, int] = "white",
) -> Image.Image:
    """Crop cell interior (inset off rules) and pad — no whole-image grid wipe."""
    interior = crop_cell_interior(image, bbox, inset_px=inset_px)
    if pad_px > 0:
        from PIL import ImageOps

        return ImageOps.expand(interior.convert("RGB"), border=int(pad_px), fill=fill)
    return interior.convert("RGB")


def crop_cell_interior(
    image: Image.Image,
    bbox: list[float] | list[int],
    *,
    inset_px: int = DEFAULT_INSET_PX,
) -> Image.Image:
    """Inset crop only (no pad) — used for zero-ink geometric blank checks."""
    x0, y0, x1, y1 = [int(v) for v in bbox]
    w, h = image.size
    ix0 = min(max(0, x0 + max(0, inset_px)), w - 1)
    iy0 = min(max(0, y0 + max(0, inset_px)), h - 1)
    ix1 = max(ix0 + 1, min(w, x1 - max(0, inset_px)))
    iy1 = max(iy0 + 1, min(h, y1 - max(0, inset_px)))
    if ix1 - ix0 < 2 or iy1 - iy0 < 2:
        ix0, iy0 = max(0, x0), max(0, y0)
        ix1, iy1 = max(ix0 + 1, min(w, x1)), max(iy0 + 1, min(h, y1))
    return image.crop((ix0, iy0, ix1, iy1))


def is_geometric_blank_raster(
    image: Image.Image,
    *,
    threshold: int = GEOMETRIC_BLANK_THRESHOLD,
    max_dark: int = GEOMETRIC_BLANK_MAX_DARK,
) -> bool:
    """True when the raster has no dark ink pixels (pure white / empty cell)."""
    import numpy as np

    arr = np.asarray(image.convert("L"), dtype=np.uint8)
    if arr.size == 0:
        return True
    return int((arr < int(threshold)).sum()) <= int(max_dark)


def choose_tesseract_psm(
    bbox: list[float] | list[int],
    *,
    median_row_height: float | None = None,
) -> int:
    """Pick Tesseract page segmentation from cell geometry only.

    - Short single-line-ish cells → PSM 7 (single text line)
    - Taller / multi-line description cells → PSM 6 (uniform block of text)
    """
    x0, y0, x1, y1 = [float(v) for v in bbox]
    height = max(1.0, y1 - y0)
    width = max(1.0, x1 - x0)
    med = float(median_row_height) if median_row_height and median_row_height > 0 else None
    if med is not None and height >= max(28.0, med * 1.55):
        return 6
    if height >= 48 and width / height >= 2.5:
        return 6
    if height >= 64:
        return 6
    return 7


def cell_is_multiline_geometry(
    bbox: list[float] | list[int],
    *,
    median_row_height: float | None = None,
) -> bool:
    """True when cell bbox height heuristics indicate a multi-line block.

    Used for Tesseract PSM and as a no-image fallback only. RapidOCR use_det
    must prefer ink-line bands (see choose_rapidocr_use_det).
    """
    return choose_tesseract_psm(bbox, median_row_height=median_row_height) == 6


def ink_line_bands(
    image: Image.Image,
    *,
    threshold: int = GEOMETRIC_BLANK_THRESHOLD,
    edge_exclude_px: int = INK_BAND_EDGE_EXCLUDE_PX,
    max_gap_merge: int = INK_BAND_MAX_GAP_MERGE,
    min_band_height: int = INK_BAND_MIN_HEIGHT,
    min_band_dark: int = INK_BAND_MIN_DARK,
    weak_vs_peak: float = INK_BAND_WEAK_VS_PEAK,
) -> list[tuple[int, int, int, int]]:
    """Substantial horizontal ink bands after excluding edge-rule remnants.

    Returns list of (y0, y1, dark_count, height). Weak secondary crumbs relative
    to the peak band are dropped so single-line cells with edge debris stay
    single-band.
    """
    import numpy as np

    arr = np.asarray(image.convert("L"), dtype=np.uint8)
    if arr.size == 0:
        return []
    h, w = arr.shape
    y0 = min(max(0, int(edge_exclude_px)), max(0, h // 5))
    y1 = max(y0 + 1, h - max(0, int(edge_exclude_px)))
    mask = arr[y0:y1] < int(threshold)
    proj = mask.sum(axis=1).astype(np.int32)
    raw: list[list[int]] = []
    in_band = False
    start = 0
    for i, count in enumerate(proj):
        if count >= 1 and not in_band:
            in_band = True
            start = i
        elif count < 1 and in_band:
            in_band = False
            raw.append([start, i - 1, int(proj[start:i].sum())])
    if in_band:
        raw.append([start, len(proj) - 1, int(proj[start:].sum())])
    if not raw:
        return []
    merged: list[list[int]] = [raw[0]]
    for band in raw[1:]:
        if band[0] - merged[-1][1] - 1 <= int(max_gap_merge):
            merged[-1][1] = band[1]
            merged[-1][2] += band[2]
        else:
            merged.append(band)
    bands: list[tuple[int, int, int, int]] = []
    min_dark = max(int(min_band_dark), int(w * 0.015))
    for s, e, dark in merged:
        bh = e - s + 1
        if bh < int(min_band_height) or dark < min_dark:
            continue
        bands.append((s + y0, e + y0, int(dark), int(bh)))
    if not bands:
        return []
    peak = max(b[2] for b in bands)
    floor = max(int(min_band_dark), int(peak * float(weak_vs_peak)))
    return [b for b in bands if b[2] >= floor]


def choose_rapidocr_use_det(
    bbox: list[float] | list[int] | None = None,
    *,
    image: Image.Image | None = None,
    row_span: int = 1,
    col_span: int = 1,
    median_row_height: float | None = None,
) -> bool:
    """Detection only for genuine multiline ink; single-line → recognition-only.

    Decision is driven by horizontal ink projection / connected line bands on
    the inset crop (edge rules excluded), not absolute cell height or DPI.
    Ordinary ~53px 400dpi single-line rows stay recognition-only. Tall genuine
    multiline and merged-cell fallback (inconclusive ink + span>1) keep the
    detector. Root: CORDSET 53px recognition-only is fast and exact; det is slow.
    """
    rs = max(1, int(row_span or 1))
    cs = max(1, int(col_span or 1))
    if image is not None:
        bands = ink_line_bands(image)
        if len(bands) >= 2:
            return True
        if len(bands) == 1:
            return False
        # Inconclusive (0 bands after edge exclude) on merged cells → detector.
        if rs > 1 or cs > 1:
            return True
        if bbox is not None:
            return cell_is_multiline_geometry(bbox, median_row_height=median_row_height)
        return False
    if rs > 1 or cs > 1:
        return True
    if bbox is not None:
        return cell_is_multiline_geometry(bbox, median_row_height=median_row_height)
    return False


def classify_cell_ink(
    image: Image.Image,
    *,
    threshold: int = GEOMETRIC_BLANK_THRESHOLD,
) -> str:
    """Classify inset-crop ink: blank | glyph.

    Any non-zero dark ink — including ellipsis, dashes, and small punctuation —
    is glyph-class content. Only pure zero-ink rasters are blank. Never treat
    sparse punctuation as geometric_blank.
    """
    import numpy as np

    arr = np.asarray(image.convert("L"), dtype=np.uint8)
    if arr.size == 0:
        return "blank"
    dark = int((arr < int(threshold)).sum())
    if dark <= GEOMETRIC_BLANK_MAX_DARK:
        return "blank"
    return "glyph"


def table_geometry_from_cells(cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per-table geometric row/col counts + header labels from detected cells.

    Uses actual max(row)/max(col); never invents a 9-column BOM on an 8-col grid.
    """
    by_table: dict[str, list[dict[str, Any]]] = {}
    for cell in cells:
        tid = str(cell.get("table_id") or "unknown")
        by_table.setdefault(tid, []).append(cell)
    out: list[dict[str, Any]] = []
    for tid, rows in sorted(by_table.items()):
        max_r = max((int(c.get("row", 0)) for c in rows), default=-1)
        max_c = max((int(c.get("col", 0)) for c in rows), default=-1)
        headers = []
        for c in sorted(
            [x for x in rows if int(x.get("row", -1)) == 0],
            key=lambda x: int(x.get("col", 0)),
        ):
            headers.append({
                "row": 0,
                "col": int(c.get("col", 0)),
                "row_span": int(c.get("row_span") or 1),
                "col_span": int(c.get("col_span") or 1),
                "cell_id": c.get("cell_id"),
                "bbox": c.get("bbox"),
            })
        out.append({
            "table_id": tid,
            "row_count": max_r + 1 if max_r >= 0 else 0,
            "col_count": max_c + 1 if max_c >= 0 else 0,
            "header_cells": headers,
            "cell_count": len(rows),
        })
    return out


def _median_row_height(cells: list[dict[str, Any]]) -> float | None:
    heights = []
    for cell in cells:
        bbox = cell.get("bbox") or [0, 0, 0, 0]
        if len(bbox) < 4:
            continue
        if int(cell.get("row_span") or 1) != 1:
            continue
        h = float(bbox[3]) - float(bbox[1])
        if h > 0:
            heights.append(h)
    if not heights:
        return None
    heights.sort()
    return float(heights[len(heights) // 2])


def _remaining_timeout_s(
    deadline_monotonic: float | None,
    *,
    fallback: float,
) -> float | None:
    """Seconds left until deadline. None = no deadline. 0 = already expired.

    Never floors an expired deadline up (no max(30, remaining) extension).
    """
    if deadline_monotonic is None:
        return float(fallback) if fallback and fallback > 0 else None
    left = float(deadline_monotonic) - time.monotonic()
    if left <= 0:
        return 0.0
    if fallback and fallback > 0:
        return min(float(fallback), left)
    return left


def _write_cell_crops(
    image: Image.Image,
    cells: list[dict[str, Any]],
    crop_dir: str,
    *,
    inset_px: int,
    pad_px: int,
    median_row_height: float | None = None,
) -> list[dict[str, Any]]:
    os.makedirs(crop_dir, exist_ok=True)
    jobs: list[dict[str, Any]] = []
    for idx, cell in enumerate(cells):
        cell_id = str(cell.get("cell_id") or f"cell-{idx}")
        bbox = cell.get("bbox")
        if not bbox or len(bbox) < 4:
            jobs.append({
                "cell_id": cell_id,
                "ok": False,
                "reason": "missing_bbox",
                "cell": cell,
            })
            continue
        interior = crop_cell_interior(image, bbox, inset_px=inset_px)
        ink_class = classify_cell_ink(interior)
        # Only pure zero-ink may skip engines. Ellipsis/dashes/punctuation run OCR.
        geometric_blank = ink_class == "blank"
        row_span = int(cell.get("row_span") or 1)
        col_span = int(cell.get("col_span") or 1)
        use_det = choose_rapidocr_use_det(
            bbox,
            image=interior,
            row_span=row_span,
            col_span=col_span,
            median_row_height=median_row_height,
        )
        crop = crop_cell_for_ocr(image, bbox, inset_px=inset_px, pad_px=pad_px)
        path = os.path.join(crop_dir, f"{idx:05d}_{cell_id.replace('/', '_')}.png")
        crop.save(path, format="PNG")
        jobs.append({
            "cell_id": cell_id,
            "ok": True,
            "path": path,
            "bbox": [int(v) for v in bbox],
            "row": cell.get("row"),
            "col": cell.get("col"),
            "row_span": row_span,
            "col_span": col_span,
            "table_id": cell.get("table_id"),
            "page": cell.get("page"),
            "crop_size": list(crop.size),
            "geometric_blank": bool(geometric_blank),
            "ink_class": ink_class,
            "ink_line_band_count": len(ink_line_bands(interior)) if not geometric_blank else 0,
            "rapidocr_use_det": bool(use_det),
            "multiline_geometry": bool(use_det),
            "cell": cell,
        })
    return jobs


def _load_partial_rapid_results(partial_path: str) -> dict[str, dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    if not partial_path or not os.path.isfile(partial_path):
        return by_id
    try:
        with open(partial_path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                cid = str(row.get("cell_id") or "")
                if cid:
                    by_id[cid] = row
    except Exception:
        pass
    return by_id


def _rapidocr_cells_batch(
    jobs: list[dict[str, Any]],
    *,
    python_bin: str,
    timeout_s: float | None = DEFAULT_RAPID_BATCH_TIMEOUT_S,
    use_cls: bool = False,
    partial_path: str | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """One RapidOCR load; OCR every successful non-blank crop path.

    For orientation-established table cells, use_cls must be False (default).
    Writes incremental JSONL to partial_path so a timeout still keeps completed cells.
    """
    batch = [
        {
            "cell_id": j["cell_id"],
            "path": j["path"],
            "use_det": bool(j.get("rapidocr_use_det")),
        }
        for j in jobs
        if j.get("ok") and j.get("path") and not j.get("geometric_blank")
    ]
    if not batch:
        return {}, {
            "available": True,
            "error": None,
            "count": 0,
            "skipped_geometric_blank": sum(1 for j in jobs if j.get("geometric_blank")),
            "use_cls": bool(use_cls),
            "recognition_only_count": 0,
            "detection_count": 0,
            "timed_out": False,
            "partial": False,
        }
    if timeout_s is not None and float(timeout_s) <= 0:
        return {}, {
            "available": False,
            "error": "rapidocr_budget_exhausted",
            "timed_out": True,
            "count": 0,
            "use_cls": bool(use_cls),
            "partial": False,
        }

    if partial_path:
        os.makedirs(os.path.dirname(partial_path) or ".", exist_ok=True)
        # Truncate any stale partial from a prior attempt.
        open(partial_path, "w", encoding="utf-8").close()

    manifest = {
        "batch": batch,
        "max_side_cap": DEFAULT_MAX_SIDE_CAP,
        "use_cls": bool(use_cls),
        "partial_path": partial_path,
    }
    with tempfile.TemporaryDirectory(prefix="smedley-rapid-batch-") as tmp:
        manifest_path = os.path.join(tmp, "batch.json")
        with open(manifest_path, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle)
        script = r"""
import json, sys
from PIL import Image
from rapidocr import RapidOCR

manifest = json.load(open(sys.argv[1], encoding="utf-8"))
batch = manifest.get("batch") or []
cap = int(manifest.get("max_side_cap") or 5000)
use_cls = bool(manifest.get("use_cls"))
partial_path = manifest.get("partial_path")
engine = RapidOCR()
max_side = 2000
for item in batch:
    try:
        side = max(Image.open(item["path"]).size)
        max_side = max(max_side, min(side, cap))
    except Exception:
        pass
engine.max_side_len = int(max_side)
out = {
    "ok": True,
    "max_side_len": int(max_side),
    "use_cls": use_cls,
    "recognition_only_count": 0,
    "detection_count": 0,
    "results": [],
}
partial_fh = open(partial_path, "a", encoding="utf-8") if partial_path else None
try:
    for item in batch:
        cell_id = item.get("cell_id")
        path = item.get("path")
        use_det = bool(item.get("use_det"))
        entry = {
            "cell_id": cell_id,
            "ok": False,
            "text": "",
            "confidence": None,
            "error": None,
            "use_cls": use_cls,
            "use_det": use_det,
            "mode": "detection" if use_det else "recognition_only",
        }
        try:
            # Orientation fixed upstream. Single-line: recognition-only.
            # Multiline description blocks keep the detector.
            result = engine(path, use_det=use_det, use_cls=use_cls)
            if use_det:
                out["detection_count"] += 1
            else:
                out["recognition_only_count"] += 1
            texts = []
            scores = []
            if hasattr(result, "txts") and result.txts is not None:
                for idx, tok in enumerate(result.txts):
                    texts.append(str(tok or ""))
                    if result.scores is not None and idx < len(result.scores):
                        try:
                            scores.append(float(result.scores[idx]))
                        except Exception:
                            pass
            elif isinstance(result, (list, tuple)) and result and result[0]:
                for row in result[0]:
                    texts.append(str(row[1] if len(row) > 1 else ""))
                    if len(row) > 2 and row[2] is not None:
                        try:
                            scores.append(float(row[2]))
                        except Exception:
                            pass
            text = " ".join(t for t in texts if t is not None).strip()
            while "  " in text:
                text = text.replace("  ", " ")
            entry["ok"] = True
            entry["text"] = text
            entry["confidence"] = (sum(scores) / len(scores)) if scores else None
            entry["token_count"] = len([t for t in texts if str(t).strip()])
        except Exception as exc:
            entry["error"] = str(exc)[:240]
        out["results"].append(entry)
        if partial_fh is not None:
            partial_fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
            partial_fh.flush()
finally:
    if partial_fh is not None:
        partial_fh.close()
print(json.dumps(out))
"""
        timed_out = False
        proc = None
        try:
            # No floor on expired/short budgets — caller owns remaining seconds.
            run_timeout = None if timeout_s is None else max(0.05, float(timeout_s))
            proc = subprocess.run(
                [python_bin, "-c", script, manifest_path],
                capture_output=True,
                text=True,
                timeout=run_timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            # Prefer incremental JSONL; stdout may be incomplete.
            by_id = _load_partial_rapid_results(partial_path or "")
            if not by_id and exc.stdout:
                try:
                    # Best-effort: last complete JSON object line if any.
                    for line in str(exc.stdout).splitlines()[::-1]:
                        line = line.strip()
                        if line.startswith("{") and '"results"' in line:
                            payload = json.loads(line)
                            for row in payload.get("results") or []:
                                cid = str(row.get("cell_id") or "")
                                if cid:
                                    by_id[cid] = row
                            break
                except Exception:
                    pass
            return by_id, {
                "available": bool(by_id),
                "error": "rapidocr_batch_timeout",
                "timed_out": True,
                "partial": True,
                "count": len(by_id),
                "use_cls": bool(use_cls),
                "partial_path": partial_path,
            }

        if proc is None or proc.returncode != 0:
            by_id = _load_partial_rapid_results(partial_path or "")
            err = (proc.stderr or proc.stdout or "rapidocr batch failed")[:400] if proc else "rapidocr batch failed"
            return by_id, {
                "available": bool(by_id),
                "error": err,
                "count": len(by_id),
                "timed_out": timed_out,
                "partial": bool(by_id),
                "use_cls": bool(use_cls),
                "partial_path": partial_path,
            }
        try:
            payload = json.loads(proc.stdout.strip().splitlines()[-1])
        except Exception as exc:
            by_id = _load_partial_rapid_results(partial_path or "")
            return by_id, {
                "available": bool(by_id),
                "error": f"rapidocr batch parse failed: {exc}",
                "count": len(by_id),
                "partial": bool(by_id),
                "use_cls": bool(use_cls),
                "timed_out": False,
            }
    by_id = {}
    for row in payload.get("results") or []:
        cid = str(row.get("cell_id") or "")
        if cid:
            by_id[cid] = row
    return by_id, {
        "available": True,
        "count": len(by_id),
        "max_side_len": payload.get("max_side_len"),
        "timed_out": False,
        "partial": False,
        "use_cls": bool(use_cls),
        "recognition_only_count": int(payload.get("recognition_only_count") or 0),
        "detection_count": int(payload.get("detection_count") or 0),
        "partial_path": partial_path,
    }


def _tesseract_one_cell(
    path: str,
    *,
    psm: int,
    tesseract_cmd: str | None,
    timeout_s: float = DEFAULT_CELL_TIMEOUT_S,
) -> dict[str, Any]:
    """Run Tesseract on one crop with a real per-call timeout (pytesseract timeout)."""
    import pytesseract

    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    image = Image.open(path)
    config = f"--psm {int(psm)}"
    timeout = max(0.05, float(timeout_s))
    try:
        text = pytesseract.image_to_string(image, config=config, timeout=timeout) or ""
    except RuntimeError as exc:
        # pytesseract raises RuntimeError on timeout
        return {
            "ok": False,
            "text": "",
            "confidence": None,
            "psm": int(psm),
            "error": f"tesseract_timeout:{exc}"[:240],
            "timed_out": True,
        }
    cleaned = " ".join(str(text).split())
    confs: list[float] = []
    try:
        from pytesseract import Output

        data = pytesseract.image_to_data(
            image, output_type=Output.DICT, config=config, timeout=timeout
        )
        for conf, tok in zip(data.get("conf") or [], data.get("text") or []):
            token = str(tok or "").strip()
            try:
                conf_f = float(conf)
            except Exception:
                conf_f = -1.0
            if token and conf_f >= 0:
                confs.append(conf_f / 100.0)
    except Exception:
        pass
    return {
        "ok": True,
        "text": cleaned,
        "confidence": (sum(confs) / len(confs)) if confs else None,
        "psm": int(psm),
        "token_count": len([t for t in cleaned.split(" ") if t]),
        "timed_out": False,
    }


def _tesseract_cells(
    jobs: list[dict[str, Any]],
    *,
    median_row_height: float | None,
    tesseract_cmd: str | None,
    max_workers: int = DEFAULT_TESS_WORKERS,
    cell_timeout_s: float = DEFAULT_CELL_TIMEOUT_S,
    deadline_monotonic: float | None = None,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Per-cell Tesseract with real subprocess timeout + shared deadline cancel.

    Does not rely on future.result(timeout) after as_completed (that is not a
    wall-clock per-job timeout). Queued jobs are cancelled when the page deadline
    expires; completed results are preserved.
    """
    pending = [
        j for j in jobs
        if j.get("ok") and j.get("path") and not j.get("geometric_blank")
    ]
    results: dict[str, dict[str, Any]] = {}
    incomplete: list[dict[str, Any]] = []
    workers = max(1, int(max_workers))

    if deadline_monotonic is not None and time.monotonic() > deadline_monotonic:
        for job in pending:
            incomplete.append({
                "cell_id": job["cell_id"],
                "reason": "batch_deadline_before_start",
                "bbox": job.get("bbox"),
                "engine": "tesseract",
            })
        return results, {
            "available": False,
            "count": 0,
            "incomplete_count": len(incomplete),
            "incomplete": incomplete[:200],
            "workers": workers,
            "cell_timeout_s": float(cell_timeout_s),
            "deadline_exhausted": True,
        }

    def _run(job: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        psm = choose_tesseract_psm(job["bbox"], median_row_height=median_row_height)
        # Cap each cell by remaining page budget when present.
        per_cell = float(cell_timeout_s)
        if deadline_monotonic is not None:
            left = deadline_monotonic - time.monotonic()
            if left <= 0:
                return job["cell_id"], {
                    "ok": False,
                    "cell_id": job["cell_id"],
                    "text": "",
                    "confidence": None,
                    "error": "batch_deadline",
                    "psm": psm,
                    "timed_out": True,
                }
            per_cell = min(per_cell, left)
        try:
            out = _tesseract_one_cell(
                job["path"],
                psm=psm,
                tesseract_cmd=tesseract_cmd,
                timeout_s=per_cell,
            )
            out["cell_id"] = job["cell_id"]
            return job["cell_id"], out
        except Exception as exc:
            return job["cell_id"], {
                "ok": False,
                "cell_id": job["cell_id"],
                "text": "",
                "confidence": None,
                "error": str(exc)[:240],
                "psm": psm,
            }

    # Submit lazily so deadline can cancel the queue before work starts.
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        future_map: dict[concurrent.futures.Future, dict[str, Any]] = {}
        submit_idx = 0

        def _submit_next() -> bool:
            nonlocal submit_idx
            if submit_idx >= len(pending):
                return False
            if deadline_monotonic is not None and time.monotonic() > deadline_monotonic:
                return False
            job = pending[submit_idx]
            submit_idx += 1
            future_map[pool.submit(_run, job)] = job
            return True

        # Prime the pool.
        for _ in range(min(workers, len(pending))):
            if not _submit_next():
                break

        while future_map:
            if deadline_monotonic is not None and time.monotonic() > deadline_monotonic:
                # Cancel queued (not-started) futures; leave running ones to finish
                # or be abandoned after we stop waiting — preserve completed.
                for fut, job in list(future_map.items()):
                    if fut.cancel():
                        incomplete.append({
                            "cell_id": job["cell_id"],
                            "reason": "batch_deadline_cancelled",
                            "bbox": job.get("bbox"),
                            "engine": "tesseract",
                        })
                        future_map.pop(fut, None)
                # Mark not-yet-submitted as incomplete.
                while submit_idx < len(pending):
                    job = pending[submit_idx]
                    submit_idx += 1
                    incomplete.append({
                        "cell_id": job["cell_id"],
                        "reason": "batch_deadline_not_started",
                        "bbox": job.get("bbox"),
                        "engine": "tesseract",
                    })
                # Drain any already-finished futures without waiting forever.
                for fut, job in list(future_map.items()):
                    if fut.done():
                        try:
                            cell_id, payload = fut.result(timeout=0)
                            results[cell_id] = payload
                            if not payload.get("ok"):
                                incomplete.append({
                                    "cell_id": cell_id,
                                    "reason": payload.get("error") or "tesseract_failed",
                                    "bbox": job.get("bbox"),
                                    "engine": "tesseract",
                                })
                        except Exception as exc:
                            incomplete.append({
                                "cell_id": job["cell_id"],
                                "reason": f"tesseract_exc:{exc}"[:200],
                                "bbox": job.get("bbox"),
                                "engine": "tesseract",
                            })
                        future_map.pop(fut, None)
                # Remaining in-flight: mark incomplete and stop waiting.
                for fut, job in list(future_map.items()):
                    if job["cell_id"] not in results:
                        incomplete.append({
                            "cell_id": job["cell_id"],
                            "reason": "batch_deadline_inflight",
                            "bbox": job.get("bbox"),
                            "engine": "tesseract",
                        })
                future_map.clear()
                break

            done, _ = concurrent.futures.wait(
                set(future_map.keys()),
                timeout=0.25,
                return_when=concurrent.futures.FIRST_COMPLETED,
            )
            if not done:
                continue
            for fut in done:
                job = future_map.pop(fut)
                try:
                    cell_id, payload = fut.result(timeout=0)
                    results[cell_id] = payload
                    if not payload.get("ok"):
                        incomplete.append({
                            "cell_id": cell_id,
                            "reason": payload.get("error") or "tesseract_failed",
                            "bbox": job.get("bbox"),
                            "engine": "tesseract",
                        })
                except Exception as exc:
                    incomplete.append({
                        "cell_id": job["cell_id"],
                        "reason": f"tesseract_exc:{exc}"[:200],
                        "bbox": job.get("bbox"),
                        "engine": "tesseract",
                    })
                _submit_next()

        # Any jobs never submitted (deadline before queue drained).
        while submit_idx < len(pending):
            job = pending[submit_idx]
            submit_idx += 1
            if job["cell_id"] not in results and not any(
                x.get("cell_id") == job["cell_id"] for x in incomplete
            ):
                incomplete.append({
                    "cell_id": job["cell_id"],
                    "reason": "batch_deadline_not_started",
                    "bbox": job.get("bbox"),
                    "engine": "tesseract",
                })

    return results, {
        "available": True,
        "count": len(results),
        "incomplete_count": len(incomplete),
        "incomplete": incomplete[:200],
        "workers": workers,
        "cell_timeout_s": float(cell_timeout_s),
    }


def _geometric_blank_engine_report(base: dict[str, Any], engine: str) -> dict[str, Any]:
    ink_class = base.get("ink_class") or "blank"
    return {
        **base,
        "engine": engine,
        "text": "",
        "blank": True,
        "geometric_blank": True,
        "ink_class": ink_class,
        "visible_ink": False,
        "both_missed_visible_ink_candidate": False,
        "fragment_count": 0,
        "fragments": [],
        "confidence_min": None,
        "confidence_mean": None,
        "incomplete": False,
        "incomplete_reason": None,
        "ocr_skipped_reason": "geometric_blank",
        "raw_engine": {"ok": True, "skipped": "geometric_blank"},
    }


def ocr_cells_isolated(
    image: Image.Image,
    cells: list[dict[str, Any]],
    *,
    evidence_dir: str,
    rapidocr_python: str | None,
    tesseract_cmd: str | None = None,
    inset_px: int = DEFAULT_INSET_PX,
    pad_px: int = DEFAULT_PAD_PX,
    tess_workers: int = DEFAULT_TESS_WORKERS,
    cell_timeout_s: float = DEFAULT_CELL_TIMEOUT_S,
    rapid_batch_timeout_s: float = DEFAULT_RAPID_BATCH_TIMEOUT_S,
    max_seconds: float | None = None,
    # Orientation-established table cells: disable RapidOCR angle classifier.
    rapidocr_use_cls: bool = False,
    orientation_established: bool = True,
    rapidocr_batch_runner: Callable[..., tuple[dict[str, dict[str, Any]], dict[str, Any]]] | None = None,
    tesseract_cells_runner: Callable[..., tuple[dict[str, dict[str, Any]], dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Run both engines on per-cell crops; return aligned cell reports + meta."""
    started = time.monotonic()
    deadline = (started + float(max_seconds)) if max_seconds is not None else None
    crop_dir = os.path.join(evidence_dir, "cell_crops")
    med_h = _median_row_height(cells)
    jobs = _write_cell_crops(
        image, cells, crop_dir, inset_px=inset_px, pad_px=pad_px, median_row_height=med_h
    )
    table_geometry = table_geometry_from_cells(cells)

    # use_cls only when orientation is NOT already established.
    use_cls = bool(rapidocr_use_cls) if not orientation_established else False

    rapid_by_id: dict[str, dict[str, Any]] = {}
    rapid_meta: dict[str, Any] = {"available": False}
    if rapidocr_python:
        runner = rapidocr_batch_runner or _rapidocr_cells_batch
        rapid_timeout = _remaining_timeout_s(deadline, fallback=rapid_batch_timeout_s)
        partial_path = os.path.join(evidence_dir, "rapidocr_partial.jsonl")
        rapid_by_id, rapid_meta = runner(
            jobs,
            python_bin=rapidocr_python,
            timeout_s=rapid_timeout,
            use_cls=use_cls,
            partial_path=partial_path,
        )
        rapid_meta = {
            **rapid_meta,
            "orientation_established": bool(orientation_established),
            "use_cls": use_cls,
        }
    else:
        rapid_meta = {
            "available": False,
            "error": "rapidocr_python_missing",
            "use_cls": use_cls,
            "orientation_established": bool(orientation_established),
        }

    tess_runner = tesseract_cells_runner or _tesseract_cells
    tess_by_id, tess_meta = tess_runner(
        jobs,
        median_row_height=med_h,
        tesseract_cmd=tesseract_cmd,
        max_workers=tess_workers,
        cell_timeout_s=cell_timeout_s,
        deadline_monotonic=deadline,
    )

    reports_a: list[dict[str, Any]] = []
    reports_b: list[dict[str, Any]] = []
    incomplete_cells: list[dict[str, Any]] = list(tess_meta.get("incomplete") or [])
    if rapid_meta.get("timed_out"):
        # Mark cells missing from partial RapidOCR as incomplete (preserve completed).
        done_ids = set(rapid_by_id.keys())
        for job in jobs:
            if not job.get("ok") or job.get("geometric_blank"):
                continue
            if job["cell_id"] not in done_ids:
                incomplete_cells.append({
                    "cell_id": job["cell_id"],
                    "reason": "rapidocr_batch_timeout",
                    "engine": "rapidocr",
                    "bbox": job.get("bbox"),
                })

    geometric_blank_count = 0
    for job in jobs:
        cell = dict(job.get("cell") or {})
        cell_id = job["cell_id"]
        bbox = job.get("bbox") or cell.get("bbox")
        base = {
            **cell,
            "cell_id": cell_id,
            "bbox": bbox,
            "row_span": cell.get("row_span", 1),
            "col_span": cell.get("col_span", 1),
            "crop_path": job.get("path"),
            "ocr_mode": "cell_isolated_crop",
            "inset_px": inset_px,
            "pad_px": pad_px,
            "orientation_established": bool(orientation_established),
            "rapidocr_use_cls": use_cls,
            "rapidocr_use_det": job.get("rapidocr_use_det"),
            "ink_class": job.get("ink_class"),
            "ink_line_band_count": job.get("ink_line_band_count"),
            "multiline_geometry": job.get("multiline_geometry"),
        }
        if not job.get("ok"):
            incomplete_cells.append({"cell_id": cell_id, "reason": job.get("reason") or "crop_failed"})
            for engine, sink in (("rapidocr", reports_a), ("tesseract", reports_b)):
                sink.append({
                    **base,
                    "engine": engine,
                    "text": "",
                    "blank": True,
                    "geometric_blank": False,
                    "visible_ink": None,
                    "fragment_count": 0,
                    "fragments": [],
                    "confidence_min": None,
                    "confidence_mean": None,
                    "incomplete": True,
                    "incomplete_reason": job.get("reason") or "crop_failed",
                })
            continue

        if job.get("geometric_blank"):
            geometric_blank_count += 1
            reports_a.append(_geometric_blank_engine_report(base, "rapidocr"))
            reports_b.append(_geometric_blank_engine_report(base, "tesseract"))
            continue

        visible = True  # non-blank by geometric check; retain ink probe for evidence
        try:
            from api.smedley_table_grid import cell_has_visible_ink

            visible = cell_has_visible_ink(image, bbox)
        except Exception:
            visible = True

        ra = rapid_by_id.get(cell_id) or {}
        rb = tess_by_id.get(cell_id) or {}
        a_text = str(ra.get("text") or "")
        b_text = str(rb.get("text") or "")
        a_incomplete = not bool(ra.get("ok"))
        b_incomplete = not bool(rb.get("ok"))
        if a_incomplete and not any(
            x.get("cell_id") == cell_id and x.get("engine") == "rapidocr"
            for x in incomplete_cells
        ):
            incomplete_cells.append({
                "cell_id": cell_id,
                "reason": ra.get("error") or "rapidocr_missing",
                "engine": "rapidocr",
            })
        reports_a.append({
            **base,
            "engine": "rapidocr",
            "text": a_text,
            "blank": a_text == "",
            "geometric_blank": False,
            "visible_ink": visible,
            "both_missed_visible_ink_candidate": bool(visible and a_text == ""),
            "fragment_count": int(ra.get("token_count") or (1 if a_text else 0)),
            "fragments": (
                [{
                    "text": a_text,
                    "bbox": bbox,
                    "confidence": ra.get("confidence"),
                    "provenance": "rapidocr.cell_batch",
                    "use_cls": use_cls,
                    "use_det": ra.get("use_det"),
                    "mode": ra.get("mode"),
                }]
                if a_text else []
            ),
            "confidence_min": ra.get("confidence"),
            "confidence_mean": ra.get("confidence"),
            "incomplete": a_incomplete,
            "incomplete_reason": None if not a_incomplete else (ra.get("error") or "rapidocr_failed"),
            "raw_engine": {
                k: ra.get(k)
                for k in ("ok", "error", "token_count", "use_cls", "use_det", "mode", "timed_out")
            },
        })
        reports_b.append({
            **base,
            "engine": "tesseract",
            "text": b_text,
            "blank": b_text == "",
            "geometric_blank": False,
            "visible_ink": visible,
            "both_missed_visible_ink_candidate": bool(visible and b_text == ""),
            "fragment_count": int(rb.get("token_count") or (1 if b_text else 0)),
            "fragments": (
                [{
                    "text": b_text,
                    "bbox": bbox,
                    "confidence": rb.get("confidence"),
                    "provenance": "tesseract.cell_psm",
                }]
                if b_text else []
            ),
            "confidence_min": rb.get("confidence"),
            "confidence_mean": rb.get("confidence"),
            "incomplete": b_incomplete,
            "incomplete_reason": None if not b_incomplete else (rb.get("error") or "tesseract_failed"),
            "tesseract_psm": rb.get("psm"),
            "raw_engine": {k: rb.get(k) for k in ("ok", "error", "psm", "token_count", "timed_out")},
        })

    return {
        "ok": True,
        "mode": "cell_isolated_crop",
        "cell_count": len(cells),
        "crop_dir": crop_dir,
        "inset_px": inset_px,
        "pad_px": pad_px,
        "median_row_height": med_h,
        "orientation_established": bool(orientation_established),
        "rapidocr_use_cls": use_cls,
        "table_geometry": table_geometry,
        "geometric_blank_count": geometric_blank_count,
        "engine_a_cells": reports_a,
        "engine_b_cells": reports_b,
        "engine_a_meta": rapid_meta,
        "engine_b_meta": tess_meta,
        "incomplete_cells": incomplete_cells,
        "incomplete_cell_count": len(incomplete_cells),
        "elapsed_ms": int((time.monotonic() - started) * 1000),
        "agreement_does_not_prove_correctness": True,
        "cells_verified": False,
    }
