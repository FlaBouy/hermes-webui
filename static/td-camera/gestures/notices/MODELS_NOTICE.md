# Model and code notices (hand-only POC)

## Human library

- Package: `@vladmandic/human@3.3.6`
- Commit: `151df64d6143db8d0cf14df39e69be2f655f9f34`
- License: MIT — see `HUMAN-LICENSE-MIT.txt`

## Hand detector (handtrack)

- Files: `models/handtrack.json`, `models/handtrack.bin`
- Origin credit: HandTracking / HandTrack ([victordibia/handtracking](https://github.com/victordibia/handtracking)) via Human Models wiki
- License: MIT — see `HANDTRACK-LICENSE.txt`

## Hand landmarks (handlandmark-lite)

- Files: `models/handlandmark-lite.json`, `models/handlandmark-lite.bin`
- Origin credit: MediaPipe Hands / HandPose (Google) via Human Models wiki
- License inheritance: Apache-2.0 — see `Apache-2.0.txt`
- Human wiki note: models are quantized/modified derivatives; original model licenses still apply

## Explicitly not loaded in this POC

Face detector/mesh/iris/emotion/description, body/pose, object detection, segmentation, antispoof, liveness, age/gender/identity.

## Production shipping policy

Fixtures are **not** included under `static/td-camera/gestures/`. Isolated POC fixtures remain under `work/vision-gestures/fixtures/` with EgoHands content-rights caveat (see that FIXTURE_NOTICE.md). Repository MIT for HandTrack/Human code does not automatically clear EgoHands image redistribution.
