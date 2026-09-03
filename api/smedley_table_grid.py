#!/usr/bin/env python3
"""Local ruled-table segmentation via OpenCV morphology + gutter splits."""

from __future__ import annotations

from typing import Any

import numpy as np
from PIL import Image


def _to_bgr(image: Image.Image) -> np.ndarray:
    import cv2

    rgb = np.array(image.convert("RGB"))
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def page_looks_raster(image: Image.Image, *, native_fragment_count: int = 0) -> bool:
    gray = image.convert("L").resize((min(900, image.size[0]), min(900, image.size[1])))
    arr = np.asarray(gray, dtype=np.float32)
    mean = float(arr.mean())
    contrast = float(arr.max() - arr.min())
    if native_fragment_count == 0 and mean < 245:
        return True
    return mean < 245 and contrast > 40


def detect_page_orientation(image: Image.Image) -> dict[str, Any]:
    """Legacy projection heuristic — prefer select_ocr_orientation for OCR work."""
    w, h = image.size
    gray = np.asarray(image.convert("L"), dtype=np.uint8)
    step = max(1, min(w, h) // 800)
    small = gray[::step, ::step]
    ink = small < 200
    row = ink.mean(axis=1)
    col = ink.mean(axis=0)
    rotate_cw_deg = 0
    reason = "upright_or_unknown"
    if h > w * 1.15 and col.std() > row.std() * 1.25:
        rotate_cw_deg = 90
        reason = "portrait_with_strong_vertical_ink_bands"
    elif w > h * 1.15 and row.std() > col.std() * 1.25:
        rotate_cw_deg = 0
        reason = "landscape_horizontal_ink"
    return {
        "rotate_cw_deg": rotate_cw_deg,
        "reason": reason,
        "image_size": [w, h],
        "original_unmodified": True,
        "method": "projection_heuristic_legacy",
    }


def page_image_coverage(image: Image.Image) -> dict[str, Any]:
    """Cheap ink/coverage evidence for sparse-native engineering rasters."""
    gray = image.convert("L")
    sample = gray.resize((min(900, gray.size[0]), min(900, gray.size[1])))
    arr = np.asarray(sample, dtype=np.float32)
    ink_ratio = float((arr < 245).mean())
    contrast = float(arr.max() - arr.min())
    return {
        "ink_ratio": round(ink_ratio, 4),
        "contrast": contrast,
        "significant": bool(ink_ratio >= 0.015 and contrast > 25),
    }


def select_ocr_orientation(
    image: Image.Image,
    *,
    tesseract_cmd: str | None = None,
    max_edge: int = 2400,
    timeout_s: float = 20.0,
    uncertainty_margin: float = 0.08,
) -> dict[str, Any]:
    """Pick 0/90/180/270 CW from document-independent OCR readability.

    Score = readable-token coverage × mean confidence. No content/cue word
    bonuses. If the top two scores are within ``uncertainty_margin`` (relative),
    leave rotation at 0 (uncertain). Each probe uses a bounded Tesseract timeout.
    """
    import pytesseract

    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    timeout = max(1.0, float(timeout_s))
    candidates: list[dict[str, Any]] = []
    for cw in (0, 90, 180, 270):
        rotated = image.rotate(-cw, expand=True) if cw else image
        probe = rotated.copy()
        probe.thumbnail((max_edge, max_edge))
        try:
            data = pytesseract.image_to_data(
                probe,
                output_type=pytesseract.Output.DICT,
                timeout=timeout,
            )
        except Exception as exc:
            candidates.append({
                "rotate_cw_deg": cw,
                "score": -1.0,
                "error": str(exc),
                "word_count": 0,
                "readable_count": 0,
                "mean_confidence": 0.0,
                "timeout_s": timeout,
            })
            continue
        words: list[str] = []
        confs: list[float] = []
        for text_tok, conf in zip(data.get("text") or [], data.get("conf") or []):
            token = str(text_tok or "").strip()
            try:
                conf_f = float(conf)
            except Exception:
                conf_f = -1.0
            if token and conf_f >= 0:
                words.append(token)
                confs.append(conf_f)
        # Readable = alphabetic tokens length>=3 (document-independent; no cue lexicon).
        readable_confs = [
            conf
            for token, conf in zip(words, confs)
            if conf >= 0.0 and len(token) >= 3 and any(ch.isalpha() for ch in token)
        ]
        readable_count = len(readable_confs)
        mean = (sum(readable_confs) / readable_count) if readable_count else 0.0
        # Coverage × mean confidence; no content/cue bonuses.
        score = float(readable_count) * mean
        candidates.append({
            "rotate_cw_deg": cw,
            "score": round(score, 2),
            "word_count": len(words),
            "readable_count": readable_count,
            "mean_confidence": round(mean, 2),
            "timeout_s": timeout,
            "sample": " ".join(words)[:180],
        })
    candidates.sort(key=lambda row: row.get("score") or -1.0, reverse=True)
    best = candidates[0] if candidates else {"rotate_cw_deg": 0, "score": 0.0}
    second = candidates[1] if len(candidates) > 1 else None
    best_score = float(best.get("score") or 0.0)
    second_score = float(second.get("score") or 0.0) if second else -1.0
    uncertain = False
    chosen_cw = int(best.get("rotate_cw_deg") or 0)
    reason = "tesseract_orientation_confidence"
    if best_score <= 0:
        chosen_cw = 0
        reason = "orientation_no_readable_signal"
        uncertain = True
    elif second is not None and best_score > 0:
        gap = best_score - second_score
        if gap < max(1.0, best_score * float(uncertainty_margin)):
            chosen_cw = 0
            reason = "orientation_uncertain_within_margin"
            uncertain = True
    return {
        "rotate_cw_deg": chosen_cw,
        "reason": reason,
        "method": "ocr_orientation_sweep",
        "image_size": list(image.size),
        "original_unmodified": True,
        "uncertain": uncertain,
        "uncertainty_margin": float(uncertainty_margin),
        "probe_timeout_s": timeout,
        "best": best,
        "candidates": candidates,
    }


def _line_masks(binary: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    import cv2

    h, w = binary.shape[:2]
    # Kernels must exceed glyph stem length. At ~400 DPI CCITT table rasters,
    # h//60 was ~18px and turned description text into phantom columns.
    horiz_len = max(30, w // 40)
    vert_len = max(40, h // 40)
    hk = cv2.getStructuringElement(cv2.MORPH_RECT, (horiz_len, 1))
    vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, vert_len))
    horiz = cv2.morphologyEx(binary, cv2.MORPH_OPEN, hk)
    vert = cv2.morphologyEx(binary, cv2.MORPH_OPEN, vk)
    # Light dilate only — heavy dilate bridges side-by-side table gutters.
    horiz = cv2.dilate(horiz, cv2.getStructuringElement(cv2.MORPH_RECT, (2, 1)), iterations=1)
    vert = cv2.dilate(vert, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 2)), iterations=1)
    return horiz, vert


def select_table_raster_orientation(
    image: Image.Image,
    *,
    pad_px: int = 16,
    tesseract_cmd: str | None = None,
    ocr_tiebreak: bool = True,
) -> dict[str, Any]:
    """Pick 0/90/180/270 CW so ruled-table geometry is strongest.

    Used for embedded CCITT table rasters that are stored sideways relative to
    reading order. Geometry score first; when 90 vs 270 (or 0 vs 180) tie on
    grid shape, optional short Tesseract header readability breaks the tie so
    upright text wins over upside-down grids with identical line counts.
    """
    from PIL import ImageOps

    best: dict[str, Any] | None = None
    candidates: list[dict[str, Any]] = []
    padded_by_cw: dict[int, Image.Image] = {}
    for cw in (0, 90, 180, 270):
        rotated = image.rotate(-cw, expand=True) if cw else image
        padded = ImageOps.expand(rotated.convert("RGB"), border=pad_px, fill="white")
        padded_by_cw[cw] = padded
        grid = detect_ruled_tables(padded, page=1)
        tables = list(grid.get("tables") or [])
        dense = [
            t for t in tables
            if int(t.get("col_count") or 0) >= 4 and int(t.get("row_count") or 0) >= 3
        ]
        primary = (
            max(dense, key=lambda t: int(t["row_count"]) * int(t["col_count"]))
            if dense else None
        )
        score = 0.0
        if grid.get("structure_verified") and primary is not None:
            score = float(primary["row_count"] * primary["col_count"])
            if len(dense) == 1:
                score += 100.0
                if padded.size[0] >= padded.size[1]:
                    score += 40.0
            else:
                score *= 0.2
        row = {
            "rotate_cw_deg": cw,
            "score": round(score, 2),
            "ok": bool(grid.get("ok")),
            "structure_verified": bool(grid.get("structure_verified")),
            "table_count": len(tables),
            "dense_table_count": len(dense),
            "primary": (
                {
                    "row_count": primary["row_count"],
                    "col_count": primary["col_count"],
                    "bbox": primary["bbox"],
                }
                if primary is not None else None
            ),
            "readability": None,
        }
        candidates.append(row)
        if best is None or row["score"] > best["score"]:
            best = row

    # Tie-break near-equal geometry (esp. 90 vs 270) via header OCR readability.
    if ocr_tiebreak and best and float(best.get("score") or 0) > 0:
        contenders = [
            c for c in candidates
            if c.get("structure_verified")
            and c.get("dense_table_count") == 1
            and float(c.get("score") or 0) >= float(best["score"]) * 0.9
        ]
        if len(contenders) >= 2:
            for c in contenders:
                primary = c.get("primary") or {}
                bbox = primary.get("bbox")
                padded = padded_by_cw[int(c["rotate_cw_deg"])]
                c["readability"] = _header_band_readability(
                    padded, bbox, tesseract_cmd=tesseract_cmd
                )
            contenders.sort(
                key=lambda c: (float(c.get("readability") or -1.0), float(c.get("score") or 0.0)),
                reverse=True,
            )
            best = contenders[0]
            best = {**best, "score": round(float(best["score"]) + float(best.get("readability") or 0), 2)}

    chosen = int((best or {}).get("rotate_cw_deg") or 0)
    uncertain = not best or float(best.get("score") or 0) <= 0
    return {
        "rotate_cw_deg": 0 if uncertain else chosen,
        "reason": "no_dense_ruled_table" if uncertain else "ruled_table_geometry_score",
        "method": "table_raster_orientation_sweep",
        "uncertain": uncertain,
        "pad_px": pad_px,
        "best": best,
        "candidates": candidates,
    }


def _header_band_readability(
    image: Image.Image,
    bbox: list[int] | None,
    *,
    tesseract_cmd: str | None = None,
    timeout_s: float = 8.0,
) -> float:
    """Cheap readable-token score on the first row band (no cue lexicon)."""
    if not bbox or len(bbox) < 4:
        return -1.0
    try:
        import pytesseract
    except Exception:
        return -1.0
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    x0, y0, x1, y1 = [int(v) for v in bbox]
    # First ~9% of table height ≈ header row on these sheets.
    hy1 = y0 + max(24, int((y1 - y0) * 0.10))
    crop = image.crop((x0, y0, x1, min(image.size[1], hy1)))
    if crop.size[0] < 8 or crop.size[1] < 8:
        return -1.0
    try:
        data = pytesseract.image_to_data(
            crop, output_type=pytesseract.Output.DICT, timeout=max(1.0, timeout_s)
        )
    except Exception:
        return -1.0
    readable_confs: list[float] = []
    for token, conf in zip(data.get("text") or [], data.get("conf") or []):
        text = str(token or "").strip()
        try:
            conf_f = float(conf)
        except Exception:
            conf_f = -1.0
        if conf_f >= 0 and len(text) >= 3 and any(ch.isalpha() for ch in text):
            readable_confs.append(conf_f)
    if not readable_confs:
        return 0.0
    # Mean confidence separates upright headers from upside-down glyph soup
    # (counts alone can favor garbage tokens).
    return sum(readable_confs) / len(readable_confs)


def _centers_from_mask(mask: np.ndarray, *, axis: int, min_gap: int) -> list[int]:
    """axis=0 -> horizontal line y centers; axis=1 -> vertical line x centers."""
    projection = (mask > 0).sum(axis=1 - axis)
    if projection.size == 0 or projection.max() == 0:
        return []
    thr = max(3, int(0.15 * projection.max()))
    active = projection >= thr
    centers: list[int] = []
    start = None
    for idx, flag in enumerate(active.tolist()):
        if flag and start is None:
            start = idx
        elif not flag and start is not None:
            centers.append((start + idx - 1) // 2)
            start = None
    if start is not None:
        centers.append((start + len(active) - 1) // 2)
    filtered: list[int] = []
    for c in centers:
        if not filtered or c - filtered[-1] >= min_gap:
            filtered.append(c)
        else:
            filtered[-1] = (filtered[-1] + c) // 2
    return filtered


def _strip_ink_ratio(gray: np.ndarray, x0: int, x1: int, y0: int, y1: int, *, threshold: int = 200) -> float:
    x0 = max(0, min(gray.shape[1], int(x0)))
    x1 = max(0, min(gray.shape[1], int(x1)))
    y0 = max(0, min(gray.shape[0], int(y0)))
    y1 = max(0, min(gray.shape[0], int(y1)))
    if x1 <= x0 or y1 <= y0:
        return 0.0
    crop = gray[y0:y1, x0:x1]
    if crop.size == 0:
        return 0.0
    return float((crop < threshold).mean())


def _header_band_ink_ratio(
    gray: np.ndarray,
    x0: int,
    x1: int,
    y0: int,
    y1: int,
) -> float:
    """Ink ratio in the upper header band of a vertical strip (grid lines removed)."""
    x0 = int(x0) + 2
    x1 = int(x1) - 2
    if x1 <= x0:
        return 0.0
    band_y1 = int(y0) + max(24, int(max(1, int(y1) - int(y0)) * 0.12))
    strip = gray[max(0, int(y0)):min(gray.shape[0], band_y1), max(0, x0):min(gray.shape[1], x1)]
    if strip.size == 0:
        return 0.0
    from PIL import Image as _Image

    cleaned = remove_grid_lines(_Image.fromarray(strip).convert("RGB"))
    arr = np.asarray(cleaned.convert("L"))
    if arr.size == 0:
        return 0.0
    return float((arr < 200).mean())


def _top_anchored_line_band(lines: list[int], *, max_gap_factor: float = 2.8, abs_cap: int = 80) -> list[int]:
    """Keep the contiguous ruled-line band starting at the first (top) line.

    Unlike ``_contiguous_line_band`` (longest anywhere), this prefers the top
    table on border-joined engineering sheets where lower title-block rules
    may continue the projection.
    """
    if len(lines) < 3:
        return lines
    gaps = [lines[i + 1] - lines[i] for i in range(len(lines) - 1)]
    med = float(sorted(gaps)[len(gaps) // 2])
    limit = max(abs_cap, int(med * max_gap_factor))
    band = [lines[0]]
    for i in range(len(lines) - 1):
        if lines[i + 1] - lines[i] <= limit:
            band.append(lines[i + 1])
        else:
            break
    if len(band) >= 3:
        return band
    return _contiguous_line_band(lines, max_gap_factor=max(3.0, max_gap_factor), abs_cap=max(140, abs_cap))


def _balanced_shared_border_splits(v_lines: list[int]) -> list[list[int]] | None:
    """Split a wide multi-column run at a shared border between two similar tables.

    Dual device schedules often share one vertical rule (no whitespace gutter).
    Prefer the most balanced split with >=4 columns on each side.
    """
    n = len(v_lines)
    if n < 11:  # need at least 4+4 cols => 5+5 lines sharing one border => 9 min; require denser
        return None
    # col_count = n-1; require enough columns that a dual-table join is plausible
    if (n - 1) < 12:
        return None
    best: tuple[float, int] | None = None
    mid = (v_lines[0] + v_lines[-1]) / 2.0
    span = max(1, v_lines[-1] - v_lines[0])
    for i in range(4, n - 4):
        # Shared border at v_lines[i]: left lines[0..i] => i cols; right lines[i..] => n-1-i cols.
        left_cols = i
        right_cols = n - 1 - i
        if left_cols < 4 or right_cols < 4:
            continue
        if abs(left_cols - right_cols) > 2:
            continue
        score = float(abs(left_cols - right_cols)) + abs(v_lines[i] - mid) / span
        if best is None or score < best[0]:
            best = (score, i)
    if best is None:
        return None
    i = best[1]
    left = v_lines[: i + 1]
    right = v_lines[i:]
    out = [g for g in (left, right) if len(g) >= 3]
    return out if len(out) >= 2 else None


def _split_vline_groups(
    v_lines: list[int],
    gray: np.ndarray,
    *,
    y0: int,
    y1: int,
    min_col_width: int = 28,
) -> list[list[int]]:
    """Split a shared v-line set into separate side-by-side tables.

    Handles three border-joined cases without filename/source hardcoding:
    1. Micro empty gutter between tables (narrow whitespace)
    2. Macro empty span (drawing / page-border dead zone with no header ink)
    3. Shared vertical border between two similarly columned tables (no gap)
    """
    if len(v_lines) < 3:
        return [v_lines] if v_lines else []
    widths = [v_lines[i + 1] - v_lines[i] for i in range(len(v_lines) - 1)]
    med = float(sorted(widths)[len(widths) // 2]) if widths else float(min_col_width)
    gutter_max = max(min_col_width, int(min(56, med * 0.40)))
    groups: list[list[int]] = [[v_lines[0]]]
    for i in range(len(v_lines) - 1):
        left, right = v_lines[i], v_lines[i + 1]
        width = right - left
        prev_w = widths[i - 1] if i > 0 else med
        next_w = widths[i + 1] if i + 1 < len(widths) else med
        header_ink = _header_band_ink_ratio(gray, left, right, y0, y1)
        # Structural gutter: micro-gap between two real data columns.
        structural_micro = (
            width <= gutter_max
            and width < max(min_col_width, med * 0.35)
            and prev_w >= max(40, med * 0.45)
            and next_w >= max(40, med * 0.45)
        )
        # Drawing / page-frame dead zone: much wider than median, no header text.
        structural_macro = (
            width >= max(160, med * 2.2)
            and header_ink < 0.02
            and (next_w >= max(36, med * 0.35) or prev_w >= max(36, med * 0.35))
        )
        weak_micro = width <= gutter_max and header_ink < 0.01 and prev_w >= 36 and next_w >= 36
        if structural_micro or structural_macro or weak_micro:
            groups.append([right])
        else:
            groups[-1].append(right)
    groups = [g for g in groups if len(g) >= 3]
    # Second pass: shared-border dual tables (wide DESCRIPTION is NOT a gutter).
    out: list[list[int]] = []
    for group in groups:
        balanced = _balanced_shared_border_splits(group)
        if balanced:
            out.extend(balanced)
        else:
            out.append(group)
    return out


def _rule_strength(mask: np.ndarray, *, axis_is_horizontal: bool, pos: int, a0: int, a1: int) -> float:
    h, w = mask.shape[:2]
    if axis_is_horizontal:
        y0 = max(0, pos - 1)
        y1 = min(h, pos + 2)
        x0 = max(0, a0)
        x1 = min(w, a1)
        strip = mask[y0:y1, x0:x1]
    else:
        x0 = max(0, pos - 1)
        x1 = min(w, pos + 2)
        y0 = max(0, a0)
        y1 = min(h, a1)
        strip = mask[y0:y1, x0:x1]
    if strip.size == 0:
        return 0.0
    return float((strip > 0).mean())


def _reject_page_footer_contamination(
    tables: list[dict[str, Any]],
    image_size: tuple[int, int],
) -> tuple[list[dict[str, Any]], list[str], bool]:
    """Drop / unverify whole-page tables whose bbox eats the title-block footer."""
    w, h = image_size
    kept: list[dict[str, Any]] = []
    warnings: list[str] = []
    uncertain = False
    footer_y = int(0.88 * h)
    for table in tables:
        bbox = table.get("bbox") or [0, 0, 0, 0]
        y1 = int(bbox[3]) if len(bbox) >= 4 else 0
        bw = int(bbox[2]) - int(bbox[0]) if len(bbox) >= 4 else 0
        # Wide band extending into footer zone is usually page-frame + title block.
        if y1 >= footer_y and bw >= 0.55 * w:
            uncertain = True
            warnings.append(
                f"{table.get('table_id')}: bbox bottom {y1} enters footer zone "
                f"(>={footer_y}); refusing structure_verified"
            )
            continue
        kept.append(table)
    return kept, warnings, uncertain


def _reject_as_table(bbox: list[int], image_shape: tuple[int, int], row_count: int, col_count: int) -> str | None:
    h, w = image_shape
    x0, y0, x1, y1 = bbox
    bw, bh = x1 - x0, y1 - y0
    area = max(0, bw) * max(0, bh)
    page_area = max(1, w * h)
    if row_count < 2 or col_count < 2:
        return "too_few_rows_or_cols"
    if area > 0.92 * page_area and row_count <= 3:
        return "page_border_or_title_frame"
    if bh < 40 or bw < 80:
        return "too_small"
    if row_count > 40 and col_count > 40:
        return "drawing_grid_like"
    if area < 0.12 * page_area and row_count <= 5 and col_count <= 5:
        return "instrument_or_title_box"
    if area < 0.20 * page_area and col_count < 4 and row_count < 6:
        return "sparse_box_not_data_table"
    if row_count >= 8 and col_count >= 8 and bh / max(1, row_count) < 12:
        return "drawing_grid_like"
    return None


def _contiguous_line_band(lines: list[int], *, max_gap_factor: float = 3.0, abs_cap: int = 140) -> list[int]:
    """Keep the longest contiguous ruled-line band; drop distant page borders."""
    if len(lines) < 3:
        return lines
    gaps = [lines[i + 1] - lines[i] for i in range(len(lines) - 1)]
    med = float(sorted(gaps)[len(gaps) // 2])
    limit = max(abs_cap, int(med * max_gap_factor))
    best: list[int] = []
    cur = [lines[0]]
    for i in range(len(lines) - 1):
        if lines[i + 1] - lines[i] <= limit:
            cur.append(lines[i + 1])
        else:
            if len(cur) > len(best):
                best = cur
            cur = [lines[i + 1]]
    if len(cur) > len(best):
        best = cur
    return best if len(best) >= 3 else lines


def page_has_dense_data_table(tables: list[dict[str, Any]]) -> bool:
    for table in tables:
        cols = int(table.get("col_count") or 0)
        rows = int(table.get("row_count") or 0)
        if cols >= 5 and rows >= 4:
            return True
        if cols >= 4 and rows >= 8:
            return True
    return False


def _redetect_table_lines(
    *,
    horiz: np.ndarray,
    vert: np.ndarray,
    gray: np.ndarray,
    x0: int,
    x1: int,
    y_search0: int,
    y_search1: int,
    seed_y0: int,
) -> tuple[list[int], list[int]] | None:
    """Re-detect h/v lines inside one table x-range so page-frame phantoms drop out.

    Page-border connected components span the whole sheet; vertical rules from
    the isometric drawing below the tables must not invent phantom columns, and
    horizontal rules must be measured per-table (unequal row pitches / bottoms).
    """
    h, w = gray.shape[:2]
    x0 = max(0, min(w - 1, int(x0)))
    # Inclusive right/bottom edges — Python slices exclude the end index, and the
    # table's outer border often sits exactly on x1/y1 from the seed group.
    x1_inclusive = max(x0 + 1, min(w - 1, int(x1)))
    x1_slice = min(w, x1_inclusive + 1)
    y_search0 = max(0, min(h - 1, int(y_search0)))
    y_search1 = max(y_search0 + 1, min(h, int(y_search1)))
    roi_h = horiz[y_search0:y_search1, x0:x1_slice]
    h_raw = [y_search0 + v for v in _centers_from_mask(roi_h, axis=0, min_gap=8)]
    if len(h_raw) < 3:
        return None
    # Prefer a band that includes the seed top (shared page-border header line).
    if h_raw[0] > seed_y0 + 25:
        # Include any strong line near the seed top inside this x-range.
        near_top = [
            y_search0 + v
            for v in _centers_from_mask(
                horiz[max(0, seed_y0 - 2):min(h, seed_y0 + 40), x0:x1_slice],
                axis=0,
                min_gap=6,
            )
        ]
        merged = sorted(set(near_top + h_raw))
        h_raw = merged
    local_h = _top_anchored_line_band(h_raw)
    if len(local_h) < 3:
        return None
    # If the first kept line is still well below a detected header rule, refuse
    # rather than mark truncated geometry as structure_verified.
    if local_h[0] > seed_y0 + 30 and any(abs(y - seed_y0) <= 8 for y in h_raw):
        # Force-include seed top when it exists in this x-range.
        top_candidates = [y for y in h_raw if y <= seed_y0 + 12]
        if top_candidates:
            local_h = _top_anchored_line_band(sorted(set(top_candidates + local_h)))
    roi_v = vert[local_h[0]:local_h[-1] + 1, x0:x1_slice]
    v_raw = [x0 + v for v in _centers_from_mask(roi_v, axis=1, min_gap=6)]
    if len(v_raw) < 3:
        return None
    return local_h, v_raw


def _build_cells_for_grid(
    *,
    page: int,
    table_idx: int,
    h_lines: list[int],
    v_lines: list[int],
    horiz: np.ndarray,
    vert: np.ndarray,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    row_count = len(h_lines) - 1
    col_count = len(v_lines) - 1
    table_id = f"p{page}-t{table_idx}"
    table = {
        "page": page,
        "table_id": table_id,
        "bbox": [int(v_lines[0]), int(h_lines[0]), int(v_lines[-1]), int(h_lines[-1])],
        "row_count": row_count,
        "col_count": col_count,
        "h_lines": [int(v) for v in h_lines],
        "v_lines": [int(v) for v in v_lines],
    }
    if col_count < 2 or row_count < 2:
        return table, [], warnings + [f"{table_id}: too few rows/cols"]

    cells: list[dict[str, Any]] = []
    consumed: set[tuple[int, int]] = set()
    for row in range(row_count):
        for col in range(col_count):
            if (row, col) in consumed:
                continue
            col_span = 1
            while True:
                nxt_col = col + col_span
                if nxt_col >= col_count or (row, nxt_col) in consumed:
                    break
                bx = int(v_lines[nxt_col])
                strength = _rule_strength(
                    vert, axis_is_horizontal=False, pos=bx, a0=h_lines[row], a1=h_lines[row + 1]
                )
                if strength < 0.02:
                    col_span += 1
                else:
                    break
            row_span = 1
            while True:
                nxt_row = row + row_span
                if nxt_row >= row_count:
                    break
                if any((nxt_row, col + dc) in consumed for dc in range(col_span)):
                    break
                by = int(h_lines[nxt_row])
                strength = _rule_strength(
                    horiz,
                    axis_is_horizontal=True,
                    pos=by,
                    a0=v_lines[col],
                    a1=v_lines[min(col + col_span, col_count)],
                )
                if strength < 0.015:
                    row_span += 1
                else:
                    break
            x0, y0 = int(v_lines[col]), int(h_lines[row])
            x1 = int(v_lines[min(col + col_span, col_count)])
            y1 = int(h_lines[min(row + row_span, row_count)])
            cell = {
                "page": page,
                "table_id": table_id,
                "table_index": table_idx,
                "row": row,
                "col": col,
                "row_span": row_span,
                "col_span": col_span,
                "bbox": [x0, y0, x1, y1],
                "cell_id": f"{table_id}-r{row}-c{col}"
                + (f"-rs{row_span}" if row_span > 1 else "")
                + (f"-cs{col_span}" if col_span > 1 else ""),
            }
            cells.append(cell)
            for rr in range(row_span):
                for cc in range(col_span):
                    consumed.add((row + rr, col + cc))
    return table, cells, warnings


def detect_ruled_tables(
    image: Image.Image,
    *,
    page: int,
    max_tables: int = 8,
    min_rows: int = 2,
    min_cols: int = 2,
) -> dict[str, Any]:
    """Detect separate side-by-side tables via ruled lines + gutter splits."""
    import cv2

    bgr = _to_bgr(image)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape[:2]
    binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 35, 10)
    horiz, vert = _line_masks(binary)
    grid = cv2.bitwise_or(horiz, vert)
    num, labels, stats, _ = cv2.connectedComponentsWithStats((grid > 0).astype(np.uint8), connectivity=8)

    warnings: list[str] = []
    tables: list[dict[str, Any]] = []
    cells: list[dict[str, Any]] = []
    structure_uncertain = False
    components = []
    for label in range(1, num):
        x, y, bw, bh, area = stats[label]
        if area < max(400, (w * h) // 5000):
            continue
        if bw < 80 or bh < 40:
            continue
        components.append((area, label, int(x), int(y), int(bw), int(bh)))
    components.sort(reverse=True)

    if not components:
        return {
            "ok": False,
            "reason": "unrecognized_table_structure",
            "structure_verified": False,
            "warnings": ["No ruled-line connected components found."],
            "tables": [],
            "cells": [],
            "page": page,
            "image_size": [int(w), int(h)],
            "structure_engine": "opencv_morphology_gutter_split",
        }

    table_idx = 0
    for area, label, x, y, bw, bh in components:
        if table_idx >= max_tables:
            warnings.append("max_tables reached; additional components ignored")
            break
        roi_h = horiz[y:y + bh, x:x + bw]
        h_lines = [int(y + v) for v in _centers_from_mask(roi_h, axis=0, min_gap=max(8, bh // 80))]
        if len(h_lines) < min_rows + 1:
            continue
        # Top-anchored band: page frames often continue ruled lines into title blocks.
        band_h = _top_anchored_line_band(h_lines)
        if len(band_h) < min_rows + 1:
            continue
        y0, y1 = int(band_h[0]), int(band_h[-1])
        # Detect verticals only inside the table y-band — full-page-height
        # components otherwise pick up isometric/drawing phantoms as columns.
        roi_v = vert[y0:y1 + 1, x:x + bw]
        v_lines = [int(x + v) for v in _centers_from_mask(roi_v, axis=1, min_gap=max(6, bw // 120))]
        if len(v_lines) < min_cols + 1:
            continue
        groups = _split_vline_groups(v_lines, gray, y0=y0, y1=y1)
        if len(groups) > 1:
            warnings.append(
                f"component label={label}: split into {len(groups)} tables at gutter/shared-border"
            )
        elif len(v_lines) >= 12 and (v_lines[-1] - v_lines[0]) > 0.55 * w:
            structure_uncertain = True
            warnings.append(
                f"component label={label}: wide multi-column region without clear gutter; structure unverified"
            )
        for group in groups:
            if table_idx >= max_tables:
                break
            # Per-table redetect: recovers header row on page-border tops and
            # drops phantom columns from content outside this table's y-extent.
            redetected = _redetect_table_lines(
                horiz=horiz,
                vert=vert,
                gray=gray,
                x0=group[0],
                x1=group[-1],
                y_search0=max(0, y - 2),
                y_search1=min(h, y + bh + 2),
                seed_y0=y0,
            )
            if redetected is None:
                warnings.append(f"component label={label}: redetect failed for x=[{group[0]},{group[-1]}]")
                continue
            local_h, local_v = redetected
            if len(local_h) < min_rows + 1 or len(local_v) < min_cols + 1:
                continue
            # Truncation guard: header text sitting above the first kept h-line
            # means we dropped the true top boundary — do not claim verified.
            if local_h[0] > y0 + 20:
                structure_uncertain = True
                warnings.append(
                    f"component label={label}: table top truncated (h0={local_h[0]} below seed {y0}); "
                    "structure unverified"
                )
            bbox = [int(local_v[0]), int(local_h[0]), int(local_v[-1]), int(local_h[-1])]
            reject = _reject_as_table(bbox, (h, w), len(local_h) - 1, len(local_v) - 1)
            if reject:
                warnings.append(f"rejected table candidate: {reject}")
                continue
            table, local_cells, local_warn = _build_cells_for_grid(
                page=page,
                table_idx=table_idx,
                h_lines=local_h,
                v_lines=local_v,
                horiz=horiz,
                vert=vert,
            )
            warnings.extend(local_warn)
            if not local_cells:
                continue
            table["component_label"] = int(label)
            tables.append(table)
            cells.extend(local_cells)
            table_idx += 1

    if not cells:
        return {
            "ok": False,
            "reason": "unrecognized_table_structure",
            "structure_verified": False,
            "warnings": warnings or ["Ruled components found but no usable table cells."],
            "tables": tables,
            "cells": [],
            "page": page,
            "image_size": [int(w), int(h)],
            "structure_engine": "opencv_morphology_gutter_split",
        }
    if not page_has_dense_data_table(tables):
        warnings.append("no dense data table (BOM/device-like); treating page as not-table")
        return {
            "ok": False,
            "reason": "not_table_engineering_drawing",
            "structure_verified": False,
            "warnings": warnings,
            "tables": tables,
            "cells": [],
            "page": page,
            "image_size": [int(w), int(h)],
            "structure_engine": "opencv_morphology_gutter_split",
            "component_count": len(components),
        }
    if structure_uncertain:
        return {
            "ok": False,
            "reason": "structure_unverified",
            "structure_verified": False,
            "warnings": warnings
            + ["Geometry uncertain; text agreements must not be treated as verified cells."],
            "tables": tables,
            "cells": [],
            "page": page,
            "image_size": [int(w), int(h)],
            "structure_engine": "opencv_morphology_gutter_split",
            "component_count": len(components),
        }
    return {
        "ok": True,
        "reason": "opencv_gutter_split_tables",
        "structure_verified": True,
        "warnings": warnings,
        "tables": tables,
        "cells": cells,
        "page": page,
        "image_size": [int(w), int(h)],
        "structure_engine": "opencv_morphology_gutter_split",
        "component_count": len(components),
    }


def remove_grid_lines(image: Image.Image) -> Image.Image:
    """Return a copy with ruled lines attenuated for OCR (original untouched)."""
    import cv2

    bgr = _to_bgr(image)
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 35, 10)
    horiz, vert = _line_masks(binary)
    grid = cv2.bitwise_or(horiz, vert)
    cleaned = bgr.copy()
    cleaned[grid > 0] = (255, 255, 255)
    rgb = cv2.cvtColor(cleaned, cv2.COLOR_BGR2RGB)
    return Image.fromarray(rgb)


def _bbox_area(bbox: list[float]) -> float:
    return max(0.0, float(bbox[2] - bbox[0])) * max(0.0, float(bbox[3] - bbox[1]))


def _intersection_area(a: list[float], b: list[float]) -> float:
    x0 = max(a[0], b[0])
    y0 = max(a[1], b[1])
    x1 = min(a[2], b[2])
    y1 = min(a[3], b[3])
    return max(0.0, x1 - x0) * max(0.0, y1 - y0)


def cell_has_visible_ink(
    image: Image.Image,
    bbox: list[float],
    *,
    threshold: int = 200,
    min_ratio: float = 0.004,
) -> bool:
    """True when cell interior has ink after removing border/rule pixels."""
    x0, y0, x1, y1 = [int(v) for v in bbox]
    x0 = max(0, x0)
    y0 = max(0, y0)
    x1 = min(image.size[0], x1)
    y1 = min(image.size[1], y1)
    if x1 - x0 < 6 or y1 - y0 < 6:
        return False
    inset = 3
    crop = image.crop((x0 + inset, y0 + inset, max(x0 + inset + 1, x1 - inset), max(y0 + inset + 1, y1 - inset)))
    if crop.size[0] < 3 or crop.size[1] < 3:
        return False
    cleaned = remove_grid_lines(crop)
    arr = np.asarray(cleaned.convert("L"), dtype=np.uint8).copy()
    # Erase residual perimeter (border bleed after crop).
    arr[:2, :] = 255
    arr[-2:, :] = 255
    arr[:, :2] = 255
    arr[:, -2:] = 255
    if arr.size == 0:
        return False
    return float((arr < threshold).mean()) >= min_ratio and int((arr < 180).sum()) >= 6


def assign_fragments_to_cells(
    cells: list[dict[str, Any]],
    fragments: list[dict[str, Any]],
    *,
    engine: str,
    image: Image.Image | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    assigned: dict[str, list[dict[str, Any]]] = {cell["cell_id"]: [] for cell in cells}
    ambiguous: list[dict[str, Any]] = []
    for frag in fragments:
        bbox = frag.get("bbox")
        if not bbox or frag.get("page") is None:
            ambiguous.append({"engine": engine, "fragment_text": frag.get("text"), "bbox": bbox, "reason": "missing_bbox_or_page"})
            continue
        scores = []
        frag_area = _bbox_area(bbox) or 1.0
        for cell in cells:
            if int(cell["page"]) != int(frag["page"]):
                continue
            inter = _intersection_area(bbox, cell["bbox"])
            if inter <= 0:
                continue
            scores.append((inter / frag_area, inter, cell))
        if not scores:
            ambiguous.append({"engine": engine, "fragment_text": frag.get("text"), "bbox": bbox, "reason": "unassigned"})
            continue
        scores.sort(reverse=True, key=lambda item: (item[0], item[1]))
        best_ratio, _, best_cell = scores[0]
        if best_ratio < 0.55 or (len(scores) > 1 and scores[1][0] > 0.25):
            ambiguous.append({
                "engine": engine,
                "fragment_text": frag.get("text"),
                "bbox": bbox,
                "reason": "boundary_crossing_or_ambiguous",
                "best_ratio": best_ratio,
                "candidate_cell_ids": [s[2]["cell_id"] for s in scores[:4]],
            })
        if best_ratio >= 0.20:
            assigned[best_cell["cell_id"]].append(frag)

    reports: list[dict[str, Any]] = []
    for cell in cells:
        frags = sorted(assigned.get(cell["cell_id"]) or [], key=lambda f: ((f.get("bbox") or [0, 0])[1], (f.get("bbox") or [0, 0])[0]))
        parts = [str(f.get("text") or "") for f in frags]
        text = " ".join(p for p in parts if p is not None).strip()
        confs = [float(f["confidence"]) for f in frags if f.get("confidence") is not None]
        visible_ink = cell_has_visible_ink(image, cell["bbox"]) if image is not None else None
        reports.append({
            **cell,
            "engine": engine,
            "text": text,
            "blank": text == "",
            "visible_ink": visible_ink,
            "both_missed_visible_ink_candidate": bool(visible_ink and text == ""),
            "fragment_count": len(frags),
            "fragments": [
                {"text": f.get("text"), "bbox": f.get("bbox"), "confidence": f.get("confidence"), "provenance": f.get("provenance")}
                for f in frags
            ],
            "confidence_min": min(confs) if confs else None,
            "confidence_mean": (sum(confs) / len(confs)) if confs else None,
        })
    return reports, ambiguous


def compare_aligned_cells(
    primary: list[dict[str, Any]],
    secondary: list[dict[str, Any]],
    *,
    low_confidence: float = 0.55,
    sample_limit: int = 40,
    include_full_lists: bool = False,
) -> dict[str, Any]:
    primary_map = {
        (c["page"], c["table_id"], c["row"], c["col"], c.get("col_span", 1), c.get("row_span", 1)): c
        for c in primary
    }
    secondary_map = {
        (c["page"], c["table_id"], c["row"], c["col"], c.get("col_span", 1), c.get("row_span", 1)): c
        for c in secondary
    }
    keys = sorted(set(primary_map) | set(secondary_map))
    matched_nonblank = []
    matched_blank = []
    disagree = []
    missing_primary = []
    missing_secondary = []
    both_missed_visible_ink = []
    low_conf = []
    for key in keys:
        left = primary_map.get(key)
        right = secondary_map.get(key)
        if left is None:
            missing_primary.append({"cell_key": key, "secondary_text": right.get("text") if right else None})
            continue
        if right is None:
            missing_secondary.append({"cell_key": key, "primary_text": left.get("text")})
            continue
        lt = left.get("text") or ""
        rt = right.get("text") or ""
        item = {
            "cell_id": left.get("cell_id") or right.get("cell_id"),
            "page": key[0],
            "table_id": key[1],
            "row": key[2],
            "col": key[3],
            "col_span": key[4],
            "row_span": key[5],
            "primary_text": lt,
            "secondary_text": rt,
            "bbox": left.get("bbox") or right.get("bbox"),
        }
        for side, cell in (("primary", left), ("secondary", right)):
            conf = cell.get("confidence_min")
            if conf is not None and float(conf) < low_confidence:
                low_conf.append({**item, "engine_side": side, "confidence_min": conf})
        if lt == "" and rt == "":
            matched_blank.append({**item, "blank": True})
            if left.get("visible_ink") or right.get("visible_ink"):
                both_missed_visible_ink.append(item)
        elif lt == rt:
            matched_nonblank.append({**item, "blank": False})
        else:
            disagree.append(item)

    limit = max(0, int(sample_limit))
    out: dict[str, Any] = {
        "schema": "smedley.table_cell_cross_check.v2",
        "matched_nonblank_count": len(matched_nonblank),
        "matched_blank_count": len(matched_blank),
        "matched_count": len(matched_nonblank) + len(matched_blank),
        "disagree_count": len(disagree),
        "missing_in_primary_count": len(missing_primary),
        "missing_in_secondary_count": len(missing_secondary),
        "blank_both_count": len(matched_blank),
        "both_missed_visible_ink_count": len(both_missed_visible_ink),
        "low_confidence_count": len(low_conf),
        "matched_nonblank_sample": matched_nonblank[:limit],
        "matched_blank_sample": matched_blank[: min(limit, 20)],
        "disagree_sample": disagree[:limit],
        "both_missed_visible_ink_sample": both_missed_visible_ink[:limit],
        "missing_in_primary_sample": missing_primary[:limit],
        "missing_in_secondary_sample": missing_secondary[:limit],
        "low_confidence_sample": low_conf[:limit],
        "agreement_does_not_prove_correctness": True,
        "comparison_unit": "page/table/row/col cell identity",
        "note": "Blank-blank agreement is reported separately and is not treated as strong OCR matching.",
    }
    if include_full_lists:
        out["full"] = {
            "matched_nonblank": matched_nonblank,
            "matched_blank": matched_blank,
            "disagree": disagree,
            "both_missed_visible_ink": both_missed_visible_ink,
            "missing_in_primary": missing_primary,
            "missing_in_secondary": missing_secondary,
            "low_confidence": low_conf,
        }
    return out
