/* TD Camera — feed-only lower-left overlay; settings on-demand via VISION→Camera. */
(function (root) {
  "use strict";

  const SOURCE_LABEL = "ThunderDome · Logitech C920";
  const DEFAULT_W = 320;
  const ASPECT = 4 / 3;
  const MIN_W = 200;
  const MIN_H = 150;
  const MARGIN = 12;

  let feed = null;
  let settings = null;
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
  /** Observational subscribers (e.g. Gestures) — share this lease; never open another. */
  const rawFrameSubscribers = new Set();
  let pollCount = 0;
  let deliveredFrameCount = 0;
  let frameSeq = 0;

  function csrfHeaders(extra) {
    const h = Object.assign({}, extra || {});
    try {
      const tok = (root.__HERMES_CONFIG__ && root.__HERMES_CONFIG__.csrfToken) || "";
      if (tok) h["X-Hermes-CSRF-Token"] = tok;
    } catch (_) {}
    return h;
  }

  function notifyVision() {
    try {
      if (typeof root.__biggySyncVisionActivity === "function") {
        root.__biggySyncVisionActivity();
      }
    } catch (_) {}
  }

  function ensureStyle() {
    if (styleReady) return Promise.resolve();
    if (document.getElementById("biggy-td-camera-overlay-css")) {
      styleReady = true;
      return Promise.resolve();
    }
    return new Promise((resolve) => {
      const link = document.createElement("link");
      link.id = "biggy-td-camera-overlay-css";
      link.rel = "stylesheet";
      link.href = "/static/td-camera/viewer-overlay.css";
      link.onload = () => { styleReady = true; resolve(); };
      link.onerror = () => { styleReady = true; resolve(); };
      document.head.appendChild(link);
    });
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

  function composerBoxRect() {
    const box = document.getElementById("composerBox");
    if (!box) return null;
    const br = box.getBoundingClientRect();
    if (!(br.width >= 40) || !(br.height >= 24)) return null;
    // Ignore mis-targeted full-bleed elements.
    if (br.width > window.innerWidth * 0.95 && br.height > window.innerHeight * 0.4) {
      return null;
    }
    return {
      left: br.left,
      top: br.top,
      right: br.right,
      bottom: br.bottom,
      width: br.width,
      height: br.height,
    };
  }

  function intersects(a, b) {
    return !(a.right <= b.left || a.left >= b.right || a.bottom <= b.top || a.top >= b.bottom);
  }

  /**
   * Viewport clamp + narrow overlap with the real #composerBox only.
   * Does NOT invent a full-width bottom exclusion rail.
   */
  function clampRect(left, top, width, height) {
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    let w = Math.min(Math.max(width, MIN_W), vw - MARGIN * 2);
    let h = Math.min(Math.max(height, MIN_H), vh - MARGIN * 2);
    // Preserve feed aspect when resizing from corner.
    if (Math.abs(w / h - ASPECT) > 0.08) {
      h = Math.round(w / ASPECT);
      if (h > vh - MARGIN * 2) {
        h = vh - MARGIN * 2;
        w = Math.round(h * ASPECT);
      }
    }
    let l = Math.max(MARGIN, Math.min(left, vw - w - MARGIN));
    let t = Math.max(MARGIN, Math.min(top, vh - h - MARGIN));
    const box = composerBoxRect();
    if (box) {
      let rect = { left: l, top: t, right: l + w, bottom: t + h };
      if (intersects(rect, box)) {
        // Prefer staying lower-left: slide fully left of composer, else nudge up.
        const leftOf = box.left - w - 8;
        if (leftOf >= MARGIN) {
          l = leftOf;
        } else {
          t = Math.max(MARGIN, box.top - h - 8);
        }
        l = Math.max(MARGIN, Math.min(l, vw - w - MARGIN));
        t = Math.max(MARGIN, Math.min(t, vh - h - MARGIN));
      }
    }
    return { left: l, top: t, width: w, height: h };
  }

  function applyFeedRect(r) {
    if (!feed) return;
    feed.style.left = `${Math.round(r.left)}px`;
    feed.style.top = `${Math.round(r.top)}px`;
    feed.style.width = `${Math.round(r.width)}px`;
    feed.style.height = `${Math.round(r.height)}px`;
    feed.style.right = "auto";
    feed.style.bottom = "auto";
  }

  function defaultFeedRect() {
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const w = Math.min(DEFAULT_W, Math.max(MIN_W, Math.floor(vw * 0.28)));
    const h = Math.round(w / ASPECT);
    // True viewport lower-left — not anchored to a full-width composer plane.
    return clampRect(MARGIN, vh - h - MARGIN, w, h);
  }

  function setMode(msg) {
    const el = settings && settings.querySelector('[data-testid="biggy-td-camera-mode"]');
    if (el) el.textContent = msg || "";
  }

  function setNote(msg) {
    const el = settings && settings.querySelector('[data-testid="biggy-td-camera-note"]');
    if (el) el.textContent = msg || "";
  }

  function setDetails(text) {
    const el = settings && settings.querySelector('[data-testid="biggy-td-camera-details-body"]');
    if (el) el.textContent = text || "";
  }

  function notifyRawFrameSubscribers(evt) {
    if (!rawFrameSubscribers.size) return;
    for (const cb of Array.from(rawFrameSubscribers)) {
      try { cb(evt); } catch (_) { /* subscriber faults stay isolated */ }
    }
  }

  /**
   * Subscribe to raw frames already fetched by this overlay's lease poll.
   * Does not open a lease, does not add polls, does not raise traffic.
   * Returns an unsubscribe function.
   */
  function subscribeRawFrames(cb) {
    if (typeof cb !== "function") return () => {};
    rawFrameSubscribers.add(cb);
    return () => { rawFrameSubscribers.delete(cb); };
  }

  function frameStats() {
    return {
      viewing: !!viewing,
      leaseActive: !!leaseId,
      pollCount,
      deliveredFrameCount,
      frameSeq,
      subscriberCount: rawFrameSubscribers.size,
      openIndependentLease: false,
      increaseRelayTraffic: false,
    };
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
    const canvas = feed && feed.querySelector("#biggy-td-camera-canvas");
    if (canvas) {
      const ctx = canvas.getContext("2d");
      if (ctx) ctx.clearRect(0, 0, canvas.width, canvas.height);
      canvas.hidden = true;
    }
    const raw = feed && feed.querySelector("#biggy-td-camera-raw");
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
    if (pollTimer) { clearTimeout(pollTimer); pollTimer = 0; }
    if (heartbeatTimer) { clearInterval(heartbeatTimer); heartbeatTimer = 0; }
    const lease = leaseId;
    leaseId = null;
    clearFrames();
    notifyRawFrameSubscribers({
      kind: "source_lost",
      reason: "camera_stop",
      at: Date.now(),
    });
    if (root.BiggyTdCameraComposite) {
      try { root.BiggyTdCameraComposite.abort(); } catch (_) {}
    }
    const startBtn = settings && settings.querySelector('[data-testid="biggy-td-camera-start"]');
    const stopBtn = settings && settings.querySelector('[data-testid="biggy-td-camera-stop"]');
    if (startBtn) startBtn.disabled = false;
    if (stopBtn) stopBtn.disabled = true;
    if (!silent) {
      setMode("Camera off");
      setNote("Preview stopped.");
    }
    if (feed) feed.classList.remove("is-live");
    notifyVision();
    if (lease) {
      try {
        await fetch("/api/td-camera/view/stop", {
          method: "POST",
          credentials: "same-origin",
          headers: csrfHeaders({ "Content-Type": "application/json" }),
          body: JSON.stringify({ lease_id: lease }),
          cache: "no-store",
        });
      } catch (_) {}
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
      const seg = data.segmentation || {};
      setDetails(
        [
          `status=${data.status || "ok"}`,
          `camera_active=${!!data.camera_active}`,
          `tunnel_process_running=${!!data.tunnel_process_running} (flag only; not transport readiness)`,
          `source=${data.source || SOURCE_LABEL}`,
          `segmentation_assets=${seg.ready ? "present" : "missing"}`,
          `native_idle_release_sec=${data.native_idle_release_sec || 10}`,
          `feed=${feed ? `${Math.round(feed.offsetWidth)}x${Math.round(feed.offsetHeight)}` : "hidden"}`,
        ].join("\n")
      );
      if (!viewing) {
        setMode("Camera ready");
        setNote("Start shows the feed only in the lower-left. Backdrop is preview-only.");
      }
    } catch (err) {
      setDetails(`health_error=${err && err.message ? err.message : String(err)}`);
    }
  }

  async function pollOnce() {
    if (!viewing || !leaseId || !feed) return;
    const myGen = frameGen;
    pollCount += 1;
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
        const raw = feed.querySelector("#biggy-td-camera-raw");
        const canvas = feed.querySelector("#biggy-td-camera-canvas");
        const backdropEl = settings && settings.querySelector("#biggy-td-camera-backdrop");
        const backdrop = (backdropEl && backdropEl.value) || "off";
        if (backdrop !== "off") canvas.hidden = true;
        await new Promise((resolve, reject) => {
          raw.onload = resolve;
          raw.onerror = reject;
          raw.src = objectUrl;
        });
        if (myGen !== frameGen || !viewing) return;
        deliveredFrameCount += 1;
        frameSeq += 1;
        // Share the decoded raw <img> with observational subscribers (Gestures).
        // No second fetch / lease — same authorized frame already retrieved.
        notifyRawFrameSubscribers({
          kind: "frame",
          seq: frameSeq,
          at: Date.now(),
          image: raw,
          width: raw.naturalWidth || 0,
          height: raw.naturalHeight || 0,
        });
        await ensureComposite();
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
        notifyRawFrameSubscribers({
          kind: "source_lost",
          reason: err && err.message ? err.message : "frame_error",
          at: Date.now(),
        });
      }
    }
    if (viewing && myGen === frameGen) {
      pollTimer = window.setTimeout(pollOnce, 200);
    }
  }

  function ensureFeed() {
    if (feed) return feed;
    feed = document.createElement("section");
    feed.id = "biggyTdCameraFeed";
    feed.className = "biggy-td-camera-feed";
    feed.setAttribute("aria-label", "ThunderDome camera feed");
    feed.setAttribute("data-testid", "biggy-td-camera-overlay");
    feed.innerHTML =
      '<canvas id="biggy-td-camera-canvas" width="640" height="480" hidden '
      + 'data-testid="biggy-td-camera-canvas"></canvas>'
      + '<img id="biggy-td-camera-raw" alt="" hidden width="1" height="1" />'
      + '<div class="biggy-td-camera-drag" data-testid="biggy-td-camera-header" '
      + 'aria-label="Move camera feed" title="Drag"></div>'
      + '<div class="biggy-td-camera-resize" data-testid="biggy-td-camera-resize" '
      + 'aria-label="Resize camera"></div>';
    document.body.appendChild(feed);
    const drag = feed.querySelector('[data-testid="biggy-td-camera-header"]');
    drag.addEventListener("pointerdown", (ev) => {
      const r = feed.getBoundingClientRect();
      dragState = {
        x: ev.clientX,
        y: ev.clientY,
        left: r.left,
        top: r.top,
        width: r.width,
        height: r.height,
      };
      try { drag.setPointerCapture(ev.pointerId); } catch (_) {}
    });
    const resize = feed.querySelector('[data-testid="biggy-td-camera-resize"]');
    resize.addEventListener("pointerdown", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      const r = feed.getBoundingClientRect();
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
    applyFeedRect(defaultFeedRect());
    return feed;
  }

  async function startPreview() {
    const startBtn = settings && settings.querySelector('[data-testid="biggy-td-camera-start"]');
    const stopBtn = settings && settings.querySelector('[data-testid="biggy-td-camera-stop"]');
    if (startBtn) startBtn.disabled = true;
    setMode("Camera ready");
    setNote("Starting preview…");
    try {
      ensureFeed();
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
      if (feed) feed.classList.add("is-live");
      if (stopBtn) stopBtn.disabled = false;
      setMode("Camera previewing");
      // Hide settings so the feed (and Presentation capture) is not covered by chrome.
      closeSettings();
      notifyVision();
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
      notifyVision();
    }
  }

  function onPointerMove(ev) {
    if (dragState && feed) {
      applyFeedRect(clampRect(
        dragState.left + (ev.clientX - dragState.x),
        dragState.top + (ev.clientY - dragState.y),
        dragState.width,
        dragState.height
      ));
      return;
    }
    if (resizeState && feed) {
      applyFeedRect(clampRect(
        resizeState.left,
        resizeState.top,
        resizeState.width + (ev.clientX - resizeState.x),
        resizeState.height + (ev.clientY - resizeState.y)
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
      if (!feed) return;
      const r = feed.getBoundingClientRect();
      applyFeedRect(clampRect(r.left, r.top, r.width, r.height));
    });
    window.addEventListener("pagehide", () => {
      close({ restoreFocus: false });
    });
  }

  function buildSettings() {
    const panel = document.createElement("section");
    panel.id = "biggyTdCameraSettings";
    panel.className = "biggy-td-camera-settings";
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", "Camera settings");
    panel.setAttribute("data-testid", "biggy-td-camera-settings");
    panel.innerHTML =
      '<header class="biggy-td-camera-settings-header">'
      + "<b>Camera settings</b>"
      + '<button type="button" data-testid="biggy-td-camera-close" aria-label="Close camera settings">Close</button>'
      + "</header>"
      + '<div class="biggy-td-camera-settings-body">'
      + '<p class="biggy-td-camera-mode" data-testid="biggy-td-camera-mode">Camera ready</p>'
      + `<p class="biggy-td-camera-source" data-testid="biggy-td-camera-source">Source: ${SOURCE_LABEL}</p>`
      + '<p class="biggy-td-camera-note" data-testid="biggy-td-camera-note"></p>'
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
      + '<p class="biggy-td-camera-hint">Start shows only the camera image (lower-left). Closing settings does not stop the feed.</p>'
      + '<details class="biggy-td-camera-details" data-testid="biggy-td-camera-details">'
      + "<summary>Details</summary>"
      + '<pre data-testid="biggy-td-camera-details-body"></pre>'
      + "</details>"
      + "</div>";

    panel.querySelector('[data-testid="biggy-td-camera-close"]').addEventListener("click", (ev) => {
      ev.preventDefault();
      closeSettings();
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

  function closeSettings() {
    if (settings && settings.parentNode) settings.remove();
    settings = null;
    try { document.getElementById("biggyVision")?.focus({ preventScroll: true }); } catch (_) {}
  }

  function openSettings() {
    installGlobal();
    ensureStyle();
    if (settings) {
      refreshHealthQuiet().catch(() => {});
      const stopBtn = settings.querySelector('[data-testid="biggy-td-camera-stop"]');
      const startBtn = settings.querySelector('[data-testid="biggy-td-camera-start"]');
      if (stopBtn) stopBtn.disabled = !viewing;
      if (startBtn) startBtn.disabled = !!viewing;
      return settings;
    }
    settings = buildSettings();
    document.body.appendChild(settings);
    const stopBtn = settings.querySelector('[data-testid="biggy-td-camera-stop"]');
    const startBtn = settings.querySelector('[data-testid="biggy-td-camera-start"]');
    if (stopBtn) stopBtn.disabled = !viewing;
    if (startBtn) startBtn.disabled = !!viewing;
    setMode(viewing ? "Camera previewing" : "Camera ready");
    setNote(viewing
      ? "Feed is live lower-left. Stop ends the feed; Close hides settings only."
      : "Start shows the feed only in the lower-left. Backdrop is preview-only.");
    refreshHealthQuiet().catch(() => {});
    return settings;
  }

  function isOpen() {
    return !!(settings || feed);
  }

  function isSettingsOpen() {
    return !!settings;
  }

  function isViewing() {
    return !!viewing;
  }

  /** VISION→Camera: settings surface (feed stays independent). */
  function open() {
    return openSettings();
  }

  async function close({ restoreFocus = true } = {}) {
    await stopPreview({ silent: true });
    closeSettings();
    if (feed && feed.parentNode) feed.remove();
    feed = null;
    notifyVision();
    if (restoreFocus) {
      try { document.getElementById("biggyVision")?.focus({ preventScroll: true }); } catch (_) {}
    }
  }

  root.BiggyTdCameraOverlay = {
    open,
    openSettings,
    closeSettings,
    close,
    isOpen,
    isSettingsOpen,
    isViewing,
    stopPreview,
    subscribeRawFrames,
    frameStats,
    /** Test hooks — not for product UI. */
    _test: {
      ensureFeed,
      defaultFeedRect,
      clampRect,
      applyFeedRect,
      frameStats,
      subscriberCount: () => rawFrameSubscribers.size,
    },
  };
})(typeof window !== "undefined" ? window : globalThis);
