#!/usr/bin/env python3
"""Shared RAG ingest event/state for watcher, Smedley sidebar, and Mk.2.

Contract: drop/rescan → write status=active (red) immediately → remain active
through extracting/indexing → indexed (green) or failed/quarantined (red)
with file identity and reason. Idle health must not hide the queue.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Any

STATUS_DIR = os.path.expanduser("~/.jarvis_rag_status")
LIBRARY_STATUS = os.path.join(STATUS_DIR, "library.json")
LEDGER_FILE = os.path.join(STATUS_DIR, "ingest_ledger.json")
WATCH_META = os.path.expanduser("~/.jarvis_rag_watch_meta.json")
WATCH_STATE = os.path.expanduser("~/.jarvis_rag_watch_state.json")
LIBRARY_ROOT = "/Users/rick/Mounts/RAG_Pool/Library"
FOCUS_FILES = ("1756-td005_-en-e.pdf", "1756-in619_-en-p.pdf")
PROCESSING = {"detected", "queued", "extracting", "indexing"}
ACTIONABLE_PHASES = {"failed", "quarantined"}
INDEXED_PHASES = {"indexed", "indexed_via_sidecar", "duplicate"}
RESOLVED_PHASES = {"resolved"}
HIDDEN_CARD_PHASES = PROCESSING | INDEXED_PHASES | RESOLVED_PHASES | {"idle", "running", "absent"}
PUB_FILENAME_RE = re.compile(
    r"^1756[-_](td|um|in)0*(\d{1,4})[-_][^\s]+\.(?:pdf|docx?)$",
    re.IGNORECASE,
)


def _iso(ts: float | None = None) -> str:
    value = time.time() if ts is None else float(ts)
    return datetime.fromtimestamp(value, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load(path: str, default: Any) -> Any:
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return default


def _save(path: str, payload: Any) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    os.replace(tmp, path)


def _safe_rel_folder(folder: str) -> str:
    parts = []
    for part in str(folder or "").replace("\\", "/").split("/"):
        if not part or part in {".", ".."}:
            continue
        cleaned = re.sub(r"[^\w\-\. ]", "_", part).strip()
        if cleaned:
            parts.append(cleaned)
    return "/".join(parts)


def canonical_pub_id(filename: str) -> str | None:
    match = PUB_FILENAME_RE.match(os.path.basename(filename or ""))
    if not match:
        return None
    kind = match.group(1).upper()
    number = int(match.group(2))
    if number >= 100:
        return f"1756-{kind}{number}"
    return f"1756-{kind}{number:03d}"


def _rel_from_path(path: str) -> str:
    real = os.path.realpath(path)
    root = os.path.realpath(LIBRARY_ROOT)
    if real == root or real.startswith(root + os.sep):
        return os.path.relpath(real, root).replace("\\", "/")
    return os.path.basename(path)


def load_ledger() -> dict[str, Any]:
    payload = _load(LEDGER_FILE, {})
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("schema", "smedley.rag_ingest_ledger.v1")
    payload.setdefault("files", {})
    payload.setdefault("recent", [])
    return payload


def write_library_status(
    *,
    status: str,
    last_file: str | None = None,
    last_error: str | None = None,
    clear_error: bool = False,
    current_phase: str | None = None,
    quarantined: int | None = None,
    chunks: int | None = None,
) -> dict[str, Any]:
    current = _load(LIBRARY_STATUS, {})
    if not isinstance(current, dict):
        current = {}
    current["name"] = "library"
    current["status"] = status
    if last_file is not None:
        current["last_file"] = last_file
    if clear_error:
        current["last_error"] = None
    elif last_error is not None:
        current["last_error"] = last_error
    if current_phase is not None:
        current["current_phase"] = current_phase
    if quarantined is not None:
        current["quarantined"] = quarantined
    if chunks is not None:
        current["last_chunks"] = chunks
    current["heartbeat"] = time.time()
    processing = status == "active" or str(current.get("current_phase") or "") in PROCESSING
    failed = status == "error" or str(current.get("current_phase") or "") in {"failed", "quarantined"}
    current["indicator"] = "red" if (processing or failed) else "green"
    current["indicator_state"] = (
        "ACTIVE" if processing else ("ALARM" if failed else "RUNNING")
    )
    _save(LIBRARY_STATUS, current)
    return current


def ocr_sidecar_path(path: str) -> str | None:
    if not path:
        return None
    root, ext = os.path.splitext(path)
    if ext.lower() != ".pdf":
        return None
    return root + ".ocr.txt"


def _hashed_paths(meta: dict[str, Any] | None = None) -> set[str]:
    payload = meta if isinstance(meta, dict) else _load(WATCH_META, {})
    out: set[str] = set()
    for stored in (payload.get("hashes") or {}).values():
        if stored:
            out.add(os.path.realpath(str(stored)))
    return out


def file_sha256(path: str) -> str | None:
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except Exception:
        return None


def is_indexed_via_sidecar(path: str, meta: dict[str, Any] | None = None) -> bool:
    sidecar = ocr_sidecar_path(path)
    if not sidecar:
        return False
    return os.path.realpath(sidecar) in _hashed_paths(meta)


def is_successfully_indexed(path: str, meta: dict[str, Any] | None = None) -> bool:
    if not path:
        return False
    payload = meta if isinstance(meta, dict) else _load(WATCH_META, {})
    real = os.path.realpath(path)
    if real in _hashed_paths(payload):
        return True
    return is_indexed_via_sidecar(real, payload)


def is_actionable_ingest_card(row: dict[str, Any], meta: dict[str, Any] | None = None) -> bool:
    phase = str(row.get("phase") or "")
    if phase in HIDDEN_CARD_PHASES or phase not in ACTIONABLE_PHASES:
        return False
    path = str(row.get("path") or "")
    if is_indexed_via_sidecar(path, meta) or is_successfully_indexed(path, meta):
        return False
    return True


def record_file_event(
    path: str,
    phase: str,
    *,
    reason: str | None = None,
    chunks: int | None = None,
    vectors: int | None = None,
    sha256: str | None = None,
    sidecar_path: str | None = None,
    sidecar_sha256: str | None = None,
    reconciliation_reason: str | None = None,
) -> dict[str, Any]:
    real = os.path.realpath(path) if path else ""
    base = os.path.basename(path or "")
    rel = _rel_from_path(path) if path else ""
    folder = os.path.dirname(rel)
    ledger = load_ledger()
    files = ledger["files"]
    entry = files.get(real) if isinstance(files.get(real), dict) else {}
    now = _iso()
    entry.update(
        {
            "path": real,
            "basename": base,
            "source": rel,
            "folder": folder,
            "pub_id": canonical_pub_id(base),
            "phase": phase,
            "reason": reason,
            "updated_at": now,
        }
    )
    if phase == "detected":
        entry["detected_at"] = now
    elif phase == "queued":
        entry["queued_at"] = now
    elif phase in {"extracting", "indexing"}:
        entry["indexing_at"] = now
    elif phase in INDEXED_PHASES:
        entry["indexed_at"] = now
        if phase == "indexed":
            entry["reason"] = None
    elif phase in RESOLVED_PHASES:
        entry["resolved_at"] = now
        entry["reason"] = None
    elif phase in {"failed", "quarantined"}:
        entry["failed_at"] = now
    if chunks is not None:
        entry["chunks"] = chunks
    if vectors is not None:
        entry["vectors"] = vectors
    if sha256 is not None:
        entry["sha256"] = sha256
    if sidecar_path is not None:
        entry["sidecar_path"] = sidecar_path
    if sidecar_sha256 is not None:
        entry["sidecar_sha256"] = sidecar_sha256
    if reconciliation_reason is not None:
        entry["reconciliation_reason"] = reconciliation_reason
        entry["reconciled_at"] = now
    files[real] = entry
    recent = [row for row in ledger.get("recent") or [] if row.get("path") != real]
    recent.insert(0, dict(entry))
    ledger["recent"] = recent[:40]
    ledger["updated"] = now
    ledger["files"] = files
    _save(LEDGER_FILE, ledger)

    if phase in PROCESSING:
        write_library_status(
            status="active",
            last_file=base,
            clear_error=True,
            current_phase=phase,
        )
    elif phase in INDEXED_PHASES | RESOLVED_PHASES:
        write_library_status(
            status="idle",
            last_file=base,
            clear_error=True,
            current_phase=phase,
            chunks=chunks,
        )
    else:
        write_library_status(
            status="error",
            last_file=base,
            last_error=f"{base}: {reason or phase}",
            current_phase=phase,
        )
    return entry


def quarantine_rows(meta: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    payload = meta if isinstance(meta, dict) else _load(WATCH_META, {})
    out = []
    for path, rec in (payload.get("quarantine") or {}).items():
        if not isinstance(rec, dict):
            rec = {"reason": str(rec)}
        base = os.path.basename(path)
        out.append(
            {
                "path": path,
                "basename": base,
                "source": _rel_from_path(path),
                "folder": os.path.dirname(_rel_from_path(path)),
                "pub_id": canonical_pub_id(base),
                "phase": "quarantined",
                "reason": rec.get("reason") or "quarantined",
                "updated_at": _iso(rec.get("last_seen") or rec.get("first_seen")),
                "chunks": None,
                "vectors": None,
            }
        )
    out.sort(key=lambda row: str(row.get("updated_at") or ""), reverse=True)
    return out


def focus_rows(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    files = ledger.get("files") or {}
    hashed = {}
    meta = _load(WATCH_META, {})
    for digest, path in (meta.get("hashes") or {}).items():
        hashed[os.path.realpath(str(path))] = digest
    rows = []
    folder = os.path.join(LIBRARY_ROOT, "Vendor Data/Allen Bradley/1756")
    for name in FOCUS_FILES:
        path = os.path.join(folder, name)
        real = os.path.realpath(path)
        existing = files.get(real) if isinstance(files.get(real), dict) else {}
        present = os.path.isfile(path)
        indexed = real in hashed
        phase = existing.get("phase")
        if indexed:
            phase = phase if phase in PROCESSING else "indexed"
        elif present and not phase:
            phase = "detected"
        st = os.stat(path) if present else None
        rows.append(
            {
                "path": real,
                "basename": name,
                "source": _rel_from_path(path),
                "folder": "Vendor Data/Allen Bradley/1756",
                "pub_id": canonical_pub_id(name),
                "phase": phase or ("absent" if not present else "detected"),
                "reason": None if indexed else existing.get("reason"),
                "updated_at": existing.get("updated_at") or (_iso(st.st_mtime) if st else None),
                "present": present,
                "indexed": indexed,
                "resolvable": present,
                "chunks": existing.get("chunks"),
                "vectors": existing.get("vectors"),
                "sha256": hashed.get(real),
            }
        )
    return rows


def build_queue(limit: int = 24) -> list[dict[str, Any]]:
    meta = _load(WATCH_META, {})
    if not isinstance(meta, dict):
        meta = {}
    ledger = load_ledger()
    by_path: dict[str, dict[str, Any]] = {}
    for row in quarantine_rows(meta):
        by_path[row["path"]] = row
    for row in ledger.get("recent") or []:
        path = str(row.get("path") or "")
        if path and path not in by_path:
            by_path[path] = row
    rows = [row for row in by_path.values() if is_actionable_ingest_card(row, meta)]

    def sort_key(row: dict[str, Any]) -> tuple:
        return (str(row.get("updated_at") or ""), str(row.get("basename") or ""))

    rows.sort(key=sort_key, reverse=True)
    return rows[:limit]


def build_ingest_status() -> dict[str, Any]:
    status = _load(LIBRARY_STATUS, {})
    if not isinstance(status, dict):
        status = {}
    meta = _load(WATCH_META, {})
    q_rows = quarantine_rows(meta)
    q_count = len(q_rows)
    status["quarantined"] = q_count
    status["quarantine_count"] = q_count
    queue = build_queue()
    status["queue"] = queue
    status["focus"] = focus_rows(load_ledger())
    status["quarantine"] = q_rows
    processing = str(status.get("status") or "") == "active" or str(status.get("current_phase") or "") in PROCESSING
    failed = str(status.get("status") or "") == "error"
    stale = False
    hb = status.get("heartbeat") or 0
    try:
        stale = (time.time() - float(hb)) >= 90
    except Exception:
        stale = True
    if processing:
        indicator, state = "red", "ACTIVE"
    elif stale or failed:
        indicator, state = "red", "ALARM"
    else:
        indicator, state = "green", "RUNNING"
    status["indicator"] = indicator
    status["indicator_state"] = state
    status["hide_idle"] = bool(queue)
    return status


def request_rescan(folder: str) -> dict[str, Any]:
    rel = _safe_rel_folder(folder)
    if not rel:
        raise ValueError("folder required")
    target = os.path.realpath(os.path.join(LIBRARY_ROOT, rel))
    root = os.path.realpath(LIBRARY_ROOT)
    if not target.startswith(root + os.sep) and target != root:
        raise ValueError("folder escapes library root")
    if not os.path.isdir(target):
        raise ValueError("Library folder does not exist: %s" % rel)
    hashed_paths = {
        os.path.realpath(str(path))
        for path in ((_load(WATCH_META, {}) or {}).get("hashes") or {}).values()
    }
    state = _load(WATCH_STATE, {})
    if not isinstance(state, dict):
        state = {}
    marked = []
    for dirpath, _, filenames in os.walk(target):
        for name in filenames:
            if name.startswith(".") or name.startswith("~"):
                continue
            path = os.path.join(dirpath, name)
            ext = os.path.splitext(name)[1].lower()
            if ext not in {".pdf", ".doc", ".docx", ".txt", ".md", ".rtf", ".html", ".htm", ".csv", ".xlsx", ".log"}:
                continue
            real = os.path.realpath(path)
            if real in hashed_paths:
                # Already indexed. Do not yank watch state — that re-grinds the library.
                continue
            state.pop(path, None)
            state.pop(real, None)
            record_file_event(path, "queued")
            marked.append(_rel_from_path(path))
    _save(WATCH_STATE, state)
    if marked:
        write_library_status(
            status="active",
            last_file=os.path.basename(marked[0]),
            clear_error=True,
            current_phase="queued",
        )
    return {"folder": rel, "queued": len(marked), "files": marked[:40], "status": "queued"}


def retry_quarantine(path: str) -> dict[str, Any]:
    real = os.path.realpath(path)
    meta = _load(WATCH_META, {})
    if not isinstance(meta, dict):
        meta = {}
    q = meta.setdefault("quarantine", {})
    if real not in q and path not in q:
        raise ValueError("not quarantined: %s" % os.path.basename(path))
    target = real if os.path.isfile(real) else path
    sha = file_sha256(target) if os.path.isfile(target) else None
    sidecar_ok = is_indexed_via_sidecar(target, meta)
    already_indexed = is_successfully_indexed(target, meta)
    q.pop(real, None)
    q.pop(path, None)
    meta.get("strikes", {}).pop(real, None)
    meta.get("strikes", {}).pop(path, None)
    if sha:
        meta.setdefault("bad_hashes", {}).pop(sha, None)
    _save(WATCH_META, meta)
    if sidecar_ok or already_indexed:
        phase = "indexed_via_sidecar" if sidecar_ok else "indexed"
        record_file_event(
            target,
            phase,
            reason=None,
            sha256=sha,
            sidecar_path=ocr_sidecar_path(target),
            reconciliation_reason="retry-skipped-already-indexed",
        )
        return {
            "path": real,
            "status": phase,
            "queued": False,
            "reason": "already indexed; retry would not re-ingest",
        }
    state = _load(WATCH_STATE, {})
    if isinstance(state, dict):
        state.pop(real, None)
        state.pop(path, None)
        _save(WATCH_STATE, state)
    record_file_event(target, "queued", reason=None)
    return {"path": real, "status": "queued", "queued": True}


def requeue_ingest_source(path: str) -> dict[str, Any]:
    """Requeue one explicit ledger-known detected/failed source.

    Clearing the watch-state entry is what transfers ownership back to the
    watcher.  Already-indexed content is never forced through a duplicate
    pass, and quarantined rows retain their dedicated hash cleanup path.
    """
    real = os.path.realpath(path)
    if not os.path.isfile(real):
        raise ValueError("ingest source file is unavailable")
    ledger = load_ledger()
    row = (ledger.get("files") or {}).get(real)
    if not isinstance(row, dict):
        row = next(
            (
                item
                for item in (ledger.get("files") or {}).values()
                if isinstance(item, dict)
                and os.path.realpath(str(item.get("path") or "")) == real
            ),
            None,
        )
    phase = str((row or {}).get("phase") or "").strip().lower()
    if phase in {"quarantined", "quarantine"}:
        return retry_quarantine(real)
    if phase not in {"detected", "failed", "error", "queued"}:
        raise ValueError("ingest record is not actionable")

    meta = _load(WATCH_META, {})
    if not isinstance(meta, dict):
        meta = {}
    digest = file_sha256(real)
    indexed_path = str((meta.get("hashes") or {}).get(digest) or "") if digest else ""
    if indexed_path and os.path.realpath(indexed_path) != real:
        duplicate_of = _rel_from_path(indexed_path)
        record_file_event(
            real,
            "duplicate",
            reason=None,
            sha256=digest,
            reconciliation_reason=f"duplicate-content:{duplicate_of}",
        )
        return {
            "path": real,
            "status": "duplicate",
            "queued": False,
            "duplicate_of": duplicate_of,
        }
    if indexed_path and os.path.realpath(indexed_path) == real:
        record_file_event(
            real,
            "indexed",
            reason=None,
            sha256=digest,
            reconciliation_reason="retry-skipped-already-indexed",
        )
        return {"path": real, "status": "indexed", "queued": False}

    state = _load(WATCH_STATE, {})
    if not isinstance(state, dict):
        state = {}
    state.pop(real, None)
    state.pop(path, None)
    _save(WATCH_STATE, state)
    record_file_event(real, "queued", reason=None)
    return {"path": real, "status": "queued", "queued": True}


def resolve_ingest_source(path: str) -> dict[str, Any]:
    """Record an operator disposition without deleting or reindexing data."""
    real = os.path.realpath(path)
    if not os.path.isfile(real):
        raise ValueError("ingest source file is unavailable")
    record_file_event(
        real,
        "resolved",
        reason=None,
        reconciliation_reason="operator-resolved",
    )
    return {"path": real, "status": "resolved", "queued": False}
