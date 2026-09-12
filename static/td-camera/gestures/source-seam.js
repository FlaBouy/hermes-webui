/**
 * Interchangeable frame source seam.
 * Existing TD relay (~5fps 640x480 authenticated same-origin) and a future
 * browser-local webcam are both adapters behind this interface.
 * This POC never increases relay traffic or touches tokens.
 */

export const SOURCE_KINDS = Object.freeze({
  FIXTURE: 'fixture',
  TD_RELAY_SEAM: 'td_relay_seam',
  BROWSER_LOCAL_FUTURE: 'browser_local_future',
  NONE: 'none',
});

export const TD_RELAY_SEAM_CONTRACT = Object.freeze({
  framePath: '/api/td-camera/frame.jpg',
  healthPath: '/api/td-camera/health',
  maxWidth: 640,
  maxHeight: 480,
  minFrameIntervalSec: 0.18,
  shareExistingLease: true,
  openIndependentLease: false,
  tokenClientVisible: false,
  increaseRelayTraffic: false,
});

export function createSourceSeam(kind, options = {}) {
  const state = {
    kind: kind || SOURCE_KINDS.NONE,
    accepted: false,
    lost: true,
    label: options.label || kind || 'none',
    lastFrameAt: 0,
    frameSeq: 0,
    notes: options.notes || '',
  };

  function accept(meta = {}) {
    state.accepted = true;
    state.lost = false;
    if (meta.label) state.label = meta.label;
    if (meta.notes) state.notes = meta.notes;
    return status();
  }

  function markLost(reason) {
    state.lost = true;
    state.accepted = false;
    state.notes = reason || 'source_lost';
    return status();
  }

  function pushFrame(frame, now = Date.now()) {
    if (!state.accepted || state.lost) {
      return { ok: false, reason: 'source_not_accepted', status: status() };
    }
    state.frameSeq += 1;
    state.lastFrameAt = now;
    return {
      ok: true,
      frameSeq: state.frameSeq,
      at: now,
      frame,
      status: status(),
    };
  }

  function status() {
    return {
      kind: state.kind,
      label: state.label,
      accepted: state.accepted,
      lost: state.lost,
      lastFrameAt: state.lastFrameAt,
      frameSeq: state.frameSeq,
      notes: state.notes,
      realCameraAccepted: state.kind === SOURCE_KINDS.TD_RELAY_SEAM && state.accepted && !state.lost,
      futureBrowserLocalReady: state.kind === SOURCE_KINDS.BROWSER_LOCAL_FUTURE,
      fixtureBound: state.kind === SOURCE_KINDS.FIXTURE && state.accepted,
    };
  }

  return { accept, markLost, pushFrame, status, SOURCE_KINDS };
}
