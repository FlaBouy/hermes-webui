/**
 * VISION→Gestures observational panel (Rev B).
 * Hand-only Human 3.3.6; Enable loads models; Off unloads owned GraphModels.
 * Reuses BiggyTdCameraOverlay raw-frame subscription — never opens a second lease.
 * Results stay in this surface; never overlays camera feed / presentation.
 */
import { createHandOnlyConfig, PINNED_HUMAN_VERSION } from './hand-config.js';
import { createHandAdapter, disposeOwnedHuman } from './hand-adapter.js';
import { createSourceSeam, SOURCE_KINDS, TD_RELAY_SEAM_CONTRACT } from './source-seam.js';
import { createDeliberateActionInterpreter } from './deliberate-action.js';
import { buildPaintCacheKey, drawLandmarks } from './paint-cache.js';

const MODEL_BASE = '/static/td-camera/gestures/models/';
const HUMAN_ESM = '/static/td-camera/gestures/vendor/human-3.3.6/dist/human.esm.js';
const MIN_INTERVAL_MS = Math.round((TD_RELAY_SEAM_CONTRACT.minFrameIntervalSec || 0.18) * 1000);

const interpreter = createDeliberateActionInterpreter({ enabled: false });
const adapter = createHandAdapter({ minIntervalMs: MIN_INTERVAL_MS, interpreter });
const seam = createSourceSeam(SOURCE_KINDS.TD_RELAY_SEAM, {
  label: 'td_relay_shared_lease',
  notes: 'shareExistingLease; openIndependentLease=false; increaseRelayTraffic=false',
});

let hostEl = null;
let human = null;
let loadToken = 0;
let loading = false;
let unsubFrames = null;
let showLandmarks = true;
let lastPaint = '';
let lastFrameSize = { w: 640, h: 480 };
let disposalCounters = { graphModelDispose: 0, modelsReset: 0, humanReset: 0 };
let pendingDisposeInstance = null;

function cameraApi() {
  return (typeof window !== 'undefined' && window.BiggyTdCameraOverlay) || null;
}

function ensureCameraModule() {
  if (cameraApi()) return Promise.resolve(cameraApi());
  return new Promise((resolve, reject) => {
    const existing = document.querySelector('script[data-biggy-td-camera-overlay]');
    if (existing) {
      existing.addEventListener('load', () => resolve(cameraApi()));
      existing.addEventListener('error', () => reject(new Error('td_camera_overlay_failed')));
      return;
    }
    const s = document.createElement('script');
    s.src = '/static/td-camera/viewer-overlay.js';
    s.dataset.biggyTdCameraOverlay = '1';
    s.onload = () => resolve(cameraApi());
    s.onerror = () => reject(new Error('td_camera_overlay_failed'));
    document.head.appendChild(s);
  });
}

// paint helpers imported from paint-cache.js

function scheduleOwnedDispose(instance) {
  if (!instance) return;
  const run = () => {
    disposeOwnedHuman(instance, disposalCounters);
    if (pendingDisposeInstance === instance) pendingDisposeInstance = null;
  };
  if (adapter.readiness().inferenceInFlight) {
    pendingDisposeInstance = instance;
    adapter.whenIdle().then(run);
  } else {
    run();
  }
}

function paint() {
  if (!hostEl) return;
  const r = adapter.readiness();
  const cam = cameraApi();
  const viewing = !!(cam && typeof cam.isViewing === 'function' && cam.isViewing());
  const obs = r.lastObservation || {};
  const pose = obs.primaryPose || '—';
  const conf = obs.primaryConfidence
    ? Number(obs.primaryConfidence).toFixed(2)
    : '—';
  const status = loading
    ? 'loading'
    : (!r.gesturesEnabled
      ? 'off'
      : (!viewing
        ? 'camera_off'
        : (obs.status || 'waiting')));

  const backend = human && human.config ? human.config.backend : null;
  const payload = buildPaintCacheKey({
    gesturesEnabled: r.gesturesEnabled,
    modelLoaded: r.modelLoaded,
    realHandDetected: r.realHandDetected,
    realCameraAccepted: r.realCameraAccepted,
    backend,
    status,
    pose,
    conf,
    viewing,
    showLandmarks,
    observation: obs,
    loading,
  });
  if (payload === lastPaint) return;
  lastPaint = payload;

  const enableBtn = hostEl.querySelector('[data-testid="biggy-gestures-enable"]');
  const offBtn = hostEl.querySelector('[data-testid="biggy-gestures-off"]');
  if (enableBtn) enableBtn.disabled = !!(r.gesturesEnabled || loading);
  if (offBtn) offBtn.disabled = !(r.gesturesEnabled || loading);

  const set = (sel, text) => {
    const el = hostEl.querySelector(sel);
    if (el) el.textContent = text;
  };
  set('[data-testid="biggy-gestures-state"]', r.gesturesEnabled ? 'On' : 'Off');
  set('[data-testid="biggy-gestures-pose"]', String(pose));
  set('[data-testid="biggy-gestures-confidence"]', String(conf));
  set('[data-testid="biggy-gestures-status"]', String(status));

  const guide = hostEl.querySelector('[data-testid="biggy-gestures-camera-guide"]');
  if (guide) {
    guide.hidden = !(r.gesturesEnabled && !viewing);
  }

  const surface = document.getElementById('biggyVisionSurface');
  if (surface && surface.dataset.activePanel === 'gestures') {
    const pill = surface.querySelector('[data-testid="biggy-vision-availability"]');
    const pillText = pill && pill.querySelector('span:last-child');
    const detail = surface.querySelector('[data-testid="biggy-vision-detail"]');
    if (pill && pillText) {
      const on = !!r.gesturesEnabled;
      pillText.textContent = on ? 'on' : 'off';
      pill.classList.toggle('is-available', on);
      pill.classList.toggle('is-off', !on);
      pill.classList.toggle('is-unavailable', false);
    }
    if (detail) {
      detail.textContent = r.gesturesEnabled
        ? (r.realHandDetected
          ? `Hand seen (${obs.primaryPose || 'hand'}). Observation only — nothing is clicked or typed.`
          : 'Gestures on. Show your hand in the Camera feed. Observation only.')
        : 'Hand observation is off until you press Enable. Uses the Camera feed when it is already running.';
    }
  }

  // Diagnostics (Details) — not main flow.
  const diag = hostEl.querySelector('[data-testid="biggy-gestures-details-body"]');
  if (diag) {
    diag.textContent = [
      `model_loaded=${r.modelLoaded ? 'yes' : (loading ? 'loading' : 'no')}`,
      `backend=${backend || '—'}`,
      `hand_detected=${r.realHandDetected ? 'yes' : 'no'}`,
      `camera_feed=${r.realCameraAccepted ? 'yes' : 'no'}`,
      `human=${PINNED_HUMAN_VERSION}`,
      `status=${status}`,
    ].join('\n');
  }

  const lmCanvas = hostEl.querySelector('[data-testid="biggy-gestures-landmarks"]');
  const srcW = obs.sourceWidth || lastFrameSize.w;
  const srcH = obs.sourceHeight || lastFrameSize.h;
  if (lmCanvas && showLandmarks && obs.landmarks && obs.landmarks.length) {
    drawLandmarks(lmCanvas, obs.landmarks, srcW, srcH);
  } else if (lmCanvas) {
    drawLandmarks(lmCanvas, [], srcW, srcH);
  }
}

async function releaseHuman() {
  loadToken += 1;
  loading = false;
  const toDispose = human;
  human = null;
  adapter.unload();
  seam.markLost('gestures_off');
  adapter.setSourceStatus(seam.status());
  scheduleOwnedDispose(toDispose);
  paint();
}

function bindFrameSubscription() {
  if (unsubFrames) return;
  const cam = cameraApi();
  if (!cam || typeof cam.subscribeRawFrames !== 'function') return;
  unsubFrames = cam.subscribeRawFrames((evt) => {
    onFrameEvent(evt).catch(() => {});
  });
}

function unbindFrameSubscription() {
  if (typeof unsubFrames === 'function') {
    try { unsubFrames(); } catch (_err) { /* ignore */ }
  }
  unsubFrames = null;
}

async function onFrameEvent(evt) {
  if (!evt) return;
  if (evt.kind === 'source_lost' || evt.kind === 'stop') {
    seam.markLost(evt.reason || 'source_lost');
    adapter.setSourceStatus(seam.status());
    paint();
    return;
  }
  if (evt.kind !== 'frame') return;
  if (!adapter.readiness().gesturesEnabled) return;
  if (!adapter.readiness().modelLoaded || !human) return;

  if (!seam.status().accepted || seam.status().lost) {
    seam.accept({ label: 'td_relay_shared_lease' });
  }
  adapter.setSourceStatus(seam.status());

  const image = evt.image;
  if (!image) return;
  const w = evt.width || image.naturalWidth || image.width || lastFrameSize.w;
  const h = evt.height || image.naturalHeight || image.height || lastFrameSize.h;
  lastFrameSize = { w, h };
  const owned = human;
  await adapter.submitFrame({
    image,
    frameSeq: evt.seq || Date.now(),
    now: evt.at || Date.now(),
    sourceWidth: w,
    sourceHeight: h,
    detectFn: (input) => owned.detect(input),
  });
  paint();
}

async function loadBackendInstance(HumanCtor, backend, token) {
  const cfg = createHandOnlyConfig({
    backend,
    modelBasePath: MODEL_BASE,
    warmup: 'none',
  });
  const instance = new HumanCtor(cfg);
  try {
    await instance.load();
  } catch (err) {
    disposeOwnedHuman(instance, disposalCounters);
    throw err;
  }
  if (token !== loadToken) {
    disposeOwnedHuman(instance, disposalCounters);
    return null;
  }
  return instance;
}

async function loadHumanIfNeeded() {
  if (human && adapter.readiness().modelLoaded) return human;
  if (loading) return null;
  loading = true;
  const token = ++loadToken;
  paint();
  try {
    const mod = await import(HUMAN_ESM);
    if (token !== loadToken) {
      loading = false;
      paint();
      return null;
    }
    const HumanCtor = mod.Human || mod.default;
    // Local-only fallback: WebGL → CPU. No WASM (would need extra runtime assets / CDN risk).
    let instance = null;
    try {
      instance = await loadBackendInstance(HumanCtor, 'webgl', token);
    } catch (_webglErr) {
      if (token !== loadToken) {
        loading = false;
        paint();
        return null;
      }
      instance = await loadBackendInstance(HumanCtor, 'cpu', token);
    }
    if (!instance || token !== loadToken) {
      if (instance) disposeOwnedHuman(instance, disposalCounters);
      loading = false;
      paint();
      return null;
    }
    await adapter.attachHuman(instance);
    if (token !== loadToken) {
      adapter.unload();
      disposeOwnedHuman(instance, disposalCounters);
      loading = false;
      paint();
      return null;
    }
    human = instance;
    loading = false;
    paint();
    return human;
  } catch (err) {
    if (token === loadToken) {
      loading = false;
      human = null;
      adapter.unload();
      paint();
    }
    throw err;
  }
}

async function enable() {
  await ensureCameraModule();
  bindFrameSubscription();
  adapter.enable();
  paint();
  try {
    await loadHumanIfNeeded();
  } catch (err) {
    const note = hostEl && hostEl.querySelector('[data-testid="biggy-gestures-error"]');
    if (note) {
      note.textContent = err && err.message ? err.message : String(err);
      note.hidden = false;
    }
    await releaseHuman();
    return;
  }
  if (!adapter.readiness().gesturesEnabled) {
    // Off during load — discard
    return;
  }
  const cam = cameraApi();
  const viewing = !!(cam && cam.isViewing && cam.isViewing());
  if (viewing) {
    seam.accept({ label: 'td_relay_shared_lease' });
    adapter.setSourceStatus(seam.status());
  } else {
    seam.markLost('camera_off');
    adapter.setSourceStatus(seam.status());
  }
  paint();
}

async function disable() {
  unbindFrameSubscription();
  await releaseHuman();
  const note = hostEl && hostEl.querySelector('[data-testid="biggy-gestures-error"]');
  if (note) {
    note.textContent = '';
    note.hidden = true;
  }
  paint();
}

function renderShell(host) {
  host.innerHTML =
    '<div class="biggy-gestures-panel" data-testid="biggy-gestures-panel">'
    + '<p class="biggy-gestures-lead">Watch hand poses from the Camera feed. Nothing is clicked or typed automatically.</p>'
    + '<div class="biggy-gestures-controls">'
    + '<button type="button" data-testid="biggy-gestures-enable">Enable</button>'
    + '<button type="button" class="danger" data-testid="biggy-gestures-off" disabled>Off</button>'
    + '<button type="button" data-testid="biggy-gestures-open-camera">Start Camera</button>'
    + '<label class="biggy-gestures-lm-toggle"><input type="checkbox" data-testid="biggy-gestures-landmarks-toggle" checked /> Show landmarks</label>'
    + '</div>'
    + '<p class="biggy-gestures-camera-guide" data-testid="biggy-gestures-camera-guide" hidden>'
    + 'Camera is off. Open Camera settings and press Start, or use Start Camera above.</p>'
    + '<dl class="biggy-gestures-status" data-testid="biggy-gestures-status-grid">'
    + '<div><dt>Gestures</dt><dd data-testid="biggy-gestures-state">Off</dd></div>'
    + '<div><dt>Pose</dt><dd data-testid="biggy-gestures-pose">—</dd></div>'
    + '<div><dt>Confidence</dt><dd data-testid="biggy-gestures-confidence">—</dd></div>'
    + '<div><dt>Status</dt><dd data-testid="biggy-gestures-status">off</dd></div>'
    + '</dl>'
    + '<canvas class="biggy-gestures-landmarks" data-testid="biggy-gestures-landmarks" width="320" height="240" aria-label="Hand landmarks"></canvas>'
    + '<p class="biggy-gestures-error" data-testid="biggy-gestures-error" hidden></p>'
    + '<details class="biggy-gestures-details" data-testid="biggy-gestures-details">'
    + '<summary>Details</summary>'
    + '<pre data-testid="biggy-gestures-details-body"></pre>'
    + '</details>'
    + '</div>';

  host.querySelector('[data-testid="biggy-gestures-enable"]').addEventListener('click', () => {
    enable().catch(() => {});
  });
  host.querySelector('[data-testid="biggy-gestures-off"]').addEventListener('click', () => {
    disable().catch(() => {});
  });
  host.querySelector('[data-testid="biggy-gestures-open-camera"]').addEventListener('click', () => {
    ensureCameraModule()
      .then((api) => {
        if (api && typeof api.openSettings === 'function') api.openSettings();
        else if (api && typeof api.open === 'function') api.open();
      })
      .catch(() => {});
  });
  host.querySelector('[data-testid="biggy-gestures-landmarks-toggle"]').addEventListener('change', (ev) => {
    showLandmarks = !!ev.target.checked;
    lastPaint = ''; // force redraw when toggling
    paint();
  });
}

function mount(host) {
  hostEl = host;
  lastPaint = '';
  renderShell(host);
  paint();
  return readiness();
}

function unmount() {
  hostEl = null;
  lastPaint = '';
}

function readiness() {
  const r = adapter.readiness();
  return {
    ...r,
    loading,
    backend: human && human.config ? human.config.backend : null,
    humanVersion: PINNED_HUMAN_VERSION,
    openIndependentLease: TD_RELAY_SEAM_CONTRACT.openIndependentLease,
    increaseRelayTraffic: TD_RELAY_SEAM_CONTRACT.increaseRelayTraffic,
    interpreterEnabled: false,
    disposalCounters: { ...disposalCounters },
  };
}

/** Test / diagnostic: push a local image without touching camera lease. */
async function submitTestImage(image, meta = {}) {
  if (!adapter.readiness().gesturesEnabled) {
    return { accepted: false, reason: 'adapter_off' };
  }
  if (!human || !adapter.readiness().modelLoaded) {
    return { accepted: false, reason: 'model_not_loaded' };
  }
  const fixtureSeam = createSourceSeam(SOURCE_KINDS.FIXTURE, { label: meta.label || 'test_image' });
  fixtureSeam.accept();
  adapter.setSourceStatus(fixtureSeam.status());
  const w = meta.sourceWidth || image.naturalWidth || image.width || lastFrameSize.w;
  const h = meta.sourceHeight || image.naturalHeight || image.height || lastFrameSize.h;
  lastFrameSize = { w, h };
  const owned = human;
  const out = await adapter.submitFrame({
    image,
    frameSeq: meta.frameSeq || Date.now(),
    sourceWidth: w,
    sourceHeight: h,
    detectFn: (input) => owned.detect(input),
  });
  const cam = cameraApi();
  const viewing = !!(cam && cam.isViewing && cam.isViewing());
  if (viewing && adapter.readiness().gesturesEnabled) {
    seam.accept({ label: 'td_relay_shared_lease' });
    adapter.setSourceStatus(seam.status(), { clearObservation: false });
  } else {
    seam.markLost(viewing ? 'gestures_probe_done' : 'camera_off');
    adapter.setSourceStatus(seam.status(), { clearObservation: false });
  }
  paint();
  return out;
}

const api = {
  mount,
  unmount,
  enable,
  disable,
  readiness,
  submitTestImage,
  buildPaintCacheKey,
  drawLandmarks,
  disposeOwnedHuman,
  _test: {
    adapter,
    seam,
    interpreter,
    TD_RELAY_SEAM_CONTRACT,
    getDisposalCounters: () => ({ ...disposalCounters }),
    resetDisposalCounters: () => {
      disposalCounters = { graphModelDispose: 0, modelsReset: 0, humanReset: 0 };
    },
    getShowLandmarks: () => showLandmarks,
    setShowLandmarks: (v) => { showLandmarks = !!v; lastPaint = ''; },
    forcePaint: () => { lastPaint = ''; paint(); },
    getLastPaint: () => lastPaint,
  },
};

if (typeof window !== 'undefined') {
  window.BiggyGestures = api;
}

export default api;
