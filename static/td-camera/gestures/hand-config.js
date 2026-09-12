/**
 * Hand-only Human configuration for the isolated vision-gestures POC.
 * Face/body/emotion/age/gender/identity/object/segmentation stay disabled.
 * modelBasePath is relative/local — never hard-codes a private host path.
 */

export const PINNED_HUMAN_VERSION = '3.3.6';
export const PINNED_HUMAN_COMMIT = '151df64d6143db8d0cf14df39e69be2f655f9f34';

export const HAND_MODELS = Object.freeze([
  'handtrack.json',
  'handtrack.bin',
  'handlandmark-lite.json',
  'handlandmark-lite.bin',
]);

export const HAND_ONLY_CONFIG = Object.freeze({
  backend: 'tensorflow',
  cacheModels: false,
  validateModels: true,
  warmup: 'none',
  debug: false,
  async: false,
  deallocate: true,
  filter: { enabled: false, return: false },
  face: { enabled: false },
  body: { enabled: false },
  object: { enabled: false },
  segmentation: { enabled: false },
  gesture: { enabled: true },
  hand: {
    enabled: true,
    rotation: true,
    landmarks: true,
    maxDetected: 2,
    minConfidence: 0.5,
    iouThreshold: 0.2,
    skipFrames: 0,
    skipTime: 0,
    detector: { modelPath: 'handtrack.json' },
    skeleton: { modelPath: 'handlandmark-lite.json' },
  },
});

/** Browser preview uses WebGL when available; Node fixture uses tensorflow. */
export function createHandOnlyConfig(overrides = {}) {
  return {
    ...HAND_ONLY_CONFIG,
    ...overrides,
    filter: { ...HAND_ONLY_CONFIG.filter, ...(overrides.filter || {}) },
    face: { enabled: false },
    body: { enabled: false },
    object: { enabled: false },
    segmentation: { enabled: false },
    gesture: { enabled: overrides.gesture?.enabled !== false },
    hand: {
      ...HAND_ONLY_CONFIG.hand,
      ...(overrides.hand || {}),
      detector: {
        ...HAND_ONLY_CONFIG.hand.detector,
        ...(overrides.hand && overrides.hand.detector),
      },
      skeleton: {
        ...HAND_ONLY_CONFIG.hand.skeleton,
        ...(overrides.hand && overrides.hand.skeleton),
      },
    },
  };
}
