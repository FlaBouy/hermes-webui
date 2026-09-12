/**
 * Deliberate-action interpreter — dwell / cooldown / neutral-reset.
 * Disabled by default. Observational only until a future reversible GUI bind.
 * Never triggers OS commands, messaging, deletes, or deploys.
 */

export const DEFAULTS = Object.freeze({
  enabled: false,
  dwellMs: 700,
  cooldownMs: 1200,
  neutralPose: 'open palm',
  qualifyingPoses: Object.freeze(['thumbs up', 'victory', 'point']),
  minConfidence: 0.55,
});

function normalizePose(pose) {
  if (!pose || typeof pose !== 'string') return null;
  return pose.trim().toLowerCase();
}

export function createDeliberateActionInterpreter(options = {}) {
  const cfg = {
    ...DEFAULTS,
    ...options,
    qualifyingPoses: Object.freeze([
      ...(options.qualifyingPoses || DEFAULTS.qualifyingPoses),
    ]),
  };

  let armed = false;
  let dwellPose = null;
  let dwellStartedAt = 0;
  let cooldownUntil = 0;
  let lastFired = null;
  const firedLog = [];

  function snapshot(now = Date.now()) {
    return {
      enabled: cfg.enabled,
      armed,
      dwellPose,
      dwellMsRemaining: dwellPose
        ? Math.max(0, cfg.dwellMs - (now - dwellStartedAt))
        : 0,
      cooldownMsRemaining: Math.max(0, cooldownUntil - now),
      lastFired,
      fireCount: firedLog.length,
    };
  }

  function resetNeutral(now = Date.now()) {
    dwellPose = null;
    dwellStartedAt = 0;
    armed = cfg.enabled;
    return {
      fired: false,
      action: null,
      reason: 'neutral_reset',
      now,
      state: snapshot(now),
    };
  }

  function disable() {
    cfg.enabled = false;
    armed = false;
    dwellPose = null;
    dwellStartedAt = 0;
    return snapshot();
  }

  function enable() {
    cfg.enabled = true;
    return resetNeutral();
  }

  function observe(obs, now = Date.now()) {
    if (!cfg.enabled) {
      return {
        fired: false,
        action: null,
        reason: 'interpreter_disabled',
        state: snapshot(now),
      };
    }

    if (!obs || obs.sourceLost) {
      dwellPose = null;
      dwellStartedAt = 0;
      return {
        fired: false,
        action: null,
        reason: 'source_lost',
        state: snapshot(now),
      };
    }

    if (obs.controllerAmbiguous) {
      dwellPose = null;
      dwellStartedAt = 0;
      return {
        fired: false,
        action: null,
        reason: 'controller_ambiguous',
        state: snapshot(now),
      };
    }

    if (now < cooldownUntil) {
      return {
        fired: false,
        action: null,
        reason: 'cooldown',
        state: snapshot(now),
      };
    }

    const pose = normalizePose(obs.primaryPose);
    const conf = Number(obs.primaryConfidence || 0);

    if (!pose || conf < cfg.minConfidence) {
      dwellPose = null;
      dwellStartedAt = 0;
      return {
        fired: false,
        action: null,
        reason: 'nonqualifying',
        state: snapshot(now),
      };
    }

    if (pose === cfg.neutralPose) {
      return resetNeutral(now);
    }

    if (!cfg.qualifyingPoses.includes(pose)) {
      dwellPose = null;
      dwellStartedAt = 0;
      return {
        fired: false,
        action: null,
        reason: 'nonqualifying',
        state: snapshot(now),
      };
    }

    if (dwellPose !== pose) {
      dwellPose = pose;
      dwellStartedAt = now;
      return {
        fired: false,
        action: null,
        reason: 'dwell_started',
        state: snapshot(now),
      };
    }

    if (now - dwellStartedAt < cfg.dwellMs) {
      return {
        fired: false,
        action: null,
        reason: 'dwell_hold',
        state: snapshot(now),
      };
    }

    const action = pose;
    lastFired = { action, at: now, confidence: conf };
    firedLog.push(lastFired);
    cooldownUntil = now + cfg.cooldownMs;
    dwellPose = null;
    dwellStartedAt = 0;
    armed = false;
    return {
      fired: true,
      action,
      reason: 'dwell_complete',
      state: snapshot(now),
    };
  }

  return {
    observe,
    enable,
    disable,
    resetNeutral,
    snapshot,
    getFiredLog: () => firedLog.slice(),
    defaults: DEFAULTS,
  };
}
