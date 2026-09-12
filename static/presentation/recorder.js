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
  let lastStatusMsg = "";
  let micEnabledPref = false;
  let micStream = null;
  let micMuted = false;
  let paused = false;
  let pausedAccumMs = 0;
  let pauseStartedAt = 0;
  let linkTaskId = "";
  let linkedFileIds = new Set();
  let linkedEvidenceKeys = new Set();

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

  function pickMime(wantAudio) {
    const withAudio = [
      "video/webm;codecs=vp9,opus",
      "video/webm;codecs=vp8,opus",
      "video/webm;codecs=vp9",
      "video/webm;codecs=vp8",
      "video/webm",
      "video/mp4",
    ];
    const videoOnly = [
      "video/mp4;codecs=avc1",
      "video/mp4",
      "video/webm;codecs=vp9",
      "video/webm;codecs=vp8",
      "video/webm",
    ];
    const prefs = wantAudio ? withAudio : videoOnly;
    for (const cand of prefs) {
      try {
        if (MediaRecorder.isTypeSupported(cand)) return cand;
      } catch (_) {}
    }
    return "";
  }

  function selectedLinkTaskId() {
    const sel = shell && shell.querySelector('[data-testid="biggy-presentation-task"]');
    if (!sel) return linkTaskId || "";
    if (sel.value) {
      linkTaskId = sel.value;
      return linkTaskId;
    }
    // Empty select: honor explicit none only when the latched option is present.
    // If the panel was rebuilt without that option, keep the latched choice.
    if (!linkTaskId) return "";
    const hasLatchOption = Array.from(sel.options || []).some((o) => o.value === linkTaskId);
    if (hasLatchOption) return "";
    return linkTaskId;
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
    try {
      if (typeof root.__biggySyncVisionActivity === "function") {
        root.__biggySyncVisionActivity();
      }
    } catch (_) {}
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
    lastStatusMsg = msg || "";
    const el = shell && shell.querySelector('[data-testid="biggy-presentation-status"]');
    if (el) el.textContent = lastStatusMsg;
    try {
      if (typeof root.__biggySyncVisionActivity === "function") {
        root.__biggySyncVisionActivity();
      }
    } catch (_) {}
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
    const pausedExtra = paused && pauseStartedAt ? (Date.now() - pauseStartedAt) : 0;
    const sec = Math.floor(Math.max(0, Date.now() - startedAt - pausedAccumMs - pausedExtra) / 1000);
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
    if (micStream) {
      try {
        micStream.getTracks().forEach((t) => t.stop());
      } catch (_) {}
    }
    micStream = null;
    paused = false;
    pauseStartedAt = 0;
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
          `session_ttl_sec=7200`,
          `pause_compatible=client_pause_within_session_ttl`,
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
      const wantMic = !!(shell && shell.querySelector('[data-testid="biggy-presentation-mic"]')
        && shell.querySelector('[data-testid="biggy-presentation-mic"]').checked);
      micEnabledPref = wantMic;
      linkTaskId = selectedLinkTaskId();
      mime = pickMime(wantMic);
      setStatus("Select the Biggy GUI window/tab to record…");
      const displayStream = await navigator.mediaDevices.getDisplayMedia({
        video: { displaySurface: "browser" },
        audio: false,
        preferCurrentTab: true,
      });
      mediaStream = displayStream;
      micMuted = false;
      pausedAccumMs = 0;
      pauseStartedAt = 0;
      paused = false;
      if (wantMic) {
        try {
          micStream = await navigator.mediaDevices.getUserMedia({
            audio: { echoCancellation: true, noiseSuppression: true },
            video: false,
          });
          micStream.getAudioTracks().forEach((t) => {
            mediaStream.addTrack(t);
            t.addEventListener("ended", () => {
              if (generation === gen && (phase === "recording" || phase === "uploading")) {
                setStatus("Microphone disconnected — video continues without narration.");
                syncShellControls();
              }
            });
          });
        } catch (micErr) {
          displayStream.getTracks().forEach((tr) => { try { tr.stop(); } catch (_) {} });
          mediaStream = null;
          throw new Error(micErr && micErr.name === "NotAllowedError"
            ? "Microphone permission denied — recording not started."
            : (`Microphone unavailable: ${micErr.message || micErr}`));
        }
      }
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
      // Hide settings before the first recorded frame — consent already granted.
      setStatus(`Recording… format=${formatLabel(mime)} · audio=${wantMic ? 'on' : 'off'} · session=${sid.slice(0, 12)}…`);
      hideSettingsKeepRecording();
      // Two rAFs: let the browser paint without the settings panel before start.
      const paintOk = await new Promise((resolve) => {
        requestAnimationFrame(() => {
          requestAnimationFrame(() => resolve(gen === generation));
        });
      });
      if (!paintOk || gen !== generation) {
        releaseTracks();
        await abortSession(sid, "superseded", gen);
        return;
      }
      recorder.start(500);
      setPhase("recording");
      startedAt = Date.now();
      timerId = window.setInterval(() => {
        setTimer();
        const pausedExtra = paused && pauseStartedAt ? (Date.now() - pauseStartedAt) : 0;
        const activeMs = startedAt
          ? Math.max(0, Date.now() - startedAt - pausedAccumMs - pausedExtra)
          : 0;
        if (startedAt && activeMs >= limits.max_duration_ms) {
          setStatus("Max duration reached — stopping…");
          stopRecording({ reason: "max_duration" }).catch(() => {});
        }
      }, 250);
      setTimer();
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
    if (paused && pauseStartedAt) {
      pausedAccumMs += Math.max(0, Date.now() - pauseStartedAt);
      pauseStartedAt = 0;
      paused = false;
    }
    const wallMs = startedAt ? Math.max(1, Date.now() - startedAt - pausedAccumMs) : 0;
    startedAt = 0;
    pausedAccumMs = 0;
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
      try {
        await linkPresentationToTask(data);
      } catch (linkErr) {
        // File is already saved — never demote to failed/interrupted for optional task link.
        setStatus(
          `Saved ${data.filename} · ${Math.round((data.duration_ms || 0) / 1000)}s · ${formatLabel(data.mime)}`
          + ` · task link failed: ${linkErr && linkErr.message ? linkErr.message : linkErr}`
        );
        const openBtn2 = shell && shell.querySelector('[data-testid="biggy-presentation-open"]');
        if (openBtn2) openBtn2.disabled = false;
      }
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

  function hideSettingsKeepRecording() {
    if (shell && shell.parentNode) shell.remove();
    shell = null;
  }

  function wireShell(panel) {
    panel.querySelector('[data-testid="biggy-presentation-close"]').addEventListener("click", () => {
      closeSettings();
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
    panel.querySelector('[data-testid="biggy-presentation-pause"]').addEventListener("click", () => {
      togglePause();
    });
    panel.querySelector('[data-testid="biggy-presentation-mute"]').addEventListener("click", () => {
      toggleMicMute();
    });
    loadPresentationTasks(panel);
  }

  async function loadPresentationTasks(panel) {
    const sel = panel.querySelector('[data-testid="biggy-presentation-task"]');
    if (!sel) return;
    if (!sel.dataset.boundChange) {
      sel.dataset.boundChange = "1";
      sel.addEventListener("change", () => {
        linkTaskId = sel.value || "";
      });
    }
    try {
      const res = await fetch("/biggy-workspace/api/v1/tasks", {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) return;
      const tasks = Array.isArray(data.tasks) ? data.tasks : [];
      tasks.forEach((task) => {
        if (!task || !task.id) return;
        const opt = document.createElement("option");
        opt.value = task.id;
        opt.textContent = task.title || task.id;
        sel.appendChild(opt);
      });
      if (linkTaskId) {
        if (!Array.from(sel.options).some((o) => o.value === linkTaskId)) {
          const opt = document.createElement("option");
          opt.value = linkTaskId;
          opt.textContent = linkTaskId;
          sel.appendChild(opt);
        }
        sel.value = linkTaskId;
      }
    } catch (_) {}
  }


  async function linkPresentationToTask(meta) {
    const taskId = selectedLinkTaskId();
    if (!taskId || !meta || !meta.file_id) return;
    if (!/^prv_[A-Za-z0-9_-]{8,64}$/.test(String(meta.file_id))) {
      setStatus(`${lastStatusMsg} · task link skipped: invalid file id`);
      return;
    }
    const key = `${taskId}:${meta.file_id}`;
    if (linkedFileIds.has(key)) return;
    const playUrl = `/api/presentation/file/${meta.file_id}`;
    const text =
      `Presentation recording linked (share reference only; video not copied).\n`
      + `file_id=${meta.file_id}\n`
      + `file=${meta.filename || ""}\n`
      + `duration_ms=${meta.duration_ms || 0}\n`
      + `play_url=${playUrl}`;
    const tinyPng =
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==";
    if (!linkedEvidenceKeys.has(key)) {
      const saveRes = await fetch("/biggy-workspace/api/v1/commands", {
        method: "POST",
        credentials: "same-origin",
        headers: csrfHeaders({ "Content-Type": "application/json", Accept: "application/json" }),
        body: JSON.stringify({
          command: "vision_evidence_save",
          params: {
            task_id: taskId,
            kind: "image_intake",
            content_type: "image/png",
            image_base64: tinyPng,
            source: "presentation_recording_ref",
            host: "browser",
            captured_at: new Date().toISOString(),
            source_state: "ok",
            guidance: {
              label: "Presentation recording",
              presentation_ref: {
                file_id: meta.file_id,
                filename: meta.filename || "",
                play_url: playUrl,
              },
            },
          },
        }),
        cache: "no-store",
      });
      const saveData = await saveRes.json().catch(() => ({}));
      if (!saveRes.ok) {
        throw new Error(saveData.error || saveData.detail || `HTTP ${saveRes.status}`);
      }
      linkedEvidenceKeys.add(key);
    }
    const attachRes = await fetch("/biggy-workspace/api/v1/commands", {
      method: "POST",
      credentials: "same-origin",
      headers: csrfHeaders({ "Content-Type": "application/json", Accept: "application/json" }),
      body: JSON.stringify({
        command: "vision_attach",
        params: {
          task_id: taskId,
          text,
          provenance: {
            source: "presentation_recording",
            captured_at: new Date().toISOString(),
            model: "none",
            endpoint_kind: "local",
            endpoint_host: "smedley",
          },
        },
      }),
      cache: "no-store",
    });
    const attachData = await attachRes.json().catch(() => ({}));
    if (!attachRes.ok) {
      throw new Error(attachData.error || attachData.detail || `HTTP ${attachRes.status}`);
    }
    linkedFileIds.add(key);
    setStatus(`${lastStatusMsg} · linked to task (Open recording from Focus evidence)`);
  }

  function togglePause() {
    if (!recorder || phase !== "recording") return;
    try {
      if (!paused && recorder.state === "recording" && typeof recorder.pause === "function") {
        recorder.pause();
        paused = true;
        pauseStartedAt = Date.now();
        setStatus("Paused — time paused is not counted. Resume or Off via VISION→Presentation.");
        syncShellControls();
        hideSettingsKeepRecording();
      } else if (paused && typeof recorder.resume === "function") {
        // Hide settings before resume so the setup panel is not recorded.
        hideSettingsKeepRecording();
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            try {
              recorder.resume();
              if (pauseStartedAt) pausedAccumMs += Math.max(0, Date.now() - pauseStartedAt);
              pauseStartedAt = 0;
              paused = false;
              setStatus("Recording resumed.");
              syncShellControls();
            } catch (err) {
              setStatus(err.message || String(err));
            }
          });
        });
      } else {
        setStatus("Pause/resume is not supported in this browser.");
        syncShellControls();
      }
    } catch (err) {
      setStatus(err.message || String(err));
      syncShellControls();
    }
  }

  function toggleMicMute() {
    if (!micStream) return;
    micMuted = !micMuted;
    micStream.getAudioTracks().forEach((t) => { t.enabled = !micMuted; });
    setStatus(micMuted ? "Microphone muted." : "Microphone unmuted.");
    syncShellControls();
    hideSettingsKeepRecording();
  }

  function buildShell() {
    const panel = document.createElement("section");
    panel.id = "biggyPresentationPanel";
    panel.className = "biggy-presentation-panel";
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", "Presentation settings");
    panel.setAttribute("data-testid", "biggy-presentation-panel");
    panel.dataset.phase = phase;
    panel.innerHTML =
      '<header class="biggy-presentation-header">'
      + "<b>Presentation settings</b>"
      + '<span class="biggy-presentation-indicator" aria-hidden="true"></span>'
      + '<span class="biggy-presentation-timer" data-testid="biggy-presentation-timer">00:00</span>'
      + '<button type="button" data-testid="biggy-presentation-close">Close</button>'
      + "</header>"
      + '<div class="biggy-presentation-body">'
      + '<p class="biggy-presentation-status" data-testid="biggy-presentation-status">Checking…</p>'
      + '<div class="biggy-presentation-controls">'
      + '<button type="button" data-testid="biggy-presentation-on">On</button>'
      + '<button type="button" class="danger" data-testid="biggy-presentation-off" disabled>Off</button>'
      + '<button type="button" data-testid="biggy-presentation-pause" disabled>Pause</button>'
      + '<button type="button" data-testid="biggy-presentation-mute" disabled>Mute mic</button>'
      + '<button type="button" data-testid="biggy-presentation-open" disabled>Open saved</button>'
      + "</div>"
      + '<label class="biggy-presentation-opt"><input type="checkbox" data-testid="biggy-presentation-mic" /> Include microphone (off by default; browser permission required)</label>'
      + '<label class="biggy-presentation-opt">Link saved recording to existing task '
      + '<select data-testid="biggy-presentation-task"><option value="">(none)</option></select></label>'
      + '<p class="biggy-presentation-note">On records the Biggy GUI you select (includes Camera feed). Settings hide while recording — reopen via VISION→Presentation for Off / Pause / Mute / Open saved. Desktop only.</p>'
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
    if (onBtn) {
      onBtn.disabled = phase === "finalizing" || phase === "recording" || phase === "choosing" || phase === "uploading";
    }
    if (offBtn) {
      offBtn.disabled = !(phase === "recording" || phase === "uploading" || phase === "finalizing");
    }
    if (openBtn) openBtn.disabled = !lastSaved;
    const pauseBtn = shell.querySelector('[data-testid="biggy-presentation-pause"]');
    const muteBtn = shell.querySelector('[data-testid="biggy-presentation-mute"]');
    if (pauseBtn) {
      pauseBtn.disabled = phase !== "recording";
      pauseBtn.textContent = paused ? "Resume" : "Pause";
    }
    if (muteBtn) {
      muteBtn.disabled = !(micStream && (phase === "recording" || phase === "uploading"));
      muteBtn.textContent = micMuted ? "Unmute mic" : "Mute mic";
    }
    const micBox = shell.querySelector('[data-testid="biggy-presentation-mic"]');
    if (micBox) {
      micBox.checked = !!micEnabledPref;
      const active = phase === "recording" || phase === "uploading" || phase === "finalizing" || phase === "choosing";
      micBox.disabled = active;
    }
    const taskSel = shell.querySelector('[data-testid="biggy-presentation-task"]');
    if (taskSel && phase === "saved") {
      /* keep selectable for next recording */
    }
    if (phase === "finalizing") setStatus("Finalizing…");
    else if (phase === "recording" || phase === "uploading") {
      setStatus(
        lastStatusMsg
        || "Recording in progress — Off stops and saves. Close hides settings only."
      );
    } else if (phase === "saved" && lastSaved) {
      if (!(lastStatusMsg && lastStatusMsg.indexOf(lastSaved.filename) >= 0 && /Saved/i.test(lastStatusMsg))) {
        setStatus(
          `Saved ${lastSaved.filename} · ${Math.round((lastSaved.duration_ms || 0) / 1000)}s · ${formatLabel(lastSaved.mime)}`
        );
      }
    } else if (phase === "failed") {
      if (lastStatusMsg) setStatus(lastStatusMsg);
    } else if (lastStatusMsg && (phase === "idle" || phase === "choosing")) {
      setStatus(lastStatusMsg);
    }
    setTimer();
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
    if (isTabletish() || !displayCaptureSupported()) {
      setStatus(TABLET_HINT);
      const onBtn = shell.querySelector('[data-testid="biggy-presentation-on"]');
      if (onBtn) onBtn.disabled = true;
    } else if (phase === "idle" || phase === "saved" || phase === "failed") {
      refreshStatus().catch(() => {});
    }
    return shell;
  }

  function closeSettings() {
    // Closing settings must not stop an active recording/finalize.
    if (shell && shell.parentNode) shell.remove();
    shell = null;
    try { document.getElementById("biggyVision")?.focus({ preventScroll: true }); } catch (_) {}
  }

  async function close() {
    // Alias for settings close — never stops capture.
    closeSettings();
  }

  root.BiggyPresentation = {
    open,
    openSettings: open,
    close,
    closeSettings,
    stopRecording,
    isOpen: () => !!shell,
    isRecording: () => phase === "recording" || phase === "uploading" || phase === "finalizing",
    phase: () => phase,
    lastStatus: () => lastStatusMsg,
    /** Test hooks — not for product UI. */
    retryLinkSaved: () => (lastSaved ? linkPresentationToTask(lastSaved) : Promise.resolve()),
    _test: {
      getLimits: () => Object.assign({}, limits),
      getLinkTaskId: () => linkTaskId,
      setLinkTaskId: (id) => { linkTaskId = String(id || ""); },
      getLinkedKeys: () => Array.from(linkedFileIds),
      getLinkedEvidenceKeys: () => Array.from(linkedEvidenceKeys),
      linkPresentationToTask,
      setLimits: (partial) => { Object.assign(limits, partial || {}); },
      getQueuedBytes: () => queuedBytes,
      getAcceptedEvents: () => acceptedEvents,
      getSeq: () => seq,
      DURATION_TOLERANCE_MS,
      failUpload,
      getGeneration: () => generation,
    },
  };
})(typeof window !== "undefined" ? window : globalThis);
