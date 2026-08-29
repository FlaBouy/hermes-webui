"""Read-only, same-origin proxy for the local A.R.G.U.S. 3D graph viewer.

This lets Biggy embed the force-graph renderer (nodes and links from the
A.R.G.U.S. RAG/memory world) in its center panel without the browser making
a direct request to the graph service on port 4719, and without
exposing a general filesystem proxy.

This module never talks to the live V6 HTTP service. It only reads a fixed,
narrow allowlist of static files already built to disk by the graph POC's own
`build.py` step (`3d.html`, `graph-data.js`). Config (the local
viewer directory path) is local-only/gitignored, mirroring
`argus_bridge.py`.

A.R.G.U.S.'s standalone chrome is suppressed in the served `3d.html` before
its first paint: Biggy's reactor is the single A.R.G.U.S. identity/status
display, and Biggy owns chat input, navigation, and workspace presentation.
The iframe contributes only the force-graph canvas and interaction runtime.
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

_PROFILE_CONFIG = Path.home() / ".hermes" / "profiles" / "biggy" / "argus-world.json"
_REPO_LOCAL_CONFIG = Path(__file__).resolve().parents[1] / "argus-world.local.json"
_LEGACY_PROFILE_CONFIG = Path.home() / ".hermes" / "profiles" / "biggy" / "jarvis-v6-world.json"
_LEGACY_REPO_LOCAL_CONFIG = Path(__file__).resolve().parents[1] / "jarvis-v6-world.local.json"

# The graph is a live view of the same NAS-backed corpus that the Smedley RAG
# service indexes.  It is deliberately read-only: ingestion remains owned by
# the existing watcher and this module merely projects its filesystem state.
DEFAULT_RAG_LIBRARY_ROOT = "/Users/rick/Mounts/RAG_Pool/Library"
DEFAULT_RAG_STATUS_URL = "http://127.0.0.1:5004/ingest-status"
DEFAULT_RAG_INGEST_LEDGER = Path.home() / ".jarvis_rag_status" / "ingest_ledger.json"
MAX_WORLD_DOCUMENTS = 4000
_WORLD_CACHE_TTL_S = 20.0
_BROWSABLE_DOCUMENT_SUFFIXES = frozenset({".pdf", ".txt", ".md", ".csv", ".json", ".html", ".htm", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"})
_world_cache_lock = threading.Lock()
_world_cache: tuple[float, bytes] | None = None

# Fixed allowlist: asset name -> content-type. Nothing outside this exact
# set of names is ever readable through this module — deliberately not a
# general static file proxy.
ALLOWED_ASSETS: dict[str, str] = {
    "3d.html": "text/html; charset=utf-8",
    "graph-data.js": "application/javascript; charset=utf-8",
}

# The upstream viewer's standalone chrome is suppressed in the document Biggy serves,
# before an embedded viewer can make its first paint. Biggy owns identity,
# composer, navigation, and workspace presentation; the iframe contributes
# only the force graph canvas and its interaction runtime.
_SUPPRESS_STYLE = (
    "<style id=\"biggy-world-prepaint-reset\">"
    "#side,#collapse,#legend,#hud,#brand,#hint,#toast,"
    "#j-orb,#j-state,#j-status,#j-brain,#jarvis,#j-inbox,#j-tasks,.foot"
    "{display:none!important}"
    "html,body,#g{margin:0!important;width:100%!important;height:100%!important;overflow:hidden!important}"
    "</style>"
)
_BASE_HREF = '<base href="/api/biggy/v6/world/">'
_TRACE_RUNTIME = r'''<script id="biggy-rag-trace-runtime">
(() => {
  'use strict';
  let traceToken = 0;
  let pulseFrame = 0;
  let pulseNode = null;
  let pulseScale = null;
  let destinationTimer = null;
  let traceGroup = null;
  let traceFlowFrame = 0;
  let traceFlowStarted = 0;
  const traceFlowSegments = [];
  const activePages = new Map();
  let directoryFilterPath = '';
  let directoryFilterIds = null;
  let nativeNodeVisibility = null;
  let nativeLinkVisibility = null;
  let ragGalaxyVisible = false;
  let ragHiddenNodeVisibility = null;
  let ragHiddenLinkVisibility = null;
  let filterCameraTimer = null;
  let idleContrastInstalled = false;
  let landingZoomApplied = false;
  let landingCameraPosition = null;
  let landingResetTimer = null;
  let argusActivityState = 'online';
  let nativeParticleSpeed = null;
  let nativeParticleWidth = null;
  const SYNAPSE_REST_SCALE = 1.5;
  const SYNAPSE_WIDTH_SCALE = 2.2;
  const SYNAPSE_THINKING_MULTIPLIER = 2;
  const FULL_SCOPE_NODE_SCALE = 6.4;
  const HOME_SAFE_FIT_SCALE = 1.3;
  const LANDING_CAMERA_FALLBACK = Object.freeze({ x: 0, y: 0, z: 2400 });
  const edge = (a, b) => `${Math.min(a,b)}:${Math.max(a,b)}`;
  const canonicalSource = value => String(value || '').replace(/\\/g, '/').replace(/^.*?\/Library\//, '').replace(/^\/+/, '');
  function graph() { return window.__os && window.__os.Graph; }
  function idOf(value) { return value && value.id !== undefined ? value.id : value; }
  function nodeFor(value) {
    const data = window.__os && window.__os.data;
    return data && data.nodes ? data.nodes[idOf(value)] : null;
  }
  function promptAnchor() {
    const data = window.__os && window.__os.data;
    // The V6 viewer turns graph-data ids into numeric renderer ids, but
    // preserves our canonical key in `p`.
    return (data && data.nodes || []).find(node => String(node && node.p) === 'key:prompt:argus') || null;
  }
  function preparePromptAnchor() {
    const g = graph();
    const anchor = promptAnchor();
    if (!g || !anchor) return null;
    // Keep the live renderer copy pinned at the same origin emitted by the
    // graph projection. Do not reheat the full 1,100+ node simulation here:
    // doing so during iframe boot can monopolize Chrome's renderer long
    // enough to trigger a Page Unresponsive dialog.
    anchor.fx = anchor.fy = anchor.fz = 0;
    anchor.x = anchor.y = anchor.z = 0;
    anchor.val = Math.max(Number(anchor.val) || 0, 22);
    return anchor;
  }
  function fullCorpusCameraPosition() {
    const g = graph();
    const data = window.__os && window.__os.data;
    if (!g || !data || !Array.isArray(data.nodes)) return Object.assign({}, LANDING_CAMERA_FALLBACK);
    let radius = 0;
    for (const node of data.nodes) {
      if (!node || !Number.isFinite(node.x) || !Number.isFinite(node.y) || !Number.isFinite(node.z)) continue;
      radius = Math.max(radius, Math.hypot(node.x, node.y, node.z));
    }
    if (!Number.isFinite(radius) || radius < 1) return Object.assign({}, LANDING_CAMERA_FALLBACK);
    const cameraObject = typeof g.camera === 'function' ? g.camera() : null;
    const verticalFov = Math.max(24, Math.min(90, Number(cameraObject && cameraObject.fov) || 60)) * Math.PI / 180;
    const aspect = Math.max(0.55, Number(cameraObject && cameraObject.aspect) || 1);
    const limitingFov = aspect < 1 ? 2 * Math.atan(Math.tan(verticalFov / 2) * aspect) : verticalFov;
    const distance = Math.max(1400, radius / Math.sin(limitingFov / 2) * 1.18 * HOME_SAFE_FIT_SCALE);
    const current = typeof g.cameraPosition === 'function' ? g.cameraPosition() : null;
    let dx = Number(current && current.x) || 0;
    let dy = Number(current && current.y) || 0;
    let dz = Number(current && current.z) || 1;
    const length = Math.hypot(dx, dy, dz) || 1;
    dx /= length; dy /= length; dz /= length;
    return { x: dx * distance, y: dy * distance, z: dz * distance };
  }
  function applyHomeViewOffset(g) {
    if (!g || typeof g.camera !== 'function') return;
    const camera = g.camera();
    if (!camera || typeof camera.setViewOffset !== 'function') return;
    let desiredCenterX = innerWidth / 2;
    let desiredCenterY = innerHeight / 2;
    try {
      const prompt = parent.document.getElementById('composerBox');
      const frame = parent.document.getElementById('biggyV6World');
      const cockpit = parent.document.getElementById('biggyCockpitStrip');
      const orb = parent.document.getElementById('j-orb');
      if (prompt && frame) {
        const promptRect = prompt.getBoundingClientRect();
        const frameRect = frame.getBoundingClientRect();
        desiredCenterX = promptRect.left + (promptRect.width / 2) - frameRect.left;
      }
      const cockpitBottom = cockpit ? cockpit.getBoundingClientRect().bottom + 14 : 72;
      const orbTop = orb ? orb.getBoundingClientRect().top - 18 : innerHeight - 360;
      if (orbTop > cockpitBottom + 120) desiredCenterY = (cockpitBottom + orbTop) / 2;
    } catch (_) {}
    const shiftLeft = Math.max(-180, Math.min(180, innerWidth / 2 - desiredCenterX));
    const shiftUp = Math.max(0, Math.min(210, innerHeight / 2 - desiredCenterY));
    camera.setViewOffset(innerWidth, innerHeight, shiftLeft, shiftUp, innerWidth, innerHeight);
    camera.updateProjectionMatrix();
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
        ? '#82ffe7' : '#6acbed';
    };
    // In 3d-force-graph any positive link width creates an individual cylinder
    // mesh.  Doing that for every corpus edge generated more than a thousand
    // extra draw objects and eventually hung Chrome. A zero width selects the
    // batched one-pixel line renderer; full opacity and the bright cyan palette
    // retain the required zoomed-out visibility. Active evidence paths remain
    // separate luminous cylinders in drawTraceOverlay().
    const idleWidth = () => 0;
    const idleNodeColor = node => {
      const group = String(node && node.g || '');
      if (group === 'prompt') return '#ffc44d';
      if (group === 'router' || group === 'folder') return '#52b8ff';
      if (group === 'document') return '#b69cff';
      return '#67e8c5';
    };
    // Preserve the original V6 accessors, then increase the ambient synapse
    // tracer size and speed by 50%. While A.R.G.U.S. is gathering evidence,
    // the same native tracers run at twice that new baseline (3x original).
    nativeParticleSpeed = typeof g.linkDirectionalParticleSpeed === 'function'
      ? g.linkDirectionalParticleSpeed() : 0.0035;
    nativeParticleWidth = typeof g.linkDirectionalParticleWidth === 'function'
      ? g.linkDirectionalParticleWidth() : 1.5;
    const particleValue = (accessor, link, fallback) => {
      const value = typeof accessor === 'function' ? accessor(link) : accessor;
      const numeric = Number(value);
      return Number.isFinite(numeric) ? numeric : fallback;
    };
    const activityMultiplier = () => argusActivityState === 'thinking'
      ? SYNAPSE_THINKING_MULTIPLIER : 1;
    g.linkDirectionalParticleSpeed(link => particleValue(nativeParticleSpeed, link, 0.0035)
      * SYNAPSE_REST_SCALE * activityMultiplier());
    g.linkDirectionalParticleWidth(link => particleValue(nativeParticleWidth, link, 1.5)
      * SYNAPSE_WIDTH_SCALE * activityMultiplier());
    // Keep inactive corpus routes legible from the room; the active trace is
    // still brighter and thicker, but the rest of the graph must not vanish.
    g.linkColor(idleColor).linkWidth(idleWidth).linkOpacity(1).nodeColor(idleNodeColor);
    if (typeof g.nodeOpacity === 'function') g.nodeOpacity(1);
    // The stock V6 scene was tuned for close-up inspection and uses subdued
    // Lambert lighting. At Home's full-corpus distance that turns otherwise
    // saturated node colors almost black. Raise ambient fill once so the
    // galaxy remains readable without changing active-trace contrast.
    const THREE = window.__os && window.__os.THREE;
    if (typeof g.lights === 'function' && THREE) {
      const ambient = new THREE.AmbientLight(0xffffff, 2.4);
      const key = new THREE.DirectionalLight(0xbfeaff, 1.6);
      key.position.set(1, 1, 2);
      g.lights([ambient, key]);
    }
    // V6's exponential fog is attractive close up, but at the full-corpus
    // camera distance it reduces nodes and links to near-black. Keep only a
    // very light depth cue in Biggy's embedded galaxy.
    const scene = typeof g.scene === 'function' ? g.scene() : null;
    if (scene && scene.fog && 'density' in scene.fog) scene.fog.density = 0.000035;
    // Brighten only the stock 1,800-point backdrop. Galaxy nodes, links, and
    // active traces keep their existing palettes and contrast.
    if (scene && Array.isArray(scene.children)) {
      const starField = scene.children.find(child => {
        if (!child || !child.isPoints || !child.geometry || !child.material) return false;
        const positions = typeof child.geometry.getAttribute === 'function'
          ? child.geometry.getAttribute('position') : null;
        return !!(positions && positions.count === 1800 && child.material.isPointsMaterial);
      });
      if (starField) {
        starField.material.color.set('#b5caff');
        starField.material.opacity = 1;
        starField.material.size = 1.9;
        starField.material.needsUpdate = true;
      }
    }
    // The stock viewer sizes geometry in world units, so the complete corpus
    // can collapse into sub-pixel dots when the operator zooms far enough out
    // to see every branch. Establish a readable full-scope floor once during
    // boot; this does not rebuild or poll the graph while the camera moves.
    if (typeof g.nodeRelSize === 'function') {
      const currentNodeScale = Number(g.nodeRelSize());
      g.nodeRelSize(Math.max(Number.isFinite(currentNodeScale) ? currentNodeScale : 0, FULL_SCOPE_NODE_SCALE));
    }
    idleContrastInstalled = true;
    return true;
  }
  function setArgusActivityState(state) {
    const next = String(state || '').toLowerCase();
    if (!next || next === argusActivityState) return;
    argusActivityState = next;
    // Accessors read the state without replacing the 1,104-link graph data.
    // refresh() updates particle geometry without reheating the simulation.
    const g = graph();
    if (g && typeof g.refresh === 'function') g.refresh();
  }
  function setRagGalaxyVisible(visible) {
    const g = graph();
    ragGalaxyVisible = visible === true;
    if (!g) return false;
    if (!ragGalaxyVisible) {
      if (ragHiddenNodeVisibility === null) {
        const current = g.nodeVisibility();
        ragHiddenNodeVisibility = current === undefined ? (() => true) : current;
      }
      if (ragHiddenLinkVisibility === null) {
        const current = g.linkVisibility();
        ragHiddenLinkVisibility = current === undefined ? (() => true) : current;
      }
      g.nodeVisibility(() => false);
      g.linkVisibility(() => false);
    } else {
      if (ragHiddenNodeVisibility !== null) g.nodeVisibility(ragHiddenNodeVisibility);
      if (ragHiddenLinkVisibility !== null) g.linkVisibility(ragHiddenLinkVisibility);
      ragHiddenNodeVisibility = null;
      ragHiddenLinkVisibility = null;
    }
    if (traceGroup) traceGroup.visible = ragGalaxyVisible;
    if (typeof g.refresh === 'function') g.refresh();
    return true;
  }
  function restoreBaseGalaxyVisibility() {
    const os = window.__os || {};
    const hadNativeFocus = !!(os.focusNode || os.litSet || os.pathInfo || os.isolateOn);
    // V6's native click-focus intentionally dims every node outside the
    // selected neighbourhood.  A Biggy trace is an overlay on the full
    // corpus, not an isolate operation, so clear that native state before a
    // trace and again on HOME.  Re-apply our room-readable idle accessors only
    // when clearFocus() actually refreshed V6's native colors and widths.
    if (hadNativeFocus && typeof os.clearFocus === 'function') {
      os.clearFocus();
      if (typeof os.hideNodeCard === 'function') os.hideNodeCard();
      idleContrastInstalled = false;
      installIdleContrast();
    }
    return hadNativeFocus;
  }
  function nodePath(node) {
    const match = /^key:(?:dir|doc):(.+)$/.exec(String(node && node.p || ''));
    return match ? match[1] : '';
  }
  function nodeUrl(node) {
    const rel = nodePath(node);
    if (!rel) return '';
    if (String(node.g) === 'document') {
      const page = Number(activePages.get(rel) || 0);
      const fragment = Number.isFinite(page) && page > 0 ? `#page=${Math.floor(page)}` : '';
      return `/api/biggy/rag-file?path=${encodeURIComponent(rel)}${fragment}`;
    }
    if (String(node.g) === 'folder') return `/api/biggy/rag-browse?path=${encodeURIComponent(rel)}`;
    return '';
  }
  function openNode(node) {
    const url = nodeUrl(node);
    if (url) window.open(url, '_blank', 'noopener');
  }
  function visibleThrough(accessor, value) {
    try {
      return (typeof accessor === 'function' ? accessor(value) : accessor) !== false;
    } catch (_) {
      return true;
    }
  }
  function frameFilteredSubtree(selected, visible) {
    const g = graph();
    if (!g || !selected || !visible || !visible.size) return;
    const nodes = Array.from(visible).map(nodeFor).filter(node => node
      && Number.isFinite(node.x) && Number.isFinite(node.y) && Number.isFinite(node.z));
    if (!nodes.length) return;
    const center = { x: selected.x, y: selected.y, z: selected.z };
    const radius = Math.max(50, ...nodes.map(node => Math.hypot(
      node.x - center.x, node.y - center.y, node.z - center.z,
    )));
    const current = g.cameraPosition();
    const controls = g.controls && g.controls();
    const priorTarget = controls && controls.target ? controls.target : { x: 0, y: 0, z: 0 };
    let dx = Number(current && current.x) - Number(priorTarget.x || 0);
    let dy = Number(current && current.y) - Number(priorTarget.y || 0);
    let dz = Number(current && current.z) - Number(priorTarget.z || 0);
    const length = Math.hypot(dx, dy, dz) || 1;
    dx /= length; dy /= length; dz /= length;
    if (controls) controls.autoRotate = false;
    const distance = Math.max(190, Math.min(1800, radius * 2.35));
    g.cameraPosition({
      x: center.x + dx * distance,
      y: center.y + dy * distance,
      z: center.z + dz * distance,
    }, center, 850);
    if (filterCameraTimer) clearTimeout(filterCameraTimer);
    filterCameraTimer = setTimeout(() => {
      const live = g.controls && g.controls();
      if (live && live.target && directoryFilterPath) {
        live.target.set(center.x, center.y, center.z);
        live.autoRotate = true;
        live.update();
      }
    }, 900);
  }
  function restoreDirectoryFilter() {
    const g = graph();
    if (filterCameraTimer) clearTimeout(filterCameraTimer);
    filterCameraTimer = null;
    if (!directoryFilterPath && !directoryFilterIds) return false;
    directoryFilterPath = '';
    directoryFilterIds = null;
    if (g) {
      if (nativeNodeVisibility !== null) g.nodeVisibility(nativeNodeVisibility);
      if (nativeLinkVisibility !== null) g.linkVisibility(nativeLinkVisibility);
      if (typeof g.refresh === 'function') g.refresh();
    }
    parent.postMessage({ type: 'biggy-galaxy-filter-restored' }, location.origin);
    return true;
  }
  function applyDirectoryFilter(path) {
    const g = graph();
    const rel = canonicalSource(path).replace(/\/+$/, '');
    const data = window.__os && window.__os.data;
    if (!g || !rel || !data || !Array.isArray(data.nodes)) return false;
    const selected = data.nodes.find(node => String(node && node.g) === 'folder' && nodePath(node) === rel);
    if (!selected) return false;
    traceToken += 1;
    if (destinationTimer) clearTimeout(destinationTimer);
    destinationTimer = null;
    stopWinnerPulse();
    clearTraceOverlay();
    restoreBaseGalaxyVisibility();
    if (nativeNodeVisibility === null) {
      const current = g.nodeVisibility();
      nativeNodeVisibility = current === undefined ? (() => true) : current;
    }
    if (nativeLinkVisibility === null) {
      const current = g.linkVisibility();
      nativeLinkVisibility = current === undefined ? (() => true) : current;
    }
    const visible = new Set();
    for (const node of data.nodes) {
      const candidate = nodePath(node);
      if (candidate === rel || nodePath(node).startsWith(`${rel}/`)) visible.add(idOf(node));
    }
    directoryFilterPath = rel;
    directoryFilterIds = visible;
    g.nodeVisibility(node => visible.has(idOf(node)) && visibleThrough(nativeNodeVisibility, node));
    g.linkVisibility(link => visible.has(idOf(link.source)) && visible.has(idOf(link.target))
      && visibleThrough(nativeLinkVisibility, link));
    if (typeof g.refresh === 'function') g.refresh();
    frameFilteredSubtree(selected, visible);
    parent.postMessage({
      type: 'biggy-galaxy-filter-focused',
      path: rel,
      nodes: visible.size,
    }, location.origin);
    return true;
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
        const rel = nodePath(node);
        if (directoryFilterPath && String(node && node.g) === 'folder') {
          applyDirectoryFilter(rel);
          return;
        }
        if (directoryFilterPath && String(node && node.g) === 'document') {
          openNode(node);
          return;
        }
        // The verified winner is already the terminal focus of the retrieval.
        // Open it at the bound page on a normal click; do not invoke V6's
        // neighbourhood-focus routine, which would make the rest of the
        // galaxy go dark and destroy the meaning of the visible route.
        if (String(node && node.g) === 'document' && rel && activePages.has(rel)) {
          openNode(node);
          return;
        }
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
    if (!rel) return { ids: [], rel: '', folder: undefined, document: undefined };
    const keys = ['prompt:argus'];
    const parts = rel.split('/').filter(Boolean);
    let cursor = '';
    for (const part of parts.slice(0, -1)) {
      cursor = cursor ? `${cursor}/${part}` : part;
      keys.push(`dir:${cursor}`);
    }
    keys.push(`doc:${rel}`);
    const ids = mapNodes();
    const route = [];
    for (const key of keys) {
      const id = ids.get(key);
      if (id === undefined) break;
      route.push(id);
    }
    return {
      ids: route,
      rel,
      folder: keys.length > 1 ? ids.get(keys[keys.length - 2]) : undefined,
      document: ids.get(keys[keys.length - 1]),
    };
  }
  function stopWinnerPulse() {
    if (pulseFrame) cancelAnimationFrame(pulseFrame);
    pulseFrame = 0;
    if (pulseNode && pulseNode.__threeObj && pulseScale) {
      pulseNode.__threeObj.scale.copy(pulseScale);
    }
    pulseNode = null;
    pulseScale = null;
  }
  function startWinnerPulse(nodeId, token) {
    stopWinnerPulse();
    const winner = nodeFor(nodeId);
    if (!winner) return;
    pulseNode = winner;
    const begin = performance.now();
    const animate = now => {
      if (token !== traceToken || !pulseNode) return stopWinnerPulse();
      const object = pulseNode.__threeObj;
      if (object && object.scale) {
        if (!pulseScale) pulseScale = object.scale.clone();
        // Deliberately quicker pulse so the winning file remains obvious after
        // the camera recenters on its containing directory.
        const factor = 1.08 + 0.18 * (0.5 + 0.5 * Math.sin((now - begin) / 135));
        object.scale.set(pulseScale.x * factor, pulseScale.y * factor, pulseScale.z * factor);
      }
      pulseFrame = requestAnimationFrame(animate);
    };
    pulseFrame = requestAnimationFrame(animate);
  }
  function destinationFamily(folderId) {
    const data = window.__os && window.__os.data;
    const folder = nodeFor(folderId);
    const folderPath = nodePath(folder);
    if (!folderPath) return new Set();
    const ids = new Set([folderId]);
    for (const node of (data && data.nodes) || []) {
      if (String(node && node.g) !== 'document') continue;
      const path = nodePath(node);
      if (path && path.slice(0, path.lastIndexOf('/')) === folderPath) ids.add(node.id);
    }
    return ids;
  }
  function frameDestination(folderId) {
    const g = graph();
    const family = destinationFamily(folderId);
    if (!g || !family.size) return;
    // Frame the terminal folder and all of its file leaves after the route
    // arrives. This is the visual handoff from directory navigation to the
    // exact document choice. ForceGraph3D.zoomToFit still walks the complete
    // Three.js scene before applying its filter; on the full RAG pool that can
    // trip Chrome's watchdog. Compute the small destination-family bounds
    // directly from graph coordinates instead.
    const nodes = Array.from(family).map(nodeFor).filter(node => node
      && Number.isFinite(node.x) && Number.isFinite(node.y) && Number.isFinite(node.z));
    if (!nodes.length) return;
    const center = nodes.reduce((sum, node) => ({
      x: sum.x + node.x, y: sum.y + node.y, z: sum.z + node.z,
    }), { x: 0, y: 0, z: 0 });
    center.x /= nodes.length; center.y /= nodes.length; center.z /= nodes.length;
    const radius = Math.max(42, ...nodes.map(node => Math.hypot(
      node.x - center.x, node.y - center.y, node.z - center.z,
    )));
    const camera = g.cameraPosition();
    const controls = g.controls && g.controls();
    const target = controls && controls.target ? controls.target : { x: 0, y: 0, z: 0 };
    let dx = Number(camera && camera.x) - Number(target.x || 0);
    let dy = Number(camera && camera.y) - Number(target.y || 0);
    let dz = Number(camera && camera.z) - Number(target.z || 0);
    const length = Math.hypot(dx, dy, dz) || 1;
    dx /= length; dy /= length; dz /= length;
    const distance = Math.max(150, radius * 3.2);
    g.cameraPosition({
      x: center.x + dx * distance,
      y: center.y + dy * distance,
      z: center.z + dz * distance,
    }, center, 1100);
  }
  function clearTraceOverlay() {
    const g = graph();
    if (traceFlowFrame) cancelAnimationFrame(traceFlowFrame);
    traceFlowFrame = 0;
    traceFlowStarted = 0;
    traceFlowSegments.length = 0;
    if (!traceGroup) return;
    if (g && typeof g.scene === 'function') g.scene().remove(traceGroup);
    traceGroup.traverse(object => {
      if (object.geometry && typeof object.geometry.dispose === 'function') object.geometry.dispose();
      const materials = Array.isArray(object.material) ? object.material : (object.material ? [object.material] : []);
      for (const material of materials) if (material && typeof material.dispose === 'function') material.dispose();
    });
    traceGroup = null;
  }
  function addTraceSegment(group, from, to, color) {
    const THREE = window.__os && window.__os.THREE;
    if (!THREE || !group || !from || !to) return false;
    const start = new THREE.Vector3(from.x, from.y, from.z);
    const end = new THREE.Vector3(to.x, to.y, to.z);
    const direction = end.clone().sub(start);
    const length = direction.length();
    if (!Number.isFinite(length) || length <= 0) return false;
    const place = (radius, opacity) => {
      const geometry = new THREE.CylinderGeometry(radius, radius, length, 8, 1, true);
      const material = new THREE.MeshBasicMaterial({
        color, transparent: opacity < 1, opacity, depthWrite: opacity >= 1,
      });
      const mesh = new THREE.Mesh(geometry, material);
      mesh.position.copy(start).add(end).multiplyScalar(0.5);
      mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), direction.clone().normalize());
      mesh.renderOrder = 90;
      group.add(mesh);
    };
    place(3.4, 0.24);
    place(1.25, 1);
    const tracer = new THREE.Mesh(
      new THREE.SphereGeometry(5.2, 10, 8),
      new THREE.MeshBasicMaterial({ color: '#d8fff7', transparent: true, opacity: 0.98, depthWrite: false }),
    );
    tracer.renderOrder = 96;
    tracer.position.copy(start);
    group.add(tracer);
    traceFlowSegments.push({ object: tracer, start, end, offset: traceFlowSegments.length * 0.17 });
    return true;
  }
  function startTraceFlow() {
    if (traceFlowFrame) cancelAnimationFrame(traceFlowFrame);
    traceFlowStarted = performance.now();
    const animate = now => {
      if (!traceGroup || !traceFlowSegments.length) {
        traceFlowFrame = 0;
        return;
      }
      const cycle = argusActivityState === 'thinking' ? 620 : 980;
      for (const segment of traceFlowSegments) {
        const progress = (((now - traceFlowStarted) / cycle) + segment.offset) % 1;
        segment.object.position.lerpVectors(segment.start, segment.end, progress);
        const pulse = 1 + 0.42 * Math.sin(progress * Math.PI);
        segment.object.scale.setScalar(pulse);
      }
      traceFlowFrame = requestAnimationFrame(animate);
    };
    traceFlowFrame = requestAnimationFrame(animate);
  }
  function drawTraceOverlay(route, failed) {
    clearTraceOverlay();
    const g = graph();
    const THREE = window.__os && window.__os.THREE;
    if (!g || !THREE || !Array.isArray(route) || route.length < 2) return false;
    traceGroup = new THREE.Group();
    traceGroup.name = 'biggy-rag-trace';
    traceGroup.visible = ragGalaxyVisible;
    for (let i = 0; i < route.length - 1; i++) {
      const from = nodeFor(route[i]), to = nodeFor(route[i + 1]);
      const key = edge(route[i], route[i + 1]);
      addTraceSegment(traceGroup, from, to, key === failed ? '#ef4444' : '#34d399');
    }
    g.scene().add(traceGroup);
    startTraceFlow();
    return true;
  }
  function restore() {
    traceToken += 1;
    if (destinationTimer) clearTimeout(destinationTimer);
    destinationTimer = null;
    stopWinnerPulse();
    clearTraceOverlay();
    activePages.clear();
    restoreDirectoryFilter();
    restoreBaseGalaxyVisibility();
    resetLandingCamera();
  }
  function apply(trace) {
    const g = graph();
    if (!g) { setTimeout(() => apply(trace), 180); return; }
    restoreDirectoryFilter();
    installIdleContrast();
    restoreBaseGalaxyVisibility();
    const resolved = routeFor(trace && trace.source);
    const route = resolved.ids;
    if (route.length < 2) {
      // Never leave an earlier successful route displayed when the current
      // receipt cannot be resolved into this ledger projection.
      restore();
      parent.postMessage({ type: 'biggy-rag-trace-applied', trace: {
        state: 'unresolved',
        source: trace && trace.source || '',
        segments: 0,
      } }, location.origin);
      return;
    }
    const token = ++traceToken;
    const page = Number(trace && trace.pdfPage || 0);
    if (resolved.rel && Number.isFinite(page) && page > 0) activePages.set(resolved.rel, Math.floor(page));
    const failed = trace && trace.state === 'failed' ? edge(route[route.length - 2], route[route.length - 1]) : '';
    drawTraceOverlay(route, failed);
    // The dormant galaxy already owns ambient particles. Query evidence is a
    // separate solid path, so do not rebuild all 1,104 native link/particle
    // objects here. Give the lightweight overlay one paint frame before moving
    // the camera and pulsing the winning file. Never call a ForceGraph link
    // accessor setter here: each setter rebuilds material state for the entire
    // corpus and can crash Chrome's renderer during a response.
    destinationTimer = setTimeout(() => {
      if (token !== traceToken) return;
      frameDestination(resolved.folder);
      destinationTimer = setTimeout(() => {
        if (token === traceToken && !failed && resolved.document !== undefined) {
          startWinnerPulse(resolved.document, token);
        }
      }, 700);
    }, 700);
    parent.postMessage({ type: 'biggy-rag-trace-applied', trace: {
      state: trace && trace.state || 'complete',
      source: trace && trace.source || '',
      pdfPage: Number.isFinite(page) && page > 0 ? Math.floor(page) : null,
      printedPage: Number(trace && trace.printedPage || 0) || null,
      segments: route.length - 1,
    } }, location.origin);
    // Keep the evidence path available for inspection and file-node clicks.
    // The parent clears it when the next prompt begins (or explicitly asks
    // for biggy-rag-trace-clear), then the next verified receipt replaces it.
  }
  addEventListener('message', event => {
    if (event.origin !== location.origin) return;
    const data = event.data || {};
    if (data.type === 'biggy-rag-trace') apply(data.trace || {});
    if (data.type === 'biggy-rag-trace-clear') {
      restore();
      parent.postMessage({ type: 'biggy-rag-trace-cleared' }, location.origin);
    }
    if (data.type === 'biggy-galaxy-filter-focus') applyDirectoryFilter(data.path);
    if (data.type === 'biggy-rag-visibility') setRagGalaxyVisible(data.visible);
    if (data.type === 'biggy-argus-state') setArgusActivityState(data.state);
    if (data.type === 'biggy-home-centerline-sync') applyHomeViewOffset(graph());
    if (data.type === 'biggy-world-pause') {
      const g = graph();
      const controls = g && g.controls && g.controls();
      if (controls) controls.autoRotate = false;
      if (g && typeof g.pauseAnimation === 'function') g.pauseAnimation();
    }
    if (data.type === 'biggy-world-resume') {
      const g = graph();
      if (g && typeof g.resumeAnimation === 'function') g.resumeAnimation();
      const controls = g && g.controls && g.controls();
      if (controls) controls.autoRotate = true;
    }
  });
  const resetLandingCamera = () => {
    const g = graph();
    if (!g) return false;
    const anchor = preparePromptAnchor();
    if (!anchor) return false;
    const controls = g.controls && g.controls();
    if (controls && controls.target) {
      // OrbitControls and an animated ForceGraph camera transition fight each
      // other when auto-rotate is already running.  That race occasionally
      // left HOME looking at empty space.  Settle one deterministic camera
      // first, then restore dormant rotation.
      controls.autoRotate = false;
      controls.target.set(0, 0, 0);
      controls.update();
    }
    if (typeof g.resumeAnimation === 'function') g.resumeAnimation();
    applyHomeViewOffset(g);
    landingCameraPosition = fullCorpusCameraPosition();
    g.cameraPosition(Object.assign({}, landingCameraPosition), { x: 0, y: 0, z: 0 }, 0);
    if (landingResetTimer) clearTimeout(landingResetTimer);
    landingResetTimer = setTimeout(() => {
      const liveControls = g.controls && g.controls();
      if (liveControls && liveControls.target) {
        liveControls.target.set(0, 0, 0);
        liveControls.autoRotate = true;
        liveControls.update();
      }
    }, 240);
    return true;
  };
  const applyLandingCamera = () => {
    const g = graph();
    if (!g || landingZoomApplied) return false;
    const anchor = preparePromptAnchor();
    if (!anchor) return false;
    const c = g.cameraPosition();
    if (!c || !Number.isFinite(c.z)) return false;
    // A pinned root only anchors the physics simulation. OrbitControls has
    // its own target, so make the Biggy Prompt/origin the camera pivot before
    // dormant auto-rotation takes over.
    const controls = g.controls();
    if (controls && controls.target) {
      controls.target.set(0, 0, 0);
      controls.update();
    }
    landingZoomApplied = true;
    // The original V6 intro-fit is intentionally disabled for an embedded
    // corpus. Biggy owns one immediate, readable landing distance instead of
    // a second zoom several seconds after the page appears.
    applyHomeViewOffset(g);
    landingCameraPosition = fullCorpusCameraPosition();
    g.cameraPosition(Object.assign({}, landingCameraPosition), { x: 0, y: 0, z: 0 }, 0);
    return true;
  };
  addEventListener('resize', () => {
    const g = graph();
    if (g) applyHomeViewOffset(g);
  });
  const waitForGraph = () => {
    if (!installIdleContrast()) { setTimeout(waitForGraph, 180); return; }
    setRagGalaxyVisible(ragGalaxyVisible);
    installGalaxyNavigation();
    // The standalone viewer already begins at a wide camera. Give its force
    // layout a brief moment to assign coordinates, then fit the complete
    // corpus around the fixed Biggy Prompt origin without a later push-in.
    setTimeout(() => {
      if (!applyLandingCamera()) { setTimeout(waitForGraph, 180); return; }
      setRagGalaxyVisible(ragGalaxyVisible);
      window.__biggyRagTraceReady = true;
      parent.postMessage({ type: 'biggy-rag-world-ready' }, location.origin);
    }, 650);
  };
  waitForGraph();
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
    for path in (
        _PROFILE_CONFIG,
        _REPO_LOCAL_CONFIG,
        _LEGACY_PROFILE_CONFIG,
        _LEGACY_REPO_LOCAL_CONFIG,
    ):
        data = _read_json_file(path)
        if isinstance(data, dict):
            merged.update(data)
    env_dir = (
        os.environ.get("ARGUS_WORLD_VIEWER_DIR")
        or os.environ.get("JARVIS_V6_VIEWER_DIR")
        or ""
    ).strip()
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
    # The standalone viewer owns a delayed intro-fit, which is correct for its
    # personal-vault page but causes a second camera move after Biggy has
    # already mounted the full corpus. The embedding runtime above owns the
    # single landing camera instead.
    text = text.replace("Graph.onEngineStop(fitOnce);\nsetTimeout(fitOnce, 9000);", "", 1)
    # Biggy never exports screenshots from the embedded galaxy. Retaining the
    # drawing buffer and full multisample antialiasing forces unnecessary GPU
    # copies on every frame and can make the physical glass renderer hang.
    text = text.replace(
        "rendererConfig: { preserveDrawingBuffer: true, antialias: true }",
        "rendererConfig: { preserveDrawingBuffer: false, antialias: false, powerPreference: 'high-performance' }",
        1,
    )
    # Eight segments remain round at the screen sizes used here and reduce
    # static sphere geometry by one third without changing node size/colour.
    text = text.replace(".nodeResolution(12)", ".nodeResolution(6)", 1)
    # Hub labels are still available through the native hover card. Rendering
    # every persistent SpriteText label adds a separate draw call even when the
    # label is too small to read at HOME zoom.
    text = text.replace("let showHubLabels = true,", "let showHubLabels = false,", 1)
    # Preserve fixed coordinates from the generated graph when V6 creates
    # its renderer-node copies. This pins BIGGY PROMPT before force layout
    # starts, so the world settles around the root without a later reheat.
    text = text.replace(
        "val: 1 + Math.sqrt(deg[i]) * 1.6, heat: heatColor(deg[i]) })),",
        "val: 1 + Math.sqrt(deg[i]) * 1.6, heat: heatColor(deg[i]), "
        "fx: n.fx, fy: n.fy, fz: n.fz })),",
        1,
    )
    # Export the viewer's existing Three.js module instance through the same
    # private seam as Graph/data. The trace runtime can then add a handful of
    # lightweight route cylinders without traversing or rebuilding 1,104
    # native link objects during a response.
    text = text.replace("window.__os = { Graph, data,", "window.__os = { Graph, data, THREE,", 1)
    # Biggy embeds only the force graph.  Prevent the standalone V6 shell from
    # issuing requests for chrome that Biggy deliberately does not serve.  The
    # rejected promise follows V6's existing catch path, which hides its own
    # orb/tasks without touching the graph renderer.
    text = text.replace(
        "fetch('/api/brand').then(r=>r.ok?r.json():Promise.reject())",
        "Promise.reject(new Error('Biggy graph-only embed'))",
        1,
    )
    # Keep the hidden element because the upstream module dereferences it
    # during boot; remove only its network source so no logo.png 404 occurs.
    text = text.replace('<img src="logo.png" alt="logo">', '<img alt="logo">', 1)
    # These six V5 add-on bays are optional in the standalone V6 viewer, but
    # they are outside Biggy's intentionally narrow local-only iframe surface
    # (calls, tools, hands, missions, effects, language helpers).  Leaving
    # their relative module tags in place makes the browser request them from
    # this proxy, where they correctly 404; some Chrome sessions then leave
    # the scene black after a fresh server restart.  The core inline graph
    # renderer is independent, so remove the optional bays before first paint
    # rather than broadening the static-file allowlist or re-enabling them.
    for module in ("fx.js", "missions.js", "lang.js", "tools.js", "hands.js", "calls.js"):
        text = text.replace(f'<script type="module" src="{module}?v=1"></script>', "", 1)
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
        "prompt": {"c": "#f4a93a", "r": 22, "glow": 54, "name": "Biggy Prompt", "pace": 0, "pause": 0, "major": True},
        "folder": {"c": "#60a5fa", "r": 7, "glow": 18, "name": "Library folder", "pace": 260, "pause": 360, "major": True},
        "document": {"c": "#a78bfa", "r": 4, "glow": 11, "name": "Indexed document", "pace": 460, "pause": 560, "major": False},
    }
    # The active prompt is the world anchor.  It is pinned at the origin, so
    # the dormant auto-rotation moves the RAG branches around the question
    # rather than allowing the root to drift through the display.
    nodes: list[dict[str, Any]] = [{
        "id": "prompt:argus", "label": "BIGGY PROMPT", "g": "prompt",
        "p": "key:prompt:argus", "fx": 0, "fy": 0, "fz": 0,
    }]
    links: list[dict[str, int]] = []
    index: dict[str, int] = {"prompt:argus": 0}

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
            add("dir:" + cursor, part, "folder", "dir:" + parent_dir if parent_dir else "prompt:argus")
        parent = "dir:" + rel.rsplit("/", 1)[0] if "/" in rel else "prompt:argus"
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


def rag_directory_tree() -> dict[str, Any]:
    """Return the exact bounded folder/document hierarchy shown by the world.

    The tree is derived from ``_build_rag_pool_graph`` rather than walking the
    NAS.  The Filter panel therefore cannot advertise a node that is absent
    from the current galaxy projection, and reading it never starts ingestion
    or touches document contents.
    """
    root: dict[str, Any] = {
        "name": "RAG Pool",
        "path": "",
        "kind": "folder",
        "children": [],
    }
    ledger = resolve_rag_ingest_ledger()
    if ledger is None:
        return {"schema": "biggy.rag_tree.v1", "root": root, "node_count": 0}

    graph = _build_rag_pool_graph(ledger)
    directories: dict[str, dict[str, Any]] = {"": root}
    for node in graph.get("nodes", []):
        if not isinstance(node, dict) or node.get("g") != "folder":
            continue
        node_id = str(node.get("id") or "")
        if not node_id.startswith("dir:"):
            continue
        path = node_id[4:]
        parent_path = path.rsplit("/", 1)[0] if "/" in path else ""
        parent = directories.get(parent_path)
        if parent is None:
            continue
        item = {
            "name": str(node.get("label") or Path(path).name),
            "path": path,
            "kind": "folder",
            "children": [],
        }
        parent["children"].append(item)
        directories[path] = item

    for node in graph.get("nodes", []):
        if not isinstance(node, dict) or node.get("g") != "document":
            continue
        node_id = str(node.get("id") or "")
        if not node_id.startswith("doc:"):
            continue
        path = node_id[4:]
        parent_path = path.rsplit("/", 1)[0] if "/" in path else ""
        parent = directories.get(parent_path)
        if parent is None:
            continue
        parent["children"].append({
            "name": str(node.get("label") or Path(path).name),
            "path": path,
            "kind": "document",
        })

    def sort_children(branch: dict[str, Any]) -> None:
        children = branch.get("children")
        if not isinstance(children, list):
            return
        children.sort(key=lambda item: (
            item.get("kind") != "folder",
            str(item.get("name") or "").casefold(),
        ))
        for child in children:
            if child.get("kind") == "folder":
                sort_children(child)

    sort_children(root)
    return {
        "schema": "biggy.rag_tree.v1",
        "root": root,
        "node_count": max(0, len(graph.get("nodes", [])) - 1),
    }


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
    disposition = "inline" if suffix in {".pdf", ".txt", ".md", ".csv", ".json", ".html", ".htm"} else "attachment"
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


def _ingest_action_target(value: object) -> tuple[str, Path, dict[str, Any]]:
    """Resolve one ledger-known source inside the configured library root."""
    rel = _safe_rag_rel(value)
    if not rel or rel not in _ledger_sources():
        raise ValueError("unknown RAG ledger source")
    root = resolve_rag_library_root()
    if root is None:
        raise ValueError("RAG library is unavailable")
    target = (root / rel).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError("invalid RAG source") from exc
    if not target.is_file():
        raise ValueError("RAG source file is unavailable")

    ledger_path = resolve_rag_ingest_ledger()
    try:
        payload = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path else {}
    except (OSError, json.JSONDecodeError):
        payload = {}
    records = payload.get("files") if isinstance(payload, dict) else {}
    row = next(
        (
            item
            for item in (records.values() if isinstance(records, dict) else [])
            if isinstance(item, dict)
            and _canonical_source(item.get("source") or item.get("path")) == rel
        ),
        None,
    )
    if not isinstance(row, dict):
        raise ValueError("unknown RAG ledger source")
    return rel, target, row


def retry_ingest_source(value: object) -> dict[str, str | bool]:
    """Explicitly re-queue one actionable ledger-known ingestion record.

    This is deliberately narrower than a general ingest endpoint: callers can
    only name a canonical source already recorded in the local ledger, and the
    resolved file must remain below the configured RAG library root.  The
    browser never auto-calls this; it is the affirmative action behind an
    operator's red-card dialog.
    """
    rel, target, row = _ingest_action_target(value)
    phase = str((row or {}).get("phase") or "").lower()
    if phase not in {"detected", "queued", "failed", "quarantined", "quarantine", "error"}:
        raise ValueError("ingestion record is not actionable")

    from api.jarvis_rag_ingest_events import requeue_ingest_source

    result = requeue_ingest_source(str(target))
    return {
        "ok": True,
        "source": rel,
        "file": target.name,
        "state": str(result.get("status") or result.get("phase") or "queued"),
        "queued": bool(result.get("queued", True)),
    }


def disposition_ingest_source(value: object, action: object) -> dict[str, str | bool]:
    """Apply one non-destructive operator disposition to an ingest row."""
    if str(action or "").strip().lower() != "resolve":
        raise ValueError("unsupported ingestion disposition")
    rel, target, row = _ingest_action_target(value)
    phase = str(row.get("phase") or "").strip().lower()
    if phase not in {"detected", "queued", "failed", "quarantined", "quarantine", "error"}:
        raise ValueError("ingestion record is not actionable")

    from api.jarvis_rag_ingest_events import resolve_ingest_source

    result = resolve_ingest_source(str(target))
    return {
        "ok": True,
        "source": rel,
        "file": target.name,
        "state": str(result.get("status") or "resolved"),
        "queued": False,
    }


def _ingest_overview(ledger_path: Path | None) -> dict[str, Any]:
    """Return bounded, display-safe RAG counters and the current activity radar."""
    empty = {"node_count": 0, "link_count": 0, "store_count": 0, "recent": []}
    if ledger_path is None:
        return empty
    try:
        payload = json.loads(ledger_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty
    records = payload.get("files") if isinstance(payload, dict) else {}
    if not isinstance(records, dict):
        return empty

    rows: list[dict[str, str]] = []
    stored = 0
    for row in records.values():
        if not isinstance(row, dict):
            continue
        source = _canonical_source(row.get("source") or row.get("path"))
        if not source:
            continue
        phase = str(row.get("phase") or "unknown").lower()
        reason = str(row.get("reason") or "")
        if phase == "indexed" or bool(row.get("indexed")):
            stored += 1
        issue = phase in {"error", "failed", "quarantined", "quarantine"} or (bool(reason) and phase != "indexed")
        activity = "issue" if issue else ("ingesting" if phase in {"detected", "queued", "indexing", "extracting", "embedding", "active"} else "complete")
        rows.append({
            "file": Path(source).name,
            "source": source,
            "state": activity,
            "phase": phase,
            "updated_at": str(row.get("updated_at") or row.get("indexed_at") or row.get("indexing_at") or ""),
            "reason": reason,
        })

    # This mirrors the bounded graph population. The root is ARGUS PROMPT;
    # every other visible tree node contributes exactly one link.
    rows.sort(key=lambda row: row["updated_at"], reverse=True)
    visible = rows[:MAX_WORLD_DOCUMENTS]
    sources = {row["source"] for row in visible}
    folders = {
        "/".join(source.split("/")[:depth])
        for source in sources
        for depth in range(1, len(source.split("/")))
    }
    node_count = 1 + len(folders) + len(sources)
    # Stable partition keeps newest events in order, with unresolved failures
    # held at the top until they are resolved and become ordinary green rows.
    recent = sorted(rows, key=lambda row: row["state"] != "issue")[:5]
    return {
        "node_count": node_count,
        "link_count": max(0, node_count - 1),
        "store_count": stored,
        "recent": recent,
    }


def ingest_status() -> dict[str, Any]:
    """Return the public RAG state used by the Galaxy and ARGUS overview."""
    started = time.monotonic()
    overview = _ingest_overview(resolve_rag_ingest_ledger())
    try:
        with urlopen(DEFAULT_RAG_STATUS_URL, timeout=2.5) as response:
            raw = response.read(64 * 1024)
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, URLError, ValueError, json.JSONDecodeError):
        # The watcher and Biggy can restart independently.  Its live monitor
        # being briefly unavailable does not mean the durable ingest ledger
        # or the RAG store disappeared.  Keep the operator's counts/radar on
        # glass and expose a reconnecting state instead of a false red alarm.
        return {
            "ok": True,
            "state": "monitor_offline",
            "phase": "reconnecting",
            "last_file": "",
            "last_error": "",
            "indicator": "amber",
            "monitor_online": False,
            "latency_ms": round((time.monotonic() - started) * 1000, 1),
            **overview,
        }
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
        "monitor_online": True,
        "latency_ms": round((time.monotonic() - started) * 1000, 1),
        **overview,
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
