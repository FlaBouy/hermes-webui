# Vision core — Hermes bridge closeout (2026-09-12)

**Card:** `vision-td-camera-cursor-20260912` (prior: `vision-core-cursor-20260912`)  
**Live release:** `vision-core-20260912-180859` (TD camera native preview + display-only local backdrop)  
**Prior live:** `vision-core-20260912-172218`  
**Hermes private destination:** `FlaBouy/hermes-webui-smedley` branch `fix/v6-embed-console-cleanup`  
**Public `origin` (nesquena/hermes-webui):** must not receive this Vision push

## What shipped (Hermes) — TD camera slice

| Path | Role |
| --- | --- |
| `api/td_camera_relay.py` | Same-origin proxy to Smedley loopback `:18765`; view leases; rate/inflight; JPEG validation ≤640×480; Bearer from server token path only |
| `api/td_camera_http.py` | `/api/td-camera` health/status/frame + view start/stop/heartbeat; CSRF + session when auth on |
| `api/routes.py` | GET/POST dispatch to TD camera handler |
| `api/helpers.py` | CSP `script-src` adds `'wasm-unsafe-eval'` for vendored MediaPipe WASM |
| `static/td-camera/viewer-composite.js` | Display-only Off/Blur/custom composite (fail-closed; no silent raw) |
| `static/td-camera/vendor/mediapipe-selfie-segmentation-0.1.1675465747/` | Vendored runtime + `LICENSE-Apache-2.0.txt` / `NOTICE.txt` |
| `tests/test_td_camera_relay.py` | Mock upstream + lease/rate/auth/CSRF + browser harness |
| `tests/fixtures/td_camera_synthetic_person.png` | Synthetic person for MediaPipe harness |
| `tests/test_vision_cockpit_entry_chromium.py` | Real cockpit→Workspace iframe TD Start/Blur/Stop |
| `tests/test_issue1909_csp_*.py` | Expect `'wasm-unsafe-eval'` in CSP assertions |

Prior Vision fulfill / cockpit capture embed paths from `vision-core-20260912-172218` remain in tree; see earlier sections of git history for that slice.

## Deployed release `vision-core-20260912-180859` (TD native preview)

- Transport: ThunderDome C920 → existing native Smedley loopback → Hermes authenticated proxy → Vision panel viewer. Preview poll ~5 fps, 640×480 JPEG snapshots. No browser producer / tablet `getUserMedia` for TD.
- Virtual background is **display-only** (local MediaPipe segmentation). Does not alter upstream. Freeze/save of TD frames deferred.
- Atlas apply: DB6 integrity/data unchanged. Coordinator owner-GUI (native AX): Vision → Visual Capture → Start → Viewing TD C920 640×480 backdrop off then Blur `seg=ok` → Stop verified. After idle: health/status ok, `camera_active=false`.
- **Observation (record only):** TD health reports `tunnel_process_running=false` while the stream remains reachable. TD service supervision changed; Rick reports reboot recovery is TD-managed. No restart/guessing performed at closeout.
- Owner tablet acceptance still pending.

## Tests (evidence, not owner tablet acceptance)

- Hermes: `tests/test_td_camera_relay.py` + CSP wasm updates; real iframe `test_cockpit_td_camera_real_workspace_iframe` **1 passed** (browser harness delta in that file: +383 lines).
- Deploy helper (handoff artifact, not in this repo): `work/vision/test_deploy_vision_core.py` **18 OK**; helper sha256 `8be0f1741fb838484f1c1964f0227501cde3d5788edf464615917a0bd708067b` (`deploy_vision_core.py`). ABSENT marker only after verified `git ls-tree` empty path.

## Explicit limits

- Preview only (~5 fps / 640×480); freeze/save TD deferred.
- Display-only local backdrop; not transport privacy.
- No claim of owner tablet production acceptance in this closeout.
- No Hermes public `origin` push for this work.
