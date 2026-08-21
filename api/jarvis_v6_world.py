"""Read-only, same-origin proxy for the local Jarvis V6 3D graph viewer.

This lets Biggy embed the real V6 force-graph renderer (nodes/links —
Jarvis's RAG/memory world) in its center panel without the browser ever
making a direct request to the V6 service on port 4719, and without
exposing a general filesystem proxy.

This module never talks to the live V6 HTTP service. It only reads a fixed,
narrow allowlist of static files already built to disk by the V6 POC's own
`build.py` step (`3d.html`, `graph-data.js`, `logo.png`). Config (the local
viewer directory path) is local-only/gitignored, mirroring
`jarvis_v6_bridge.py`.

Jarvis V6's own presence chrome (orb/state/model chip, inbox, tasks, prompt
bar) is suppressed in the served `3d.html` via a small injected <style>
block: Biggy's header reactor is the single Jarvis identity/status display,
and Biggy owns chat input. The graph/scene renderer and its own viewer
chrome (canvas, node inspector, legend, hud, search) are left untouched.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

# Default location of the V6 POC's built viewer assets on this Mac. Override
# via the local (gitignored) config file below if the POC checkout moves.
DEFAULT_VIEWER_DIR = (
    "/Users/rick/Documents/Codex/2026-08-20/"
    "referenced-chatgpt-conversation-this-is-an/work/jarvis-v6-poc/"
    "brain-jarvis/viewer"
)

_PROFILE_CONFIG = Path.home() / ".hermes" / "profiles" / "biggy" / "jarvis-v6-world.json"
_REPO_LOCAL_CONFIG = Path(__file__).resolve().parents[1] / "jarvis-v6-world.local.json"

# Fixed allowlist: asset name -> content-type. Nothing outside this exact
# set of names is ever readable through this module — deliberately not a
# general static file proxy.
ALLOWED_ASSETS: dict[str, str] = {
    "3d.html": "text/html; charset=utf-8",
    "graph-data.js": "application/javascript; charset=utf-8",
    "logo.png": "image/png",
}

# Jarvis V6's own presence/chat chrome — suppressed here because Biggy's
# header reactor is the single identity/status surface and Biggy's own
# composer is the only input surface. The graph/scene module and its own
# viewer chrome (#g canvas, #side, #legend, #hud) are unaffected.
_SUPPRESS_STYLE = (
    "<style>#j-orb,#j-state,#j-status,#j-brain,#jarvis,#j-inbox,#j-tasks"
    "{display:none!important}</style>"
)
_BASE_HREF = '<base href="/api/biggy/v6/world/">'

_FALLBACK_HTML = (
    "<!doctype html><html><head><meta charset=\"utf-8\">"
    "<style>"
    "html,body{margin:0;height:100%;background:radial-gradient(ellipse at 50% 40%,"
    "#0f151b 0%,#05070a 70%);display:flex;align-items:center;justify-content:center;"
    "font-family:ui-monospace,'SF Mono',monospace}"
    ".msg{color:#5a6b62;font-size:12px;letter-spacing:.08em;text-transform:uppercase;"
    "text-align:center;border:1px solid rgba(52,211,153,.25);border-radius:12px;"
    "padding:18px 26px;background:rgba(10,22,18,.5)}"
    ".msg small{display:block;margin-top:6px;font-size:9px;opacity:.65;"
    "letter-spacing:.04em;text-transform:none}"
    "</style></head><body><div class=\"msg\">V6 graph unavailable"
    "<small>local viewer assets not found on disk</small></div></body></html>"
)

# Scoped CSP for the embedded V6 viewer only. The rest of Biggy stays on the
# strict shared policy in api/helpers.py (frame-ancestors 'none'); this
# response intentionally allows same-origin framing plus the CDN the V6
# viewer's own <script type="importmap"> points at for Three.js.
WORLD_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://esm.sh; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; "
    "connect-src 'self' https://esm.sh; "
    "worker-src 'self' blob:; "
    "frame-ancestors 'self'; "
    "base-uri 'self'"
)


def load_world_config() -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for path in (_PROFILE_CONFIG, _REPO_LOCAL_CONFIG):
        data = _read_json_file(path)
        if isinstance(data, dict):
            merged.update(data)
    env_dir = (os.environ.get("JARVIS_V6_VIEWER_DIR") or "").strip()
    if env_dir:
        merged["viewer_dir"] = env_dir
    return merged


def resolve_viewer_dir() -> Path | None:
    cfg = load_world_config()
    raw = str(cfg.get("viewer_dir") or DEFAULT_VIEWER_DIR).strip()
    try:
        candidate = Path(raw).expanduser().resolve()
    except Exception:
        return None
    if not candidate.is_dir():
        return None
    if not (candidate / "3d.html").is_file():
        return None
    return candidate


def serve_asset(name: str) -> tuple[bytes, str, int]:
    """Return (body, content_type, status) for one allowlisted asset name.

    Always returns a 200 with a designed fallback page for `3d.html` when
    the viewer is unavailable, so the embedding iframe never shows a raw
    browser error page.
    """
    content_type = ALLOWED_ASSETS.get(name)
    if content_type is None:
        return b'{"error":"not found"}', "application/json; charset=utf-8", 404

    viewer_dir = resolve_viewer_dir()
    if viewer_dir is None:
        return _asset_unavailable(name, content_type)

    target = (viewer_dir / name).resolve()
    try:
        target.relative_to(viewer_dir)  # defense in depth vs traversal
    except ValueError:
        return b'{"error":"not found"}', "application/json; charset=utf-8", 404

    if not target.is_file():
        return _asset_unavailable(name, content_type)

    try:
        data = target.read_bytes()
    except OSError:
        return _asset_unavailable(name, content_type)

    if name == "3d.html":
        data = _patch_index_html(data)

    return data, content_type, 200


def _asset_unavailable(name: str, content_type: str) -> tuple[bytes, str, int]:
    if name == "3d.html":
        return _FALLBACK_HTML.encode("utf-8"), "text/html; charset=utf-8", 200
    return b"", content_type, 404


def _patch_index_html(data: bytes) -> bytes:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return data
    injected = _BASE_HREF + _SUPPRESS_STYLE
    if "<head>" in text:
        text = text.replace("<head>", "<head>" + injected, 1)
    else:
        text = injected + text
    return text.encode("utf-8")


def _read_json_file(path: Path) -> dict[str, Any] | None:
    try:
        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except OSError:
        return None
    except json.JSONDecodeError:
        return None
