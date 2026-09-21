# Biggy camera background

Live Biggy is launchd `ai.biggy.webui` on `http://127.0.0.1:8790`. After the 2026-09-21 correction the listener was pid 39779, parent 39777, grandparent 1.

Deployed:

- OBSBOT capture `1920×1080` JPEG (`api/local_obsbot.py` on the live checkout). One measured frame was 185322 bytes. Relay accepts up to 1920×1080 and 1.2 MB.
- Backdrop composite uses the preview's device pixels, long side capped at 1600. Off uses the source pixels and is not resampled.
- Owner file `/Users/rick/Mounts/Z/DATA/EGS copy.jpeg` (3607×2029, EXIF orientation 1, 1787856 bytes) decoded in the isolated test. Static stamp `egs-bg-20260921c`.
- Raw gesture/vision subscribers still receive the uncomposited frame.

Not deployed / not proven:

- Signed-in Off → EGS → `EGS copy.jpeg` → Off with a person in frame. This Cursor browser is login-walled at `:8790` and was not given the password.
- HEIC/HEIF decode.
- The isolated branch's `api/td_camera_relay.py` is the old ThunderDome proxy. It was not copied onto the live tree. Live capture is the dirty `local_obsbot.py` plus the live relay.

Rollback of the static files and the pre-1080 Python constants: `/Users/rick/hermes-webui/backups/egs-camera-resolution-20260921T133119/`. Reload Python with `launchctl kickstart -k gui/$(id -u)/ai.biggy.webui`.

Commit `5d23285bf4456225791c12983b07af2c6855c544` on private `feature/egs-camera-background`. Not on public `nesquena/hermes-webui`.
