/* Viewer-side TD frame composite (MediaPipe selfie segmentation). Display only. */
(function (root) {
  "use strict";

  const VENDOR =
    "/static/td-camera/vendor/mediapipe-selfie-segmentation-0.1.1675465747/";

  let segmenter = null;
  let segReady = false;
  let segFailed = false;
  let latestMask = null;
  let customBg = null;
  let maskCanvas = null;
  let maskCtx = null;
  let generation = 0;
  let closed = false;

  async function loadSegmenter() {
    if (closed) return false;
    if (segReady) return true;
    if (segFailed) return false;
    const gen = generation;
    try {
      await new Promise((resolve, reject) => {
        const s = document.createElement("script");
        s.src = VENDOR + "selfie_segmentation.js";
        s.onload = resolve;
        s.onerror = () => reject(new Error("segmentation_script_failed"));
        document.head.appendChild(s);
      });
      if (closed || gen !== generation) return false;
      if (!root.SelfieSegmentation) throw new Error("SelfieSegmentation missing");
      segmenter = new root.SelfieSegmentation({
        locateFile: (file) => VENDOR + file,
      });
      segmenter.setOptions({ modelSelection: 1 });
      segmenter.onResults((results) => {
        if (closed) return;
        latestMask = results && results.segmentationMask ? results.segmentationMask : null;
      });
      if (typeof segmenter.initialize === "function") await segmenter.initialize();
      if (closed || gen !== generation) return false;
      segReady = true;
      return true;
    } catch (_) {
      if (gen === generation) {
        segFailed = true;
        segReady = false;
        segmenter = null;
        latestMask = null;
      }
      return false;
    }
  }

  function setCustomBackdrop(img) {
    customBg = img || null;
  }

  function ensureMask(w, h) {
    if (!maskCanvas) {
      maskCanvas = document.createElement("canvas");
      maskCtx = maskCanvas.getContext("2d", { willReadFrequently: true });
    }
    if (maskCanvas.width !== w || maskCanvas.height !== h) {
      maskCanvas.width = w;
      maskCanvas.height = h;
    }
  }

  /**
   * Draw sourceImage onto outCanvas with optional backdrop.
   * Fail closed: backdrop != off without successful mask → ok:false (do not show raw).
   * Never paints an intermediate raw frame when backdrop requires segmentation.
   */
  async function compositeToCanvas(sourceImage, outCanvas, backdropMode, opts) {
    const mode = backdropMode || "off";
    const gen = (opts && opts.generation != null) ? opts.generation : generation;
    if (closed || gen !== generation) {
      return { ok: false, composited: false, seg: "aborted", error: "compositor aborted" };
    }
    const w = Math.min(640, sourceImage.naturalWidth || sourceImage.width || 640);
    const h = Math.min(480, sourceImage.naturalHeight || sourceImage.height || 480);
    const ctx = outCanvas.getContext("2d");

    if (mode === "off") {
      outCanvas.width = w;
      outCanvas.height = h;
      ctx.drawImage(sourceImage, 0, 0, w, h);
      return { ok: true, composited: false, seg: "off" };
    }

    // Keep prior canvas hidden by caller until ok — do not draw raw first.
    if (!segReady || !segmenter) {
      const loaded = await loadSegmenter();
      if (!loaded || closed || gen !== generation) {
        return {
          ok: false,
          composited: false,
          seg: segFailed ? "failed" : "unavailable",
          error: "Local person segmentation unavailable — raw feed not shown while backdrop is selected.",
        };
      }
    }

    await segmenter.send({ image: sourceImage });
    if (closed || gen !== generation) {
      return { ok: false, composited: false, seg: "aborted", error: "compositor aborted" };
    }
    if (!latestMask) {
      return {
        ok: false,
        composited: false,
        seg: "unavailable",
        error: "Segmentation mask missing — raw feed not shown while backdrop is selected.",
      };
    }

    ensureMask(w, h);
    maskCtx.clearRect(0, 0, w, h);
    maskCtx.drawImage(latestMask, 0, 0, w, h);

    const bg = document.createElement("canvas");
    bg.width = w;
    bg.height = h;
    const bgx = bg.getContext("2d");
    if (mode === "blur") {
      // Background-only blur via person mask — not whole-frame blur as the product output.
      bgx.filter = "blur(12px)";
      bgx.drawImage(sourceImage, 0, 0, w, h);
      bgx.filter = "none";
    } else if (mode === "custom" && customBg) {
      bgx.drawImage(customBg, 0, 0, w, h);
    } else if (mode === "custom") {
      return {
        ok: false,
        composited: false,
        seg: "unavailable",
        error: "Choose a custom backdrop image, or switch backdrop to Off.",
      };
    }

    if (closed || gen !== generation) {
      return { ok: false, composited: false, seg: "aborted", error: "compositor aborted" };
    }

    outCanvas.width = w;
    outCanvas.height = h;
    ctx.drawImage(sourceImage, 0, 0, w, h);
    const frame = ctx.getImageData(0, 0, w, h);
    const mask = maskCtx.getImageData(0, 0, w, h);
    const bgData = bgx.getImageData(0, 0, w, h);
    const d = frame.data;
    const m = mask.data;
    const b = bgData.data;
    for (let i = 0; i < d.length; i += 4) {
      const a = m[i] / 255;
      d[i] = d[i] * a + b[i] * (1 - a);
      d[i + 1] = d[i + 1] * a + b[i + 1] * (1 - a);
      d[i + 2] = d[i + 2] * a + b[i + 2] * (1 - a);
    }
    ctx.putImageData(frame, 0, 0);
    return { ok: true, composited: true, seg: "ok" };
  }

  function reset() {
    generation += 1;
    latestMask = null;
  }

  function abort() {
    closed = true;
    generation += 1;
    latestMask = null;
    try {
      if (segmenter && typeof segmenter.close === "function") segmenter.close();
    } catch (_) { /* ignore */ }
    segmenter = null;
    segReady = false;
  }

  function reopen() {
    closed = false;
    generation += 1;
    latestMask = null;
  }

  function currentGeneration() {
    return generation;
  }

  root.BiggyTdCameraComposite = {
    loadSegmenter,
    setCustomBackdrop,
    compositeToCanvas,
    reset,
    abort,
    reopen,
    currentGeneration,
    get segReady() { return segReady; },
    get segFailed() { return segFailed; },
    VENDOR,
  };
})(typeof window !== "undefined" ? window : globalThis);
