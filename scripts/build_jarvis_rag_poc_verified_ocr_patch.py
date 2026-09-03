#!/usr/bin/env python3
"""Build and dry-run the staged jarvis_rag_poc producer patch (in-repo only)."""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "runtime/argus-rag/staging/jarvis_rag_poc.py.base-20260902"
PATCHED = ROOT / "runtime/argus-rag/staging/jarvis_rag_poc.py.patched-20260902"
DIFF = ROOT / "runtime/argus-rag/patches/jarvis_rag_poc_verified_ocr_20260902.diff"
TESTDIR = ROOT / "runtime/argus-rag/staging/patchtest"


def must_replace(src: str, old: str, new: str, label: str) -> str:
    if old not in src:
        raise SystemExit(f"missing block: {label}")
    return src.replace(old, new, 1)


def main() -> None:
    text = BASE.read_text(encoding="utf-8")
    text = must_replace(
        text,
        """                manifest = {
                    \"schema\": \"jarvis.pdf_extraction.v2\", \"source\": os.path.realpath(path),
                    \"quality_state\": \"verified\", \"extraction_mode\": \"sidecar\",
                    \"page_count\": None, \"ocr_pages\": [], \"text_pages\": [],
                    \"extracted_chars\": len(text), \"warnings\": [],
                    \"sidecar_path\": os.path.realpath(sidecar),
                }
""",
        """                manifest = {
                    \"schema\": \"jarvis.pdf_extraction.v2\", \"source\": os.path.realpath(path),
                    \"quality_state\": \"needs_review\", \"extraction_mode\": \"sidecar\",
                    \"ocr_verification_state\": \"unverified\",
                    \"page_count\": None, \"ocr_pages\": [], \"text_pages\": [],
                    \"extracted_chars\": len(text),
                    \"warnings\": [\"Independent OCR/table verification required for sidecar extractions.\"],
                    \"sidecar_path\": os.path.realpath(sidecar),
                }
""",
        "sidecar",
    )
    text = must_replace(
        text,
        """        quality = \"needs_review\" if warnings else \"verified\"
    return {
        \"schema\": \"jarvis.pdf_extraction.v2\",
        \"source\": os.path.realpath(path),
        \"fingerprint\": os.path.basename(_ocr_cache_path(path))[:-3],
        \"quality_state\": quality,
        \"extraction_mode\": mode,
        \"page_count\": len(profiles),
""",
        """        if mode in {\"full_ocr\", \"mixed_selective_ocr\"}:
            quality = \"needs_review\"
            if \"Independent OCR/table verification required.\" not in warnings:
                warnings.append(\"Independent OCR/table verification required.\")
        else:
            quality = \"needs_review\" if warnings else \"verified\"
    return {
        \"schema\": \"jarvis.pdf_extraction.v2\",
        \"source\": os.path.realpath(path),
        \"fingerprint\": os.path.basename(_ocr_cache_path(path))[:-3],
        \"quality_state\": quality,
        \"extraction_mode\": mode,
        \"ocr_verification_state\": (
            \"unverified\" if mode in {\"full_ocr\", \"mixed_selective_ocr\", \"sidecar\"} else \"not_applicable\"
        ),
        \"page_count\": len(profiles),
""",
        "quality",
    )
    text = must_replace(
        text,
        """    machine = {
        \"chunks\": n,
        \"quality_state\": manifest.get(\"quality_state\", \"failed\"),
        \"extraction_mode\": manifest.get(\"extraction_mode\"),
        \"page_count\": manifest.get(\"page_count\"),
""",
        """    machine = {
        \"chunks\": n,
        \"quality_state\": manifest.get(\"quality_state\", \"failed\"),
        \"extraction_mode\": manifest.get(\"extraction_mode\"),
        \"ocr_verification_state\": manifest.get(\"ocr_verification_state\"),
        \"page_count\": manifest.get(\"page_count\"),
""",
        "machine",
    )
    text = must_replace(
        text,
        """def extract_with_manifest(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == \".pdf\":
        return _pdf_with_manifest(path)
""",
        """def extract_with_manifest(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == \".dxf\":
        try:
            import sys
            hermes_root = \"/Users/rick/hermes-webui\"
            if hermes_root not in sys.path:
                sys.path.insert(0, hermes_root)
            from api.smedley_dxf_extract import extract_dxf
            from api.jarvis_rag_ingest_events import evidence_root_for, file_sha256
            sha = file_sha256(path)
            evidence_dir = evidence_root_for(sha, basename=os.path.basename(path))
            payload = extract_dxf(path, evidence_dir=evidence_dir, update_ledger=False, source_sha256=sha)
            texts = payload.get(\"texts\") or []
            text_out = \"\\n\".join(str(item.get(\"text\") or \"\") for item in texts)
            manifest = {
                \"schema\": \"jarvis.dxf_extraction.v1\",
                \"source\": os.path.realpath(path),
                \"quality_state\": payload.get(\"quality_state\") or \"needs_review\",
                \"extraction_mode\": \"dxf_native\",
                \"ocr_verification_state\": \"not_applicable\",
                \"page_count\": None,
                \"ocr_pages\": [],
                \"text_pages\": [],
                \"extracted_chars\": len(text_out),
                \"table_rows\": 0,
                \"warnings\": list(payload.get(\"warnings\") or []),
                \"manifest_path\": payload.get(\"manifest_path\"),
            }
            return text_out, manifest
        except Exception as exc:
            print(\"      [dxf] hermes extractor unavailable (%s); skipping DXF\" % exc, flush=True)
            return \"\", {
                \"schema\": \"jarvis.dxf_extraction.v1\",
                \"source\": os.path.realpath(path),
                \"quality_state\": \"failed\",
                \"extraction_mode\": \"dxf_native\",
                \"ocr_verification_state\": \"not_applicable\",
                \"warnings\": [\"DXF extractor unavailable: %s\" % exc],
                \"page_count\": None,
                \"ocr_pages\": [],
                \"text_pages\": [],
                \"extracted_chars\": 0,
                \"table_rows\": 0,
                \"manifest_path\": None,
            }
    if ext == \".pdf\":
        return _pdf_with_manifest(path)
""",
        "dxf",
    )
    PATCHED.write_text(text, encoding="utf-8")
    proc = subprocess.run(["diff", "-u", str(BASE), str(PATCHED)], capture_output=True, text=True)
    out = proc.stdout
    out = re.sub(r"^--- .*$", "--- jarvis_rag_poc.py", out, count=1, flags=re.M)
    out = re.sub(r"^\+\+\+ .*$", "+++ jarvis_rag_poc.py", out, count=1, flags=re.M)
    DIFF.parent.mkdir(parents=True, exist_ok=True)
    DIFF.write_text(out, encoding="utf-8")
    print("base_sha", hashlib.sha256(BASE.read_bytes()).hexdigest())
    print("patched_sha", hashlib.sha256(PATCHED.read_bytes()).hexdigest())
    print("diff_lines", len(out.splitlines()))

    if TESTDIR.exists():
        shutil.rmtree(TESTDIR)
    TESTDIR.mkdir(parents=True)
    shutil.copy2(BASE, TESTDIR / "jarvis_rag_poc.py")
    dry = subprocess.run(["patch", "-p0", "--dry-run"], cwd=TESTDIR, input=out, text=True, capture_output=True)
    print("dry-run", dry.returncode, dry.stdout.strip(), dry.stderr.strip())
    if dry.returncode != 0:
        raise SystemExit("dry-run failed")
    apply = subprocess.run(["patch", "-p0"], cwd=TESTDIR, input=out, text=True, capture_output=True)
    print("apply", apply.returncode, apply.stdout.strip(), apply.stderr.strip())
    if apply.returncode != 0:
        raise SystemExit("apply failed")
    syn = subprocess.run(["python3", "-m", "py_compile", "jarvis_rag_poc.py"], cwd=TESTDIR, capture_output=True, text=True)
    print("syntax", syn.returncode, syn.stderr.strip())
    if syn.returncode != 0:
        raise SystemExit("syntax failed")
    print("PATCH_AND_SYNTAX_OK")


if __name__ == "__main__":
    main()
