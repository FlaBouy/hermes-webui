"""Owner-scoped Presentation video storage on the configured data share.

Env (Atlas configures private runtime; no personal paths in tracked defaults):
  BIGGY_PRESENTATION_DIR         Absolute directory for finalized videos
  BIGGY_PRESENTATION_MOUNT_ROOT  Parent path that must be an actual mount

Fail closed when share is unavailable — never mkdir a local shadow store.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SESSION_ID_RE = re.compile(r"^prs_[A-Za-z0-9_-]{16,64}$")
FILE_ID_RE = re.compile(r"^prv_[A-Za-z0-9_-]{8,64}$")
SAFE_OWNER_RE = re.compile(r"^own_[a-f0-9]{32}$")
# Per-recording dir under share: presentation-YYYYMMDD-HHMMSS-xxxxxxxx/recording.ext
SAFE_REL_RECORDING_RE = re.compile(
    r"^presentation-\d{8}-\d{6}-[A-Za-z0-9_-]{8}/recording\.(webm|mp4)$"
)

MAX_CHUNK_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 500 * 1024 * 1024
MAX_DURATION_MS = 30 * 60 * 1000
MAX_CHUNKS = 4096
MAX_SESSIONS_PER_OWNER = 2
SESSION_TTL_SEC = 2 * 60 * 60
MIN_MEDIA_BYTES = 256

EBML_MAGIC = b"\x1a\x45\xdf\xa3"
WEBM_SEGMENT = b"\x18\x53\x80\x67"
WEBM_CLUSTER = b"\x1f\x43\xb6\x75"

ALLOWED_MIME = frozenset(
    {
        "video/webm",
        "video/mp4",
        "video/webm;codecs=vp8",
        "video/webm;codecs=vp9",
        "video/webm;codecs=vp8,opus",
        "video/webm;codecs=vp9,opus",
        "video/mp4;codecs=avc1",
        "video/mp4;codecs=h264",
    }
)


class PresentationError(Exception):
    def __init__(self, code: str, status: int = 400, detail: str | None = None):
        self.code = code
        self.status = status
        self.detail = detail or code
        super().__init__(self.detail)


@dataclass
class _Session:
    session_id: str
    owner_key: str
    created_at: float
    expires_at: float
    partial_dir: Path
    next_seq_expected: int = 0
    received: dict[int, dict[str, Any]] = field(default_factory=dict)
    total_bytes: int = 0
    mime: str = ""
    state: str = "recording"  # recording | interrupted | finalized | failed
    finalized_path: Path | None = None
    file_id: str | None = None
    duration_ms: int = 0
    content_sha256: str = ""
    lock: threading.Lock = field(default_factory=threading.Lock)


_lock = threading.Lock()
_sessions: dict[str, _Session] = {}
_files: dict[str, dict[str, Any]] = {}
_index_loaded = False


def reset_for_tests() -> None:
    global _index_loaded
    with _lock:
        _sessions.clear()
        _files.clear()
        _index_loaded = False


def derive_owner_key(session_material: str) -> str:
    """Non-secret derived owner identity — never persist raw cookie/token."""
    digest = hashlib.sha256(
        f"biggy-presentation-owner-v1:{session_material}".encode("utf-8")
    ).hexdigest()[:32]
    return f"own_{digest}"


def _env_path(name: str) -> Path | None:
    raw = str(os.environ.get(name) or "").strip()
    if not raw:
        return None
    return Path(raw).expanduser()


def _is_mount_root(path: Path) -> bool:
    try:
        return bool(os.path.ismount(str(path)))
    except OSError:
        return False


def _confined(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    root_res = root.resolve()
    if resolved != root_res and root_res not in resolved.parents:
        raise PresentationError("path_traversal_rejected", 400)
    return resolved


def share_status() -> dict[str, Any]:
    """Report share readiness: configured mount + writable dest (no leftover-dir stand-in)."""
    mount = _env_path("BIGGY_PRESENTATION_MOUNT_ROOT")
    dest = _env_path("BIGGY_PRESENTATION_DIR")
    out: dict[str, Any] = {
        "configured": bool(mount and dest),
        "ready": False,
        "mount_root_set": bool(mount),
        "presentation_dir_set": bool(dest),
        "mount_verified": False,
        "error": None,
        "max_chunk_bytes": MAX_CHUNK_BYTES,
        "max_total_bytes": MAX_TOTAL_BYTES,
        "max_duration_ms": MAX_DURATION_MS,
        "max_chunks": MAX_CHUNKS,
    }
    if not mount or not dest:
        out["error"] = "presentation_share_unconfigured"
        return out
    probe: Path | None = None
    try:
        if not mount.exists() or not mount.is_dir():
            out["error"] = "presentation_mount_unavailable"
            return out
        if not _is_mount_root(mount):
            # Leftover directory must not stand in for a mounted share.
            out["error"] = "presentation_mount_not_mounted"
            return out
        out["mount_verified"] = True
        if not dest.exists() or not dest.is_dir():
            out["error"] = "presentation_dir_unavailable"
            return out
        dest_res = dest.resolve()
        mount_res = mount.resolve()
        if mount_res != dest_res and mount_res not in dest_res.parents:
            out["error"] = "presentation_dir_outside_mount"
            return out
        probe_parent = dest / ".partial"
        try:
            probe_parent.mkdir(mode=0o700, exist_ok=True)
        except OSError:
            out["error"] = "presentation_share_not_writable"
            return out
        # Unique exclusive probe — no pid-only race.
        probe = probe_parent / f".write_probe_{uuid.uuid4().hex}"
        try:
            fd = os.open(str(probe), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            try:
                os.write(fd, b"ok")
            finally:
                os.close(fd)
        except OSError:
            out["error"] = "presentation_share_not_writable"
            return out
        out["ready"] = True
        return out
    except OSError:
        out["error"] = "presentation_share_unavailable"
        return out
    finally:
        if probe is not None:
            try:
                if probe.exists():
                    probe.unlink()
            except OSError:
                pass


def require_ready_share() -> tuple[Path, Path]:
    status = share_status()
    if not status["ready"]:
        raise PresentationError(status.get("error") or "presentation_share_unavailable", 503)
    mount = _env_path("BIGGY_PRESENTATION_MOUNT_ROOT")
    dest = _env_path("BIGGY_PRESENTATION_DIR")
    assert mount is not None and dest is not None
    return mount.resolve(), dest.resolve()


def _index_dir(root: Path) -> Path:
    path = _confined(root / ".index", root)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def _write_index(root: Path, meta: dict[str, Any]) -> None:
    idx = _index_dir(root)
    file_id = str(meta["file_id"])
    path = _confined(idx / f"{file_id}.json", idx)
    tmp = path.with_suffix(".json.tmp")
    # Never persist raw cookie material — owner_key is already derived.
    safe = {
        k: meta[k]
        for k in (
            "file_id",
            "filename",
            "title",
            "mime",
            "bytes",
            "duration_ms",
            "session_id",
            "owner_key",
            "play_url",
            "state",
            "content_sha256",
            "recovery",
        )
        if k in meta
    }
    tmp.write_text(json.dumps(safe, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _load_index_unlocked(root: Path) -> None:
    global _index_loaded
    idx = root / ".index"
    if not idx.is_dir():
        _index_loaded = True
        return
    for path in idx.glob("prv_*.json"):
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(meta, dict):
            continue
        fid = str(meta.get("file_id") or "")
        if FILE_ID_RE.match(fid) and meta.get("owner_key"):
            meta.setdefault("recovery", "index_reloaded")
            _files[fid] = meta
    _index_loaded = True


def _ensure_index(root: Path) -> None:
    with _lock:
        if not _index_loaded:
            _load_index_unlocked(root)


def _owner_dir(root: Path, owner_key: str) -> Path:
    if not SAFE_OWNER_RE.match(owner_key):
        raise PresentationError("invalid_owner", 400)
    path = _confined(root / ".partial" / owner_key, root)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def _purge_expired_unlocked(now: float) -> None:
    dead = [sid for sid, s in _sessions.items() if s.expires_at < now and s.state != "finalized"]
    for sid in dead:
        sess = _sessions.pop(sid, None)
        if sess and sess.state != "finalized":
            sess.state = "interrupted"
            _write_meta(sess)


def _write_meta(sess: _Session) -> None:
    meta = {
        "session_id": sess.session_id,
        "owner_key": sess.owner_key,
        "state": sess.state,
        "next_seq_expected": sess.next_seq_expected,
        "total_bytes": sess.total_bytes,
        "mime": sess.mime,
        "duration_ms": sess.duration_ms,
        "file_id": sess.file_id,
        "finalized_path": str(sess.finalized_path) if sess.finalized_path else None,
        "content_sha256": sess.content_sha256,
        "chunks": {str(k): v for k, v in sess.received.items()},
        "updated_at": time.time(),
    }
    path = sess.partial_dir / "meta.json"
    tmp = sess.partial_dir / "meta.json.tmp"
    tmp.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _reload_session_from_disk(owner_key: str, session_id: str) -> _Session | None:
    """Recover interrupted session metadata from share after process restart."""
    try:
        _, root = require_ready_share()
    except PresentationError:
        return None
    meta_path = root / ".partial" / owner_key / session_id / "meta.json"
    try:
        meta_path = _confined(meta_path, root)
        raw = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, PresentationError):
        return None
    if not isinstance(raw, dict) or raw.get("owner_key") != owner_key:
        return None
    sess = _Session(
        session_id=session_id,
        owner_key=owner_key,
        created_at=time.monotonic(),
        expires_at=time.monotonic() + SESSION_TTL_SEC,
        partial_dir=meta_path.parent,
        next_seq_expected=int(raw.get("next_seq_expected") or 0),
        received={int(k): v for k, v in (raw.get("chunks") or {}).items()},
        total_bytes=int(raw.get("total_bytes") or 0),
        mime=str(raw.get("mime") or ""),
        state=str(raw.get("state") or "interrupted"),
        file_id=raw.get("file_id"),
        duration_ms=int(raw.get("duration_ms") or 0),
        content_sha256=str(raw.get("content_sha256") or ""),
    )
    if raw.get("finalized_path"):
        sess.finalized_path = Path(str(raw["finalized_path"]))
    return sess


def start_session(owner_key: str) -> dict[str, Any]:
    if not SAFE_OWNER_RE.match(owner_key):
        raise PresentationError("invalid_owner", 400)
    _, root = require_ready_share()
    _ensure_index(root)
    now = time.monotonic()
    with _lock:
        _purge_expired_unlocked(now)
        owned = [s for s in _sessions.values() if s.owner_key == owner_key and s.state == "recording"]
        if len(owned) >= MAX_SESSIONS_PER_OWNER:
            raise PresentationError("too_many_presentation_sessions", 429)
        session_id = "prs_" + secrets.token_urlsafe(18)
        owner_root = _owner_dir(root, owner_key)
        partial = _confined(owner_root / session_id, root)
        partial.mkdir(parents=True, exist_ok=False, mode=0o700)
        sess = _Session(
            session_id=session_id,
            owner_key=owner_key,
            created_at=now,
            expires_at=now + SESSION_TTL_SEC,
            partial_dir=partial,
        )
        _sessions[session_id] = sess
        _write_meta(sess)
    return {
        "session_id": session_id,
        "max_chunk_bytes": MAX_CHUNK_BYTES,
        "max_total_bytes": MAX_TOTAL_BYTES,
        "max_duration_ms": MAX_DURATION_MS,
        "max_chunks": MAX_CHUNKS,
        "audio_default": False,
        "formats_preferred": ["video/mp4", "video/webm"],
    }


def _get_session(owner_key: str, session_id: str) -> _Session:
    if not SESSION_ID_RE.match(session_id or ""):
        raise PresentationError("invalid_session_id", 400)
    with _lock:
        sess = _sessions.get(session_id)
        if not sess:
            recovered = _reload_session_from_disk(owner_key, session_id)
            if recovered:
                _sessions[session_id] = recovered
                sess = recovered
            else:
                raise PresentationError("session_not_found", 404)
        if sess.owner_key != owner_key:
            raise PresentationError("forbidden", 403)
        if time.monotonic() > sess.expires_at and sess.state == "recording":
            sess.state = "interrupted"
            _write_meta(sess)
            raise PresentationError("session_expired", 410)
        return sess


def receive_chunk(
    owner_key: str,
    session_id: str,
    seq: int,
    data: bytes,
    *,
    content_sha256: str | None = None,
) -> dict[str, Any]:
    require_ready_share()
    if seq < 0 or seq >= MAX_CHUNKS:
        raise PresentationError("invalid_chunk_sequence", 400)
    if not data:
        raise PresentationError("empty_chunk", 400)
    if len(data) > MAX_CHUNK_BYTES:
        raise PresentationError("chunk_too_large", 413)
    digest = hashlib.sha256(data).hexdigest()
    if content_sha256 and content_sha256.lower() != digest:
        raise PresentationError("chunk_checksum_mismatch", 400)

    sess = _get_session(owner_key, session_id)
    with sess.lock:
        if sess.state != "recording":
            raise PresentationError(f"session_{sess.state}", 409)
        # Re-verify confinement against live share root.
        _, root = require_ready_share()
        _confined(sess.partial_dir, root)

        prior = sess.received.get(seq)
        if prior is not None:
            if prior.get("sha256") == digest and prior.get("bytes") == len(data):
                return {
                    "session_id": session_id,
                    "seq": seq,
                    "idempotent": True,
                    "total_bytes": sess.total_bytes,
                    "next_seq_expected": sess.next_seq_expected,
                }
            raise PresentationError("chunk_conflict", 409)
        if seq != sess.next_seq_expected:
            raise PresentationError(
                "chunk_out_of_order",
                409,
                detail=f"expected_seq={sess.next_seq_expected} got={seq}",
            )
        if sess.total_bytes + len(data) > MAX_TOTAL_BYTES:
            raise PresentationError("recording_too_large", 413)

        chunk_path = _confined(sess.partial_dir / f"chunk_{seq:06d}.bin", root)
        tmp = _confined(sess.partial_dir / f"chunk_{seq:06d}.bin.tmp", root)
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, chunk_path)
        sess.received[seq] = {"sha256": digest, "bytes": len(data)}
        sess.total_bytes += len(data)
        sess.next_seq_expected = seq + 1
        sess.expires_at = time.monotonic() + SESSION_TTL_SEC
        _write_meta(sess)
        return {
            "session_id": session_id,
            "seq": seq,
            "idempotent": False,
            "total_bytes": sess.total_bytes,
            "next_seq_expected": sess.next_seq_expected,
        }


def _ext_for_mime(mime: str) -> str:
    base = (mime or "").split(";")[0].strip().lower()
    if base == "video/mp4":
        return ".mp4"
    return ".webm"


MEDIA_HEAD_BYTES = 512 * 1024


def _read_bounded_head(path: Path, limit: int = MEDIA_HEAD_BYTES) -> bytes:
    with open(path, "rb") as fh:
        return fh.read(limit)


def validate_media_bytes(data: bytes, mime: str) -> None:
    """Container-structure check on bytes/prefix (not a full decoder proof).

    WebM must *start* with EBML; Segment then Cluster must appear in order.
    Rejects arbitrary payloads that merely contain those signatures mid-stream.
    MP4 must begin with a plausible size + ``ftyp`` brand box.
    """
    if len(data) < 16:
        raise PresentationError("media_too_small", 400)
    base = (mime or "").split(";")[0].strip().lower()
    if base == "video/webm":
        if not data.startswith(EBML_MAGIC):
            raise PresentationError("invalid_webm_magic", 400)
        seg_at = data.find(WEBM_SEGMENT)
        if seg_at < 4:
            raise PresentationError("invalid_webm_segment", 400)
        clu_at = data.find(WEBM_CLUSTER, seg_at + 4)
        if clu_at < 0:
            raise PresentationError("invalid_webm_no_cluster", 400)
        return
    if base == "video/mp4":
        if len(data) < 16 or data[4:8] != b"ftyp":
            raise PresentationError("invalid_mp4_ftyp", 400)
        box_size = int.from_bytes(data[0:4], "big")
        if box_size not in (0, 1) and (box_size < 16 or box_size > 1024 * 1024):
            raise PresentationError("invalid_mp4_ftyp_size", 400)
        brand = data[8:12]
        if brand == b"\x00\x00\x00\x00":
            raise PresentationError("invalid_mp4_brand", 400)
        return
    raise PresentationError("unsupported_mime", 400)


def validate_media_file(path: Path, mime: str, *, expected_bytes: int) -> None:
    """Stream-safe validation: full-file stat + bounded head only (no full read)."""
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise PresentationError("media_stat_failed", 400, detail=str(exc)) from exc
    if size < MIN_MEDIA_BYTES:
        raise PresentationError("media_too_small", 400)
    if expected_bytes and size != expected_bytes:
        raise PresentationError("bytecount_mismatch", 409)
    head = _read_bounded_head(path)
    validate_media_bytes(head, mime)


def _meta_from_finalized_session(
    sess: _Session,
    *,
    owner_key: str,
    mime_n: str,
    title: str | None,
    root: Path,
) -> dict[str, Any]:
    final_path = sess.finalized_path
    assert final_path is not None and sess.file_id
    try:
        rel = final_path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise PresentationError("path_traversal_rejected", 400) from exc
    if not SAFE_REL_RECORDING_RE.match(rel):
        raise PresentationError("invalid_recording_path", 500)
    label = (title or Path(rel).name).strip()[:200] or Path(rel).name
    return {
        "file_id": sess.file_id,
        "filename": rel,
        "title": label,
        "mime": mime_n.split(";")[0],
        "bytes": final_path.stat().st_size if final_path.is_file() else int(sess.total_bytes),
        "duration_ms": int(sess.duration_ms),
        "session_id": sess.session_id,
        "owner_key": owner_key,
        "play_url": f"/api/presentation/file/{sess.file_id}",
        "state": "saved",
        "content_sha256": sess.content_sha256,
        "recovery": "rebuilt_index",
    }


def _write_all(fd: int, data: bytes) -> None:
    """Write buffer fully — os.write may return short counts on SMB."""
    view = memoryview(data)
    while len(view):
        n = os.write(fd, view)
        if n <= 0:
            raise OSError("short_write_zero")
        view = view[n:]


def _copy_file_fd(src: Path, fd: int) -> int:
    written = 0
    with open(src, "rb") as inp:
        while True:
            block = inp.read(65536)
            if not block:
                break
            _write_all(fd, block)
            written += len(block)
    return written


def _publish_in_recording_dir(
    *,
    root: Path,
    src: Path,
    stamp: str,
    file_id: str,
    ext: str,
    expected_bytes: int,
) -> tuple[Path, str]:
    """Exclusive per-recording directory + staged partial + rename to final.

    Production macOS SMB rejects hardlinks (errno 45). Never write incomplete
    bytes to the final recording name. Staging uses ``recording{ext}.partial``;
    only a successful same-directory rename publishes ``recording{ext}``.
    """
    dir_name = f"presentation-{stamp}-{file_id[4:12]}"
    pub_dir = _confined(root / dir_name, root)
    try:
        os.mkdir(str(pub_dir), 0o755)
    except FileExistsError as exc:
        raise PresentationError("final_name_collision", 409) from exc
    except OSError as exc:
        raise PresentationError("publish_failed", 500, detail=str(exc)) from exc

    staging = _confined(pub_dir / f"recording{ext}.partial", root)
    final_path = _confined(pub_dir / f"recording{ext}", root)
    rel = f"{dir_name}/recording{ext}"
    if not SAFE_REL_RECORDING_RE.match(rel):
        raise PresentationError("invalid_recording_path", 500)

    fd = -1
    try:
        if final_path.exists():
            raise PresentationError("final_name_collision", 409)
        fd = os.open(str(staging), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        written = _copy_file_fd(src, fd)
        try:
            os.fsync(fd)
        except OSError:
            # Some SMB mounts reject fsync — size check below still required.
            pass
        os.close(fd)
        fd = -1
        staged_size = staging.stat().st_size
        if written != expected_bytes or staged_size != expected_bytes:
            raise PresentationError(
                "publish_bytecount_mismatch",
                500,
                detail=f"written={written} staged={staged_size} expected={expected_bytes}",
            )
        if final_path.exists():
            raise PresentationError("final_name_collision", 409)
        # Same-directory rename: final name appears only when content is complete.
        os.rename(str(staging), str(final_path))
        if not final_path.is_file() or final_path.stat().st_size != expected_bytes:
            raise PresentationError("publish_verify_failed", 500)
        return final_path, rel
    except PresentationError:
        # Leave .partial for recovery when present; never leave a final name half-written.
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
            fd = -1
        if final_path.exists() and staging.exists():
            # Rename did not complete cleanly — prefer keeping partial, remove bad final.
            try:
                final_path.unlink()
            except OSError:
                pass
        raise
    except OSError as exc:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        raise PresentationError("publish_failed", 500, detail=str(exc)) from exc


def finalize_session(
    owner_key: str,
    session_id: str,
    *,
    mime: str,
    duration_ms: int,
    total_chunks: int,
    title: str | None = None,
    content_sha256: str | None = None,
) -> dict[str, Any]:
    mime_n = (mime or "").strip().lower()
    if mime_n not in ALLOWED_MIME and mime_n.split(";")[0] not in {"video/webm", "video/mp4"}:
        raise PresentationError("unsupported_mime", 400)
    if duration_ms < 1:
        raise PresentationError("invalid_duration", 400)
    if duration_ms > MAX_DURATION_MS:
        raise PresentationError("duration_exceeded", 400)
    if total_chunks < 1:
        raise PresentationError("no_chunks", 400)

    sess = _get_session(owner_key, session_id)
    _, root = require_ready_share()
    _ensure_index(root)
    with sess.lock:
        if sess.state == "finalized" and sess.file_id:
            meta = _files.get(sess.file_id)
            if not meta:
                _load_index_unlocked(root)
                meta = _files.get(sess.file_id)
            if meta:
                return dict(meta)
            # File published but index missing — rebuild idempotently.
            if sess.finalized_path and sess.finalized_path.is_file():
                meta = _meta_from_finalized_session(
                    sess,
                    owner_key=owner_key,
                    mime_n=mime_n or sess.mime,
                    title=title,
                    root=root,
                )
                with _lock:
                    _files[sess.file_id] = meta
                _write_index(root, meta)
                return dict(meta)
            raise PresentationError("finalized_index_missing", 500)

        if sess.state not in {"recording", "interrupted"}:
            raise PresentationError(f"session_{sess.state}", 409)
        if total_chunks != sess.next_seq_expected or len(sess.received) != total_chunks:
            sess.state = "interrupted"
            _write_meta(sess)
            raise PresentationError(
                "incomplete_chunks",
                409,
                detail=f"have={len(sess.received)} expected={total_chunks}",
            )
        if sess.total_bytes < MIN_MEDIA_BYTES:
            sess.state = "interrupted"
            _write_meta(sess)
            raise PresentationError("empty_recording", 400)

        file_id = "prv_" + secrets.token_urlsafe(12)
        ext = _ext_for_mime(mime_n)
        stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())

        assembled = _confined(sess.partial_dir / f"assembled{ext}", root)
        hasher = hashlib.sha256()
        written = 0
        with open(assembled, "wb") as out:
            for i in range(total_chunks):
                chunk = _confined(sess.partial_dir / f"chunk_{i:06d}.bin", root)
                if not chunk.is_file():
                    sess.state = "interrupted"
                    _write_meta(sess)
                    raise PresentationError("missing_chunk_file", 409)
                expected = sess.received[i]["sha256"]
                chunk_hasher = hashlib.sha256()
                with open(chunk, "rb") as inp:
                    while True:
                        block = inp.read(65536)
                        if not block:
                            break
                        chunk_hasher.update(block)
                        hasher.update(block)
                        out.write(block)
                        written += len(block)
                if chunk_hasher.hexdigest() != expected:
                    sess.state = "interrupted"
                    _write_meta(sess)
                    raise PresentationError("chunk_checksum_mismatch", 409)

        assembled_size = assembled.stat().st_size
        if assembled_size != sess.total_bytes or written != sess.total_bytes:
            sess.state = "interrupted"
            _write_meta(sess)
            raise PresentationError("bytecount_mismatch", 409)
        digest = hasher.hexdigest()
        if content_sha256 and content_sha256.lower() != digest:
            sess.state = "interrupted"
            _write_meta(sess)
            raise PresentationError("content_checksum_mismatch", 400)
        try:
            validate_media_file(
                assembled, mime_n.split(";")[0], expected_bytes=sess.total_bytes
            )
        except PresentationError:
            sess.state = "interrupted"
            _write_meta(sess)
            raise

        try:
            final_path, rel = _publish_in_recording_dir(
                root=root,
                src=assembled,
                stamp=stamp,
                file_id=file_id,
                ext=ext,
                expected_bytes=sess.total_bytes,
            )
        except PresentationError:
            sess.state = "interrupted"
            _write_meta(sess)
            raise
        finally:
            try:
                assembled.unlink(missing_ok=True)
            except OSError:
                pass

        # Mark finalized on disk before index so a crash mid-index is recoverable.
        sess.state = "finalized"
        sess.mime = mime_n
        sess.duration_ms = int(duration_ms)
        sess.file_id = file_id
        sess.finalized_path = final_path
        sess.content_sha256 = digest
        _write_meta(sess)

        label = (title or Path(rel).name).strip()[:200] or Path(rel).name
        meta = {
            "file_id": file_id,
            "filename": rel,
            "title": label,
            "mime": mime_n.split(";")[0],
            "bytes": final_path.stat().st_size,
            "duration_ms": int(duration_ms),
            "session_id": session_id,
            "owner_key": owner_key,
            "play_url": f"/api/presentation/file/{file_id}",
            "state": "saved",
            "content_sha256": digest,
            "recovery": "live",
        }
        with _lock:
            _files[file_id] = meta
        try:
            _write_index(root, meta)
        except OSError:
            # Final file exists and session meta is finalized — retry rebuilds index.
            meta = dict(meta)
            meta["recovery"] = "index_write_pending"
        return dict(meta)


def mark_interrupted(owner_key: str, session_id: str, reason: str = "client_stop") -> dict[str, Any]:
    sess = _get_session(owner_key, session_id)
    with sess.lock:
        if sess.state == "finalized":
            return {"session_id": session_id, "state": "finalized", "file_id": sess.file_id, "saved": True}
        sess.state = "interrupted"
        _write_meta(sess)
        return {
            "session_id": session_id,
            "state": "interrupted",
            "reason": reason,
            "total_bytes": sess.total_bytes,
            "chunks": len(sess.received),
            "saved": False,
            "message": "Recording interrupted — partial retained; not marked saved.",
        }


def get_file_meta(owner_key: str, file_id: str) -> dict[str, Any]:
    if not FILE_ID_RE.match(file_id or ""):
        raise PresentationError("invalid_file_id", 400)
    _, root = require_ready_share()
    _ensure_index(root)
    with _lock:
        meta = _files.get(file_id)
        if not meta:
            _load_index_unlocked(root)
            meta = _files.get(file_id)
    if not meta:
        raise PresentationError("file_not_found", 404)
    if meta.get("owner_key") != owner_key:
        raise PresentationError("forbidden", 403)
    return dict(meta)


def open_file(owner_key: str, file_id: str) -> tuple[Path, dict[str, Any]]:
    meta = get_file_meta(owner_key, file_id)
    _, root = require_ready_share()
    rel = str(meta.get("filename") or "")
    if not SAFE_REL_RECORDING_RE.match(rel):
        raise PresentationError("invalid_recording_path", 400)
    path = _confined(root / rel, root)
    if not path.is_file() or path.stat().st_size < 1:
        raise PresentationError("file_missing", 404)
    return path, meta


def session_recovery_status(owner_key: str, session_id: str) -> dict[str, Any]:
    """Honest recovery status for interrupted uploads after restart."""
    if not SESSION_ID_RE.match(session_id or ""):
        raise PresentationError("invalid_session_id", 400)
    with _lock:
        sess = _sessions.get(session_id)
    if not sess:
        sess = _reload_session_from_disk(owner_key, session_id)
        if sess:
            with _lock:
                _sessions[session_id] = sess
    if not sess or sess.owner_key != owner_key:
        raise PresentationError("session_not_found", 404)
    return {
        "session_id": session_id,
        "state": sess.state,
        "saved": sess.state == "finalized",
        "total_bytes": sess.total_bytes,
        "chunks": len(sess.received),
        "file_id": sess.file_id,
        "recovery": "memory" if session_id in _sessions else "disk",
    }
