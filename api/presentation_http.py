"""HTTP handlers for Biggy Presentation recording (desktop MediaRecorder uploads)."""

from __future__ import annotations

import json
import re
from urllib.parse import parse_qs
from pathlib import Path

from api import presentation_store as store

_RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")


def _json(handler, status: int, payload: dict) -> bool:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)
    return True


def _owner_key(handler) -> str:
    """Derive non-secret owner identity from verified session (never persist raw cookie)."""
    from api.auth import is_auth_enabled, parse_cookie, verify_session

    cookie = parse_cookie(handler)
    if is_auth_enabled():
        if not cookie or not verify_session(cookie):
            raise store.PresentationError("unauthenticated", 401)
        material = cookie.split(".", 1)[0]
        return store.derive_owner_key(material)
    if cookie:
        return store.derive_owner_key(cookie.split(".", 1)[0])
    return store.derive_owner_key("presentation-auth-disabled")


def _read_body(handler, max_bytes: int) -> bytes:
    length = int(handler.headers.get("Content-Length") or 0)
    if length < 0 or length > max_bytes:
        raise store.PresentationError("body_too_large", 413)
    if length == 0:
        return b""
    data = handler.rfile.read(length)
    if len(data) != length:
        raise store.PresentationError("body_truncated", 400)
    return data


def _read_json(handler, max_bytes: int = 65536) -> dict:
    raw = _read_body(handler, max_bytes)
    if not raw:
        return {}
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise store.PresentationError("invalid_json", 400) from exc
    if not isinstance(data, dict):
        raise store.PresentationError("invalid_json", 400)
    return data


def _send_file_range(handler, fpath, meta: dict) -> bool:
    size = fpath.stat().st_size
    ctype = meta.get("mime") or "video/webm"
    filename = Path(str(meta.get("filename") or "recording.webm")).name
    if "/" in filename or "\\" in filename or filename in {".", ".."}:
        filename = "recording.webm"
    range_hdr = (handler.headers.get("Range") or "").strip()
    if not range_hdr:
        handler.send_response(200)
        handler.send_header("Content-Type", ctype)
        handler.send_header("Content-Length", str(size))
        handler.send_header("Accept-Ranges", "bytes")
        handler.send_header("Cache-Control", "private, no-store")
        handler.send_header("Content-Disposition", f'inline; filename="{filename}"')
        handler.end_headers()
        with open(fpath, "rb") as fh:
            while True:
                block = fh.read(65536)
                if not block:
                    break
                handler.wfile.write(block)
        return True

    m = _RANGE_RE.fullmatch(range_hdr)
    if not m:
        raise store.PresentationError("invalid_range", 416)
    start_s, end_s = m.group(1), m.group(2)
    start = int(start_s) if start_s else 0
    end = int(end_s) if end_s else size - 1
    if start < 0 or end < start or start >= size:
        handler.send_response(416)
        handler.send_header("Content-Range", f"bytes */{size}")
        handler.send_header("Content-Length", "0")
        handler.end_headers()
        return True
    end = min(end, size - 1)
    length = end - start + 1
    handler.send_response(206)
    handler.send_header("Content-Type", ctype)
    handler.send_header("Content-Length", str(length))
    handler.send_header("Content-Range", f"bytes {start}-{end}/{size}")
    handler.send_header("Accept-Ranges", "bytes")
    handler.send_header("Cache-Control", "private, no-store")
    handler.send_header("Content-Disposition", f'inline; filename="{filename}"')
    handler.end_headers()
    with open(fpath, "rb") as fh:
        fh.seek(start)
        remaining = length
        while remaining > 0:
            block = fh.read(min(65536, remaining))
            if not block:
                break
            handler.wfile.write(block)
            remaining -= len(block)
    return True


def handle_presentation(handler, parsed, method: str) -> bool | None:
    path = str(getattr(parsed, "path", "") or "")
    if not path.startswith("/api/presentation"):
        return False

    try:
        if method == "GET" and path == "/api/presentation/status":
            _owner_key(handler)
            status = store.share_status()
            status["tablet_supported"] = False
            status["desktop_only"] = True
            status["audio_default"] = False
            return _json(handler, 200, status)

        if method == "POST" and path == "/api/presentation/session/start":
            key = _owner_key(handler)
            _read_json(handler)
            return _json(handler, 200, store.start_session(key))

        if method == "GET" and path.startswith("/api/presentation/session/") and path.endswith("/recovery"):
            key = _owner_key(handler)
            session_id = path[len("/api/presentation/session/") : -len("/recovery")]
            return _json(handler, 200, store.session_recovery_status(key, session_id))

        if method == "POST" and path.startswith("/api/presentation/session/") and path.endswith("/chunk"):
            key = _owner_key(handler)
            session_id = path[len("/api/presentation/session/") : -len("/chunk")]
            qs = parse_qs(str(getattr(parsed, "query", "") or ""))
            try:
                seq = int((qs.get("seq") or ["-1"])[0])
            except ValueError as exc:
                raise store.PresentationError("invalid_chunk_sequence", 400) from exc
            sha = (handler.headers.get("X-Presentation-Chunk-SHA256") or "").strip() or None
            data = _read_body(handler, store.MAX_CHUNK_BYTES)
            return _json(
                handler,
                200,
                store.receive_chunk(key, session_id, seq, data, content_sha256=sha),
            )

        if method == "POST" and path.startswith("/api/presentation/session/") and path.endswith("/finalize"):
            key = _owner_key(handler)
            session_id = path[len("/api/presentation/session/") : -len("/finalize")]
            body = _read_json(handler)
            return _json(
                handler,
                200,
                store.finalize_session(
                    key,
                    session_id,
                    mime=str(body.get("mime") or ""),
                    duration_ms=int(body.get("duration_ms") or 0),
                    total_chunks=int(body.get("total_chunks") or 0),
                    title=str(body.get("title") or "") or None,
                    content_sha256=str(body.get("content_sha256") or "") or None,
                ),
            )

        if method == "POST" and path.startswith("/api/presentation/session/") and path.endswith("/abort"):
            key = _owner_key(handler)
            session_id = path[len("/api/presentation/session/") : -len("/abort")]
            body = _read_json(handler)
            return _json(
                handler,
                200,
                store.mark_interrupted(key, session_id, reason=str(body.get("reason") or "abort")),
            )

        if method == "GET" and path.startswith("/api/presentation/file/"):
            key = _owner_key(handler)
            file_id = path[len("/api/presentation/file/") :].strip("/")
            if "/" in file_id or ".." in file_id:
                raise store.PresentationError("path_traversal_rejected", 400)
            fpath, meta = store.open_file(key, file_id)
            return _send_file_range(handler, fpath, meta)

    except store.PresentationError as exc:
        return _json(handler, exc.status, {"error": exc.code, "detail": exc.detail})
    except Exception:
        return _json(handler, 500, {"error": "presentation_internal_error"})

    return _json(handler, 404, {"error": "not_found"})
