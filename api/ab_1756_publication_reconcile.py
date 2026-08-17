#!/usr/bin/env python3
"""Auto-build 1756 publication aliases from the live library + ingest records.

Drop → watcher → hash/index remains the ingest path. This module does not
replace ingest. It reconciles deterministic TD/UM/IN aliases so Smedley can
resolve 1756-TD005 / 1756-IN619 (and zero-padded variants) without a manual
manifest publish step.

Ingest is never inferred from file presence alone: indexed=true only when the
watcher's content-hash map records the file.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Any

STATUS_DIR = os.path.expanduser("~/.jarvis_rag_status")
ALIASES_FILE = os.path.join(STATUS_DIR, "publication_aliases.json")
LEDGER_FILE = os.path.join(STATUS_DIR, "ingest_ledger.json")
WATCH_META = os.path.expanduser("~/.jarvis_rag_watch_meta.json")
WATCH_STATUS = os.path.join(STATUS_DIR, "library.json")
DEFAULT_LIBRARY_ROOT = "/Users/rick/Mounts/RAG_Pool/Library"
FAMILY_REL = "Vendor Data/Allen Bradley/1756"
SMB = "smb://192.168.0.25/RAG_Pool/Library/Vendor Data/Allen Bradley/1756"
FILENAME_RE = re.compile(
    r"^1756[-_](td|um|in)0*(\d{1,4})[-_][^\s]+\.(?:pdf|docx?)$",
    re.IGNORECASE,
)


def _iso(ts: float | None = None) -> str:
    value = time.time() if ts is None else float(ts)
    return datetime.fromtimestamp(value, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_json(path: str, default: Any) -> Any:
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload
    except Exception:
        return default


def _save_json(path: str, payload: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    os.replace(tmp, path)


def canonical_doc_no(kind: str, number: int) -> str:
    kind_u = str(kind or "").upper()
    if number >= 100:
        return f"1756-{kind_u}{number}"
    return f"1756-{kind_u}{number:03d}"


def aliases_for(kind: str, number: int, filename: str, doc_no: str) -> dict[str, list[str]]:
    kind_u = str(kind or "").upper()
    p3 = f"{number:03d}"
    p4 = f"{number:04d}"
    exact = [
        doc_no,
        filename,
        f"1756-{kind_u}{p3}" if number < 100 else f"1756-{kind_u}{number}",
    ]
    normalized = [
        f"{kind_u}{number}",
        f"{kind_u}{p3}",
        f"{kind_u}{p4}",
        f"{kind_u}-{number}",
        f"{kind_u}-{p3}",
        f"{kind_u}-{p4}",
        f"1756-{kind_u}{number}",
        f"1756-{kind_u}{p3}",
        f"1756-{kind_u}{p4}",
        f"1756 {kind_u}{p3}",
        f"1756-{kind_u}-{p3}",
        f"1756-{kind_u}-{p4}",
        filename.lower(),
        doc_no.lower(),
    ]
    # Owner-cited zero-padded TD0005 maps to 1756-TD005.
    if kind_u == "TD" and number == 5:
        normalized.extend(["TD0005", "TD-0005", "1756-TD0005", "1756-TD-0005"])
    seen_exact: list[str] = []
    for item in exact:
        if item and item not in seen_exact:
            seen_exact.append(item)
    seen_norm: list[str] = []
    for item in normalized:
        key = str(item)
        if key and key not in seen_norm and key not in seen_exact:
            seen_norm.append(key)
    return {"exact": seen_exact, "normalized": seen_norm}


def parse_1756_filename(name: str) -> tuple[str, int] | None:
    match = FILENAME_RE.match(os.path.basename(str(name or "")))
    if not match:
        return None
    return str(match.group(1)).upper(), int(match.group(2))


def hashed_paths(watch_meta: dict[str, Any] | None = None) -> dict[str, str]:
    meta = watch_meta if isinstance(watch_meta, dict) else _load_json(WATCH_META, {})
    hashes = meta.get("hashes") if isinstance(meta, dict) else {}
    out: dict[str, str] = {}
    if not isinstance(hashes, dict):
        return out
    for digest, path in hashes.items():
        key = os.path.realpath(str(path))
        out[key] = str(digest)
    return out


def ingest_phase_for(
    path: str,
    *,
    hashed: dict[str, str],
    watch_status: dict[str, Any] | None,
    ledger_entry: dict[str, Any] | None,
    quarantined: dict[str, Any] | None,
) -> tuple[str, str | None]:
    """Return (phase, reason). Indexed only from ingest records, not presence."""
    real = os.path.realpath(path)
    base = os.path.basename(path)
    q = (quarantined or {}).get(path) or (quarantined or {}).get(real)
    if isinstance(q, dict):
        return "failed", str(q.get("reason") or "quarantined")
    status = watch_status if isinstance(watch_status, dict) else {}
    last_file = str(status.get("last_file") or "")
    raw = str(status.get("status") or "")
    last_error = status.get("last_error")
    if raw == "active" and last_file == base:
        return "indexing", None
    if raw == "error" and last_file == base:
        return "failed", str(last_error or "ingest error")
    if real in hashed:
        return "indexed", None
    if isinstance(ledger_entry, dict) and ledger_entry.get("phase") in {
        "detected",
        "indexing",
        "indexed",
        "failed",
    }:
        return str(ledger_entry.get("phase")), ledger_entry.get("reason")
    if os.path.isfile(path):
        return "detected", None
    return "absent", "not on disk"


def scan_1756_publications(
    library_root: str,
    *,
    watch_meta: dict[str, Any] | None = None,
    watch_status: dict[str, Any] | None = None,
    ledger: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = os.path.realpath(library_root or DEFAULT_LIBRARY_ROOT)
    folder = os.path.join(root, FAMILY_REL)
    hashed = hashed_paths(watch_meta)
    status = watch_status if isinstance(watch_status, dict) else _load_json(WATCH_STATUS, {})
    meta = watch_meta if isinstance(watch_meta, dict) else _load_json(WATCH_META, {})
    quarantine = meta.get("quarantine") if isinstance(meta.get("quarantine"), dict) else {}
    ledger_files = {}
    if isinstance(ledger, dict) and isinstance(ledger.get("files"), dict):
        ledger_files = ledger["files"]
    publications: list[dict[str, Any]] = []
    if os.path.isdir(folder):
        for name in sorted(os.listdir(folder)):
            parsed = parse_1756_filename(name)
            if not parsed:
                continue
            kind, number = parsed
            path = os.path.join(folder, name)
            real = os.path.realpath(path)
            rel = f"{FAMILY_REL}/{name}".replace("\\", "/")
            doc_no = canonical_doc_no(kind, number)
            digest = hashed.get(real)
            entry_ledger = ledger_files.get(real) or ledger_files.get(path)
            phase, reason = ingest_phase_for(
                path,
                hashed=hashed,
                watch_status=status,
                ledger_entry=entry_ledger if isinstance(entry_ledger, dict) else None,
                quarantined=quarantine,
            )
            st = os.stat(path) if os.path.isfile(path) else None
            aliases = aliases_for(kind, number, name, doc_no)
            publications.append(
                {
                    "kind": kind,
                    "number": number,
                    "family_code": "1756",
                    "canonical_filename": name,
                    "source": rel,
                    "doc_no": doc_no,
                    "publication_identifier": doc_no,
                    "title": doc_no,
                    "revision": None,
                    "date": None,
                    "language": "EN",
                    "aliases_exact": aliases["exact"],
                    "aliases_normalized": aliases["normalized"],
                    "present": bool(st),
                    "indexed": bool(digest),
                    "resolvable": bool(st),
                    "ingest_phase": phase,
                    "ingest_reason": reason,
                    "sha256": digest,
                    "mtime_utc": _iso(st.st_mtime) if st else None,
                    "bytes": st.st_size if st else None,
                }
            )
    return {
        "schema": "smedley.ab_1756_publication_manifest.v1",
        "generated_by": "ab_1756_publication_reconcile",
        "generated_at": _iso(),
        "library_relpath": FAMILY_REL,
        "smb": SMB,
        "vendor": "Allen-Bradley / Rockwell Automation",
        "family": "1756 ControlLogix",
        "note": (
            "Auto-reconciled from the live 1756 library + watcher hash map. "
            "indexed=true only when ~/.jarvis_rag_watch_meta.json records the file hash. "
            "Owner aliases such as TD0005 map zero-insensitively to 1756-TD005. "
            "No manual publish sequence is required."
        ),
        "publications": publications,
    }


def load_or_reconcile_manifest(
    *,
    library_root: str = "",
    persist: bool = True,
) -> dict[str, Any]:
    root = library_root or DEFAULT_LIBRARY_ROOT
    payload = scan_1756_publications(root)
    if persist and payload.get("publications"):
        try:
            _save_json(ALIASES_FILE, payload)
        except Exception:
            pass
    if payload.get("publications"):
        return payload
    committed = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ab_1756_publication_manifest.json")
    fallback = _load_json(committed, {})
    return fallback if isinstance(fallback, dict) else {}


def publication_glass_rows(payload: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    data = payload if isinstance(payload, dict) else _load_json(ALIASES_FILE, {})
    rows = []
    for entry in data.get("publications") or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("doc_no") in {"1756-TD005", "1756-IN619"} or (
            str(entry.get("kind")).upper() in {"TD", "IN"}
            and int(entry.get("number") or 0) in {5, 619}
        ):
            rows.append(
                {
                    "doc_no": entry.get("doc_no"),
                    "filename": entry.get("canonical_filename"),
                    "source": entry.get("source"),
                    "present": bool(entry.get("present")),
                    "indexed": bool(entry.get("indexed")),
                    "resolvable": bool(entry.get("resolvable")),
                    "ingest_phase": entry.get("ingest_phase"),
                    "ingest_reason": entry.get("ingest_reason"),
                    "mtime_utc": entry.get("mtime_utc"),
                    "sha256": entry.get("sha256"),
                }
            )
    rows.sort(key=lambda row: str(row.get("doc_no") or ""))
    return rows


def main() -> int:
    payload = load_or_reconcile_manifest(persist=True)
    rows = publication_glass_rows(payload)
    print(json.dumps({"aliases": ALIASES_FILE, "count": len(payload.get("publications") or []), "focus": rows}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
