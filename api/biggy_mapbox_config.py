"""Biggy Mapbox public-token config (display-only).

Reads BIGGY_MAPBOX_PUBLIC_TOKEN from process env or the Biggy profile .env.
Never logs or returns the token in error paths beyond the intentional config payload.
Origin-restricted: only local Biggy WebUI origins and the exact configured
HERMES_WEBUI_SMEDLEY_PUBLIC_ORIGIN may fetch this endpoint.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

TOKEN_ENV = "BIGGY_MAPBOX_PUBLIC_TOKEN"
PUBLIC_ORIGIN_ENV = "HERMES_WEBUI_SMEDLEY_PUBLIC_ORIGIN"
_BIGGY_ENV = Path.home() / ".hermes" / "profiles" / "biggy" / ".env"
_TOKEN_LINE = re.compile(
    rf"^\s*{re.escape(TOKEN_ENV)}\s*=\s*(.+?)\s*$",
    re.MULTILINE,
)

# Origin allowlist for Mapbox public-token delivery (local Biggy surfaces).
_ALLOWED_LOOPBACK_ORIGINS = frozenset(
    {
        "http://127.0.0.1:8787",
        "http://localhost:8787",
        "http://127.0.0.1:8788",
        "http://localhost:8788",
        "http://127.0.0.1:8790",
        "http://localhost:8790",
        "https://127.0.0.1:8787",
        "https://localhost:8787",
        "https://127.0.0.1:8790",
        "https://localhost:8790",
    }
)

_ALLOWED_LOOPBACK_HOSTS = frozenset(
    {
        "127.0.0.1:8787",
        "localhost:8787",
        "127.0.0.1:8788",
        "localhost:8788",
        "127.0.0.1:8790",
        "localhost:8790",
    }
)


def _read_token_from_profile_env() -> str:
    try:
        if not _BIGGY_ENV.is_file():
            return ""
        text = _BIGGY_ENV.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    m = _TOKEN_LINE.search(text)
    if not m:
        return ""
    raw = m.group(1).strip().strip('"').strip("'")
    return raw


def resolve_mapbox_public_token() -> str:
    """Return public Mapbox token string or empty. Never print/log the value."""
    tok = (os.environ.get(TOKEN_ENV) or "").strip()
    if not tok:
        tok = _read_token_from_profile_env()
    if tok.startswith("pk.") and len(tok) >= 20:
        return tok
    return ""


def _normalize_strict_origin(value: object) -> str:
    """Normalize to scheme://host[:port], or '' when invalid/forbidden.

    Rejects credentials, query, fragment, non-root path, wildcards, and
    non-http(s) schemes. Host is lowercased. Exact string match after this
    step is the authorization boundary (no suffix lookalikes).
    """
    raw = str(value or "").strip()
    if not raw:
        return ""
    if "*" in raw or "?" in raw:
        return ""
    try:
        parts = urlsplit(raw)
    except Exception:
        return ""
    if parts.scheme not in ("http", "https"):
        return ""
    if parts.username is not None or parts.password is not None:
        return ""
    if parts.query or parts.fragment:
        return ""
    path = parts.path or ""
    if path not in ("", "/"):
        return ""
    host = (parts.hostname or "").strip().lower()
    if not host:
        return ""
    # Bracket IPv6 for rebuild; urlsplit hostname is unbracketed.
    if ":" in host and not host.startswith("["):
        host_out = f"[{host}]"
    else:
        host_out = host
    port = parts.port
    if port is not None:
        return f"{parts.scheme}://{host_out}:{port}"
    return f"{parts.scheme}://{host_out}"


def _origin_from_referer(referer: object) -> str:
    """Extract scheme://host[:port] from a Referer URL, or '' when invalid.

    Path/query/fragment on the Referer are ignored after extraction. Credentials
    and wildcards in the authority still fail closed.
    """
    raw = str(referer or "").strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
    except Exception:
        return ""
    if parts.scheme not in ("http", "https"):
        return ""
    if parts.username is not None or parts.password is not None:
        return ""
    netloc = parts.netloc or ""
    if "*" in netloc or "?" in netloc:
        return ""
    host = (parts.hostname or "").strip().lower()
    if not host:
        return ""
    if ":" in host and not host.startswith("["):
        host_out = f"[{host}]"
    else:
        host_out = host
    port = parts.port
    if port is not None:
        return f"{parts.scheme}://{host_out}:{port}"
    return f"{parts.scheme}://{host_out}"


def _configured_public_origin() -> str:
    """Return normalized HERMES_WEBUI_SMEDLEY_PUBLIC_ORIGIN, or '' if unset/invalid."""
    return _normalize_strict_origin(os.environ.get(PUBLIC_ORIGIN_ENV) or "")


def _allowed_origins() -> frozenset[str]:
    allowed = set(_ALLOWED_LOOPBACK_ORIGINS)
    public = _configured_public_origin()
    if public:
        allowed.add(public)
    return frozenset(allowed)


def origin_allowed(
    origin: str | None,
    referer: str | None = None,
    host: str | None = None,
) -> bool:
    allowed = _allowed_origins()

    o = _normalize_strict_origin(origin)
    if o and o in allowed:
        return True

    # Same-origin fetch may omit Origin; accept Referer from allowlisted origins.
    ref_origin = _origin_from_referer(referer)
    if ref_origin and ref_origin in allowed:
        return True

    # Loopback Host header only (local Biggy WebUI). Never authorize the
    # configured public origin (or any other host) via Host alone — Host is
    # trivial to spoof on cross-origin fetches.
    h = (host or "").strip().lower()
    if h in _ALLOWED_LOOPBACK_HOSTS:
        return True
    return False


def mapbox_public_config(
    *,
    origin: str | None = None,
    referer: str | None = None,
    host: str | None = None,
) -> dict[str, Any]:
    """Build non-secret metadata + token for allowed origins only."""
    allowed = origin_allowed(origin, referer, host)
    tok = resolve_mapbox_public_token() if allowed else ""
    available = bool(allowed and tok)
    return {
        "schema": "biggy.mapbox_public_config.v1",
        "available": available,
        "token_env": TOKEN_ENV,
        "token_prefix": "pk." if available else None,
        "token_set": bool(tok) if allowed else False,
        "origin_allowed": allowed,
        "display": "mapbox_gl_js",
        "decision_maker": False,
        # Public token only — delivered to allowed Biggy origins for GL JS.
        "token": tok if available else None,
        "reason": None
        if available
        else (
            "ORIGIN_NOT_ALLOWED"
            if not allowed
            else ("TOKEN_MISSING_OR_INVALID" if not tok else "UNAVAILABLE")
        ),
    }
