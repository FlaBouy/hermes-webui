/* Viewer-side TD frame composite (MediaPipe selfie segmentation). Display only.
 * Decorative backdrop never mutates the raw machine-vision frame path.
 * Background images are cover-fit (proportions preserved) and never pre-flipped.
 */
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
  let bgCanvas = null;
  let bgCtx = null;
  let generation = 0;
  let closed = false;
  let loadInflight = null;

  function drawCover(ctx, img, w, h) {
    const iw = img.naturalWidth || img.width || 0;
    const ih = img.naturalHeight || img.height || 0;
    if (!iw || !ih) {
      ctx.fillStyle = "#000";
      ctx.fillRect(0, 0, w, h);
      return { dx: 0, dy: 0, dw: w, dh: h, scale: 1 };
    }
    const scale = Math.max(w / iw, h / ih);
    const dw = iw * scale;
    const dh = ih * scale;
    const dx = (w - dw) / 2;
    const dy = (h - dh) / 2;
    ctx.drawImage(img, dx, dy, dw, dh);
    return { dx, dy, dw, dh, scale };
  }

  async function loadSegmenter() {
    if (closed) return false;
    if (segReady) return true;
    if (segFailed) return false;
    if (loadInflight) return loadInflight;
    const gen = generation;
    loadInflight = (async () => {
      try {
        await new Promise((resolve, reject) => {
          if (root.SelfieSegmentation) {
            resolve();
            return;
          }
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
      } finally {
        loadInflight = null;
      }
    })();
    return loadInflight;
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

  function ensureBg(w, h) {
    if (!bgCanvas) {
      bgCanvas = document.createElement("canvas");
      bgCtx = bgCanvas.getContext("2d", { willReadFrequently: true });
    }
    if (bgCanvas.width !== w || bgCanvas.height !== h) {
      bgCanvas.width = w;
      bgCanvas.height = h;
    }
  }

  function fail(seg, error, ms) {
    return { ok: false, composited: false, seg, error, ms };
  }

  /**
   * Backdrop output is the preview's device pixels, not the camera JPEG.
   * The JPEG is often 640×480; painting a large still into that bitmap and
   * letting CSS enlarge it is what pixelates the background.
   * Off stays on the source pixels so the original frame is not resampled.
   */
  function outputPixelSize(sw, sh, mode, opts) {
    if (mode === "off") {
      return { w: sw, h: sh, sourceLimited: false };
    }
    const dpr = Math.min(Math.max((opts && opts.devicePixelRatio) || 1, 1), 3);
    const cssW = (opts && opts.displayWidth) || 0;
    const cssH = (opts && opts.displayHeight) || 0;
    let w = sw;
    let h = sh;
    if (cssW >= 2 && cssH >= 2) {
      w = Math.max(sw, Math.round(cssW * dpr));
      h = Math.max(sh, Math.round(cssH * dpr));
      const aspect = sw / sh;
      if (w / h > aspect) h = Math.round(w / aspect);
      else w = Math.round(h * aspect);
    }
    const cap = 1600;
    const longSide = Math.max(w, h);
    if (longSide > cap) {
      const scale = cap / longSide;
      w = Math.max(1, Math.round(w * scale));
      h = Math.max(1, Math.round(h * scale));
    }
    return { w, h, sourceLimited: sw < w || sh < h };
  }

  /**
   * Draw sourceImage onto outCanvas with optional backdrop.
   * Fail closed: backdrop != off without successful mask → ok:false (do not show raw).
   * Never paints an intermediate raw frame when backdrop requires segmentation.
   * Modes: off | egs | custom | blur (blur retained for compositor tests).
   */
  async function compositeToCanvas(sourceImage, outCanvas, backdropMode, opts) {
    const t0 = (typeof performance !== "undefined" && performance.now) ? performance.now() : Date.now();
    const elapsed = () => {
      const now = (typeof performance !== "undefined" && performance.now) ? performance.now() : Date.now();
      return Math.round((now - t0) * 10) / 10;
    };
    const mode = backdropMode || "off";
    const gen = (opts && opts.generation != null) ? opts.generation : generation;
    if (closed || gen !== generation) {
      return fail("aborted", "compositor aborted", elapsed());
    }
    const sw = sourceImage.naturalWidth || sourceImage.width || 0;
    const sh = sourceImage.naturalHeight || sourceImage.height || 0;
    if (!(sw > 0) || !(sh > 0)) {
      return fail("unavailable", "Camera frame has no pixel size.", elapsed());
    }
    const sized = outputPixelSize(sw, sh, mode, opts);
    const w = sized.w;
    const h = sized.h;
    const ctx = outCanvas.getContext("2d");
    const meta = {
      sourceWidth: sw,
      sourceHeight: sh,
      outputWidth: w,
      outputHeight: h,
      sourceLimited: sized.sourceLimited,
    };

    if (mode === "off") {
      outCanvas.width = w;
      outCanvas.height = h;
      ctx.imageSmoothingEnabled = true;
      ctx.drawImage(sourceImage, 0, 0, w, h);
      return { ok: true, composited: false, seg: "off", ms: elapsed(), ...meta };
    }

    if (!segReady || !segmenter) {
      const loaded = await loadSegmenter();
      if (!loaded || closed || gen !== generation) {
        return fail(
          segFailed ? "failed" : "unavailable",
          "Local person segmentation unavailable — raw feed not shown while backdrop is selected.",
          elapsed()
        );
      }
    }

    await segmenter.send({ image: sourceImage });
    if (closed || gen !== generation) {
      return fail("aborted", "compositor aborted", elapsed());
    }
    if (!latestMask) {
      return fail(
        "unavailable",
        "Segmentation mask missing — raw feed not shown while backdrop is selected.",
        elapsed()
      );
    }

    ensureMask(w, h);
    maskCtx.imageSmoothingEnabled = true;
    maskCtx.imageSmoothingQuality = "high";
    maskCtx.clearRect(0, 0, w, h);
    maskCtx.drawImage(latestMask, 0, 0, w, h);

    ensureBg(w, h);
    bgCtx.setTransform(1, 0, 0, 1, 0, 0);
    bgCtx.filter = "none";
    bgCtx.imageSmoothingEnabled = true;
    bgCtx.imageSmoothingQuality = "high";
    bgCtx.clearRect(0, 0, w, h);
    if (mode === "blur") {
      bgCtx.filter = "blur(12px)";
      bgCtx.drawImage(sourceImage, 0, 0, w, h);
      bgCtx.filter = "none";
    } else if ((mode === "custom" || mode === "egs") && customBg) {
      drawCover(bgCtx, customBg, w, h);
    } else if (mode === "egs") {
      return fail(
        "unavailable",
        "EGS background image is not loaded — raw feed not shown while backdrop is selected.",
        elapsed()
      );
    } else if (mode === "custom") {
      return fail(
        "unavailable",
        "Choose a custom backdrop image, or switch backdrop to Off.",
        elapsed()
      );
    } else {
      return fail(
        "unavailable",
        "Unknown backdrop mode — raw feed not shown.",
        elapsed()
      );
    }

    if (closed || gen !== generation) {
      return fail("aborted", "compositor aborted", elapsed());
    }

    outCanvas.width = w;
    outCanvas.height = h;
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(sourceImage, 0, 0, w, h);
    const frame = ctx.getImageData(0, 0, w, h);
    const mask = maskCtx.getImageData(0, 0, w, h);
    const bgData = bgCtx.getImageData(0, 0, w, h);
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
    return { ok: true, composited: true, seg: "ok", ms: elapsed(), ...meta };
  }

  function reset() {
    generation += 1;
    latestMask = null;
  }

  function abort() {
    closed = true;
    generation += 1;
    latestMask = null;
    loadInflight = null;
    try {
      if (segmenter && typeof segmenter.close === "function") segmenter.close();
    } catch (_) { /* ignore */ }
    segmenter = null;
    segReady = false;
    // Keep segFailed sticky until reopen so UI can report honestly after stop.
  }

  function reopen() {
    closed = false;
    generation += 1;
    latestMask = null;
    // Allow a fresh load after camera restart; do not silently reuse a failed flag
    // as "ready". A previous failure remains until a successful loadSegmenter.
  }

  function currentGeneration() {
    return generation;
  }

  root.BiggyTdCameraComposite = {
    loadSegmenter,
    setCustomBackdrop,
    compositeToCanvas,
    drawCover,
    outputPixelSize,
    reset,
    abort,
    reopen,
    currentGeneration,
    get segReady() { return segReady; },
    get segFailed() { return segFailed; },
    VENDOR,
  };
})(typeof window !== "undefined" ? window : globalThis);
