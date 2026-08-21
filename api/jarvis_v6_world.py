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
import mimetypes
import os
import threading
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

# Default location of the V6 POC's built viewer assets on this Mac. Override
# via the local (gitignored) config file below if the POC checkout moves.
DEFAULT_VIEWER_DIR = (
    "/Users/rick/Documents/Codex/2026-08-20/"
    "referenced-chatgpt-conversation-this-is-an/work/jarvis-v6-poc/"
    "brain-jarvis/viewer"
)

_PROFILE_CONFIG = Path.home() / ".hermes" / "profiles" / "biggy" / "jarvis-v6-world.json"
_REPO_LOCAL_CONFIG = Path(__file__).resolve().parents[1] / "jarvis-v6-world.local.json"

# The graph is a live view of the same NAS-backed corpus that the Smedley RAG
# service indexes.  It is deliberately read-only: ingestion remains owned by
# the existing watcher and this module merely projects its filesystem state.
DEFAULT_RAG_LIBRARY_ROOT = "/Users/rick/Mounts/RAG_Pool/Library"
DEFAULT_RAG_STATUS_URL = "http://127.0.0.1:5004/ingest-status"
DEFAULT_RAG_INGEST_LEDGER = Path.home() / ".jarvis_rag_status" / "ingest_ledger.json"
MAX_WORLD_DOCUMENTS = 4000
_WORLD_CACHE_TTL_S = 20.0
_BROWSABLE_DOCUMENT_SUFFIXES = frozenset({".pdf", ".txt", ".md", ".csv", ".json", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"})
_world_cache_lock = threading.Lock()
_world_cache: tuple[float, bytes] | None = None

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
_TRACE_RUNTIME = r'''<script id="biggy-rag-trace-runtime">
(() => {
  'use strict';
  let original = null;
  let clearTimer = null;
  let idleContrastInstalled = false;
  let landingZoomApplied = false;
  const edge = (a, b) => `${Math.min(a,b)}:${Math.max(a,b)}`;
  const canonicalSource = value => String(value || '').replace(/\\/g, '/').replace(/^.*?\/Library\//, '').replace(/^\/+/, '');
  function graph() { return window.__os && window.__os.Graph; }
  function idOf(value) { return value && value.id !== undefined ? value.id : value; }
  function nodeFor(value) {
    const data = window.__os && window.__os.data;
    return data && data.nodes ? data.nodes[idOf(value)] : null;
  }
  function installIdleContrast() {
    const g = graph();
    if (!g || idleContrastInstalled) return !!g;
    // Keep V6's own directional particle callbacks.  This only makes the
    // dormant corpus readable from across the room: folder spine links are
    // brighter/thicker than document leaves, while active routes remain the
    // stronger green/red treatment below.
    const idleColor = link => {
      const a = nodeFor(link.source), b = nodeFor(link.target);
      return (a && b && (a.g === 'router' || b.g === 'router' || (a.g === 'folder' && b.g === 'folder')))
        ? '#32978a' : '#276274';
    };
    const idleWidth = link => {
      const a = nodeFor(link.source), b = nodeFor(link.target);
      return (a && b && (a.g === 'router' || b.g === 'router' || (a.g === 'folder' && b.g === 'folder'))) ? 0.95 : 0.5;
    };
    g.linkColor(idleColor).linkWidth(idleWidth).linkOpacity(0.74);
    idleContrastInstalled = true;
    return true;
  }
  function nodePath(node) {
    const match = /^key:(?:dir|doc):(.+)$/.exec(String(node && node.p || ''));
    return match ? match[1] : '';
  }
  function nodeUrl(node) {
    const rel = nodePath(node);
    if (!rel) return '';
    if (String(node.g) === 'document') return `/api/biggy/rag-file?path=${encodeURIComponent(rel)}`;
    if (String(node.g) === 'folder') return `/api/biggy/rag-browse?path=${encodeURIComponent(rel)}`;
    return '';
  }
  function openNode(node) {
    const url = nodeUrl(node);
    if (url) window.open(url, '_blank', 'noopener');
  }
  function addNodeAction(node) {
    const url = nodeUrl(node), card = document.getElementById('j-nodecard');
    if (!url || !card || card.querySelector('[data-biggy-rag-open]')) return;
    const link = document.createElement('a');
    link.href = url; link.target = '_blank'; link.rel = 'noopener';
    link.dataset.biggyRagOpen = '1';
    link.textContent = node.g === 'document' ? 'Open document ↗' : 'Browse folder ↗';
    link.style.cssText = 'display:inline-block;margin-top:12px;color:#34d399;font:700 11px ui-monospace,monospace;text-decoration:none;';
    card.appendChild(link);
  }
  function installGalaxyNavigation() {
    const g = graph(), host = document.getElementById('g');
    if (!g || !host || host.dataset.biggyNavigationInstalled) return !!g;
    host.dataset.biggyNavigationInstalled = '1';
    const focus = window.__os && window.__os.onNodeClick;
    const showCard = window.__os && window.__os.showNodeCard;
    if (typeof focus === 'function') {
      g.onNodeClick((node, event) => {
        focus(node, event);
        if (typeof showCard === 'function' && !(event && event.shiftKey)) {
          showCard(node, event); addNodeAction(node);
        }
        if (event && (event.metaKey || event.ctrlKey)) openNode(node);
      });
    }
    if (typeof showCard === 'function') {
      g.onNodeRightClick((node, event) => { showCard(node, event); addNodeAction(node); });
    }
    // Middle-button drag translates the camera and target together in the
    // visible screen plane; left drag remains V6's native orbit control.
    let active = false, lastX = 0, lastY = 0, priorRotate = false;
    const stop = event => {
      if (!active) return;
      active = false;
      const controls = g.controls();
      if (controls) controls.autoRotate = priorRotate;
      try { host.releasePointerCapture(event.pointerId); } catch (_) {}
    };
    host.addEventListener('pointerdown', event => {
      if (event.button !== 1) return;
      active = true; lastX = event.clientX; lastY = event.clientY;
      const controls = g.controls(); priorRotate = !!(controls && controls.autoRotate);
      if (controls) controls.autoRotate = false;
      try { host.setPointerCapture(event.pointerId); } catch (_) {}
      event.preventDefault(); event.stopPropagation();
    }, true);
    host.addEventListener('pointermove', event => {
      if (!active) return;
      const dx = event.clientX - lastX, dy = event.clientY - lastY;
      lastX = event.clientX; lastY = event.clientY;
      const camera = g.camera(), controls = g.controls();
      if (!camera || !controls || !camera.matrixWorld || !camera.matrixWorld.elements) return;
      const distance = camera.position.distanceTo(controls.target);
      const scale = (2 * distance * Math.tan((camera.fov || 45) * Math.PI / 360)) / Math.max(host.clientHeight, 1);
      const m = camera.matrixWorld.elements;
      const shiftX = (m[0] * -dx + m[4] * dy) * scale;
      const shiftY = (m[1] * -dx + m[5] * dy) * scale;
      const shiftZ = (m[2] * -dx + m[6] * dy) * scale;
      camera.position.x += shiftX; camera.position.y += shiftY; camera.position.z += shiftZ;
      controls.target.x += shiftX; controls.target.y += shiftY; controls.target.z += shiftZ;
      controls.update();
      event.preventDefault(); event.stopPropagation();
    }, true);
    host.addEventListener('pointerup', stop, true);
    host.addEventListener('pointercancel', stop, true);
    host.addEventListener('auxclick', event => { if (event.button === 1) event.preventDefault(); }, true);
    return true;
  }
  function mapNodes() {
    const out = new Map();
    const data = window.__os && window.__os.data;
    for (const n of (data && data.nodes) || []) {
      const match = /^key:(.+)$/.exec(String(n.p || ''));
      if (match) out.set(match[1], n.id);
    }
    return out;
  }
  function routeFor(source) {
    const rel = canonicalSource(source);
    if (!rel) return [];
    const keys = ['root:rag-pool'];
    const parts = rel.split('/').filter(Boolean);
    let cursor = '';
    for (const part of parts.slice(0, -1)) {
      cursor = cursor ? `${cursor}/${part}` : part;
      keys.push(`dir:${cursor}`);
    }
    keys.push(`doc:${rel}`);
    const ids = mapNodes();
    return keys.map(key => ids.get(key)).filter(id => id !== undefined);
  }
  function restore() {
    const g = graph();
    if (!g || !original) return;
    g.linkColor(original.color).linkWidth(original.width)
      .linkDirectionalParticles(original.particles)
      .linkDirectionalParticleColor(original.particleColor)
      .linkDirectionalParticleWidth(original.particleWidth);
    original = null;
  }
  function apply(trace) {
    const g = graph();
    if (!g) { setTimeout(() => apply(trace), 180); return; }
    installIdleContrast();
    const route = routeFor(trace && trace.source);
    if (route.length < 2) return;
    if (!original) {
      original = { color: g.linkColor(), width: g.linkWidth(), particles: g.linkDirectionalParticles(), particleColor: g.linkDirectionalParticleColor(), particleWidth: g.linkDirectionalParticleWidth() };
    }
    const active = new Set();
    for (let i = 0; i < route.length - 1; i++) active.add(edge(route[i], route[i + 1]));
    const failed = trace && trace.state === 'failed' ? edge(route[route.length - 2], route[route.length - 1]) : '';
    const paint = link => {
      const key = edge(idOf(link.source), idOf(link.target));
      if (key === failed) return '#ef4444';
      if (active.has(key)) return '#34d399';
      return 'rgba(32,55,64,.24)';
    };
    g.linkColor(paint).linkWidth(link => active.has(edge(idOf(link.source), idOf(link.target))) ? 2.6 : 0)
      .linkDirectionalParticles(link => active.has(edge(idOf(link.source), idOf(link.target))) ? 5 : 0)
      .linkDirectionalParticleColor(paint).linkDirectionalParticleWidth(2.2);
    parent.postMessage({ type: 'biggy-rag-trace-applied', trace: { state: trace && trace.state || 'complete', source: trace && trace.source || '', segments: route.length - 1 } }, location.origin);
    if (clearTimer) clearTimeout(clearTimer);
    clearTimer = setTimeout(restore, trace && trace.state === 'failed' ? 18000 : 12000);
  }
  addEventListener('message', event => {
    if (event.origin !== location.origin) return;
    const data = event.data || {};
    if (data.type === 'biggy-rag-trace') apply(data.trace || {});
    if (data.type === 'biggy-rag-trace-clear') restore();
  });
  const waitForGraph = () => {
    if (!installIdleContrast()) setTimeout(waitForGraph, 180);
    else installGalaxyNavigation();
  };
  waitForGraph();
  // The upstream V6 viewer fits the entire graph for a small personal vault.
  // A thousand-node corpus needs a closer landing distance to read the
  // hierarchy across the room.  This executes once, after V6's own intro-fit;
  // normal orbit/wheel controls remain entirely untouched afterwards.
  setTimeout(() => {
    const g = graph();
    if (!g || landingZoomApplied) return;
    const c = g.cameraPosition();
    if (!c || !Number.isFinite(c.z)) return;
    landingZoomApplied = true;
    g.cameraPosition({ x: c.x * 0.38, y: c.y * 0.38, z: c.z * 0.38 }, undefined, 1300);
  }, 11800);
  window.__biggyRagTraceReady = true;
})();
</script>'''

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


def resolve_rag_library_root() -> Path | None:
    """Resolve the corpus root without ever following it outside the mount."""
    cfg = load_world_config()
    raw = str(cfg.get("rag_library_root") or DEFAULT_RAG_LIBRARY_ROOT).strip()
    try:
        candidate = Path(raw).expanduser().resolve()
    except Exception:
        return None
    return candidate if candidate.is_dir() else None


def resolve_rag_ingest_ledger() -> Path | None:
    cfg = load_world_config()
    raw = str(cfg.get("rag_ingest_ledger") or DEFAULT_RAG_INGEST_LEDGER).strip()
    try:
        candidate = Path(raw).expanduser().resolve()
    except Exception:
        return None
    return candidate if candidate.is_file() else None


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
    elif name == "graph-data.js":
        data = _rag_pool_graph_data(data)

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
    injected = _BASE_HREF + _SUPPRESS_STYLE + _TRACE_RUNTIME
    if "<head>" in text:
        text = text.replace("<head>", "<head>" + injected, 1)
    else:
        text = injected + text
    return text.encode("utf-8")


def _rag_pool_graph_data(fallback: bytes) -> bytes:
    """Build a bounded directory/document graph from the live RAG Pool.

    Folder nodes form the stable backbone.  File nodes are leaves.  Each node
    carries a private, canonical key in ``p`` so the iframe trace overlay can
    light the exact folder-to-document route returned by retrieval.
    """
    global _world_cache
    ledger = resolve_rag_ingest_ledger()
    if ledger is None:
        return fallback
    now = time.monotonic()
    with _world_cache_lock:
        if _world_cache and now - _world_cache[0] < _WORLD_CACHE_TTL_S:
            return _world_cache[1]
    try:
        graph = _build_rag_pool_graph(ledger)
        rendered = ("const GRAPH = " + json.dumps(graph, separators=(",", ":")) + ";\n").encode("utf-8")
    except OSError:
        return fallback
    with _world_cache_lock:
        _world_cache = (now, rendered)
    return rendered


def _build_rag_pool_graph(ledger_path: Path) -> dict[str, Any]:
    groups = {
        "router": {"c": "#34d399", "r": 11, "glow": 30, "name": "RAG Pool", "pace": 0, "pause": 0, "major": True},
        "folder": {"c": "#60a5fa", "r": 7, "glow": 18, "name": "Library folder", "pace": 260, "pause": 360, "major": True},
        "document": {"c": "#a78bfa", "r": 4, "glow": 11, "name": "Indexed document", "pace": 460, "pause": 560, "major": False},
    }
    nodes: list[dict[str, str]] = [{"id": "root:rag-pool", "label": "RAG Pool", "g": "router", "p": "key:root:rag-pool"}]
    links: list[dict[str, int]] = []
    index: dict[str, int] = {"root:rag-pool": 0}

    def add(key: str, label: str, group: str, parent: str) -> None:
        if key in index:
            return
        index[key] = len(nodes)
        nodes.append({"id": key, "label": label, "g": group, "p": "key:" + key})
        links.append({"s": index[parent], "t": index[key]})

    try:
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        ledger = {}
    records = ledger.get("files") if isinstance(ledger, dict) else {}
    candidates: list[tuple[str, dict[str, Any]]] = []
    for row in records.values() if isinstance(records, dict) else []:
        if not isinstance(row, dict):
            continue
        rel = _canonical_source(row.get("source") or row.get("path"))
        if rel:
            candidates.append((rel, row))
    # The ledger is the ingestion authority.  Keeping the most recently
    # touched records under the browser limit guarantees active/failed work is
    # never displaced by cold corpus leaves.
    candidates.sort(key=lambda item: str(item[1].get("updated_at") or item[1].get("indexed_at") or ""), reverse=True)
    candidates = candidates[:MAX_WORLD_DOCUMENTS]
    for rel, _row in sorted(candidates, key=lambda item: item[0]):
        parts = rel.split("/")
        cursor = ""
        for part in parts[:-1]:
            cursor = f"{cursor}/{part}" if cursor else part
            parent_dir = cursor.rsplit("/", 1)[0] if "/" in cursor else ""
            add("dir:" + cursor, part, "folder", "dir:" + parent_dir if parent_dir else "root:rag-pool")
        parent = "dir:" + rel.rsplit("/", 1)[0] if "/" in rel else "root:rag-pool"
        add("doc:" + rel, Path(rel).name, "document", parent)
    return {"brand": {"name": "RAG POOL", "logo": False}, "groups": groups, "nodes": nodes, "links": links}


def _canonical_source(value: object) -> str:
    source = str(value or "").replace("\\", "/")
    marker = "/Library/"
    if marker in source:
        source = source.split(marker, 1)[1]
    return source.strip("/")


def rag_folder_entries(value: object) -> list[dict[str, str]] | None:
    """List one virtual RAG folder from ledger-known sources only."""
    rel = _safe_rag_rel(value)
    if rel is None:
        return None
    prefix = rel + "/" if rel else ""
    entries: dict[str, dict[str, str]] = {}
    for source in _ledger_sources():
        if prefix and not source.startswith(prefix):
            continue
        remainder = source[len(prefix):] if prefix else source
        if not remainder:
            continue
        name, separator, _tail = remainder.partition("/")
        child_rel = f"{rel}/{name}" if rel else name
        entries[name] = {"name": name, "path": child_rel, "kind": "folder" if separator else "document"}
    return [entries[name] for name in sorted(entries, key=str.casefold)]


def resolve_rag_document(value: object) -> tuple[Path, Path, str, str] | None:
    """Return a ledger-known document plus safe browser delivery metadata."""
    rel = _safe_rag_rel(value)
    if not rel or rel not in _ledger_sources() or Path(rel).suffix.lower() not in _BROWSABLE_DOCUMENT_SUFFIXES:
        return None
    root = resolve_rag_library_root()
    if root is None:
        return None
    target = (root / rel).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return None
    if not target.is_file():
        return None
    suffix = target.suffix.lower()
    mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    disposition = "inline" if suffix in {".pdf", ".txt", ".md", ".csv", ".json"} else "attachment"
    return root, target, mime, disposition


def _safe_rag_rel(value: object) -> str | None:
    rel = _canonical_source(value)
    if not rel:
        return ""
    return None if any(part in {"", ".", ".."} for part in rel.split("/")) else rel


def _ledger_sources() -> set[str]:
    ledger_path = resolve_rag_ingest_ledger()
    if ledger_path is None:
        return set()
    try:
        payload = json.loads(ledger_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    records = payload.get("files") if isinstance(payload, dict) else {}
    return {
        source
        for row in (records.values() if isinstance(records, dict) else [])
        if isinstance(row, dict)
        for source in [_safe_rag_rel(row.get("source") or row.get("path"))]
        if source
    }


def ingest_status() -> dict[str, Any]:
    """Return the public ingestion ledger needed to paint a real failed edge."""
    try:
        with urlopen(DEFAULT_RAG_STATUS_URL, timeout=2.5) as response:
            raw = response.read(64 * 1024)
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, URLError, ValueError, json.JSONDecodeError):
        return {"ok": False, "state": "offline"}
    if not isinstance(payload, dict):
        return {"ok": False, "state": "error"}
    last_file = str(payload.get("last_file") or "")
    # The watcher sometimes reports only a basename.  Resolve it through its
    # own ledger before emitting a trace target; otherwise the UI would have
    # to guess a branch when duplicate filenames exist.
    if last_file and "/" not in last_file.replace("\\", "/"):
        last_file = _ledger_source_for_basename(last_file) or last_file
    return {
        "ok": True,
        "state": str(payload.get("status") or "unknown"),
        "phase": str(payload.get("current_phase") or ""),
        "last_file": last_file,
        "last_error": str(payload.get("last_error") or ""),
        "indicator": str(payload.get("indicator") or ""),
    }


def _ledger_source_for_basename(basename: str) -> str:
    ledger_path = resolve_rag_ingest_ledger()
    if ledger_path is None:
        return ""
    try:
        payload = json.loads(ledger_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    records = payload.get("files") if isinstance(payload, dict) else {}
    matches = []
    for row in records.values() if isinstance(records, dict) else []:
        if not isinstance(row, dict):
            continue
        source = _canonical_source(row.get("source") or row.get("path"))
        if source and Path(source).name == basename:
            matches.append(source)
    return matches[0] if len(matches) == 1 else ""


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
