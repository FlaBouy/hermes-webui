"""Biggy Mapbox public-token config (display-only).

Reads BIGGY_MAPBOX_PUBLIC_TOKEN from process env or the Biggy profile .env.
Never logs or returns the token in error paths beyond the intentional config payload.
Origin-restricted: only local Biggy WebUI origins may fetch this endpoint.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

TOKEN_ENV = "BIGGY_MAPBOX_PUBLIC_TOKEN"
_BIGGY_ENV = Path.home() / ".hermes" / "profiles" / "biggy" / ".env"
_TOKEN_LINE = re.compile(
    rf"^\s*{re.escape(TOKEN_ENV)}\s*=\s*(.+?)\s*$",
    re.MULTILINE,
)

# Origin allowlist for Mapbox public-token delivery (local Biggy surfaces only).
_ALLOWED_ORIGINS = frozenset(
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


def origin_allowed(
    origin: str | None,
    referer: str | None = None,
    host: str | None = None,
) -> bool:
    o = (origin or "").strip().rstrip("/")
    if o in _ALLOWED_ORIGINS:
        return True
    # Same-origin fetch may omit Origin; accept Referer from allowlisted hosts.
    ref = (referer or "").strip()
    if ref:
        try:
            p = urlparse(ref)
            base = f"{p.scheme}://{p.netloc}".rstrip("/")
            if base in _ALLOWED_ORIGINS:
                return True
        except Exception:
            pass
    # Loopback Host header only (local Biggy WebUI); no remote Host spoof trust beyond allowlist.
    h = (host or "").strip().lower()
    if h in (
        "127.0.0.1:8787",
        "localhost:8787",
        "127.0.0.1:8788",
        "localhost:8788",
        "127.0.0.1:8790",
        "localhost:8790",
    ):
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
