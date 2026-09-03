#!/usr/bin/env python3
"""Extract embedded PDF page images as table-raster candidates (pypdfium2).

Engineering sheets often embed BOM/device tables as separate ~400 DPI CCITT
rasters. Prefer those bitmaps (with placement/transform provenance) over a
downsampled whole-page render for ruled-grid geometry. Whole-page fallback
remains the caller's responsibility when no dense table candidates qualify.
"""

from __future__ import annotations

import hashlib
import os
from typing import Any

from PIL import Image, ImageOps

from api.smedley_table_grid import detect_ruled_tables, select_table_raster_orientation

# Bounded extraction — not a free-for-all image dump.
DEFAULT_MAX_IMAGES_PER_PAGE = 8
DEFAULT_MIN_EDGE_PX = 400
DEFAULT_MIN_PIXELS = 200_000
DEFAULT_MAX_PIXELS_PER_IMAGE = 20_000_000
DEFAULT_PAD_PX = 16


def _matrix_tuple(matrix: Any) -> list[float]:
    return [
        float(getattr(matrix, "a", 0.0)),
        float(getattr(matrix, "b", 0.0)),
        float(getattr(matrix, "c", 0.0)),
        float(getattr(matrix, "d", 0.0)),
        float(getattr(matrix, "e", 0.0)),
        float(getattr(matrix, "f", 0.0)),
    ]


def _meta_dict(meta: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in (
        "width",
        "height",
        "horizontal_dpi",
        "vertical_dpi",
        "bits_per_pixel",
        "colorspace",
        "marked_content_id",
    ):
        if hasattr(meta, key):
            try:
                out[key] = getattr(meta, key)
            except Exception:
                continue
    return out


def extract_page_embedded_images(
    page: Any,
    *,
    page_no: int,
    out_dir: str,
    source_sha256: str,
    max_images: int = DEFAULT_MAX_IMAGES_PER_PAGE,
    min_edge_px: int = DEFAULT_MIN_EDGE_PX,
    min_pixels: int = DEFAULT_MIN_PIXELS,
    max_pixels_per_image: int = DEFAULT_MAX_PIXELS_PER_IMAGE,
) -> dict[str, Any]:
    """Dump page image XObjects to PNG with placement provenance.

    Does not modify the PDF. Skips images below table-candidate size thresholds
    as unprocessed non-table candidates (not drawing-coverage claims). Returns
    candidates sorted by
    pixel area (largest first), capped by ``max_images``.
    """
    import pypdfium2 as pdfium

    os.makedirs(out_dir, exist_ok=True)
    page_size = None
    try:
        page_size = [float(v) for v in page.get_size()]
    except Exception:
        page_size = None

    raw_objects: list[Any] = []
    try:
        for obj in page.get_objects():
            if int(getattr(obj, "type", -1)) == int(pdfium.raw.FPDF_PAGEOBJ_IMAGE):
                raw_objects.append(obj)
    except Exception as exc:
        return {
            "ok": False,
            "reason": f"page_object_walk_failed:{exc}",
            "page": page_no,
            "images": [],
            "skipped": [],
        }

    images: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for index, obj in enumerate(raw_objects):
        if len(images) >= max_images:
            skipped.append({"image_index": index, "reason": "max_images_per_page"})
            continue
        try:
            px = obj.get_px_size()
            width_px, height_px = int(px[0]), int(px[1])
        except Exception as exc:
            skipped.append({"image_index": index, "reason": f"px_size:{exc}"})
            continue
        area = width_px * height_px
        if min(width_px, height_px) < min_edge_px or area < min_pixels:
            skipped.append(
                {
                    "image_index": index,
                    # Narrow strip / logo / calc block — not assumed ornament.
                    "reason": "unprocessed_non_table_candidate",
                    "detail": "below_table_candidate_size_threshold",
                    "px_size": [width_px, height_px],
                }
            )
            continue
        if area > max_pixels_per_image:
            skipped.append(
                {
                    "image_index": index,
                    "reason": "exceeds_max_pixels_per_image",
                    "px_size": [width_px, height_px],
                }
            )
            continue
        try:
            bounds = [float(v) for v in obj.get_bounds()]
            matrix = _matrix_tuple(obj.get_matrix())
            meta = _meta_dict(obj.get_metadata())
            bitmap = obj.get_bitmap()
            try:
                pil = bitmap.to_pil().convert("RGB")
            finally:
                close = getattr(bitmap, "close", None)
                if callable(close):
                    close()
        except Exception as exc:
            skipped.append({"image_index": index, "reason": f"bitmap_extract:{exc}"})
            continue
        # Immutable bytes for this extract (content identity under orientation).
        raw_path = os.path.join(out_dir, f"page-{page_no:03d}-img-{index:03d}-source.png")
        pil.save(raw_path, format="PNG")
        with open(raw_path, "rb") as handle:
            image_sha = hashlib.sha256(handle.read()).hexdigest()
        images.append(
            {
                "page": page_no,
                "image_index": index,
                "object_index_on_page": index,
                "px_size": [width_px, height_px],
                "source_bbox_pdf": bounds,
                "placement_matrix": matrix,
                "page_size_pdf": page_size,
                "image_metadata": meta,
                "source_sha256": source_sha256,
                "image_sha256": image_sha,
                "source_png": raw_path,
                "coordinate_space": "pdf_page_user_space_bbox_plus_pixel_raster",
                "original_unmodified_pdf": True,
            }
        )

    images.sort(key=lambda row: row["px_size"][0] * row["px_size"][1], reverse=True)
    return {
        "ok": True,
        "reason": "pypdfium2_page_image_objects",
        "page": page_no,
        "engine": "pypdfium2.PdfImage",
        "image_object_count": len(raw_objects),
        "candidate_count": len(images),
        "images": images,
        "skipped": skipped,
    }


def prepare_embedded_table_raster(
    candidate: dict[str, Any],
    *,
    oriented_dir: str,
    pad_px: int = DEFAULT_PAD_PX,
    tesseract_cmd: str | None = None,
) -> dict[str, Any]:
    """Orient + pad an embedded image and run ruled-table detection."""
    os.makedirs(oriented_dir, exist_ok=True)
    source_png = str(candidate["source_png"])
    image = Image.open(source_png).convert("RGB")
    orientation = select_table_raster_orientation(
        image, pad_px=pad_px, tesseract_cmd=tesseract_cmd, ocr_tiebreak=True
    )
    rotate_cw = int(orientation.get("rotate_cw_deg") or 0)
    rotated = image.rotate(-rotate_cw, expand=True) if rotate_cw else image
    padded = ImageOps.expand(rotated, border=pad_px, fill="white")
    oriented_path = os.path.join(
        oriented_dir,
        f"page-{int(candidate['page']):03d}-img-{int(candidate['image_index']):03d}"
        f"-rot{rotate_cw}cw-pad{pad_px}.png",
    )
    padded.save(oriented_path, format="PNG")
    grid = detect_ruled_tables(padded, page=int(candidate["page"]))
    tables = list(grid.get("tables") or [])
    dense = [
        t for t in tables
        if int(t.get("col_count") or 0) >= 4 and int(t.get("row_count") or 0) >= 3
    ]
    # Single embedded raster should usually yield one table; multi-split on a
    # clean CCITT bitmap is treated as unverified geometry.
    structure_verified = bool(grid.get("structure_verified")) and len(dense) == 1
    if bool(grid.get("structure_verified")) and len(dense) != 1:
        grid = {
            **grid,
            "ok": False,
            "structure_verified": False,
            "reason": "embedded_raster_ambiguous_table_split",
            "cells": [],
            "warnings": list(grid.get("warnings") or [])
            + ["embedded raster did not resolve to exactly one dense table"],
        }
        structure_verified = False
    # Namespace table/cell ids by embedded image index so multi-raster pages
    # do not collide in cross-check identity (page/table/row/col).
    img_idx = int(candidate.get("image_index") or 0)
    namespaced_tables: list[dict[str, Any]] = []
    namespaced_cells: list[dict[str, Any]] = []
    if structure_verified:
        orig_to_new: dict[str, str] = {}
        for table in tables:
            t = dict(table)
            old_id = str(t.get("table_id") or f"p{candidate['page']}-t0")
            new_id = f"p{int(candidate['page'])}-img{img_idx}-{old_id}"
            t["table_id"] = new_id
            t["embedded_image_index"] = img_idx
            namespaced_tables.append(t)
            orig_to_new[old_id] = new_id
        for cell in grid.get("cells") or []:
            c = dict(cell)
            old_tid = str(c.get("table_id") or "")
            new_tid = orig_to_new.get(old_tid, f"p{int(candidate['page'])}-img{img_idx}-{old_tid}")
            c["table_id"] = new_tid
            c["embedded_image_index"] = img_idx
            old_cid = str(c.get("cell_id") or "")
            c["cell_id"] = (
                old_cid.replace(old_tid, new_tid, 1)
                if old_tid and old_tid in old_cid
                else f"{new_tid}-r{c.get('row')}-c{c.get('col')}"
            )
            namespaced_cells.append(c)
    return {
        **candidate,
        "orientation": orientation,
        "rotate_cw_deg": rotate_cw,
        "pad_px": pad_px,
        "oriented_png": oriented_path,
        "oriented_size": list(padded.size),
        "table_structure": {
            "ok": bool(grid.get("ok")) and structure_verified,
            "reason": grid.get("reason") if structure_verified else (grid.get("reason") or "embedded_unverified"),
            "structure_verified": structure_verified,
            "structure_engine": grid.get("structure_engine"),
            "table_count": len(namespaced_tables),
            "cell_count": len(namespaced_cells),
            "warnings": grid.get("warnings") or [],
            "tables": [
                {
                    "table_id": t.get("table_id"),
                    "bbox": t.get("bbox"),
                    "row_count": t.get("row_count"),
                    "col_count": t.get("col_count"),
                    "h_lines": t.get("h_lines"),
                    "v_lines": t.get("v_lines"),
                    "embedded_image_index": img_idx,
                }
                for t in namespaced_tables
            ],
        },
        "grid_cells": namespaced_cells,
        "grid_full": grid if structure_verified else None,
    }


def collect_embedded_table_candidates(
    page: Any,
    *,
    page_no: int,
    evidence_dir: str,
    source_sha256: str,
    pad_px: int = DEFAULT_PAD_PX,
    max_images: int = DEFAULT_MAX_IMAGES_PER_PAGE,
    tesseract_cmd: str | None = None,
) -> dict[str, Any]:
    """Extract + orient + grid-score embedded images for one page."""
    raw_dir = os.path.join(evidence_dir, "embedded_table_rasters", "source")
    oriented_dir = os.path.join(evidence_dir, "embedded_table_rasters", "oriented")
    extracted = extract_page_embedded_images(
        page,
        page_no=page_no,
        out_dir=raw_dir,
        source_sha256=source_sha256,
        max_images=max_images,
    )
    prepared: list[dict[str, Any]] = []
    for candidate in extracted.get("images") or []:
        prepared.append(
            prepare_embedded_table_raster(
                candidate,
                oriented_dir=oriented_dir,
                pad_px=pad_px,
                tesseract_cmd=tesseract_cmd,
            )
        )
    verified = [row for row in prepared if (row.get("table_structure") or {}).get("structure_verified")]
    failed = [
        {
            "kind": "candidate_structure_failed",
            "image_index": row.get("image_index"),
            "px_size": row.get("px_size"),
            "source_bbox_pdf": row.get("source_bbox_pdf"),
            "reason": (row.get("table_structure") or {}).get("reason"),
            "warnings": (row.get("table_structure") or {}).get("warnings") or [],
        }
        for row in prepared
        if not (row.get("table_structure") or {}).get("structure_verified")
    ]
    # Size-threshold skips are unprocessed non-table candidates (e.g. speed-calc
    # strips). Completeness is scoped to detected table candidates only — not
    # full drawing / all embedded image coverage.
    significant_skips = [
        dict(item, kind="skipped_significant")
        for item in (extracted.get("skipped") or [])
        if str(item.get("reason") or "") != "unprocessed_non_table_candidate"
    ]
    nontable_skips = [
        dict(item, kind="unprocessed_non_table_candidate")
        for item in (extracted.get("skipped") or [])
        if str(item.get("reason") or "") == "unprocessed_non_table_candidate"
    ]
    # Back-compat alias for prior field name (do not treat as ornament claim).
    ornament_skips = list(nontable_skips)
    omissions = failed + significant_skips
    coverage_complete = bool(verified) and not omissions
    return {
        "ok": bool(extracted.get("ok")),
        "reason": extracted.get("reason"),
        "page": page_no,
        "engine": extracted.get("engine"),
        "image_object_count": extracted.get("image_object_count"),
        "candidate_count": len(prepared),
        "structure_verified_count": len(verified),
        "failed_candidate_count": len(failed),
        "significant_skip_count": len(significant_skips),
        "unprocessed_non_table_candidate_count": len(nontable_skips),
        "ornament_skip_count": len(ornament_skips),  # alias; not an ornament claim
        "omissions": omissions,
        "coverage_complete": coverage_complete,
        "coverage_scope": "detected_table_candidates",
        "coverage_note": (
            "coverage_complete means verified table candidates have no significant "
            "omissions; unprocessed non-table candidates are out of table scope"
        ),
        # Prefer embedded when any verified table exists; completeness is separate.
        "prefer_embedded_over_page_render": len(verified) >= 1,
        "candidates": prepared,
        "skipped": extracted.get("skipped") or [],
        "unprocessed_non_table_candidates": nontable_skips,
    }
