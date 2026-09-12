/* TD Camera overlay — root Biggy GUI viewer (same-origin Hermes /api/td-camera). */
(function (root) {
  "use strict";

  const SOURCE_LABEL = "ThunderDome · Logitech C920";
  const DEFAULT_W = 380;
  const DEFAULT_H = 340;
  const MIN_W = 280;
  const MIN_H = 240;
  const MARGIN = 10;
  const COMPOSER_CLEARANCE = 18;

  let shell = null;
  let viewing = false;
  let pollTimer = 0;
  let heartbeatTimer = 0;
  let objectUrl = null;
  let customFileUrl = null;
  let leaseId = null;
  let frameGen = 0;
  let dragState = null;
  let resizeState = null;
  let bound = false;
  let styleReady = false;
  let compositeReady = false;

  function csrfHeaders(extra) {
    const h = Object.assign({}, extra || {});
    try {
      const tok =
        (root.__HERMES_CONFIG__ && root.__HERMES_CONFIG__.csrfToken) || "";
      if (tok) h["X-Hermes-CSRF-Token"] = tok;
    } catch (_) { /* ignore */ }
    return h;
  }

  function ensureStyle() {
    if (styleReady) return;
    if (document.getElementById("biggy-td-camera-overlay-css")) {
      styleReady = true;
      return;
    }
    const link = document.createElement("link");
    link.id = "biggy-td-camera-overlay-css";
    link.rel = "stylesheet";
    link.href = "/static/td-camera/viewer-overlay.css";
    document.head.appendChild(link);
    styleReady = true;
  }

  async function ensureComposite() {
    if (root.BiggyTdCameraComposite) {
      compositeReady = true;
      return true;
    }
    await new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = "/static/td-camera/viewer-composite.js";
      s.onload = resolve;
      s.onerror = () => reject(new Error("td_composite_script_failed"));
      document.head.appendChild(s);
    });
    compositeReady = !!root.BiggyTdCameraComposite;
    return compositeReady;
  }

  function composerTop() {
    const wrap = document.getElementById("composerWrap")
      || document.querySelector(".composer-wrap");
    if (!wrap) return window.innerHeight - 160;
    const r = wrap.getBoundingClientRect();
    return Math.max(120, Math.round(r.top));
  }

  function clampRect(left, top, width, height) {
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const maxBottom = composerTop() - COMPOSER_CLEARANCE;
    const w = Math.min(Math.max(width, MIN_W), vw - MARGIN * 2);
    const h = Math.min(Math.max(height, MIN_H), Math.max(MIN_H, maxBottom - MARGIN));
    let l = left;
    let t = top;
    l = Math.max(MARGIN, Math.min(l, vw - w - MARGIN));
    t = Math.max(MARGIN, Math.min(t, maxBottom - h));
    if (t < MARGIN) t = MARGIN;
    return { left: l, top: t, width: w, height: h };
  }

  function applyRect(r) {
    if (!shell) return;
    shell.style.left = `${Math.round(r.left)}px`;
    shell.style.top = `${Math.round(r.top)}px`;
    shell.style.width = `${Math.round(r.width)}px`;
    shell.style.height = `${Math.round(r.height)}px`;
    shell.style.right = "auto";
    shell.style.bottom = "auto";
  }

  function defaultRect() {
    const w = Math.min(DEFAULT_W, window.innerWidth - MARGIN * 2);
    const h = Math.min(DEFAULT_H, Math.max(MIN_H, composerTop() - MARGIN - COMPOSER_CLEARANCE));
    return clampRect(MARGIN + 2, composerTop() - COMPOSER_CLEARANCE - h, w, h);
  }

  function setMode(mode) {
    const el = shell && shell.querySelector('[data-testid="biggy-td-camera-mode"]');
    if (el) el.textContent = mode;
  }

  function setNote(msg) {
    const el = shell && shell.querySelector('[data-testid="biggy-td-camera-note"]');
    if (el) el.textContent = msg || "";
  }

  function setDetails(text) {
    const el = shell && shell.querySelector('[data-testid="biggy-td-camera-details-body"]');
    if (el) el.textContent = text || "";
  }

  function clearFrames() {
    if (objectUrl) {
      try { URL.revokeObjectURL(objectUrl); } catch (_) {}
      objectUrl = null;
    }
    if (customFileUrl) {
      try { URL.revokeObjectURL(customFileUrl); } catch (_) {}
      customFileUrl = null;
    }
    const canvas = shell && shell.querySelector("#biggy-td-camera-canvas");
    if (canvas) {
      const ctx = canvas.getContext("2d");
      if (ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
      canvas.hidden = true;
    }
    const raw = shell && shell.querySelector("#biggy-td-camera-raw");
    if (raw) {
      raw.removeAttribute("src");
      raw.hidden = true;
    }
    if (root.BiggyTdCameraComposite) {
      try { root.BiggyTdCameraComposite.setCustomBackdrop(null); } catch (_) {}
      try { root.BiggyTdCameraComposite.reset(); } catch (_) {}
    }
  }

  async function stopPreview({ silent } = {}) {
    viewing = false;
    frameGen += 1;
    if (pollTimer) {
      clearTimeout(pollTimer);
      pollTimer = 0;
    }
    if (heartbeatTimer) {
      clearInterval(heartbeatTimer);
      heartbeatTimer = 0;
    }
    const lease = leaseId;
    leaseId = null;
    clearFrames();
    if (root.BiggyTdCameraComposite) {
      try { root.BiggyTdCameraComposite.abort(); } catch (_) {}
    }
    const startBtn = shell && shell.querySelector('[data-testid="biggy-td-camera-start"]');
    const stopBtn = shell && shell.querySelector('[data-testid="biggy-td-camera-stop"]');
    if (startBtn) startBtn.disabled = false;
    if (stopBtn) stopBtn.disabled = true;
    if (!silent) {
      setMode("Camera off");
      setNote("Preview stopped. Native camera idle-releases ~10s after last frame request.");
    }
    if (lease) {
      try {
        await fetch("/api/td-camera/view/stop", {
          method: "POST",
          credentials: "same-origin",
          headers: csrfHeaders({ "Content-Type": "application/json" }),
          body: JSON.stringify({ lease_id: lease }),
          cache: "no-store",
        });
      } catch (_) { /* best effort */ }
    }
  }

  async function refreshHealthQuiet() {
    try {
      const res = await fetch("/api/td-camera/health", {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setDetails(`health_http=${res.status} error=${data.error || "health_failed"}`);
        return;
      }
      // tunnel_process_running is diagnostic only — never claim transport down from it.
      const seg = data.segmentation || {};
      setDetails(
        [
          `status=${data.status || "ok"}`,
          `camera_active=${!!data.camera_active}`,
          `tunnel_process_running=${!!data.tunnel_process_running} (flag only; not transport readiness)`,
          `source=${data.source || SOURCE_LABEL}`,
          `segmentation_assets=${seg.ready ? "present" : "missing"}`,
          `native_idle_release_sec=${data.native_idle_release_sec || 10}`,
          `bounds=${shell ? `${Math.round(shell.offsetWidth)}x${Math.round(shell.offsetHeight)}` : "n/a"}`,
        ].join("\n")
      );
      if (!viewing) {
        setMode("Camera ready");
        setNote("Backdrop applies to preview only.");
      }
    } catch (err) {
      setDetails(`health_error=${err && err.message ? err.message : String(err)}`);
    }
  }

  async function pollOnce() {
    if (!viewing || !leaseId || !shell) return;
    const myGen = frameGen;
    try {
      const frameRes = await fetch("/api/td-camera/frame.jpg", {
        credentials: "same-origin",
        headers: { "X-TD-Camera-Lease": leaseId, Accept: "image/jpeg" },
        cache: "no-store",
      });
      if (myGen !== frameGen || !viewing) return;
      if (frameRes.status === 429) {
        /* backpressure */
      } else if (!frameRes.ok) {
        const errBody = await frameRes.json().catch(() => ({}));
        throw new Error(errBody.error || `HTTP ${frameRes.status}`);
      } else {
        const blob = await frameRes.blob();
        if (myGen !== frameGen || !viewing) return;
        if (objectUrl) {
          try { URL.revokeObjectURL(objectUrl); } catch (_) {}
        }
        objectUrl = URL.createObjectURL(blob);
        const raw = shell.querySelector("#biggy-td-camera-raw");
        const canvas = shell.querySelector("#biggy-td-camera-canvas");
        const backdropEl = shell.querySelector("#biggy-td-camera-backdrop");
        const backdrop = (backdropEl && backdropEl.value) || "off";
        if (backdrop !== "off") canvas.hidden = true;
        await new Promise((resolve, reject) => {
          raw.onload = resolve;
          raw.onerror = reject;
          raw.src = objectUrl;
        });
        if (myGen !== frameGen || !viewing) return;
        await ensureComposite();
        if (root.BiggyTdCameraComposite && root.BiggyTdCameraComposite.reopen) {
          /* reopen after abort within session handled at Start */
        }
        const compGen = root.BiggyTdCameraComposite.currentGeneration();
        const result = await root.BiggyTdCameraComposite.compositeToCanvas(
          raw,
          canvas,
          backdrop,
          { generation: compGen }
        );
        if (myGen !== frameGen || !viewing) return;
        if (!result.ok) {
          canvas.hidden = true;
          setMode("Camera previewing");
          setNote(result.error || "Backdrop compositing failed — raw not shown.");
        } else {
          canvas.hidden = false;
          setMode("Camera previewing");
          setNote(
            `Preview ${canvas.width}×${canvas.height} · backdrop=${backdrop}`
              + (result.seg ? ` · seg=${result.seg}` : "")
          );
        }
      }
    } catch (err) {
      if (myGen === frameGen && viewing) {
        setNote(err.message || String(err));
      }
    }
    if (viewing && myGen === frameGen) {
      pollTimer = window.setTimeout(pollOnce, 200);
    }
  }

  async function startPreview() {
    const startBtn = shell && shell.querySelector('[data-testid="biggy-td-camera-start"]');
    const stopBtn = shell && shell.querySelector('[data-testid="biggy-td-camera-stop"]');
    if (startBtn) startBtn.disabled = true;
    setMode("Camera ready");
    setNote("Starting preview…");
    try {
      await ensureComposite();
      if (root.BiggyTdCameraComposite && root.BiggyTdCameraComposite.reopen) {
        root.BiggyTdCameraComposite.reopen();
      }
      const res = await fetch("/api/td-camera/view/start", {
        method: "POST",
        credentials: "same-origin",
        headers: csrfHeaders({ "Content-Type": "application/json" }),
        body: "{}",
        cache: "no-store",
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      leaseId = data.lease_id;
      frameGen += 1;
      viewing = true;
      if (stopBtn) stopBtn.disabled = false;
      setMode("Camera previewing");
      heartbeatTimer = window.setInterval(() => {
        if (!viewing || !leaseId) return;
        fetch("/api/td-camera/view/heartbeat", {
          method: "POST",
          credentials: "same-origin",
          headers: csrfHeaders({ "Content-Type": "application/json" }),
          body: JSON.stringify({ lease_id: leaseId }),
          cache: "no-store",
        }).catch(() => {});
      }, 15000);
      pollOnce();
    } catch (err) {
      if (startBtn) startBtn.disabled = false;
      setMode("Camera ready");
      setNote(err.message || String(err));
    }
  }

  function onPointerMove(ev) {
    if (dragState) {
      const dx = ev.clientX - dragState.x;
      const dy = ev.clientY - dragState.y;
      applyRect(clampRect(
        dragState.left + dx,
        dragState.top + dy,
        dragState.width,
        dragState.height
      ));
      return;
    }
    if (resizeState) {
      const dx = ev.clientX - resizeState.x;
      const dy = ev.clientY - resizeState.y;
      applyRect(clampRect(
        resizeState.left,
        resizeState.top,
        resizeState.width + dx,
        resizeState.height + dy
      ));
    }
  }

  function onPointerUp() {
    dragState = null;
    resizeState = null;
  }

  function installGlobal() {
    if (bound) return;
    bound = true;
    window.addEventListener("pointermove", onPointerMove, { passive: true });
    window.addEventListener("pointerup", onPointerUp, { passive: true });
    window.addEventListener("pointercancel", onPointerUp, { passive: true });
    window.addEventListener("resize", () => {
      if (!shell) return;
      const r = shell.getBoundingClientRect();
      applyRect(clampRect(r.left, r.top, r.width, r.height));
    });
    window.addEventListener("pagehide", () => {
      close({ restoreFocus: false });
    });
    document.addEventListener("keydown", (ev) => {
      if (ev.key !== "Escape" || !shell) return;
      const vision = document.getElementById("biggyVisionSurface");
      if (vision) return;
      const menu = document.getElementById("biggyVisionMenu");
      if (menu && !menu.hidden) return;
      ev.preventDefault();
      close();
    }, true);
  }

  function buildShell() {
    const panel = document.createElement("section");
    panel.id = "biggyTdCameraOverlay";
    panel.className = "biggy-td-camera-overlay";
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", "ThunderDome camera");
    panel.setAttribute("data-testid", "biggy-td-camera-overlay");
    panel.innerHTML =
      '<header class="biggy-td-camera-header" data-testid="biggy-td-camera-header">'
      + '<b>Camera</b>'
      + '<button type="button" class="biggy-td-camera-close" data-testid="biggy-td-camera-close" '
      + 'aria-label="Close camera">Close</button>'
      + "</header>"
      + '<div class="biggy-td-camera-body">'
      + '<p class="biggy-td-camera-mode" data-testid="biggy-td-camera-mode">Camera ready</p>'
      + `<p class="biggy-td-camera-source" data-testid="biggy-td-camera-source">Source: ${SOURCE_LABEL}</p>`
      + '<p class="biggy-td-camera-note" data-testid="biggy-td-camera-note">Backdrop applies to preview only.</p>'
      + '<div class="biggy-td-camera-controls">'
      + '<button type="button" data-testid="biggy-td-camera-start">Start</button>'
      + '<button type="button" class="danger" data-testid="biggy-td-camera-stop" disabled>Stop</button>'
      + '<label>Backdrop <select id="biggy-td-camera-backdrop" data-testid="biggy-td-camera-backdrop">'
      + '<option value="off" selected>Off</option>'
      + '<option value="blur">Blur</option>'
      + '<option value="custom">Custom</option>'
      + "</select></label>"
      + '<label class="biggy-td-camera-file">Custom image'
      + '<input type="file" id="biggy-td-camera-backdrop-file" accept="image/png,image/jpeg,image/webp" hidden '
      + 'data-testid="biggy-td-camera-backdrop-file" />'
      + "</label>"
      + "</div>"
      + '<canvas id="biggy-td-camera-canvas" width="640" height="480" hidden '
      + 'data-testid="biggy-td-camera-canvas"></canvas>'
      + '<img id="biggy-td-camera-raw" alt="" hidden width="1" height="1" />'
      + '<details class="biggy-td-camera-details" data-testid="biggy-td-camera-details">'
      + "<summary>Details</summary>"
      + '<pre data-testid="biggy-td-camera-details-body"></pre>'
      + "</details>"
      + "</div>"
      + '<div class="biggy-td-camera-resize" data-testid="biggy-td-camera-resize" '
      + 'aria-label="Resize camera"></div>';

    const header = panel.querySelector('[data-testid="biggy-td-camera-header"]');
    header.addEventListener("pointerdown", (ev) => {
      if (ev.target.closest("button")) return;
      const r = panel.getBoundingClientRect();
      dragState = {
        x: ev.clientX,
        y: ev.clientY,
        left: r.left,
        top: r.top,
        width: r.width,
        height: r.height,
      };
      try { header.setPointerCapture(ev.pointerId); } catch (_) {}
    });

    const resize = panel.querySelector('[data-testid="biggy-td-camera-resize"]');
    resize.addEventListener("pointerdown", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      const r = panel.getBoundingClientRect();
      resizeState = {
        x: ev.clientX,
        y: ev.clientY,
        left: r.left,
        top: r.top,
        width: r.width,
        height: r.height,
      };
      try { resize.setPointerCapture(ev.pointerId); } catch (_) {}
    });

    panel.querySelector('[data-testid="biggy-td-camera-close"]').addEventListener("click", (ev) => {
      ev.preventDefault();
      close();
    });
    panel.querySelector('[data-testid="biggy-td-camera-start"]').addEventListener("click", () => {
      startPreview().catch(() => {});
    });
    panel.querySelector('[data-testid="biggy-td-camera-stop"]').addEventListener("click", () => {
      stopPreview().catch(() => {});
    });
    const fileInput = panel.querySelector("#biggy-td-camera-backdrop-file");
    fileInput.addEventListener("change", async () => {
      const file = fileInput.files && fileInput.files[0];
      fileInput.value = "";
      if (!file) return;
      try {
        await ensureComposite();
        if (customFileUrl) {
          try { URL.revokeObjectURL(customFileUrl); } catch (_) {}
        }
        customFileUrl = URL.createObjectURL(file);
        const img = new Image();
        await new Promise((res, rej) => {
          img.onload = res;
          img.onerror = rej;
          img.src = customFileUrl;
        });
        root.BiggyTdCameraComposite.setCustomBackdrop(img);
        const sel = panel.querySelector("#biggy-td-camera-backdrop");
        if (sel) sel.value = "custom";
        setNote("Custom backdrop loaded for preview.");
      } catch (err) {
        setNote(err.message || String(err));
      }
    });

    return panel;
  }

  function isOpen() {
    return !!shell;
  }

  function open() {
    ensureStyle();
    installGlobal();
    if (shell) {
      applyRect(clampRect(
        shell.getBoundingClientRect().left,
        shell.getBoundingClientRect().top,
        shell.offsetWidth,
        shell.offsetHeight
      ));
      refreshHealthQuiet().catch(() => {});
      return shell;
    }
    shell = buildShell();
    document.body.appendChild(shell);
    applyRect(defaultRect());
    const backdrop = shell.querySelector("#biggy-td-camera-backdrop");
    if (backdrop) backdrop.value = "off";
    setMode("Camera ready");
    setNote("Backdrop applies to preview only.");
    refreshHealthQuiet().catch(() => {});
    try {
      shell.querySelector('[data-testid="biggy-td-camera-close"]')
        ?.focus({ preventScroll: true });
    } catch (_) {}
    return shell;
  }

  async function close({ restoreFocus = true } = {}) {
    await stopPreview({ silent: true });
    if (root.BiggyTdCameraComposite) {
      try { root.BiggyTdCameraComposite.abort(); } catch (_) {}
    }
    clearFrames();
    if (shell && shell.parentNode) shell.remove();
    shell = null;
    setMode("Camera off");
    if (restoreFocus) {
      try { document.getElementById("biggyVision")?.focus({ preventScroll: true }); } catch (_) {}
    }
  }

  root.BiggyTdCameraOverlay = {
    open,
    close,
    isOpen,
    stopPreview,
  };
})(typeof window !== "undefined" ? window : globalThis);
