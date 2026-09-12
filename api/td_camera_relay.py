"""Hermes same-origin proxy to the existing ThunderDome→Smedley camera service.

Upstream (verified transport, not owned by this module):
  http://127.0.0.1:18765  (Smedley loopback reverse-SSH from ThunderDome)
  Bearer token from ~/.config/td-camera/token (server-side only; never URL/logs)
  GET /health     — no camera open
  GET /snapshot.jpg — 640x480 JPEG (opens camera on demand)
  GET /stream.mjpg — ~5 fps multipart (unused; snapshot-poll preferred)

GUI auth + CSRF-gated view leases: page-load health cannot activate the camera.
Virtual backdrop is viewer-side only; transport stays raw.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import secrets
import struct
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

UPSTREAM_BASE = "http://127.0.0.1:18765"
TOKEN_PATH = Path.home() / ".config" / "td-camera" / "token"
MAX_JPEG_BYTES = 180_000
MAX_WIDTH = 640
MAX_HEIGHT = 480
MIN_FRAME_INTERVAL_SEC = 0.18  # ~5 fps ceiling aligned with native service
VIEW_LEASE_TTL_SEC = 45.0
UPSTREAM_TIMEOUT_SEC = 8.0
MAX_UPSTREAM_SNAPSHOT_INFLIGHT = 2
MAX_LEASES_PER_OWNER = 4
SOURCE_DEVICE = "Logitech HD Pro Webcam C920"
SOURCE_HOST = "thunderdome"
ASSOCIATION_LABEL = (
    "ThunderDome · Logitech C920 (verified native transport via Smedley loopback :18765)"
)
VENDOR_REL = "static/td-camera/vendor/mediapipe-selfie-segmentation-0.1.1675465747"
PRIVACY_NOTE = (
    "Raw transport is private TD→Smedley→authorized Hermes viewer. "
    "Virtual background affects display/output only, not the upstream feed."
)
# Same Hermes session cookie may Start multiple independent leases (tabs).
# Stop(lease_id) ends only that lease — tab A cannot silently stop tab B.
MULTI_VIEWER_POLICY = (
    "independent_view_leases_per_start; stop_by_lease_id_only; "
    "same_session_tabs_do_not_share_one_lease"
)
NATIVE_IDLE_RELEASE_SEC = 10

_ROOT = Path(__file__).resolve().parents[1]
_lock = threading.RLock()

_token_override: str | None = None
_upstream_override: str | None = None
_fetch_override = None


@dataclass
class _ViewLease:
    lease_id: str
    owner_key: str
    expires_at: float
    created_at: float
    last_frame_at: float = 0.0
    reserved_until: float = 0.0
    inflight: bool = False


_leases: dict[str, _ViewLease] = {}  # lease_id -> lease
_last_health: dict[str, Any] | None = None
_last_health_at = 0.0
_upstream_inflight = 0


class RelayError(Exception):
    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code = code
        self.status = status


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise RelayError("upstream_redirect_refused", 502)


def reset_for_tests() -> None:
    global _leases, _last_health, _last_health_at, _token_override, _upstream_override, _fetch_override
    global _upstream_inflight
    with _lock:
        _leases = {}
        _last_health = None
        _last_health_at = 0.0
        _token_override = None
        _upstream_override = None
        _fetch_override = None
        _upstream_inflight = 0


def configure_for_tests(
    *,
    token: str | None = None,
    upstream: str | None = None,
    fetch=None,
) -> None:
    global _token_override, _upstream_override, _fetch_override
    _token_override = token
    _upstream_override = upstream
    _fetch_override = fetch


def owner_key_from_session_cookie(cookie_value: str | None) -> str:
    raw = (cookie_value or "").strip()
    if not raw:
        raise RelayError("unauthenticated", 401)
    return hashlib.sha256(f"td-camera-viewer:{raw}".encode("utf-8")).hexdigest()[:40]


def vendor_dir() -> Path:
    return _ROOT / VENDOR_REL


def vendor_ready() -> dict[str, Any]:
    d = vendor_dir()
    required = (
        "selfie_segmentation.js",
        "selfie_segmentation.tflite",
        "selfie_segmentation_solution_simd_wasm_bin.wasm",
        "NOTICE.txt",
        "LICENSE-Apache-2.0.txt",
    )
    missing = [name for name in required if not (d / name).is_file()]
    return {
        "ready": not missing,
        "version": "0.1.1675465747",
        "license": "Apache-2.0",
        "path": f"/{VENDOR_REL}/",
        "missing": missing,
    }


def _read_token() -> str:
    if _token_override is not None:
        return _token_override
    try:
        raw = TOKEN_PATH.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RelayError("token_unavailable", 503) from exc
    if not raw:
        raise RelayError("token_unavailable", 503)
    return raw


def _upstream_base() -> str:
    return (_upstream_override or UPSTREAM_BASE).rstrip("/")


def _purge_expired_unlocked(now: float | None = None) -> None:
    now = time.monotonic() if now is None else now
    dead = [lid for lid, lease in _leases.items() if now >= lease.expires_at and not lease.inflight]
    for lid in dead:
        del _leases[lid]


def _jpeg_sof_dimensions(data: bytes) -> tuple[int, int]:
    """Parse JPEG SOF dimensions; raise RelayError on malformed/oversized."""
    if len(data) < 4 or data[0:2] != b"\xff\xd8":
        raise RelayError("invalid_jpeg", 502)
    if data[-2:] != b"\xff\xd9" and b"\xff\xd9" not in data[-16:]:
        # EOI may be present; prefer real decode below when Pillow available.
        pass
    i = 2
    while i < len(data) - 8:
        if data[i] != 0xFF:
            i += 1
            continue
        while i < len(data) and data[i] == 0xFF:
            i += 1
        if i >= len(data):
            break
        marker = data[i]
        i += 1
        if marker in (0xD8, 0xD9):
            continue
        if marker == 0x01 or (0xD0 <= marker <= 0xD7):
            continue
        if i + 1 >= len(data):
            break
        seglen = struct.unpack(">H", data[i : i + 2])[0]
        if seglen < 2 or i + seglen > len(data):
            raise RelayError("invalid_jpeg", 502)
        # SOF0..SOF3, SOF5..SOF7, SOF9..SOF11, SOF13..SOF15
        if marker in {
            0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
            0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
        }:
            if seglen < 7:
                raise RelayError("invalid_jpeg", 502)
            height, width = struct.unpack(">HH", data[i + 3 : i + 7])
            return int(width), int(height)
        i += seglen
    # Fallback: Pillow full open
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(data))
        img.load()
        return int(img.width), int(img.height)
    except Exception as exc:
        raise RelayError("invalid_jpeg", 502) from exc


def validate_jpeg_frame(data: bytes) -> tuple[int, int]:
    if not data or len(data) > MAX_JPEG_BYTES:
        raise RelayError("frame_too_large" if data and len(data) > MAX_JPEG_BYTES else "invalid_jpeg", 413 if data and len(data) > MAX_JPEG_BYTES else 502)
    width, height = _jpeg_sof_dimensions(data)
    if width < 1 or height < 1 or width > MAX_WIDTH or height > MAX_HEIGHT:
        raise RelayError("dimensions_out_of_bounds", 502)
    return width, height


def _upstream_get(path: str) -> tuple[int, dict[str, str], bytes]:
    if _fetch_override is not None:
        return _fetch_override(path)
    token = _read_token()
    base = _upstream_base()
    if not base.startswith("http://127.0.0.1:") and not base.startswith("http://localhost:"):
        # Production origin is fixed loopback; tests may override to 127.0.0.1:ephemeral.
        if _upstream_override is None:
            raise RelayError("upstream_origin_refused", 502)
    url = f"{base}{path}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "*/*",
            "Cache-Control": "no-store",
        },
        method="GET",
    )
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=UPSTREAM_TIMEOUT_SEC) as resp:
            status = int(getattr(resp, "status", 200) or 200)
            headers = {k.lower(): v for k, v in resp.headers.items()}
            body = resp.read(MAX_JPEG_BYTES + 1)
            return status, headers, body
    except RelayError:
        raise
    except urllib.error.HTTPError as exc:
        body = exc.read(4096) if hasattr(exc, "read") else b""
        return int(exc.code), {}, body
    except TimeoutError as exc:
        raise RelayError("upstream_timeout", 504) from exc
    except OSError as exc:
        raise RelayError("upstream_unreachable", 502) from exc


def fetch_health(*, cache_sec: float = 2.0) -> dict[str, Any]:
    """Proxy upstream /health. Does not open the camera."""
    global _last_health, _last_health_at
    with _lock:
        now = time.monotonic()
        if _last_health is not None and now - _last_health_at < cache_sec:
            return dict(_last_health)
    status, _headers, body = _upstream_get("/health")
    if status != 200:
        raise RelayError("upstream_health_failed", 502 if status >= 500 else status)
    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception as exc:
        raise RelayError("upstream_health_invalid", 502) from exc
    if not isinstance(payload, dict):
        raise RelayError("upstream_health_invalid", 502)
    out = {
        "status": payload.get("status") or "ok",
        "source": payload.get("source") or SOURCE_DEVICE,
        "camera_active": bool(payload.get("camera_active")),
        "tunnel_process_running": bool(payload.get("tunnel_process_running")),
        "host": SOURCE_HOST,
        "device": SOURCE_DEVICE,
        "association": ASSOCIATION_LABEL,
        "privacy_note": PRIVACY_NOTE,
        "native_idle_release_sec": NATIVE_IDLE_RELEASE_SEC,
        # Transport health is separate from viewer segmentation readiness.
        "segmentation": vendor_ready(),
    }
    with _lock:
        _last_health = dict(out)
        _last_health_at = time.monotonic()
    return out


def start_view(owner_key: str) -> dict[str, Any]:
    """Create an independent view lease (new lease_id per Start; multitab-safe)."""
    with _lock:
        now = time.monotonic()
        _purge_expired_unlocked(now)
        owned = [L for L in _leases.values() if L.owner_key == owner_key]
        if len(owned) >= MAX_LEASES_PER_OWNER:
            raise RelayError("too_many_view_leases", 429)
        lease_id = secrets.token_urlsafe(24)
        _leases[lease_id] = _ViewLease(
            lease_id=lease_id,
            owner_key=owner_key,
            expires_at=now + VIEW_LEASE_TTL_SEC,
            created_at=now,
        )
        return {
            "lease_id": lease_id,
            "expires_in_sec": VIEW_LEASE_TTL_SEC,
            "renewed": False,
            "association": ASSOCIATION_LABEL,
            "privacy_note": PRIVACY_NOTE,
            "native_idle_release_sec": NATIVE_IDLE_RELEASE_SEC,
            "multi_viewer_policy": MULTI_VIEWER_POLICY,
        }


def stop_view(owner_key: str, lease_id: str | None = None) -> dict[str, Any]:
    """Stop only the named lease. Requires lease_id so tab A cannot stop tab B."""
    with _lock:
        if not lease_id:
            raise RelayError("lease_id_required", 400)
        lease = _leases.get(lease_id)
        if not lease:
            return {
                "ok": True,
                "stopped": False,
                "native_idle_release_sec": NATIVE_IDLE_RELEASE_SEC,
            }
        if lease.owner_key != owner_key:
            raise RelayError("lease_owner_mismatch", 403)
        del _leases[lease_id]
        return {
            "ok": True,
            "stopped": True,
            "native_idle_release_sec": NATIVE_IDLE_RELEASE_SEC,
            "note": (
                "Hermes stopped polling for this lease; native TD camera releases ~"
                f"{NATIVE_IDLE_RELEASE_SEC}s after last frame request (no explicit stop API)."
            ),
        }


def heartbeat_view(owner_key: str, lease_id: str) -> dict[str, Any]:
    with _lock:
        now = time.monotonic()
        _purge_expired_unlocked(now)
        lease = _leases.get(lease_id)
        if not lease or lease.owner_key != owner_key:
            raise RelayError("lease_invalid", 409)
        lease.expires_at = now + VIEW_LEASE_TTL_SEC
        return {"ok": True, "expires_in_sec": VIEW_LEASE_TTL_SEC}


def status(*, viewer_owner_key: str | None = None) -> dict[str, Any]:
    with _lock:
        now = time.monotonic()
        _purge_expired_unlocked(now)
        mine = [
            L for L in _leases.values()
            if viewer_owner_key and L.owner_key == viewer_owner_key
        ]
        health = dict(_last_health) if _last_health else None
        return {
            "view_active": bool(mine),
            "active_lease_count": len(mine),
            "association": ASSOCIATION_LABEL,
            "privacy_note": PRIVACY_NOTE,
            "multi_viewer_policy": MULTI_VIEWER_POLICY,
            "source_host": SOURCE_HOST,
            "source_device": SOURCE_DEVICE,
            "native_idle_release_sec": NATIVE_IDLE_RELEASE_SEC,
            "bounds": {
                "max_jpeg_bytes": MAX_JPEG_BYTES,
                "max_width": MAX_WIDTH,
                "max_height": MAX_HEIGHT,
                "min_interval_sec": MIN_FRAME_INTERVAL_SEC,
                "view_lease_ttl_sec": VIEW_LEASE_TTL_SEC,
                "max_upstream_snapshot_inflight": MAX_UPSTREAM_SNAPSHOT_INFLIGHT,
                "max_leases_per_owner": MAX_LEASES_PER_OWNER,
                "target_fps": "~5 snapshot-poll",
            },
            "segmentation": vendor_ready(),
            "upstream_health_cached": health,
            "path": "snapshot_poll",
        }


def fetch_snapshot_for_viewer(owner_key: str, lease_id: str) -> tuple[bytes, dict[str, str]]:
    """Fetch one upstream snapshot. Requires active view lease. Activates camera.

    Rate/inflight reserved under lock before upstream I/O. If the lease is stopped
    or expires during the fetch, the JPEG is discarded and the lease is not renewed.
    """
    global _upstream_inflight
    with _lock:
        now = time.monotonic()
        _purge_expired_unlocked(now)
        lease = _leases.get(lease_id)
        if not lease or lease.owner_key != owner_key:
            raise RelayError("view_lease_required", 403)
        if now >= lease.expires_at:
            del _leases[lease_id]
            raise RelayError("view_lease_required", 403)
        if lease.inflight or now < lease.reserved_until:
            raise RelayError("rate_limited", 429)
        if lease.last_frame_at and now - lease.last_frame_at < MIN_FRAME_INTERVAL_SEC:
            raise RelayError("rate_limited", 429)
        if _upstream_inflight >= MAX_UPSTREAM_SNAPSHOT_INFLIGHT:
            raise RelayError("upstream_busy", 429)
        lease.inflight = True
        lease.reserved_until = now + MIN_FRAME_INTERVAL_SEC
        _upstream_inflight += 1

    try:
        status_code, _headers, body = _upstream_get("/snapshot.jpg")
    finally:
        with _lock:
            _upstream_inflight = max(0, _upstream_inflight - 1)
            lease = _leases.get(lease_id)
            if lease and lease.owner_key == owner_key:
                lease.inflight = False

    # Lease may have been stopped while in flight — discard, do not renew.
    with _lock:
        lease = _leases.get(lease_id)
        if not lease or lease.owner_key != owner_key or time.monotonic() >= lease.expires_at:
            if lease and time.monotonic() >= lease.expires_at:
                del _leases[lease_id]
            raise RelayError("view_lease_required", 403)

    if status_code == 401:
        raise RelayError("upstream_unauthorized", 502)
    if status_code == 503:
        raise RelayError("camera_unavailable", 503)
    if status_code != 200:
        raise RelayError("upstream_snapshot_failed", 502)

    width, height = validate_jpeg_frame(body)

    with _lock:
        lease = _leases.get(lease_id)
        if not lease or lease.owner_key != owner_key or time.monotonic() >= lease.expires_at:
            if lease and time.monotonic() >= lease.expires_at:
                del _leases[lease_id]
            raise RelayError("view_lease_required", 403)
        now = time.monotonic()
        lease.last_frame_at = now
        lease.expires_at = now + VIEW_LEASE_TTL_SEC

    headers = {
        "Content-Type": "image/jpeg",
        "Cache-Control": "no-store",
        "X-TD-Camera-Host": SOURCE_HOST,
        "X-TD-Camera-Device": SOURCE_DEVICE,
        "X-TD-Camera-Transport": "raw",
        "X-TD-Camera-Path": "snapshot_poll",
        "X-TD-Camera-Width": str(width),
        "X-TD-Camera-Height": str(height),
    }
    return body, headers


def read_json_body(handler, *, max_bytes: int = 64_000) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length") or 0)
    if length < 0 or length > max_bytes:
        raise RelayError("body_too_large", 413)
    raw = handler.rfile.read(length) if length else b""
    if not raw:
        return {}
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise RelayError("invalid_json", 400) from exc
    if not isinstance(data, dict):
        raise RelayError("invalid_json", 400)
    return data
