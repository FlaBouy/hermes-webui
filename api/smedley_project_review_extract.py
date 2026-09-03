#!/usr/bin/env python3
"""Callable Project Review extraction entry points (DXF + verified OCR evidence)."""

from __future__ import annotations

import os
from typing import Any

from api.jarvis_rag_ingest_events import (
    LIBRARY_ROOT,
    _safe_rel_folder,
    evidence_root_for,
)
from api.smedley_dxf_extract import DEFAULT_MAX_BYTES as DXF_MAX_BYTES
from api.smedley_dxf_extract import capabilities as dxf_capabilities
from api.smedley_dxf_extract import extract_dxf
from api.smedley_pdf_ocr_verify import DEFAULT_MAX_BYTES as PDF_MAX_BYTES
from api.smedley_pdf_ocr_verify import capabilities as pdf_capabilities
from api.smedley_pdf_ocr_verify import verify_pdf
from api.smedley_source_snapshot import materialize_source_snapshot

UNSUPPORTED_CAD = {".dwg", ".rvt", ".rfa", ".ifc"}


def capabilities() -> dict[str, Any]:
    dxf = dxf_capabilities()
    pdf = pdf_capabilities()
    return {
        "schema": "smedley.project_review_extract_capabilities.v2",
        "callable": True,
        "tool_name": "project_review_extract",
        "mcp_tools": ["project_review_extract_capabilities", "project_review_extract"],
        "routes": [
            "/api/smedley/project-review/extract",
            "/api/smedley/project-review/extract/capabilities",
            "/api/biggy/projects/reviews/extract",
            "/api/biggy/projects/reviews/extract/capabilities",
        ],
        "profile_activation": {
            "smedley_route": "Requires authenticated session with active profile smedley (or Biggy coordinating a Smedley-owned review project_id).",
            "biggy_route": "Requires Biggy project review record with review_owner=smedley and a valid rag_folder under Projects/Projects - YYYY/...",
            "mcp_required_env": {
                "HERMES_WEBUI_STATE_DIR": "/Users/rick/.hermes/profiles/biggy/webui-state",
            },
        },
        "dxf": dxf,
        "pdf_ocr": pdf,
        "notes": [
            "DWG/RVT require approved export/conversion; direct support is not claimed.",
            "Evidence writes only to the server-owned isolated evidence root outside the RAG library.",
            "Does not replace rag_search; this is a dedicated Project Review extraction tool.",
            "MCP tools are project_review_extract_capabilities and project_review_extract.",
            "path accepts: (1) relative to rag_folder, (2) full library-relative path beginning "
            "with rag_folder (prefix stripped — do not double-join), (3) absolute under rag_folder. "
            "Traversal/symlink escape fails closed.",
        ],
        "path_forms": {
            "relative": "WB3339-012.pdf or subdir/file.pdf inside rag_folder",
            "library_relative": "Projects/Projects - 2026/<project>/file.pdf when that equals rag_folder + file",
            "absolute": "Absolute path already inside the rag_folder realpath",
            "rejected": ["..", "symlink escape", "Library/ + rag_folder double-join outside scope"],
        },
    }


def _normalize_path_under_rag(path: str, *, rag_folder: str, library_root: str) -> str:
    """Normalize accepted extract path forms to a candidate under the RAG folder.

    Accepted:
      1. basename / relative path inside the RAG folder
      2. full library-relative path that begins with the RAG folder (prefix stripped)
      3. absolute path already inside the RAG folder

    Rejected later by realpath escape checks: ``..``, symlink escape, paths outside folder.
    """
    raw = str(path or "").strip().replace("\\", "/")
    if not raw or "\x00" in raw:
        raise ValueError("invalid path")
    rel_folder = _safe_rel_folder(rag_folder)
    if not rel_folder:
        raise ValueError("project RAG folder is required and must be non-empty")
    root = os.path.realpath(library_root)
    scoped = os.path.realpath(os.path.join(root, rel_folder))
    if scoped != root and not scoped.startswith(root + os.sep):
        raise ValueError("RAG folder escapes library root")
    if not os.path.isdir(scoped):
        raise ValueError("RAG folder does not exist")

    # Absolute path — must resolve under scoped.
    if os.path.isabs(raw):
        return raw

    # Strip optional Library/ prefix if operators paste mirrored NAS paths.
    lowered = raw
    for prefix in ("Library/", "library/"):
        if lowered.startswith(prefix):
            lowered = lowered[len(prefix) :]
            break

    folder = rel_folder.replace("\\", "/").rstrip("/")
    # Full library-relative path that already includes the RAG folder.
    if lowered == folder or lowered.startswith(folder + "/"):
        remainder = "" if lowered == folder else lowered[len(folder) + 1 :]
        if not remainder:
            raise ValueError("path required")
        if remainder.startswith("/") or remainder.startswith("../") or "/../" in f"/{remainder}/":
            raise ValueError("invalid path")
        return remainder

    # Reject obvious double-join attempts that escape via parent segments.
    if ".." in lowered.split("/"):
        raise ValueError("invalid path")
    return lowered


def _resolve_scoped_path(path: str, *, rag_folder: str) -> str:
    rel_or_abs = _normalize_path_under_rag(path, rag_folder=rag_folder, library_root=LIBRARY_ROOT)
    rel_folder = _safe_rel_folder(rag_folder)
    root = os.path.realpath(LIBRARY_ROOT)
    scoped = os.path.realpath(os.path.join(root, rel_folder))
    candidate = os.path.realpath(
        rel_or_abs if os.path.isabs(rel_or_abs) else os.path.join(scoped, rel_or_abs)
    )
    # Fail closed on symlink / traversal escape.
    if candidate != scoped and not candidate.startswith(scoped + os.sep):
        raise ValueError("path is outside the selected Project Review RAG folder")
    if not os.path.isfile(candidate):
        raise ValueError("source file not found")
    # Also require the unresolved join stays under scoped before realpath when relative.
    if not os.path.isabs(rel_or_abs):
        joined = os.path.normpath(os.path.join(scoped, rel_or_abs))
        if joined != scoped and not joined.startswith(scoped + os.sep):
            raise ValueError("path is outside the selected Project Review RAG folder")
    return candidate


def extract_project_document(
    path: str,
    *,
    rag_folder: str,
    kind: str | None = None,
    update_ledger: bool = True,
    producer_mode: str | None = None,
    max_pages: int = 8,
    force_raster_ocr: bool | None = None,
) -> dict[str, Any]:
    """Run the appropriate extractor into a server-owned evidence directory."""
    if max_pages is None or int(max_pages) < 1:
        raise ValueError("max_pages must be a positive integer")
    max_pages = int(max_pages)
    real = _resolve_scoped_path(path, rag_folder=rag_folder)
    ext = os.path.splitext(real)[1].lower()
    requested = (kind or "auto").strip().lower() or "auto"
    if requested == "auto":
        if ext == ".dxf":
            requested = "dxf"
        elif ext == ".pdf":
            requested = "pdf"
        elif ext in UNSUPPORTED_CAD:
            requested = "cad_export_required"
        else:
            raise ValueError(f"unsupported review extract type: {ext or '(none)'}")

    caps = capabilities()
    from api.biggy_project_review_runtime import (
        annotate_sample_only_extract_result,
        is_sample_only_source,
    )

    sample_only = is_sample_only_source(real)
    # Sample fixtures stay on disk; never write them into production ledgers.
    effective_update_ledger = bool(update_ledger) and not sample_only

    if requested == "cad_export_required" or ext in UNSUPPORTED_CAD:
        return annotate_sample_only_extract_result(
            real,
            {
                "schema": "smedley.project_review_extract.v2",
                "ok": False,
                "state": "needs_approved_export",
                "source": real,
                "reason": (
                    f"{ext.upper()} is not directly readable in Biggy/Smedley. "
                    "Use an approved export/conversion to DXF or PDF first."
                ),
                "capabilities": caps,
            },
        )

    # Snapshot first: hash immutable evidence copy, then map provenance to live path.
    # Parsers open the snapshot only; library original is never the parse target.
    import shutil
    import tempfile

    max_bytes = DXF_MAX_BYTES if requested == "dxf" else PDF_MAX_BYTES
    stage = tempfile.mkdtemp(prefix="smedley-pr-snap-")
    try:
        snap = materialize_source_snapshot(real, evidence_dir=stage, max_bytes=max_bytes)
        source_sha = snap["source_sha256"]
        evidence_dir = evidence_root_for(source_sha, basename=os.path.basename(real))
        dest_snap_root = os.path.join(evidence_dir, "source_snapshot")
        os.makedirs(dest_snap_root, exist_ok=True)
        moved = None
        for name in os.listdir(os.path.join(stage, "source_snapshot")):
            src_f = os.path.join(stage, "source_snapshot", name)
            dst_f = os.path.join(dest_snap_root, name)
            if os.path.exists(dst_f):
                # Keep prior evidence; write under an extra unique suffix.
                stem, ext = os.path.splitext(name)
                dst_f = os.path.join(dest_snap_root, f"{stem}.keep{os.getpid()}{ext}")
            shutil.move(src_f, dst_f)
            moved = dst_f
        if not moved:
            raise RuntimeError("snapshot relocate failed")
        snap = {
            **snap,
            "snapshot_path": moved,
            "parse_path": moved,
            "source_path": real,
        }
        if requested == "dxf":
            result = extract_dxf(
                real,
                evidence_dir=evidence_dir,
                update_ledger=effective_update_ledger,
                source_sha256=source_sha,
                source_snapshot=snap,
            )
        elif requested == "pdf":
            result = verify_pdf(
                real,
                evidence_dir=evidence_dir,
                update_ledger=effective_update_ledger,
                producer_mode=producer_mode,
                max_pages=max_pages,
                force_raster_ocr=force_raster_ocr,
                source_sha256=source_sha,
                source_snapshot=snap,
            )
        else:
            raise ValueError(f"unknown extract kind: {requested}")
    finally:
        shutil.rmtree(stage, ignore_errors=True)

    return annotate_sample_only_extract_result(
        real,
        {
            "schema": "smedley.project_review_extract.v2",
            "ok": bool(result.get("ok")),
            "kind": requested,
            "source": real,
            "source_sha256": source_sha,
            "rag_folder": _safe_rel_folder(rag_folder),
            "evidence_dir": evidence_dir,
            "result": result,
            "capabilities": caps,
            "evidence_refs": {
                "manifest_path": result.get("manifest_path"),
                "visual_renders": result.get("visual_renders"),
                "raw_engine_outputs": result.get("raw_engine_outputs"),
                "ocr_verification_state": result.get("ocr_verification_state"),
                "quality_state": result.get("quality_state"),
                "extraction_mode": result.get("extraction_mode") or (
                    "dxf_native" if requested == "dxf" else None
                ),
            },
        },
    )
