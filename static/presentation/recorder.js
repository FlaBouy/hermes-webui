/* Biggy Presentation — desktop MediaRecorder of owner-selected GUI display. */
(function (root) {
  "use strict";

  const TABLET_HINT =
    "Presentation recording is desktop-only today. Tablet capture is deferred.";
  const UPLOAD_TIMEOUT_MS = 30000;
  const MAX_QUEUED_BYTES = 12 * 1024 * 1024;
  const MAX_QUEUED_CHUNKS = 8;
  /** Scheduling slack for wall-clock vs max_duration stop (ms). */
  const DURATION_TOLERANCE_MS = 1000;

  let shell = null;
  let phase = "idle"; // idle|choosing|recording|uploading|finalizing|failed|saved
  let generation = 0;
  let mediaStream = null;
  let recorder = null;
  let sessionId = null;
  let startedAt = 0;
  let timerId = 0;
  let seq = 0;
  let mime = "";
  let styleReady = false;
  let lastSaved = null;
  let limits = {
    max_chunk_bytes: 2 * 1024 * 1024,
    max_total_bytes: 500 * 1024 * 1024,
    max_duration_ms: 30 * 60 * 1000,
    max_chunks: 4096,
  };
  /** Bytes reserved for accepted events not yet fully uploaded. */
  let queuedBytes = 0;
  let queuedPieceCount = 0;
  let uploadFailed = null;
  let totalUploadedBytes = 0;
  let pageLifecycleBound = false;
  /** Ordered accepted MediaRecorder events — single consumer preserves byte order. */
  let eventQueue = [];
  let acceptedEvents = 0;
  let consumerActive = false;
  let consumerChain = Promise.resolve();
  let drainWaiters = [];
  let stopping = false;

  function csrfHeaders(extra) {
    const h = Object.assign({}, extra || {});
    try {
      const tok = (root.__HERMES_CONFIG__ && root.__HERMES_CONFIG__.csrfToken) || "";
      if (tok) h["X-Hermes-CSRF-Token"] = tok;
    } catch (_) {}
    return h;
  }

  function isTabletish() {
    try {
      if (root.matchMedia && root.matchMedia("(pointer: coarse)").matches && window.innerWidth < 900) {
        return true;
      }
    } catch (_) {}
    const ua = String(navigator.userAgent || "");
    return /iPad|iPhone|Android/i.test(ua) && !/Macintosh.*Safari/i.test(ua);
  }

  function displayCaptureSupported() {
    return !!(
      navigator.mediaDevices
      && typeof navigator.mediaDevices.getDisplayMedia === "function"
      && typeof MediaRecorder !== "undefined"
    );
  }

  function pickMime() {
    const prefs = [
      "video/mp4;codecs=avc1",
      "video/mp4",
      "video/webm;codecs=vp9",
      "video/webm;codecs=vp8",
      "video/webm",
    ];
    for (const t of prefs) {
      try {
        if (MediaRecorder.isTypeSupported(t)) return t;
      } catch (_) {}
    }
    return "";
  }

  function formatLabel(m) {
    const base = (m || "").split(";")[0];
    if (base === "video/mp4") return "MP4";
    if (base === "video/webm") return "WebM (browser native; MP4 not supported here)";
    return base || "unknown";
  }

  function setPhase(next) {
    phase = next;
    if (shell) shell.dataset.phase = next;
  }

  function ensureStyle() {
    if (styleReady) return;
    if (document.getElementById("biggy-presentation-css")) {
      styleReady = true;
      return;
    }
    const link = document.createElement("link");
    link.id = "biggy-presentation-css";
    link.rel = "stylesheet";
    link.href = "/static/presentation/presentation.css";
    document.head.appendChild(link);
    styleReady = true;
  }

  function setStatus(msg) {
    const el = shell && shell.querySelector('[data-testid="biggy-presentation-status"]');
    if (el) el.textContent = msg || "";
  }

  function setDetails(text) {
    const el = shell && shell.querySelector('[data-testid="biggy-presentation-details-body"]');
    if (el) el.textContent = text || "";
  }

  function setTimer() {
    const el = shell && shell.querySelector('[data-testid="biggy-presentation-timer"]');
    if (!el) return;
    if ((phase !== "recording" && phase !== "uploading") || !startedAt) {
      el.textContent = "00:00";
      return;
    }
    const sec = Math.floor((Date.now() - startedAt) / 1000);
    const m = String(Math.floor(sec / 60)).padStart(2, "0");
    const s = String(sec % 60).padStart(2, "0");
    el.textContent = `${m}:${s}`;
  }

  function releaseTracks() {
    if (recorder) {
      try {
        if (recorder.state !== "inactive") recorder.stop();
      } catch (_) {}
    }
    recorder = null;
    if (mediaStream) {
      try {
        mediaStream.getTracks().forEach((t) => t.stop());
      } catch (_) {}
    }
    mediaStream = null;
  }

  async function sha256Hex(buf) {
    const hash = await crypto.subtle.digest("SHA-256", buf);
    return Array.from(new Uint8Array(hash))
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("");
  }

  /**
   * Timeout covers headers AND body. AbortSignal stays armed until body read finishes.
   */
  async function fetchWithTimeout(url, options, timeoutMs) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      const res = await fetch(url, Object.assign({}, options, { signal: ctrl.signal }));
      const text = await res.text();
      let data = {};
      try {
        data = text ? JSON.parse(text) : {};
      } catch (_) {
        data = {};
      }
      return { res, data, text };
    } finally {
      clearTimeout(timer);
    }
  }

  function splitBlob(blob, maxBytes) {
    if (blob.size <= maxBytes) return [blob];
    const parts = [];
    let offset = 0;
    while (offset < blob.size) {
      parts.push(blob.slice(offset, offset + maxBytes));
      offset += maxBytes;
    }
    return parts;
  }

  function notifyDrainWaiters() {
    if (acceptedEvents === 0 && !consumerActive && eventQueue.length === 0) {
      const waiters = drainWaiters.splice(0, drainWaiters.length);
      waiters.forEach((fn) => fn());
    }
  }

  function failUpload(err, gen) {
    if (gen !== generation) return;
    uploadFailed = err;
    setPhase("failed");
    setStatus(`Upload failed — not saved (${err.message || err}).`);
    eventQueue = [];
    acceptedEvents = 0;
    queuedBytes = 0;
    queuedPieceCount = 0;
    notifyDrainWaiters();
    try {
      if (recorder && recorder.state !== "inactive") recorder.stop();
    } catch (_) {}
    releaseTracks();
  }

  function pieceCountFor(size) {
    return Math.max(1, Math.ceil(size / limits.max_chunk_bytes));
  }

  /**
   * Accept a full dataavailable event synchronously: reserve bytes, enqueue atomically.
   * Splitting/upload happens only in the single consumer — no interleaved pieces.
   */
  function acceptDataEvent(blob, gen, sid) {
    if (gen !== generation || sid !== sessionId || !blob || !blob.size) return false;
    if (uploadFailed) return false;
    if (totalUploadedBytes + queuedBytes + blob.size > limits.max_total_bytes) {
      failUpload(new Error("recording_too_large"), gen);
      return false;
    }
    const pieces = pieceCountFor(blob.size);
    if (seq + queuedPieceCount + pieces > limits.max_chunks) {
      failUpload(new Error("too_many_chunks"), gen);
      return false;
    }
    if (
      acceptedEvents >= MAX_QUEUED_CHUNKS
      || queuedBytes + blob.size > MAX_QUEUED_BYTES
    ) {
      failUpload(new Error("upload_backpressure"), gen);
      return false;
    }
    queuedBytes += blob.size;
    queuedPieceCount += pieces;
    acceptedEvents += 1;
    eventQueue.push({ blob, gen, sid, bytes: blob.size, pieces });
    kickConsumer();
    return true;
  }

  function kickConsumer() {
    if (consumerActive) return;
    consumerActive = true;
    consumerChain = consumerChain.then(runConsumer, runConsumer);
  }

  async function runConsumer() {
    try {
      while (eventQueue.length && !uploadFailed) {
        const item = eventQueue.shift();
        if (!item) break;
        if (item.gen !== generation || item.sid !== sessionId || uploadFailed) {
          queuedBytes = Math.max(0, queuedBytes - item.bytes);
          queuedPieceCount = Math.max(0, queuedPieceCount - item.pieces);
          acceptedEvents = Math.max(0, acceptedEvents - 1);
          continue;
        }
        const parts = splitBlob(item.blob, limits.max_chunk_bytes);
        try {
          for (const part of parts) {
            if (uploadFailed || item.gen !== generation) break;
            const mySeq = seq;
            seq += 1;
            await uploadChunk(part, mySeq, item.gen, item.sid);
          }
        } catch (err) {
          failUpload(err, item.gen);
        } finally {
          queuedBytes = Math.max(0, queuedBytes - item.bytes);
          queuedPieceCount = Math.max(0, queuedPieceCount - item.pieces);
          acceptedEvents = Math.max(0, acceptedEvents - 1);
        }
      }
    } finally {
      consumerActive = false;
      if (eventQueue.length && !uploadFailed) {
        kickConsumer();
      } else {
        notifyDrainWaiters();
      }
    }
  }

  function drainAcceptedEvents() {
    if (acceptedEvents === 0 && !consumerActive && eventQueue.length === 0) {
      return Promise.resolve();
    }
    return new Promise((resolve) => {
      drainWaiters.push(resolve);
      kickConsumer();
      notifyDrainWaiters();
    });
  }

  async function uploadChunk(blob, sequence, gen, sid) {
    if (gen !== generation) throw new Error("generation_mismatch");
    // Allow uploads for this sid even while sessionId retained through finalize.
    if (sid !== sessionId && !(stopping && sessionId === sid)) {
      throw new Error("session_mismatch");
    }
    const buf = await blob.arrayBuffer();
    const digest = await sha256Hex(buf);
    const url = `/api/presentation/session/${encodeURIComponent(sid)}/chunk?seq=${sequence}`;
    let lastErr = null;
    for (let i = 0; i < 3; i += 1) {
      if (gen !== generation) throw new Error("generation_mismatch");
      try {
        const { res, data } = await fetchWithTimeout(
          url,
          {
            method: "POST",
            credentials: "same-origin",
            headers: csrfHeaders({
              "Content-Type": "application/octet-stream",
              "X-Presentation-Chunk-SHA256": digest,
            }),
            body: buf,
            cache: "no-store",
          },
          UPLOAD_TIMEOUT_MS
        );
        if (!res.ok) throw new Error(data.detail || data.error || `chunk HTTP ${res.status}`);
        totalUploadedBytes += buf.byteLength;
        return data;
      } catch (err) {
        lastErr = err;
        await new Promise((r) => setTimeout(r, 200 * (i + 1)));
      }
    }
    throw lastErr || new Error("chunk_upload_failed");
  }

  function onDataAvailable(ev, gen, sid) {
    if (gen !== generation || sid !== sessionId) return;
    if (!ev.data || !ev.data.size) return;
    acceptDataEvent(ev.data, gen, sid);
  }

  async function refreshStatus() {
    try {
      const { res, data } = await fetchWithTimeout(
        "/api/presentation/status",
        {
          method: "GET",
          credentials: "same-origin",
          headers: { Accept: "application/json" },
          cache: "no-store",
        },
        UPLOAD_TIMEOUT_MS
      );
      if (!res.ok) throw new Error(data.detail || data.error || `HTTP ${res.status}`);
      if (data.max_chunk_bytes) limits.max_chunk_bytes = data.max_chunk_bytes;
      if (data.max_total_bytes) limits.max_total_bytes = data.max_total_bytes;
      if (data.max_duration_ms) limits.max_duration_ms = data.max_duration_ms;
      if (data.max_chunks) limits.max_chunks = data.max_chunks;
      setDetails(
        [
          `share_ready=${!!data.ready}`,
          `mount_verified=${!!data.mount_verified}`,
          `error=${data.error || "none"}`,
          `desktop_only=${!!data.desktop_only}`,
          `tablet_supported=${!!data.tablet_supported}`,
          `max_duration_ms=${limits.max_duration_ms}`,
          `max_chunk_bytes=${limits.max_chunk_bytes}`,
          `max_total_bytes=${limits.max_total_bytes}`,
          `audio_default=off`,
          `format_pref=MP4 then WebM`,
        ].join("\n")
      );
      if (!data.ready) {
        setStatus(data.error === "presentation_share_unconfigured"
          ? "Presentation share not configured."
          : "Presentation share unavailable — cannot save.");
        return data;
      }
      if (phase === "idle") setStatus("Ready — Start records the GUI you select (includes Camera overlay).");
      return data;
    } catch (err) {
      setStatus(err.message || String(err));
      return null;
    }
  }

  async function abortSession(sid, reason, gen) {
    if (!sid) return;
    try {
      await fetchWithTimeout(
        `/api/presentation/session/${encodeURIComponent(sid)}/abort`,
        {
          method: "POST",
          credentials: "same-origin",
          headers: csrfHeaders({ "Content-Type": "application/json" }),
          body: JSON.stringify({ reason: reason || "abort" }),
          cache: "no-store",
        },
        UPLOAD_TIMEOUT_MS
      );
    } catch (_) {}
    if (gen === generation && sessionId === sid) sessionId = null;
  }

  function resetUploadState() {
    eventQueue = [];
    acceptedEvents = 0;
    queuedBytes = 0;
    queuedPieceCount = 0;
    uploadFailed = null;
    totalUploadedBytes = 0;
    seq = 0;
    stopping = false;
    consumerChain = Promise.resolve();
    drainWaiters = [];
  }

  async function startRecording() {
    if (phase === "finalizing") {
      setStatus("Previous recording still finalizing — wait for save to finish.");
      return;
    }
    if (phase !== "idle" && phase !== "failed" && phase !== "saved") return;
    const onBtn = shell && shell.querySelector('[data-testid="biggy-presentation-on"]');
    const offBtn = shell && shell.querySelector('[data-testid="biggy-presentation-off"]');
    if (isTabletish() || !displayCaptureSupported()) {
      setStatus(TABLET_HINT);
      return;
    }
    if (onBtn) onBtn.disabled = true;
    generation += 1;
    const gen = generation;
    resetUploadState();
    sessionId = null;
    setPhase("choosing");
    setStatus("Checking share…");
    const st = await refreshStatus();
    if (gen !== generation) return;
    if (!st || !st.ready) {
      setPhase("idle");
      if (onBtn) onBtn.disabled = false;
      return;
    }
    try {
      const { res: startRes, data: startData } = await fetchWithTimeout(
        "/api/presentation/session/start",
        {
          method: "POST",
          credentials: "same-origin",
          headers: csrfHeaders({ "Content-Type": "application/json" }),
          body: "{}",
          cache: "no-store",
        },
        UPLOAD_TIMEOUT_MS
      );
      if (!startRes.ok) throw new Error(startData.detail || startData.error || `HTTP ${startRes.status}`);
      if (startData.max_chunk_bytes) limits.max_chunk_bytes = startData.max_chunk_bytes;
      if (startData.max_total_bytes) limits.max_total_bytes = startData.max_total_bytes;
      if (startData.max_duration_ms) limits.max_duration_ms = startData.max_duration_ms;
      if (startData.max_chunks) limits.max_chunks = startData.max_chunks;
      sessionId = startData.session_id;
      const sid = sessionId;
      mime = pickMime();
      setStatus("Select the Biggy GUI window/tab to record…");
      mediaStream = await navigator.mediaDevices.getDisplayMedia({
        video: { displaySurface: "browser" },
        audio: false,
        preferCurrentTab: true,
      });
      if (gen !== generation) {
        releaseTracks();
        await abortSession(sid, "superseded", gen);
        return;
      }
      mediaStream.getVideoTracks().forEach((t) => {
        t.addEventListener("ended", () => {
          if (generation === gen && (phase === "recording" || phase === "choosing")) {
            stopRecording({ reason: "display_ended" }).catch(() => {});
          }
        });
      });
      recorder = new MediaRecorder(mediaStream, mime ? { mimeType: mime } : undefined);
      mime = recorder.mimeType || mime || "video/webm";
      recorder.ondataavailable = (ev) => {
        onDataAvailable(ev, gen, sid);
      };
      recorder.onerror = () => {
        failUpload(new Error("recorder_error"), gen);
      };
      recorder.start(500);
      setPhase("recording");
      startedAt = Date.now();
      timerId = window.setInterval(() => {
        setTimer();
        if (startedAt && Date.now() - startedAt >= limits.max_duration_ms) {
          setStatus("Max duration reached — stopping…");
          stopRecording({ reason: "max_duration" }).catch(() => {});
        }
      }, 250);
      setTimer();
      if (offBtn) offBtn.disabled = false;
      shell?.classList.add("is-recording");
      setStatus(`Recording… format=${formatLabel(mime)} · audio=off · session=${sid.slice(0, 12)}…`);
    } catch (err) {
      releaseTracks();
      const sid = sessionId;
      await abortSession(sid, "start_failed", gen);
      setPhase("failed");
      if (onBtn) onBtn.disabled = false;
      setStatus(err.message || String(err));
    }
  }

  function resolveDurationMs(wallMs, reason) {
    if (reason === "max_duration") {
      // Limit-triggered stop: always finish within the permitted bound.
      return Math.min(Math.max(1, wallMs), limits.max_duration_ms);
    }
    if (wallMs > limits.max_duration_ms + DURATION_TOLERANCE_MS) {
      return -1; // hard reject
    }
    if (wallMs > limits.max_duration_ms) {
      return limits.max_duration_ms; // within scheduling tolerance
    }
    return Math.max(1, wallMs);
  }

  async function stopRecording({ reason } = {}) {
    if (phase === "finalizing" || phase === "idle") return;
    if (phase === "choosing") {
      generation += 1;
      releaseTracks();
      const sid = sessionId;
      sessionId = null;
      await abortSession(sid, reason || "chooser_cancelled", generation);
      setPhase("idle");
      const onBtn = shell && shell.querySelector('[data-testid="biggy-presentation-on"]');
      if (onBtn) onBtn.disabled = false;
      setStatus("Cancelled before capture started — nothing saved.");
      return;
    }
    if (stopping && (phase === "uploading" || phase === "recording")) {
      // Re-entrant Off while already stopping — wait for existing path.
      return;
    }
    const gen = generation;
    const sid = sessionId;
    const onBtn = shell && shell.querySelector('[data-testid="biggy-presentation-on"]');
    const offBtn = shell && shell.querySelector('[data-testid="biggy-presentation-off"]');
    if (offBtn) offBtn.disabled = true;
    if (timerId) {
      clearInterval(timerId);
      timerId = 0;
    }
    shell?.classList.remove("is-recording");
    const wallMs = startedAt ? Math.max(1, Date.now() - startedAt) : 0;
    startedAt = 0;
    setTimer();
    const durationMs = resolveDurationMs(wallMs, reason);

    if (uploadFailed) {
      setPhase("failed");
      await abortSession(sid, "upload_failed", gen);
      if (onBtn) onBtn.disabled = false;
      setStatus(`Not saved (${uploadFailed.message || uploadFailed}).`);
      releaseTracks();
      return;
    }

    stopping = true;
    setPhase("uploading");
    const flush = new Promise((resolve) => {
      if (!recorder || recorder.state === "inactive") {
        resolve();
        return;
      }
      recorder.addEventListener("stop", () => resolve(), { once: true });
      try { recorder.requestData(); } catch (_) {}
      try { recorder.stop(); } catch (_) { resolve(); }
    });
    await flush;
    releaseTracks();
    // Drain every accepted event (including final stop flush) before finalize.
    await drainAcceptedEvents();
    await consumerChain.catch(() => {});
    stopping = false;

    if (uploadFailed || gen !== generation) {
      await abortSession(sid, "upload_failed", gen);
      if (onBtn) onBtn.disabled = false;
      return;
    }
    if (!sid) {
      setPhase("idle");
      setStatus("Stopped — nothing to save.");
      if (onBtn) onBtn.disabled = false;
      return;
    }
    if (seq < 1 || wallMs < 1 || totalUploadedBytes < 256) {
      await abortSession(sid, reason || "empty", gen);
      setPhase("failed");
      setStatus("Stopped — empty/incomplete recording not saved.");
      if (onBtn) onBtn.disabled = false;
      return;
    }
    if (durationMs < 0) {
      await abortSession(sid, "duration_exceeded", gen);
      setPhase("failed");
      setStatus("Not saved — exceeded max duration.");
      if (onBtn) onBtn.disabled = false;
      return;
    }

    setPhase("finalizing");
    // Keep sessionId + generation through finalize retries; Close must not idle-race.
    sessionId = sid;
    try {
      setStatus("Finalizing…");
      let lastErr = null;
      let data = null;
      for (let i = 0; i < 3; i += 1) {
        if (gen !== generation) throw new Error("finalizing_generation_mismatch");
        try {
          const { res, data: body } = await fetchWithTimeout(
            `/api/presentation/session/${encodeURIComponent(sid)}/finalize`,
            {
              method: "POST",
              credentials: "same-origin",
              headers: csrfHeaders({ "Content-Type": "application/json" }),
              body: JSON.stringify({
                mime,
                duration_ms: durationMs,
                total_chunks: seq,
                title: "Presentation recording",
              }),
              cache: "no-store",
            },
            UPLOAD_TIMEOUT_MS
          );
          data = body;
          if (!res.ok) throw new Error(data.detail || data.error || `HTTP ${res.status}`);
          lastErr = null;
          break;
        } catch (err) {
          lastErr = err;
          await new Promise((r) => setTimeout(r, 250 * (i + 1)));
        }
      }
      if (lastErr) throw lastErr;
      if (gen !== generation) {
        // Superseded mid-finalize — still keep result if saved; do not start overwriting.
        lastSaved = data;
        return;
      }
      lastSaved = data;
      sessionId = null;
      setPhase("saved");
      setStatus(
        `Saved ${data.filename} · ${Math.round((data.duration_ms || 0) / 1000)}s · ${formatLabel(data.mime)}`
      );
      const openBtn = shell && shell.querySelector('[data-testid="biggy-presentation-open"]');
      if (openBtn) openBtn.disabled = false;
    } catch (err) {
      if (gen === generation) {
        setPhase("failed");
        setStatus(
          `Not saved (${err.message || err}). Session ${sid} retained as interrupted — not marked saved.`
        );
      }
    } finally {
      if (gen === generation && onBtn) onBtn.disabled = false;
    }
  }

  async function openSaved() {
    if (!lastSaved || !lastSaved.play_url) {
      setStatus("No saved presentation in this session.");
      return;
    }
    try {
      if (root.__biggyDocumentViewerReady) {
        await root.__biggyDocumentViewerReady;
      }
    } catch (err) {
      setStatus(`Viewer failed to load (${err && err.message ? err.message : err}).`);
      return;
    }
    const api = root.BiggyDocumentViewer;
    if (!api || typeof api.open !== "function") {
      setStatus("In-GUI viewer unavailable.");
      return;
    }
    if (!api.supportsPresentation) {
      setStatus("Viewer is stale (no presentation support) — reload GUI, then Open saved.");
      return;
    }
    let ok = false;
    try {
      ok = !!api.open(lastSaved.play_url, lastSaved.title || lastSaved.filename);
    } catch (err) {
      setStatus(`Viewer open failed (${err && err.message ? err.message : err}).`);
      return;
    }
    if (!ok) {
      setStatus("Viewer rejected this recording URL — not opened.");
    }
  }

  function onPageHide() {
    if (phase === "recording" || phase === "choosing" || phase === "uploading") {
      const sid = sessionId;
      generation += 1;
      releaseTracks();
      eventQueue = [];
      acceptedEvents = 0;
      abortSession(sid, "pagehide", generation);
      setPhase("failed");
      setStatus("Interrupted by page hide — not saved.");
    }
  }

  function installPageLifecycle() {
    if (pageLifecycleBound) return;
    pageLifecycleBound = true;
    window.addEventListener("pagehide", onPageHide);
    window.addEventListener("beforeunload", onPageHide);
  }

  function wireShell(panel) {
    panel.querySelector('[data-testid="biggy-presentation-close"]').addEventListener("click", () => {
      close();
    });
    panel.querySelector('[data-testid="biggy-presentation-on"]').addEventListener("click", () => {
      startRecording().catch(() => {});
    });
    panel.querySelector('[data-testid="biggy-presentation-off"]').addEventListener("click", () => {
      stopRecording({ reason: "owner_off" }).catch(() => {});
    });
    panel.querySelector('[data-testid="biggy-presentation-open"]').addEventListener("click", () => {
      openSaved().catch(() => {});
    });
  }

  function buildShell() {
    const panel = document.createElement("section");
    panel.id = "biggyPresentationPanel";
    panel.className = "biggy-presentation-panel";
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", "Presentation recording");
    panel.setAttribute("data-testid", "biggy-presentation-panel");
    panel.dataset.phase = phase;
    panel.innerHTML =
      '<header class="biggy-presentation-header">'
      + "<b>Presentation</b>"
      + '<span class="biggy-presentation-indicator" aria-hidden="true"></span>'
      + '<span class="biggy-presentation-timer" data-testid="biggy-presentation-timer">00:00</span>'
      + '<button type="button" data-testid="biggy-presentation-close">Close</button>'
      + "</header>"
      + '<div class="biggy-presentation-body">'
      + '<p class="biggy-presentation-status" data-testid="biggy-presentation-status">Checking…</p>'
      + '<div class="biggy-presentation-controls">'
      + '<button type="button" data-testid="biggy-presentation-on">On</button>'
      + '<button type="button" class="danger" data-testid="biggy-presentation-off" disabled>Off</button>'
      + '<button type="button" data-testid="biggy-presentation-open" disabled>Open saved</button>'
      + "</div>"
      + '<p class="biggy-presentation-note">Records the Biggy GUI you select (includes Camera overlay/backdrop). Audio off. Desktop only.</p>'
      + '<details data-testid="biggy-presentation-details"><summary>Details</summary>'
      + '<pre data-testid="biggy-presentation-details-body"></pre></details>'
      + "</div>";
    wireShell(panel);
    return panel;
  }

  function syncShellControls() {
    if (!shell) return;
    shell.dataset.phase = phase;
    const onBtn = shell.querySelector('[data-testid="biggy-presentation-on"]');
    const offBtn = shell.querySelector('[data-testid="biggy-presentation-off"]');
    const openBtn = shell.querySelector('[data-testid="biggy-presentation-open"]');
    if (onBtn) onBtn.disabled = phase === "finalizing" || phase === "recording" || phase === "choosing" || phase === "uploading";
    if (offBtn) offBtn.disabled = phase !== "recording";
    if (openBtn) openBtn.disabled = !lastSaved;
    if (phase === "finalizing") setStatus("Finalizing…");
    else if (phase === "saved" && lastSaved) {
      setStatus(
        `Saved ${lastSaved.filename} · ${Math.round((lastSaved.duration_ms || 0) / 1000)}s · ${formatLabel(lastSaved.mime)}`
      );
    }
  }

  function open() {
    ensureStyle();
    installPageLifecycle();
    if (shell) {
      syncShellControls();
      refreshStatus().catch(() => {});
      return shell;
    }
    shell = buildShell();
    document.body.appendChild(shell);
    syncShellControls();
    if (phase !== "finalizing" && phase !== "saved" && phase !== "failed") {
      setPhase(phase === "idle" ? "idle" : phase);
    }
    if (isTabletish() || !displayCaptureSupported()) {
      setStatus(TABLET_HINT);
      const onBtn = shell.querySelector('[data-testid="biggy-presentation-on"]');
      if (onBtn) onBtn.disabled = true;
    } else if (phase === "idle") {
      refreshStatus().catch(() => {});
    }
    return shell;
  }

  async function close() {
    if (phase === "recording" || phase === "choosing" || phase === "uploading") {
      await stopRecording({ reason: "panel_close" }).catch(() => {});
    }
    // During finalizing: hide panel but keep generation/session/phase so reopen
    // cannot start a racing new recording over the pending save.
    if (shell && shell.parentNode) shell.remove();
    shell = null;
    if (phase !== "finalizing") {
      if (phase !== "saved" && phase !== "failed") {
        setPhase("idle");
      }
    }
  }

  root.BiggyPresentation = {
    open,
    close,
    isOpen: () => !!shell,
    isRecording: () => phase === "recording",
    phase: () => phase,
    /** Test hooks — not for product UI. */
    _test: {
      getLimits: () => Object.assign({}, limits),
      setLimits: (partial) => { Object.assign(limits, partial || {}); },
      getQueuedBytes: () => queuedBytes,
      getAcceptedEvents: () => acceptedEvents,
      getSeq: () => seq,
      DURATION_TOLERANCE_MS,
    },
  };
})(typeof window !== "undefined" ? window : globalThis);
