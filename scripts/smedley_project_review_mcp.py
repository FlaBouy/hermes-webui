#!/usr/bin/env python3
"""Dedicated FastMCP adapter for Smedley Project Review extraction.

Separate from scripts/smedley_rag_mcp.py so rag_search remains single-purpose.
This tool binds project_id + path to the Hermes extract implementation and
returns concise evidence references (no Qdrant indexing).

Requires explicit HERMES_WEBUI_STATE_DIR (Biggy webui-state) so project lookup
does not silently read a Smedley-profile HERMES_HOME store.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Fail closed if staged activation forgot the Biggy state dir.
_REQUIRED_STATE = os.environ.get("HERMES_WEBUI_STATE_DIR", "").strip()
if not _REQUIRED_STATE:
    # Allow smoke/capabilities without state; extract path still requires it.
    pass

mcp = FastMCP(
    "smedley_project_review",
    instructions=(
        "Dedicated Project Review extraction tools: "
        "project_review_extract_capabilities and project_review_extract. "
        "Does not replace rag_search. "
        "Call project_review_extract_capabilities before claiming engines are installed. "
        "Call project_review_extract with an existing project_id and a path inside that "
        "review's RAG folder. update_ledger defaults false. "
        "Requires HERMES_WEBUI_STATE_DIR pointing at the Biggy webui-state that owns projects.json."
    ),
)


def _load_review_project(project_id: str) -> dict:
    from api.models import load_projects
    from api.profiles import _profiles_match

    state_dir = (os.environ.get("HERMES_WEBUI_STATE_DIR") or "").strip()
    if not state_dir:
        raise ValueError(
            "HERMES_WEBUI_STATE_DIR is required (expected Biggy webui-state, "
            "e.g. /Users/rick/.hermes/profiles/biggy/webui-state)"
        )
    pid = (project_id or "").strip()
    if not pid:
        raise ValueError("project_id required")
    # Read-only: never migrate/write projects.json from the MCP adapter.
    projects = load_projects(_migrate=False)
    project = next(
        (
            item
            for item in projects
            if str(item.get("project_id") or "") == pid
            and (
                _profiles_match(item.get("profile"), "smedley")
                or (
                    _profiles_match(item.get("profile"), "biggy")
                    and str((item.get("review") or {}).get("review_owner") or "") == "smedley"
                )
            )
        ),
        None,
    )
    if project is None:
        raise ValueError("project review not found for project_id")
    review = project.get("review") or {}
    rag_folder = str(review.get("rag_folder") or "").strip()
    if not rag_folder:
        raise ValueError("project review is missing a valid RAG folder")
    return project


@mcp.tool()
def project_review_extract_capabilities() -> str:
    """Return DXF/OCR Project Review extractor capabilities and activation notes."""
    from api.smedley_project_review_extract import capabilities

    payload = capabilities()
    payload["activation"] = {
        "mcp_server": "smedley_project_review",
        "tools": ["project_review_extract_capabilities", "project_review_extract"],
        "profile": "smedley",
        "required_env": {
            "HERMES_WEBUI_STATE_DIR": "/Users/rick/.hermes/profiles/biggy/webui-state",
            "note": "Must match live Biggy plist webui-state so project_id resolves.",
        },
        "note": "Stage under Smedley profile mcp_servers; do not edit live config from this tool.",
    }
    payload["state_dir"] = (os.environ.get("HERMES_WEBUI_STATE_DIR") or "").strip() or None
    return json.dumps(payload, indent=2)


@mcp.tool()
def project_review_extract(
    project_id: str,
    path: str,
    kind: str = "auto",
    max_pages: int = 8,
    update_ledger: bool = False,
    producer_mode: str = "",
) -> str:
    """Extract DXF or PDF/OCR evidence for one file inside a Project Review RAG folder.

    Returns concise state + evidence refs. Does not index into Qdrant.
    """
    from api.smedley_project_review_extract import extract_project_document

    try:
        project = _load_review_project(project_id)
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc), "project_id": project_id})
    review = project.get("review") or {}
    rag_folder = str(review.get("rag_folder") or "").strip()
    try:
        max_pages_i = int(max_pages)
    except Exception as exc:
        return json.dumps({"ok": False, "error": f"max_pages must be a positive integer: {exc}"})
    if max_pages_i < 1:
        return json.dumps({"ok": False, "error": "max_pages must be a positive integer"})
    try:
        result = extract_project_document(
            path,
            rag_folder=rag_folder,
            kind=(kind or "auto"),
            update_ledger=bool(update_ledger),
            producer_mode=(producer_mode or None) or None,
            max_pages=min(max_pages_i, 12),
        )
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc), "project_id": project_id})
    body = {
        "ok": bool(result.get("ok")),
        "tool": "project_review_extract",
        "mcp_tools": ["project_review_extract_capabilities", "project_review_extract"],
        "project_id": project_id,
        "project_name": project.get("name"),
        "rag_folder": rag_folder,
        "kind": result.get("kind"),
        "source": result.get("source"),
        "source_sha256": result.get("source_sha256"),
        "evidence_dir": result.get("evidence_dir"),
        "evidence_refs": result.get("evidence_refs"),
        "sample_only": bool(result.get("sample_only")),
        "production_findings_allowed": result.get(
            "production_findings_allowed",
            False if result.get("sample_only") else True,
        ),
        "warnings": list(result.get("warnings") or []),
        "state": (result.get("result") or {}).get("state"),
        "ocr_verification_state": (result.get("result") or {}).get("ocr_verification_state"),
        "quality_state": (result.get("result") or {}).get("quality_state"),
        "reason": (result.get("result") or {}).get("reason"),
        "counts": (result.get("result") or {}).get("counts"),
        # Supply measured table dimensions so the narrator does not infer
        # a nine-column device schedule for an eight-column BOM.
        "table_geometry": [
            {
                "page": page.get("page"),
                "table_id": table.get("table_id"),
                "row_count_including_header": table.get("row_count"),
                "column_count": table.get("col_count"),
            }
            for page in (result.get("result") or {}).get("pages", [])
            if isinstance(page, dict)
            for table in (page.get("table_structure") or {}).get("tables", [])
            if isinstance(table, dict)
        ],
        "cross_check_summary": {
            k: (result.get("result") or {}).get("cross_check", {}).get(k)
            for k in (
                "matched_nonblank_count",
                "matched_blank_count",
                "disagree_count",
                "both_missed_visible_ink_count",
                "ambiguous_assignment_count",
                "cells_verified",
                "structure_verified",
            )
        }
        if (result.get("result") or {}).get("cross_check")
        else None,
    }
    if body["sample_only"]:
        body["production_findings_allowed"] = False
        note = (
            "TEST-ONLY sample fixture — leave original in place; do not treat extract "
            "as Hosford production findings."
        )
        if note not in body["warnings"]:
            body["warnings"].append(note)
    return json.dumps(body, indent=2)


if __name__ == "__main__":
    if os.environ.get("SMEDLEY_PROJECT_REVIEW_MCP_SMOKE") == "1":
        print(project_review_extract_capabilities())
    else:
        mcp.run()
