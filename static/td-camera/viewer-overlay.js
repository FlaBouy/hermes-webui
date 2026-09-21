/* TD Camera — feed-only lower-left overlay; settings on-demand via VISION→Camera. */
(function (root) {
  "use strict";

  const SOURCE_LABEL = "Smedley · OBSBOT Meet Flip";
  const DEFAULT_W = 320;
  const ASPECT = 4 / 3;
  const MIN_W = 200;
  const MIN_H = 150;
  const MARGIN = 12;
  const BG_STORAGE_KEY = "biggy:td-camera-bg:v1";
  const BG_DB_NAME = "biggy-td-camera-bg-v1";
  const BG_STORE = "images";
  const CAMERA_BG_ASSET = "egs-bg-20260921b";
  const EGS_SRC = "/static/td-camera/backgrounds/egs.jpg?v=" + CAMERA_BG_ASSET;
  const MAX_CUSTOM_BYTES = 8 * 1024 * 1024;
  const ALLOWED_TYPES = Object.freeze(["image/jpeg", "image/png", "image/webp"]);
  const CONSUMERS = Object.freeze({
    preview: "processed",
    freeze_snapshot: "processed_when_backdrop_on_else_raw",
    gestures_vision: "raw",
    presentation_recording: "not_a_camera_consumer",
    outgoing_virtual_camera: "not_provided",
  });

  let feed = null;
  let settings = null;
  let viewing = false;
  let pollTimer = 0;
  let heartbeatTimer = 0;
  let objectUrl = null;
  let lastRawBlob = null;
  let lastRawAt = 0;
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
  let backdropMode = "off";
  let egsImage = null;
  let customImage = null;
  let customName = "";
  let lastCompositeMs = 0;
  let egsLoadPromise = null;
  let starting = false;

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
      link.href = "/static/td-camera/viewer-overlay.css?v=" + CAMERA_BG_ASSET;
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
      s.src = "/static/td-camera/viewer-composite.js?v=" + CAMERA_BG_ASSET;
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
      backdropMode,
      lastCompositeMs,
      consumers: CONSUMERS,
    };
  }

  function persistMode() {
    try {
      root.localStorage.setItem(BG_STORAGE_KEY, JSON.stringify({
        mode: backdropMode === "custom" ? "custom" : (backdropMode === "egs" ? "egs" : "off"),
        customName: customName || "",
      }));
    } catch (_) { /* storage may be blocked */ }
  }

  function readPersistedMode() {
    try {
      const raw = root.localStorage.getItem(BG_STORAGE_KEY);
      if (!raw) return { mode: "off", customName: "" };
      const parsed = JSON.parse(raw);
      const mode = parsed && parsed.mode;
      if (mode === "egs" || mode === "custom" || mode === "off") {
        return { mode, customName: (parsed.customName || "").slice(0, 180) };
      }
    } catch (_) { /* ignore */ }
    return { mode: "off", customName: "" };
  }

  function idbRequest(req) {
    return new Promise((resolve, reject) => {
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error || new Error("idb_failed"));
    });
  }

  function openBgDb() {
    if (!root.indexedDB) return Promise.reject(new Error("IndexedDB unavailable"));
    return new Promise((resolve, reject) => {
      const req = root.indexedDB.open(BG_DB_NAME, 1);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains(BG_STORE)) db.createObjectStore(BG_STORE);
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error || new Error("idb_open_failed"));
    });
  }

  async function saveCustomBlob(blob, name) {
    const db = await openBgDb();
    try {
      const tx = db.transaction(BG_STORE, "readwrite");
      tx.objectStore(BG_STORE).put({ blob, name: name || "", type: blob.type || "image/jpeg" }, "custom");
      await new Promise((resolve, reject) => {
        tx.oncomplete = resolve;
        tx.onerror = () => reject(tx.error || new Error("idb_put_failed"));
        tx.onabort = () => reject(tx.error || new Error("idb_put_aborted"));
      });
    } finally {
      try { db.close(); } catch (_) {}
    }
  }

  async function loadCustomBlob() {
    const db = await openBgDb();
    try {
      const tx = db.transaction(BG_STORE, "readonly");
      const rec = await idbRequest(tx.objectStore(BG_STORE).get("custom"));
      return rec && rec.blob ? rec : null;
    } finally {
      try { db.close(); } catch (_) {}
    }
  }

  async function clearCustomBlob() {
    try {
      const db = await openBgDb();
      try {
        const tx = db.transaction(BG_STORE, "readwrite");
        tx.objectStore(BG_STORE).delete("custom");
        await new Promise((resolve, reject) => {
          tx.oncomplete = resolve;
          tx.onerror = () => reject(tx.error || new Error("idb_delete_failed"));
        });
      } finally {
        try { db.close(); } catch (_) {}
      }
    } catch (_) { /* ignore */ }
  }

  function classifyCustomFile(file) {
    if (!file) throw new Error("No image selected.");
    const alias = {
      "image/jpg": "image/jpeg",
      "image/pjpeg": "image/jpeg",
      "image/x-png": "image/png",
    };
    let type = String(file.type || "").toLowerCase();
    if (alias[type]) type = alias[type];
    const name = String(file.name || "").toLowerCase();
    if (!type) {
      if (/\.jpe?g$/.test(name)) type = "image/jpeg";
      else if (/\.png$/.test(name)) type = "image/png";
      else if (/\.webp$/.test(name)) type = "image/webp";
    }
    if (type === "image/heic" || type === "image/heif" || /\.hei[cf]$/.test(name)) {
      throw new Error("HEIC/HEIF is not decoded here. Export a JPEG, PNG, or WebP.");
    }
    if (ALLOWED_TYPES.indexOf(type) < 0) {
      throw new Error("Use a JPEG, PNG, or WebP image.");
    }
    if (!(file.size > 0) || file.size > MAX_CUSTOM_BYTES) {
      throw new Error("Image must be between 1 byte and 8 MB.");
    }
    return type;
  }

  function validateCustomFile(file) {
    return classifyCustomFile(file);
  }

  function decodeImageFromUrl(url) {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.onload = () => {
        const done = () => {
          if (!(img.naturalWidth > 0) || !(img.naturalHeight > 0)) {
            reject(new Error("Image could not be decoded."));
            return;
          }
          resolve(img);
        };
        if (typeof img.decode === "function") img.decode().then(done).catch(done);
        else done();
      };
      img.onerror = () => reject(new Error("Image could not be decoded."));
      img.src = url;
    });
  }

  async function decodeCustomBlob(blob) {
    if (typeof createImageBitmap === "function") {
      try {
        const bitmap = await createImageBitmap(blob, { imageOrientation: "from-image" });
        if (bitmap && bitmap.width > 0 && bitmap.height > 0) return bitmap;
      } catch (_) { /* fall through to Image decode */ }
    }
    const url = URL.createObjectURL(blob);
    try {
      return await decodeImageFromUrl(url);
    } catch (err) {
      try { URL.revokeObjectURL(url); } catch (_) {}
      throw err;
    }
  }

  async function ensureEgsImage() {
    if (egsImage && egsImage.naturalWidth) return egsImage;
    if (egsLoadPromise) return egsLoadPromise;
    egsLoadPromise = decodeImageFromUrl(EGS_SRC).then((img) => {
      egsImage = img;
      return img;
    }).catch((err) => {
      egsLoadPromise = null;
      throw err;
    });
    return egsLoadPromise;
  }

  async function adoptCustomFile(file) {
    classifyCustomFile(file);
    await ensureComposite();
    if (customFileUrl) {
      try { URL.revokeObjectURL(customFileUrl); } catch (_) {}
      customFileUrl = null;
    }
    const img = await decodeCustomBlob(file);
    customImage = img;
    customName = String(file.name || "custom").slice(0, 180);
    await saveCustomBlob(file, customName);
    backdropMode = "custom";
    persistMode();
    if (root.BiggyTdCameraComposite) {
      root.BiggyTdCameraComposite.setCustomBackdrop(customImage);
    }
    return img;
  }

  async function restorePersistedBackdrop() {
    const saved = readPersistedMode();
    customName = saved.customName || "";
    if (saved.mode === "egs") {
      try {
        await ensureEgsImage();
        backdropMode = "egs";
      } catch (_) {
        backdropMode = "off";
      }
    } else if (saved.mode === "custom") {
      try {
        const rec = await loadCustomBlob();
        if (rec && rec.blob) {
          if (customFileUrl) {
            try { URL.revokeObjectURL(customFileUrl); } catch (_) {}
          }
          customImage = await decodeCustomBlob(rec.blob);
          customName = rec.name || customName;
          backdropMode = "custom";
        } else {
          backdropMode = "off";
        }
      } catch (_) {
        backdropMode = "off";
      }
    } else {
      backdropMode = "off";
    }
    persistMode();
    return backdropMode;
  }

  async function applyBackdropImage() {
    await ensureComposite();
    if (!root.BiggyTdCameraComposite) return;
    if (backdropMode === "egs") {
      await ensureEgsImage();
      root.BiggyTdCameraComposite.setCustomBackdrop(egsImage);
    } else if (backdropMode === "custom" && customImage) {
      root.BiggyTdCameraComposite.setCustomBackdrop(customImage);
    } else {
      root.BiggyTdCameraComposite.setCustomBackdrop(null);
    }
  }

  function syncBackdropSelect() {
    const sel = settings && settings.querySelector("#biggy-td-camera-backdrop");
    if (sel) sel.value = backdropMode === "custom" ? "custom" : (backdropMode === "egs" ? "egs" : "off");
  }

  function backdropLabel() {
    if (backdropMode === "egs") return "EGS";
    if (backdropMode === "custom") return customName ? ("custom:" + customName) : "custom";
    return "off";
  }

  let restoreStarted = false;
  function startRestore() {
    if (restoreStarted) return;
    restoreStarted = true;
    restorePersistedBackdrop().then(() => applyBackdropImage().catch(() => {})).catch(() => {});
  }

  function clearFrames() {
    if (objectUrl) {
      try { URL.revokeObjectURL(objectUrl); } catch (_) {}
      objectUrl = null;
    }
    lastRawBlob = null;
    lastRawAt = 0;
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
    const freezeBtn = settings && settings.querySelector('[data-testid="biggy-td-camera-freeze"]');
    if (startBtn) startBtn.disabled = false;
    if (stopBtn) stopBtn.disabled = true;
    if (freezeBtn) freezeBtn.disabled = true;
    if (!silent) {
      setMode("Camera off");
      setNote("Preview stopped. Overlay closed. Background selection is remembered.");
    }
    if (feed && feed.parentNode) feed.remove();
    feed = null;
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

  async function freezeFrame() {
    if (!viewing) throw new Error("Camera feed is not live.");
    if (!lastRawBlob || (Date.now() - lastRawAt) > 5000) {
      throw new Error("No recent camera frame — wait for the feed, then Freeze again.");
    }
    const backdrop = backdropMode || "off";
    let blob = lastRawBlob;
    let source = "obsbot_local_raw";
    if (backdrop !== "off" && feed) {
      const canvas = feed.querySelector("#biggy-td-camera-canvas");
      if (canvas && !canvas.hidden) {
        blob = await new Promise((resolve, reject) => {
          canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("preview_freeze_failed"))), "image/jpeg", 0.92);
        });
        source = "obsbot_local_preview";
      }
    }
    // Open Focus panel and ingest without a second camera lease/poll.
    if (typeof root.openBiggyVisionSurface === "function") {
      root.openBiggyVisionSurface("focus");
    }
    // Ensure module exists; ingestFreeze can queue until mount.
    if (!root.BiggyVisionFocusGuidance) {
      await new Promise((resolve, reject) => {
        const s = document.createElement("script");
        s.src = "/static/vision/focus-guidance.js";
        s.onload = resolve;
        s.onerror = reject;
        document.head.appendChild(s);
      });
    }
    let api = root.BiggyVisionFocusGuidance;
    if (!api || typeof api.ingestFreeze !== "function") {
      throw new Error("Focus panel unavailable — open VISION→Focus, then Freeze.");
    }
    await api.ingestFreeze({ blob, contentType: blob.type || "image/jpeg", source });
    // Give async Focus mount a moment to paint the queued freeze.
    for (let i = 0; i < 20; i += 1) {
      await new Promise((r) => setTimeout(r, 25));
      const fr = api.getFrame && api.getFrame();
      if (fr && fr.blob) break;
    }
    setNote(`Frozen ${source} — save from Focus to an existing task.`);
    closeSettings();
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
        setNote("Start shows the feed only in the lower-left. Background applies to the processed preview and Freeze; Gestures still receive the raw frame.");
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
        lastRawBlob = blob;
        lastRawAt = Date.now();
        if (objectUrl) {
          try { URL.revokeObjectURL(objectUrl); } catch (_) {}
        }
        objectUrl = URL.createObjectURL(blob);
        const raw = feed.querySelector("#biggy-td-camera-raw");
        const canvas = feed.querySelector("#biggy-td-camera-canvas");
        const backdrop = backdropMode || "off";
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
          processed: false,
        });
        await ensureComposite();
        await applyBackdropImage();
        const compGen = root.BiggyTdCameraComposite.currentGeneration();
        const result = await root.BiggyTdCameraComposite.compositeToCanvas(
          raw,
          canvas,
          backdrop,
          { generation: compGen }
        );
        if (myGen !== frameGen || !viewing) return;
        lastCompositeMs = result.ms || 0;
        if (!result.ok) {
          canvas.hidden = true;
          setMode("Camera previewing");
          setNote(result.error || "Background compositing failed — raw not shown as background-enabled.");
        } else {
          canvas.hidden = false;
          setMode("Camera previewing");
          setNote(
            `Preview ${canvas.width}×${canvas.height} · background=${backdropLabel()}`
              + (result.seg ? ` · seg=${result.seg}` : "")
              + (result.ms != null ? ` · ${result.ms}ms` : "")
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
    feed.setAttribute("aria-label", "Smedley OBSBOT camera feed");
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
    if (viewing || starting) return;
    starting = true;
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
      await applyBackdropImage();
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
      const freezeBtn = settings && settings.querySelector('[data-testid="biggy-td-camera-freeze"]');
      if (freezeBtn) freezeBtn.disabled = false;
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
    } finally {
      starting = false;
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
      + '<button type="button" data-testid="biggy-td-camera-freeze" disabled>Freeze frame</button>'
      + '<label class="biggy-td-camera-bg-label">Background '
      + '<select id="biggy-td-camera-backdrop" data-testid="biggy-td-camera-backdrop" aria-label="Camera background">'
      + '<option value="off">Off</option>'
      + '<option value="egs">EGS</option>'
      + '<option value="custom">Choose image…</option>'
      + "</select></label>"
      + '<input type="file" id="biggy-td-camera-backdrop-file" accept="image/png,image/jpeg,image/webp" hidden '
      + 'data-testid="biggy-td-camera-backdrop-file" />'
      + "</div>"
      + '<p class="biggy-td-camera-hint">Start shows the camera image lower-left. Background composites the person over EGS or a chosen image in the preview and Freeze. Gestures keep the raw frame. Stop releases capture. Closing settings does not stop the feed.</p>'
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
    panel.querySelector('[data-testid="biggy-td-camera-freeze"]').addEventListener("click", () => {
      freezeFrame().catch((err) => {
        setNote(err.message || String(err));
      });
    });
    const fileInput = panel.querySelector("#biggy-td-camera-backdrop-file");
    const sel = panel.querySelector("#biggy-td-camera-backdrop");
    sel.value = backdropMode === "custom" ? "custom" : (backdropMode === "egs" ? "egs" : "off");
    sel.addEventListener("change", async () => {
      const prev = backdropMode;
      const next = sel.value;
      try {
        if (next === "off") {
          backdropMode = "off";
          persistMode();
          if (root.BiggyTdCameraComposite) root.BiggyTdCameraComposite.setCustomBackdrop(null);
          setNote("Background off — original camera image restored.");
          return;
        }
        if (next === "egs") {
          await ensureEgsImage();
          backdropMode = "egs";
          persistMode();
          await applyBackdropImage();
          setNote("EGS background selected. Person is composited over the local EGS image.");
          return;
        }
        if (next === "custom") {
          fileInput.click();
          sel.value = prev === "custom" ? "custom" : (prev === "egs" ? "egs" : "off");
        }
      } catch (err) {
        backdropMode = prev;
        sel.value = prev === "custom" ? "custom" : (prev === "egs" ? "egs" : "off");
        persistMode();
        setNote(err.message || String(err));
      }
    });
    fileInput.addEventListener("change", async () => {
      const file = fileInput.files && fileInput.files[0];
      fileInput.value = "";
      if (!file) {
        syncBackdropSelect();
        return;
      }
      try {
        await adoptCustomFile(file);
        syncBackdropSelect();
        setNote("Custom background saved. Replaces the previous custom image.");
      } catch (err) {
        syncBackdropSelect();
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
      const freezeBtn = settings.querySelector('[data-testid="biggy-td-camera-freeze"]');
      if (stopBtn) stopBtn.disabled = !viewing;
      if (startBtn) startBtn.disabled = !!viewing;
      if (freezeBtn) freezeBtn.disabled = !viewing;
      syncBackdropSelect();
      return settings;
    }
    settings = buildSettings();
    document.body.appendChild(settings);
    const stopBtn = settings.querySelector('[data-testid="biggy-td-camera-stop"]');
    const startBtn = settings.querySelector('[data-testid="biggy-td-camera-start"]');
    const freezeBtn = settings.querySelector('[data-testid="biggy-td-camera-freeze"]');
    if (stopBtn) stopBtn.disabled = !viewing;
    if (startBtn) startBtn.disabled = !!viewing;
    if (freezeBtn) freezeBtn.disabled = !viewing;
    syncBackdropSelect();
    setMode(viewing ? "Camera previewing" : "Camera ready");
    setNote(viewing
      ? "Feed is live lower-left. Stop ends the feed; Close hides settings only."
      : "Start shows the feed only in the lower-left. Background applies to processed preview/Freeze, not Gestures.");
    refreshHealthQuiet().catch(() => {});
    startRestore();
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
    startRestore();
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
    freezeFrame,
    subscribeRawFrames,
    frameStats,
    consumers: CONSUMERS,
    /** Test hooks — not for product UI. */
    _test: {
      ensureFeed,
      defaultFeedRect,
      clampRect,
      applyFeedRect,
      frameStats,
      subscriberCount: () => rawFrameSubscribers.size,
      setLastRawBlob: (blob) => { lastRawBlob = blob; lastRawAt = Date.now(); },
      validateCustomFile,
      persistMode,
      readPersistedMode,
      setBackdropMode: (mode) => { backdropMode = mode; persistMode(); },
      getBackdropMode: () => backdropMode,
      adoptCustomFile,
      restorePersistedBackdrop,
      applyBackdropImage,
      EGS_SRC,
      MAX_CUSTOM_BYTES,
      ALLOWED_TYPES,
      CONSUMERS,
    },
  };
})(typeof window !== "undefined" ? window : globalThis);
