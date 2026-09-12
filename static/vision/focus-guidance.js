/* VISION Focus + Screen Guidance — Hermes root surface (browser permissions only). */
(function (root) {
  "use strict";

  const ORIGINAL_MAX = 1500000;
  const INFERENCE_MAX = 400000;
  let hostEl = null;
  let frame = null;
  /** Frame identity generation — advances on replace/crop/clear/unmount/lost. */
  let generation = 0;
  /** Analyze request generation — advances when answers must be discarded. */
  let analyzeGen = 0;
  let crop = null;
  let cropDrag = null;
  let lastGuidance = null;
  let styleReady = false;
  let pendingFreeze = null;
  let uiPrefs = { taskId: "", role: "", finding: "", expected: "", question: "" };
  let previewToken = 0;
  let frameSeq = 0;

  function csrfHeaders(extra) {
    const h = Object.assign({ "Content-Type": "application/json", Accept: "application/json" }, extra || {});
    try {
      const tok = (root.__HERMES_CONFIG__ && root.__HERMES_CONFIG__.csrfToken) || "";
      if (tok) h["X-Hermes-CSRF-Token"] = tok;
    } catch (_) {}
    return h;
  }

  function ensureStyle() {
    if (styleReady || document.getElementById("biggy-vision-focus-css")) {
      styleReady = true;
      return;
    }
    const link = document.createElement("link");
    link.id = "biggy-vision-focus-css";
    link.rel = "stylesheet";
    link.href = "/static/vision/focus-guidance.css";
    document.head.appendChild(link);
    styleReady = true;
  }

  function setStatus(msg) {
    const el = hostEl && hostEl.querySelector('[data-testid="biggy-focus-status"]');
    if (el) el.textContent = msg || "";
  }

  function setGuideOut(msg) {
    const el = hostEl && hostEl.querySelector('[data-testid="biggy-guidance-answer"]');
    if (el) el.textContent = msg || "";
  }

  function clearGuidanceAnswer(reason) {
    analyzeGen += 1;
    lastGuidance = null;
    setGuideOut(reason || "");
  }

  function browserHostLabel() {
    try {
      return (location && location.hostname) ? String(location.hostname).slice(0, 120) : "browser";
    } catch (_) {
      return "browser";
    }
  }

  function blobToBase64(blob) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        const s = String(reader.result || "");
        const i = s.indexOf(",");
        resolve(i >= 0 ? s.slice(i + 1) : s);
      };
      reader.onerror = reject;
      reader.readAsDataURL(blob);
    });
  }

  function intakeRejectReason(byteLength, contentType) {
    const allowed = { "image/png": 1, "image/jpeg": 1, "image/webp": 1 };
    if (!allowed[contentType]) return "Unsupported image type.";
    if (!byteLength || byteLength < 1) return "Empty image body.";
    if (byteLength > ORIGINAL_MAX) {
      return `Image exceeds ${ORIGINAL_MAX} byte intake limit.`;
    }
    return null;
  }

  async function buildInferenceImage(blob, contentType) {
    if (blob.size <= INFERENCE_MAX) {
      return { blob, contentType: contentType || "image/png" };
    }
    const url = URL.createObjectURL(blob);
    try {
      const img = await new Promise((resolve, reject) => {
        const i = new Image();
        i.onload = () => resolve(i);
        i.onerror = () => reject(new Error("Could not decode image for inference resize"));
        i.src = url;
      });
      let w = img.naturalWidth || 1280;
      let h = img.naturalHeight || 720;
      const canvas = document.createElement("canvas");
      let quality = 0.85;
      let out = null;
      for (let attempt = 0; attempt < 8; attempt += 1) {
        canvas.width = Math.max(64, Math.round(w));
        canvas.height = Math.max(64, Math.round(h));
        canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
        out = await new Promise((res) => canvas.toBlob(res, "image/jpeg", quality));
        if (out && out.size <= INFERENCE_MAX) break;
        w *= 0.75;
        h *= 0.75;
        quality = Math.max(0.45, quality - 0.08);
      }
      if (!out || out.size > INFERENCE_MAX) {
        throw new Error(`Could not resize under ${INFERENCE_MAX} bytes for local analysis.`);
      }
      return { blob: out, contentType: "image/jpeg" };
    } finally {
      URL.revokeObjectURL(url);
    }
  }

  async function loadTasks() {
    const sel = hostEl && hostEl.querySelector('[data-testid="biggy-focus-task"]');
    if (!sel) return;
    try {
      const res = await fetch("/biggy-workspace/api/v1/tasks", {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
        cache: "no-store",
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      const tasks = Array.isArray(data.tasks) ? data.tasks : [];
      const prev = sel.value;
      sel.innerHTML = '<option value="">Select existing task…</option>';
      tasks.forEach((t) => {
        if (!t || !t.id) return;
        const opt = document.createElement("option");
        opt.value = t.id;
        opt.textContent = `${t.title || t.id} (${t.status || "open"})`;
        sel.appendChild(opt);
      });
      const want = sel.dataset.restoreTask || uiPrefs.taskId || prev;
      if (want) {
        sel.value = want;
        if (sel.value === want) {
          delete sel.dataset.restoreTask;
          refreshEvidenceList(want);
        }
      }
    } catch (err) {
      setStatus(`Tasks unavailable: ${err.message || err}`);
    }
  }

  function openInGui(url, title) {
    const api = root.BiggyDocumentViewer;
    if (!api || typeof api.open !== "function") {
      setStatus("In-GUI viewer unavailable — keep using Focus; no external window opened.");
      return false;
    }
    return !!api.open(url, title || "");
  }

  function paintPreview() {
    const canvas = hostEl && hostEl.querySelector('[data-testid="biggy-focus-canvas"]');
    if (!canvas || !frame || !frame.blob) {
      if (canvas) canvas.hidden = true;
      return;
    }
    const myToken = ++previewToken;
    const expectedId = frame.id;
    const img = new Image();
    const url = URL.createObjectURL(frame.blob);
    img.onload = () => {
      URL.revokeObjectURL(url);
      if (myToken !== previewToken || !frame || frame.id !== expectedId) return;
      const natW = img.naturalWidth || 1;
      const natH = img.naturalHeight || 1;
      const maxW = 560;
      const scale = Math.min(1, maxW / natW);
      canvas.width = Math.max(1, Math.round(natW * scale));
      canvas.height = Math.max(1, Math.round(natH * scale));
      const ctx = canvas.getContext("2d");
      ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
      if (crop) {
        const sx = (crop.x / natW) * canvas.width;
        const sy = (crop.y / natH) * canvas.height;
        const sw = (crop.w / natW) * canvas.width;
        const sh = (crop.h / natH) * canvas.height;
        ctx.fillStyle = "rgba(0,0,0,.45)";
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.clearRect(sx, sy, sw, sh);
        ctx.drawImage(img, crop.x, crop.y, crop.w, crop.h, sx, sy, sw, sh);
        ctx.strokeStyle = "#75e5b8";
        ctx.lineWidth = 2;
        ctx.strokeRect(sx, sy, sw, sh);
      }
      canvas.hidden = false;
      canvas.dataset.natW = String(natW);
      canvas.dataset.natH = String(natH);
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      if (myToken !== previewToken) return;
      setStatus("Preview failed.");
    };
    img.src = url;
  }

  function clampCropToNatural(raw, natW, natH) {
    const iw = Math.max(1, natW | 0);
    const ih = Math.max(1, natH | 0);
    let x = Math.max(0, Math.min(iw - 1, Math.round(raw.x)));
    let y = Math.max(0, Math.min(ih - 1, Math.round(raw.y)));
    let w = Math.max(1, Math.round(raw.w));
    let h = Math.max(1, Math.round(raw.h));
    if (x + w > iw) w = Math.max(1, iw - x);
    if (y + h > ih) h = Math.max(1, ih - y);
    return { x, y, w, h, image_width: iw, image_height: ih };
  }

  function commitCrop(nextCrop) {
    const before = crop ? JSON.stringify(crop) : "";
    crop = nextCrop;
    const after = crop ? JSON.stringify(crop) : "";
    if (before !== after) {
      generation += 1;
      if (frame) frame.gen = generation;
      clearGuidanceAnswer("Crop changed — previous answer cleared.");
    }
    paintPreview();
  }

  function wireCrop(canvas) {
    canvas.addEventListener("pointerdown", (ev) => {
      if (!frame) return;
      const r = canvas.getBoundingClientRect();
      const x = ((ev.clientX - r.left) / Math.max(1, r.width)) * canvas.width;
      const y = ((ev.clientY - r.top) / Math.max(1, r.height)) * canvas.height;
      cropDrag = { x0: x, y0: y, x1: x, y1: y };
      try { canvas.setPointerCapture(ev.pointerId); } catch (_) {}
    });
    canvas.addEventListener("pointermove", (ev) => {
      if (!cropDrag || !frame) return;
      const r = canvas.getBoundingClientRect();
      cropDrag.x1 = ((ev.clientX - r.left) / Math.max(1, r.width)) * canvas.width;
      cropDrag.y1 = ((ev.clientY - r.top) / Math.max(1, r.height)) * canvas.height;
      const natW = Number(canvas.dataset.natW || canvas.width);
      const natH = Number(canvas.dataset.natH || canvas.height);
      const sx = Math.min(cropDrag.x0, cropDrag.x1);
      const sy = Math.min(cropDrag.y0, cropDrag.y1);
      const sw = Math.abs(cropDrag.x1 - cropDrag.x0);
      const sh = Math.abs(cropDrag.y1 - cropDrag.y0);
      const next = clampCropToNatural(
        {
          x: (sx / canvas.width) * natW,
          y: (sy / canvas.height) * natH,
          w: (sw / canvas.width) * natW,
          h: (sh / canvas.height) * natH,
        },
        natW,
        natH
      );
      // Live paint without advancing generation until pointerup.
      crop = next;
      paintPreview();
    });
    function endDrag() {
      if (!cropDrag) return;
      cropDrag = null;
      if (crop) commitCrop(Object.assign({}, crop));
    }
    canvas.addEventListener("pointerup", endDrag);
    canvas.addEventListener("pointercancel", endDrag);
  }

  function stopStreamTracks(stream) {
    if (!stream) return;
    try {
      stream.getTracks().forEach((t) => { try { t.stop(); } catch (_) {} });
    } catch (_) {}
  }

  async function captureDisplay() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getDisplayMedia) {
      setStatus("Screen capture is not available in this browser.");
      return;
    }
    setStatus("Choose a window or tab…");
    let stream = null;
    try {
      stream = await navigator.mediaDevices.getDisplayMedia({
        video: { displaySurface: "browser" },
        audio: false,
        preferCurrentTab: true,
      });
    } catch (err) {
      setStatus(err && err.name === "NotAllowedError"
        ? "Capture cancelled — permission not granted."
        : (err.message || String(err)));
      return;
    }
    const track = stream.getVideoTracks()[0];
    const settings = (track && typeof track.getSettings === "function") ? track.getSettings() : {};
    const label = (track && track.label) ? String(track.label).slice(0, 160) : "";
    const surface = settings.displaySurface || "unknown";
    const myGen = ++generation;
    clearGuidanceAnswer("");
    crop = null;
    let lost = false;
    track.addEventListener("ended", () => {
      lost = true;
      // Capture already stopped intentionally after snapshot — only mark lost if
      // this generation is still the active Focus frame and we never finished.
      if (frame && frame.gen === myGen && frame.sourceState === "capturing") {
        frame.sourceState = "lost";
        setStatus("Focus source lost before snapshot completed.");
      }
    });
    const video = document.createElement("video");
    video.muted = true;
    video.playsInline = true;
    video.srcObject = stream;
    try {
      await video.play().catch(() => {});
      await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
      if (myGen !== generation) return;
      const w = video.videoWidth || 640;
      const h = video.videoHeight || 360;
      const c = document.createElement("canvas");
      c.width = w;
      c.height = h;
      c.getContext("2d").drawImage(video, 0, 0, w, h);
      const blob = await new Promise((res) => c.toBlob((b) => res(b), "image/png"));
      if (!blob) {
        setStatus("Capture failed — empty frame.");
        return;
      }
      const reject = intakeRejectReason(blob.size, "image/png");
      if (reject) {
        setStatus(reject);
        return;
      }
      if (myGen !== generation) return;
      if (lost) {
        setStatus("Focus source lost — capture again.");
        return;
      }
      frameSeq += 1;
      frame = {
        id: `focus_${frameSeq}`,
        blob,
        contentType: "image/png",
        capturedAt: new Date().toISOString(),
        source: `browser_capture:${surface}${label ? `:${label}` : ""}`.slice(0, 200),
        kind: "screen_capture",
        host: browserHostLabel(),
        sourceState: "ok",
        gen: myGen,
        targetLabel: label || surface,
        targetSettings: settings,
      };
      setStatus(`Focus ready · ${w}×${h} · ${frame.targetLabel} · snapshot ${frame.capturedAt}`);
      paintPreview();
    } catch (err) {
      if (myGen === generation) setStatus(err.message || String(err));
    } finally {
      stopStreamTracks(stream);
    }
  }

  async function intakeFile(file) {
    if (!file) return;
    const type = file.type || "image/png";
    const reject = intakeRejectReason(file.size, type);
    if (reject) {
      setStatus(reject);
      return;
    }
    const myGen = ++generation;
    clearGuidanceAnswer("");
    crop = null;
    frameSeq += 1;
    frame = {
      id: `intake_${frameSeq}`,
      blob: file,
      contentType: type,
      capturedAt: new Date().toISOString(),
      source: `image_intake:${file.name || type}`.slice(0, 200),
      kind: "image_intake",
      host: browserHostLabel(),
      sourceState: "ok",
      gen: myGen,
      targetLabel: file.name || type,
    };
    setStatus(`Intake ready · ${file.name || type} · ${file.size} B`);
    paintPreview();
  }

  function guidancePayload() {
    const role = (hostEl.querySelector('[data-testid="biggy-focus-role"]') || {}).value || "";
    const finding = (hostEl.querySelector('[data-testid="biggy-focus-finding"]') || {}).value || "";
    const expected = (hostEl.querySelector('[data-testid="biggy-focus-expected"]') || {}).value || "";
    const hasMeta = !!(role || finding || expected.trim() || crop);
    if (!hasMeta) return null;
    const g = {
      x: 0.5,
      y: 0.5,
      label: "Focus evidence",
      clicks: false,
      types: false,
    };
    if (role) g.role = role;
    if (finding) g.finding = finding;
    if (expected.trim()) g.expected_outcome = expected.trim();
    if (crop) g.crop = Object.assign({}, crop);
    return g;
  }

  function cropBlob(srcBlob, c) {
    return new Promise((resolve, reject) => {
      const img = new Image();
      const url = URL.createObjectURL(srcBlob);
      img.onload = () => {
        URL.revokeObjectURL(url);
        const canvas = document.createElement("canvas");
        canvas.width = c.w;
        canvas.height = c.h;
        canvas.getContext("2d").drawImage(img, c.x, c.y, c.w, c.h, 0, 0, c.w, c.h);
        canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("crop_failed"))), "image/png");
      };
      img.onerror = () => {
        URL.revokeObjectURL(url);
        reject(new Error("crop_decode_failed"));
      };
      img.src = url;
    });
  }

  async function analyzeGuidance() {
    if (!frame) {
      setStatus("Capture or intake an image first.");
      return;
    }
    if (frame.sourceState && frame.sourceState !== "ok") {
      setStatus(`Source is ${frame.sourceState}; capture a fresh Focus image.`);
      return;
    }
    const q = ((hostEl.querySelector('[data-testid="biggy-guidance-question"]') || {}).value || "").trim();
    if (!q) {
      setGuideOut("Enter a question about the Focus image.");
      return;
    }
    const reject = intakeRejectReason(frame.blob.size, frame.contentType);
    if (reject) {
      setStatus(reject);
      return;
    }
    const snap = {
      id: frame.id,
      gen: frame.gen,
      analyze: ++analyzeGen,
      crop: crop ? Object.assign({}, crop) : null,
      capturedAt: frame.capturedAt,
    };
    setGuideOut("Asking local vision…");
    try {
      let workBlob = frame.blob;
      let workType = frame.contentType;
      if (snap.crop) {
        workBlob = await cropBlob(frame.blob, snap.crop);
        workType = "image/png";
      }
      if (snap.analyze !== analyzeGen || !frame || frame.id !== snap.id || frame.gen !== snap.gen) {
        setGuideOut("Focus changed — question cancelled.");
        return;
      }
      const infer = await buildInferenceImage(workBlob, workType);
      if (snap.analyze !== analyzeGen || !frame || frame.id !== snap.id || frame.gen !== snap.gen) {
        setGuideOut("Focus changed — question cancelled.");
        return;
      }
      const original_b64 = await blobToBase64(workBlob);
      const body = {
        content_type: workType,
        image_base64: original_b64,
        prompt: `${q}\n\nAnswer only from this image. If uncertain, say so. Do not invent pixel coordinates as verified facts.`,
        source: frame.source,
        captured_at: frame.capturedAt,
        host: frame.host,
      };
      if (infer.blob.size !== workBlob.size || infer.contentType !== workType) {
        body.inference_image_base64 = await blobToBase64(infer.blob);
        body.inference_content_type = infer.contentType;
      }
      if (snap.analyze !== analyzeGen || !frame || frame.id !== snap.id || frame.gen !== snap.gen) {
        setGuideOut("Focus changed — question cancelled.");
        return;
      }
      const res = await fetch("/biggy-workspace/api/v1/vision/analyze", {
        method: "POST",
        credentials: "same-origin",
        headers: csrfHeaders(),
        body: JSON.stringify(body),
        cache: "no-store",
      });
      const data = await res.json().catch(() => ({}));
      if (snap.analyze !== analyzeGen || !frame || frame.id !== snap.id || frame.gen !== snap.gen) {
        setGuideOut("Focus changed — answer discarded.");
        return;
      }
      if (!res.ok) {
        lastGuidance = null;
        setGuideOut(`Unavailable: ${data.error || data.detail || data.message || `HTTP ${res.status}`}`);
        return;
      }
      if (data.available === false) {
        lastGuidance = null;
        setGuideOut(`Unavailable: ${data.message || "Local vision unavailable"}`);
        return;
      }
      const text = data.text || data.analysis || "";
      const provenance = data.provenance || null;
      if (!text || !provenance || provenance.endpoint_kind !== "local") {
        lastGuidance = null;
        setGuideOut("Local analysis unavailable — no external inference used.");
        return;
      }
      lastGuidance = {
        text,
        provenance,
        frameId: snap.id,
        gen: snap.gen,
        analyze: snap.analyze,
        crop: snap.crop,
      };
      setGuideOut(text);
      setStatus("Guidance answer ready (local). Coordinates are not treated as verified.");
    } catch (err) {
      if (snap.analyze === analyzeGen) {
        lastGuidance = null;
        setGuideOut(`Unavailable: ${err.message || err}`);
      }
    }
  }

  async function saveEvidence() {
    if (!frame) {
      setStatus("Nothing to save.");
      return;
    }
    const taskId = (hostEl.querySelector('[data-testid="biggy-focus-task"]') || {}).value || "";
    if (!taskId) {
      setStatus("Select an existing task (nothing is created automatically).");
      return;
    }
    if (frame.sourceState && frame.sourceState !== "ok") {
      setStatus(`Source is ${frame.sourceState}; capture fresh before save.`);
      return;
    }
    const reject = intakeRejectReason(frame.blob.size, frame.contentType);
    if (reject) {
      setStatus(reject);
      return;
    }
    const snap = {
      id: frame.id,
      gen: frame.gen,
      blob: frame.blob,
      contentType: frame.contentType,
      source: frame.source,
      kind: frame.kind,
      host: frame.host,
      capturedAt: frame.capturedAt,
      sourceState: frame.sourceState || "ok",
      crop: crop ? Object.assign({}, crop) : null,
      guidance: guidancePayload(),
      answer: (lastGuidance
        && lastGuidance.frameId === frame.id
        && lastGuidance.gen === frame.gen
        && lastGuidance.analyze === analyzeGen)
        ? lastGuidance
        : null,
    };
    try {
      const image_base64 = await blobToBase64(snap.blob);
      if (!frame || frame.id !== snap.id || frame.gen !== snap.gen) {
        setStatus("Focus changed before save.");
        return;
      }
      const params = {
        task_id: taskId,
        kind: snap.kind,
        content_type: snap.contentType,
        image_base64,
        source: snap.source,
        host: snap.host,
        captured_at: snap.capturedAt,
        source_state: snap.sourceState,
      };
      if (snap.guidance) params.guidance = snap.guidance;
      if (snap.answer && snap.answer.text && snap.answer.provenance) {
        params.analysis_text = snap.answer.text;
        params.analysis_provenance = snap.answer.provenance;
      }
      const res = await fetch("/biggy-workspace/api/v1/commands", {
        method: "POST",
        credentials: "same-origin",
        headers: csrfHeaders(),
        body: JSON.stringify({ command: "vision_evidence_save", params }),
        cache: "no-store",
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || data.detail || `HTTP ${res.status}`);
      const artId = data.artifact && data.artifact.id ? data.artifact.id : "ok";
      setStatus(`Saved evidence ${artId} to task.`);
      await refreshEvidenceList(taskId);
    } catch (err) {
      setStatus(`Save failed: ${err.message || err}`);
    }
  }

  async function refreshEvidenceList(taskId) {
    const list = hostEl && hostEl.querySelector('[data-testid="biggy-focus-evidence"]');
    if (!list || !taskId) return;
    list.innerHTML = "<li>Loading…</li>";
    try {
      const res = await fetch(
        `/biggy-workspace/api/v1/evidence?task_id=${encodeURIComponent(taskId)}`,
        { credentials: "same-origin", headers: { Accept: "application/json" }, cache: "no-store" }
      );
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
      const items = Array.isArray(data.artifacts) ? data.artifacts : [];
      if (!items.length) {
        list.innerHTML = "<li>No saved evidence for this task.</li>";
        return;
      }
      list.innerHTML = "";
      items.forEach((art) => {
        const li = document.createElement("li");
        li.className = "biggy-focus-evidence-item";
        const g = art.guidance || (art.analysis && art.analysis.guidance) || {};
        const role = g.role ? ` · ${g.role}` : "";
        const finding = g.finding ? ` · ${g.finding}` : "";
        const cropNote = g.crop ? " · crop" : "";
        const meta = document.createElement("div");
        meta.textContent =
          `${art.id || "ev"} · ${art.source || ""} · ${art.captured_at || ""} · ${art.source_state || ""}${role}${finding}${cropNote}`;
        li.appendChild(meta);
        const actions = document.createElement("div");
        actions.className = "biggy-focus-evidence-actions";
        const origUrl = art.original_url
          || `/biggy-workspace/api/v1/evidence/${art.id}/original`;
        const origBtn = document.createElement("button");
        origBtn.type = "button";
        origBtn.textContent = "Open original";
        origBtn.setAttribute("data-testid", `biggy-focus-open-original-${art.id}`);
        origBtn.addEventListener("click", () => {
          if (!openInGui(origUrl, art.id)) setStatus("Could not open original in GUI viewer.");
        });
        actions.appendChild(origBtn);
        if (art.analysis && (art.analysis.text || art.analysis.available)) {
          const anUrl = art.analysis_url
            || `/biggy-workspace/api/v1/evidence/${art.id}/analysis.txt`;
          const anBtn = document.createElement("button");
          anBtn.type = "button";
          anBtn.textContent = "Open analysis";
          anBtn.setAttribute("data-testid", `biggy-focus-open-analysis-${art.id}`);
          anBtn.addEventListener("click", () => {
            if (!openInGui(anUrl, `${art.id} analysis`)) setStatus("Could not open analysis in GUI viewer.");
          });
          actions.appendChild(anBtn);
        }
        if (g.presentation_ref && g.presentation_ref.play_url) {
          const pBtn = document.createElement("button");
          pBtn.type = "button";
          pBtn.textContent = "Open recording";
          pBtn.addEventListener("click", () => {
            if (!openInGui(g.presentation_ref.play_url, g.presentation_ref.filename || "Presentation")) {
              setStatus("Could not open recording in GUI viewer.");
            }
          });
          actions.appendChild(pBtn);
        }
        li.appendChild(actions);
        list.appendChild(li);
      });
    } catch (err) {
      list.innerHTML = `<li>Evidence list unavailable: ${err.message || err}</li>`;
    }
  }

  async function ingestFreeze(payload) {
    if (!payload || !payload.blob) throw new Error("freeze_empty");
    if (!hostEl) {
      pendingFreeze = payload;
      return;
    }
    const reject = intakeRejectReason(payload.blob.size, payload.contentType || "image/jpeg");
    if (reject) {
      setStatus(reject);
      return;
    }
    const myGen = ++generation;
    clearGuidanceAnswer("");
    crop = null;
    frameSeq += 1;
    frame = {
      id: `cam_${frameSeq}`,
      blob: payload.blob,
      contentType: payload.contentType || "image/jpeg",
      capturedAt: new Date().toISOString(),
      source: payload.source || "td_camera_raw",
      kind: "image_intake",
      host: "td_camera",
      sourceState: "ok",
      gen: myGen,
      targetLabel: payload.source || "td_camera_raw",
    };
    pendingFreeze = null;
    setStatus(`Camera freeze · ${payload.source || "raw"} — select task to save.`);
    paintPreview();
  }


  function captureUiPrefs() {
    if (!hostEl) return;
    const g = (sel) => hostEl.querySelector(sel);
    uiPrefs = {
      taskId: (g('[data-testid="biggy-focus-task"]') || {}).value || uiPrefs.taskId || "",
      role: (g('[data-testid="biggy-focus-role"]') || {}).value || uiPrefs.role || "",
      finding: (g('[data-testid="biggy-focus-finding"]') || {}).value || uiPrefs.finding || "",
      expected: (g('[data-testid="biggy-focus-expected"]') || {}).value || uiPrefs.expected || "",
      question: (g('[data-testid="biggy-guidance-question"]') || {}).value || uiPrefs.question || "",
    };
  }

  function restoreUi() {
    if (!hostEl) return;
    const setVal = (sel, v) => {
      const el = hostEl.querySelector(sel);
      if (el && v != null) el.value = v;
    };
    setVal('[data-testid="biggy-focus-role"]', uiPrefs.role || "");
    setVal('[data-testid="biggy-focus-finding"]', uiPrefs.finding || "");
    setVal('[data-testid="biggy-focus-expected"]', uiPrefs.expected || "");
    setVal('[data-testid="biggy-guidance-question"]', uiPrefs.question || "");
    const taskSel = hostEl.querySelector('[data-testid="biggy-focus-task"]');
    if (taskSel && uiPrefs.taskId) {
      taskSel.value = uiPrefs.taskId;
      if (taskSel.value !== uiPrefs.taskId) {
        // Option may load async — retry after tasks.
        taskSel.dataset.restoreTask = uiPrefs.taskId;
      } else {
        refreshEvidenceList(uiPrefs.taskId);
      }
    }
    if (frame) {
      setStatus(
        frame.sourceState === "ok"
          ? `Focus ready · ${frame.targetLabel || frame.source} · snapshot ${frame.capturedAt || ""}`
          : `Focus · ${frame.sourceState}`
      );
      paintPreview();
    }
    if (lastGuidance && lastGuidance.text
        && frame && lastGuidance.frameId === frame.id && lastGuidance.gen === frame.gen) {
      setGuideOut(lastGuidance.text);
    }
  }

  function buildHtml() {
    return (
      '<div class="biggy-focus-guidance" data-testid="biggy-focus-guidance">'
      + '<p class="biggy-focus-note">Focus holds one captured window/tab or intake image. Optional crop keeps the original. Guidance asks the local vision model about that image — it never clicks or types.</p>'
      + '<div class="biggy-focus-row">'
      + '<button type="button" data-testid="biggy-focus-capture">Capture window/tab</button>'
      + '<label class="biggy-focus-file">Intake image'
      + '<input type="file" accept="image/png,image/jpeg,image/webp" hidden data-testid="biggy-focus-file" /></label>'
      + '<button type="button" data-testid="biggy-focus-clear-crop">Clear crop</button>'
      + "</div>"
      + '<p class="biggy-focus-status" data-testid="biggy-focus-status">No Focus image</p>'
      + '<canvas class="biggy-focus-canvas" data-testid="biggy-focus-canvas" hidden width="320" height="180"></canvas>'
      + '<div class="biggy-focus-meta">'
      + '<label>Task <select data-testid="biggy-focus-task"><option value="">Select existing task…</option></select></label>'
      + '<label>Role <select data-testid="biggy-focus-role">'
      + '<option value="">(none)</option><option value="before">Before</option>'
      + '<option value="after">After</option><option value="finding">Finding</option></select></label>'
      + '<label>Finding <select data-testid="biggy-focus-finding">'
      + '<option value="">(none)</option><option value="confirmed">Confirmed</option>'
      + '<option value="failed">Failed</option><option value="inconclusive">Inconclusive</option></select></label>'
      + '<label>Expected outcome <input type="text" data-testid="biggy-focus-expected" maxlength="500" placeholder="Optional" /></label>'
      + "</div>"
      + '<div class="biggy-focus-row">'
      + '<button type="button" data-testid="biggy-focus-save">Save evidence</button>'
      + '<button type="button" data-testid="biggy-focus-discard">Clear Focus</button>'
      + "</div>"
      + '<ul class="biggy-focus-evidence" data-testid="biggy-focus-evidence"></ul>'
      + '<hr class="biggy-focus-sep" />'
      + "<h3>Screen Guidance</h3>"
      + '<p class="biggy-focus-note">Uses the Focus image (or crop). Uncertain answers stay uncertain — coordinates are not claimed as verified.</p>'
      + '<textarea data-testid="biggy-guidance-question" rows="2" placeholder="What should I notice here?"></textarea>'
      + '<div class="biggy-focus-row">'
      + '<button type="button" data-testid="biggy-guidance-ask">Ask local vision</button>'
      + "</div>"
      + '<pre class="biggy-guidance-answer" data-testid="biggy-guidance-answer"></pre>'
      + "</div>"
    );
  }

  function wire(rootEl) {
    rootEl.querySelector('[data-testid="biggy-focus-capture"]').addEventListener("click", () => {
      captureDisplay().catch(() => {});
    });
    const file = rootEl.querySelector('[data-testid="biggy-focus-file"]');
    file.addEventListener("change", () => {
      const f = file.files && file.files[0];
      file.value = "";
      intakeFile(f).catch(() => {});
    });
    rootEl.querySelector('[data-testid="biggy-focus-clear-crop"]').addEventListener("click", () => {
      if (crop) commitCrop(null);
      else paintPreview();
    });
    rootEl.querySelector('[data-testid="biggy-focus-save"]').addEventListener("click", () => {
      saveEvidence().catch(() => {});
    });
    rootEl.querySelector('[data-testid="biggy-focus-discard"]').addEventListener("click", () => {
      discard();
    });
    rootEl.querySelector('[data-testid="biggy-guidance-ask"]').addEventListener("click", () => {
      analyzeGuidance().catch(() => {});
    });
    rootEl.querySelector('[data-testid="biggy-focus-task"]').addEventListener("change", (ev) => {
      const id = ev.target.value;
      captureUiPrefs();
      if (id) refreshEvidenceList(id);
    });
    ["biggy-focus-role", "biggy-focus-finding", "biggy-focus-expected", "biggy-guidance-question"].forEach((id) => {
      const el = rootEl.querySelector(`[data-testid="${id}"]`);
      if (el) el.addEventListener("change", () => captureUiPrefs());
      if (el && el.tagName === "TEXTAREA") el.addEventListener("input", () => captureUiPrefs());
      if (el && el.tagName === "INPUT") el.addEventListener("input", () => captureUiPrefs());
    });
    wireCrop(rootEl.querySelector('[data-testid="biggy-focus-canvas"]'));
  }

  function mount(container) {
    ensureStyle();
    if (!container) return null;
    hostEl = container;
    container.innerHTML = buildHtml();
    wire(container);
    loadTasks();
    restoreUi();
    if (pendingFreeze) {
      ingestFreeze(pendingFreeze).catch(() => {});
    }
    return {
      ingestFreeze,
      getFrame: () => frame,
      discard,
    };
  }

  /** Soft leave — keep frame/crop/answer for Focus↔Guidance↔Overview return. */
  function detach() {
    captureUiPrefs();
    hostEl = null;
  }

  /** Explicit discard / hard close — ends Focus snapshot state. */
  function discard() {
    generation += 1;
    clearGuidanceAnswer("");
    frame = null;
    crop = null;
    lastGuidance = null;
    uiPrefs = { taskId: "", role: "", finding: "", expected: "", question: "" };
    pendingFreeze = null;
    if (hostEl) {
      setStatus("Focus cleared.");
      paintPreview();
      setGuideOut("");
    }
  }

  function unmount() {
    // Hard clear when Vision surface closes.
    detach();
    discard();
  }

  root.BiggyVisionFocusGuidance = {
    mount,
    unmount,
    detach,
    discard,
    getFrame: () => frame,
    ingestFreeze: (p) => ingestFreeze(p),
  };
})(typeof window !== "undefined" ? window : globalThis);
