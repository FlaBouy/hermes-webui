/**
 * Hand recognition adapter — observational output only.
 * One inference in flight; drop stale frames; bounded rate; cleanup on Off/loss.
 * Lifecycle/source generations invalidate deferred detects after Stop/Off.
 * Second hand / second person does not silently become the controller.
 */

import { createHandOnlyConfig, PINNED_HUMAN_VERSION } from './hand-config.js';
import { createDeliberateActionInterpreter } from './deliberate-action.js';

function pickPose(gestures) {
  if (!gestures || !gestures.length) return null;
  const preferred = ['thumbs up', 'victory', 'point', 'open palm'];
  for (const p of preferred) {
    if (gestures.some((g) => String(g).toLowerCase() === p)) return p;
  }
  return String(gestures[0]).toLowerCase();
}

function emptyObservation(status) {
  return {
    at: Date.now(),
    handCount: 0,
    controllerAmbiguous: false,
    primaryPose: null,
    primaryConfidence: 0,
    landmarks: [],
    landmarkCount: 0,
    sourceWidth: null,
    sourceHeight: null,
    allGestures: [],
    hands: [],
    sourceLost: status === 'source_lost',
    status,
  };
}

/**
 * Dispose GraphModels owned by a Human instance.
 * Uses model.dispose() + models.reset() + human.reset() (sets env.initial so
 * module-level handtrack caches clear on next load). Never calls global
 * tf.disposeVariables() — that would hit other TF consumers.
 */
export function disposeOwnedHuman(instance, counters = null) {
  if (!instance) return counters;
  const bag = instance.models && instance.models.models;
  if (bag && typeof bag === 'object') {
    for (const key of Object.keys(bag)) {
      const model = bag[key];
      if (model && typeof model.dispose === 'function') {
        try {
          model.dispose();
          if (counters) counters.graphModelDispose = (counters.graphModelDispose || 0) + 1;
        } catch (_err) { /* already disposed */ }
      }
      bag[key] = null;
    }
  }
  try {
    if (instance.models && typeof instance.models.reset === 'function') {
      instance.models.reset();
      if (counters) counters.modelsReset = (counters.modelsReset || 0) + 1;
    }
  } catch (_err) { /* ignore */ }
  try {
    if (typeof instance.reset === 'function') {
      instance.reset();
      if (counters) counters.humanReset = (counters.humanReset || 0) + 1;
    }
  } catch (_err) { /* ignore */ }
  return counters;
}

export function createHandAdapter(options = {}) {
  const minIntervalMs = options.minIntervalMs != null ? options.minIntervalMs : 200;
  const maxHandsForController = 1;
  const interpreter = options.interpreter || createDeliberateActionInterpreter({ enabled: false });

  let enabled = false;
  let modelLoaded = false;
  let human = null;
  /** Held until the owning detect await completes — never cleared early by Off. */
  let inflightToken = null;
  let lifecycleGen = 0;
  let sourceGen = 0;
  let latestSeq = 0;
  let lastInferAt = 0;
  let lastObservation = emptyObservation('adapter_off');
  let sourceStatus = { accepted: false, lost: true, kind: 'none' };
  let idleWaiters = [];

  function notifyIdle() {
    if (inflightToken) return;
    const waiters = idleWaiters;
    idleWaiters = [];
    for (const resolve of waiters) resolve();
  }

  function whenIdle() {
    if (!inflightToken) return Promise.resolve();
    return new Promise((resolve) => { idleWaiters.push(resolve); });
  }

  async function attachHuman(humanInstance) {
    human = humanInstance;
    const loaded = human && human.models && typeof human.models.loaded === 'function'
      ? human.models.loaded()
      : [];
    // Panel owns initial load; only load here if models are not yet present.
    if (human && typeof human.load === 'function'
      && !(loaded.includes('handtrack') || loaded.includes('handskeleton'))) {
      await human.load();
    }
    const after = human && human.models && typeof human.models.loaded === 'function'
      ? human.models.loaded()
      : [];
    modelLoaded = !!(after.includes('handtrack') || after.includes('handskeleton') || human);
    return readiness();
  }

  function setSourceStatus(status, opts = {}) {
    const clearObservation = opts.clearObservation !== false;
    const prevLost = !!(sourceStatus.lost || !sourceStatus.accepted);
    sourceStatus = status || { accepted: false, lost: true, kind: 'none' };
    const nowLost = !!(sourceStatus.lost || !sourceStatus.accepted);
    if (nowLost && !prevLost) {
      sourceGen += 1; // invalidate in-flight detects that started while source was live
    }
    if (!nowLost && prevLost) {
      // Fresh accept — new generation already advanced on loss; keep gen monotonic.
    }
    if (clearObservation && nowLost) {
      lastObservation = emptyObservation('source_lost');
      interpreter.observe(lastObservation);
    }
  }

  function enable() {
    enabled = true;
    return readiness();
  }

  function disable() {
    enabled = false;
    lifecycleGen += 1; // invalidate in-flight — token stays until detect completes
    lastObservation = emptyObservation('adapter_off');
    interpreter.disable();
    return readiness();
  }

  /** Release model refs after Off. Does not clear inflightToken early. */
  function unload() {
    disable();
    human = null;
    modelLoaded = false;
    lifecycleGen += 1;
    latestSeq += 1;
    lastObservation = emptyObservation('adapter_off');
    return readiness();
  }

  function readiness() {
    return {
      gesturesEnabled: enabled,
      modelLoaded,
      humanVersion: PINNED_HUMAN_VERSION,
      source: sourceStatus,
      realHandDetected: !!(lastObservation && lastObservation.handCount > 0),
      realCameraAccepted: !!(sourceStatus && sourceStatus.realCameraAccepted),
      inferenceInFlight: !!inflightToken,
      lifecycleGen,
      sourceGen,
      lastObservation,
      interpreter: interpreter.snapshot(),
    };
  }

  function normalizeDetection(raw, meta = {}) {
    const hands = Array.isArray(raw && raw.hand) ? raw.hand : [];
    const gestures = Array.isArray(raw && raw.gesture) ? raw.gesture : [];
    const handCount = hands.length;
    const controllerAmbiguous = handCount > maxHandsForController;

    let primary = null;
    let primaryPose = null;
    let primaryConfidence = 0;

    if (handCount === 1) {
      primary = hands[0];
      primaryConfidence = Number(primary.score || 0);
      const g = gestures.filter((x) => x.hand === 0).map((x) => x.gesture);
      primaryPose = pickPose(g) || (primary.label || null);
    }

    return {
      at: Date.now(),
      handCount,
      controllerAmbiguous,
      primaryPose: primaryPose ? String(primaryPose).toLowerCase() : null,
      primaryConfidence,
      landmarks: primary && Array.isArray(primary.keypoints)
        ? primary.keypoints.map((k, idx) => {
          if (Array.isArray(k)) {
            return { part: idx, x: k[0], y: k[1], z: k[2] ?? null, score: null };
          }
          return {
            part: k.part || k.name || idx,
            x: k.position?.[0] ?? k.x ?? null,
            y: k.position?.[1] ?? k.y ?? null,
            z: k.position?.[2] ?? k.z ?? null,
            score: k.score ?? null,
          };
        })
        : [],
      landmarkCount: primary && primary.keypoints ? primary.keypoints.length : 0,
      sourceWidth: meta.sourceWidth != null ? meta.sourceWidth : null,
      sourceHeight: meta.sourceHeight != null ? meta.sourceHeight : null,
      box: primary && primary.box ? primary.box : null,
      allGestures: gestures.map((g) => ({ hand: g.hand, gesture: g.gesture })),
      hands: hands.map((h, i) => ({
        index: i,
        score: h.score,
        label: h.label,
        landmarkCount: (h.keypoints || []).length,
      })),
      sourceLost: false,
      status: controllerAmbiguous
        ? 'multiple_hands_no_controller'
        : handCount === 1
          ? 'hand_detected'
          : 'no_hand',
    };
  }

  async function submitFrame({ image, frameSeq, now, detectFn, sourceWidth, sourceHeight }) {
    const t = now != null ? now : Date.now();
    latestSeq = Math.max(latestSeq, frameSeq || 0);

    if (!enabled) {
      return { accepted: false, reason: 'adapter_off', observation: lastObservation };
    }
    if (!modelLoaded || !detectFn) {
      return { accepted: false, reason: 'model_not_loaded', observation: lastObservation };
    }
    if (!sourceStatus.accepted || sourceStatus.lost) {
      lastObservation = emptyObservation('source_lost');
      return { accepted: false, reason: 'source_lost', observation: lastObservation };
    }
    if (inflightToken) {
      return { accepted: false, reason: 'dropped_inflight', observation: lastObservation };
    }
    if (t - lastInferAt < minIntervalMs) {
      return { accepted: false, reason: 'rate_limited', observation: lastObservation };
    }

    const mySeq = frameSeq || latestSeq;
    const myLifecycle = lifecycleGen;
    const mySource = sourceGen;
    const token = { myLifecycle, mySource, mySeq };
    inflightToken = token;
    lastInferAt = t;
    try {
      const raw = await detectFn(image);
      // Post-await gates: enabled, lifecycle, source, and seq must still match.
      if (!enabled || myLifecycle !== lifecycleGen) {
        return {
          accepted: false,
          reason: 'lifecycle_invalidated',
          observation: lastObservation,
        };
      }
      if (mySource !== sourceGen || !sourceStatus.accepted || sourceStatus.lost) {
        if (!lastObservation.sourceLost) {
          lastObservation = emptyObservation('source_lost');
        }
        return {
          accepted: false,
          reason: 'source_lost_during_infer',
          observation: lastObservation,
        };
      }
      if (mySeq < latestSeq) {
        return { accepted: false, reason: 'dropped_stale', observation: lastObservation };
      }
      const observation = normalizeDetection(raw, { sourceWidth, sourceHeight });
      lastObservation = observation;
      const action = interpreter.observe(observation, t);
      return {
        accepted: true,
        reason: 'inferred',
        observation,
        action,
        readiness: readiness(),
      };
    } finally {
      if (inflightToken === token) inflightToken = null;
      notifyIdle();
    }
  }

  return {
    attachHuman,
    setSourceStatus,
    enable,
    disable,
    unload,
    readiness,
    submitFrame,
    whenIdle,
    createHandOnlyConfig,
    interpreter,
    disposeOwnedHuman,
  };
}
