# Biggy local pet controls

The **PET** button sits at the bottom of the PA right sidebar. Open PA, then PET.
Closing PA hides the settings popup and PET button, not the enabled pet. The popup
is outside the rail's clipping area. The Orb and prompt axis are unchanged.

Open PET to select a local pet, turn it on/off, adjust its height from 64 to
448 CSS pixels, or refresh the local catalog. Choices persist in this browser's
`biggy:pets:v1` local storage, independently of chat sessions. A first installation
is off; a missing selected pet is never silently replaced by an enabled pet.

Drag the visible pet with a mouse or touch to place it anywhere on screen. Its
position persists as viewport-relative coordinates and remains inside the viewport
after resizing. With the pet focused, arrow keys move it 8 pixels (Shift: 24).
Escape during a drag cancels that movement. **Place above Message Biggy** resets
Bones to the default spot just above the left edge of the typing field. Biggy's
**Place right of dialog** defaults to the right of the visible conversation lane,
bottom-aligned; with no dialog, it falls back to the right of the message prompt.
Each pet saves its own size, position, and animation controls. Biggy defaults to
256px tall; the initial 128px Biggy setting is doubled once during migration.
Opening PET
temporarily avoids overlap with its controls without replacing the saved position.

## Local assets

The read-only catalog uses `BIGGY_PETS_DIR`, defaulting to `~/.codex/pets` on the
server's machine. Each immediate child directory contains `pet.json` and its
sprite sheet. No network share is needed after assets are copied locally.
The source share is not modified by this feature. Future replacements should be
copied locally and loaded with **Refresh**.

This preview supports the supplied version-2 sprite layout: a 1536 × 2288 PNG or
WebP sheet, 8 columns × 11 rows, 192 × 208 pixels per frame. It loops the first
seven frames of the first (idle) row. It does **not** use movement/action rows or
modify the artist's asset. Full roaming, voice, and agent-reactive behaviors are
not part of this change. The current Bones sheet has inconsistent movement rows;
those should be replaced by the finished sprite before adding those behaviors.

Biggy also supports the supplied `strip-v1` six-frame coffee-sip PNG (2172 × 724,
362 × 724 per frame), preserving its native aspect ratio. The local manifest supplies
frame dimensions, count, and durations `[280,110,110,140,140,320]` milliseconds.
The PNG and reference GIF are copied to `~/.codex/pets/biggy`; share originals remain
unchanged. `defaultAnchor: "dialog-right"` selects the dialog placement.

Animation controls: **Animation speed** (25–150%), **Pause between animations**
(0–20 seconds), and **Random timing**. Biggy starts at half speed with an 8-second
pause varied randomly from 4 to 12 seconds. Randomness changes rest time, not frame
order, so the reach/sip/lower sequence remains coherent. Zero pause means continuous.
Bones retains its original speed and continuous idle until changed. All controls
persist per pet and add no model or voice calls.

Manifest example:

```json
{
  "id": "bones",
  "displayName": "Bones",
  "spriteVersionNumber": 2,
  "spritesheetPath": "spritesheet.webp"
}
```

Pet directory names and IDs must match and use lowercase letters, digits,
underscores or hyphens. Sprite paths must be simple PNG/WebP filenames.
Symlinks, traversal paths, active formats, malformed manifests and unsupported
versions are rejected. Files are size-bounded and opened relative to held directory
handles with symlink protection. This local-file reader currently requires POSIX
directory-handle support (the Smedley macOS deployment).

`GET /api/biggy/pets` lists compatible manifests; `GET /api/biggy/pets/{id}/sprite`
serves only their named image. Both use the existing WebUI authentication boundary.
Responses expose no local filesystem paths. Image URLs change with content hashes;
browser refresh can pick up a replacement without an application restart.

## Performance and lifecycle

No LLM, TTS, microphone, external request, or recurring catalog polling is used.
The animation uses frame-specific timers only while enabled and the
page is visible. Reduced-motion preferences stop animation. Disabled pets have no
animation timer. The sprite accepts pointer input only within its own bounding
box for dragging; place it clear of controls you need to click. Its default position
clears the prompt and it moves clear of the open resize/settings panel. Unmount releases timers,
observers, pending catalog requests and listeners.

## Verification

- `./scripts/test.sh tests/test_biggy_pets.py`: catalog, multiple pets, missing
  files, version/path/symlink guards, replacement invalidation.
- `node tests/browser_biggy_pets.cjs` with Playwright available: actual frontend
  selection, visibility, sizing, drag/keyboard movement, saved position, unchanged composer geometry,
  reduced motion, missing selected pet, empty/error recovery and teardown.
  Isolated harness widths: 1920, 1366 and 390. This is responsive coverage of the
  pet component, not a claim that every existing Biggy panel is mobile-ready.
- Set `BIGGY_TEST_CHROMIUM` to an installed Chromium executable if necessary;
  `BIGGY_PET_TEST_SPRITE` optionally uses a supplied local sprite instead of the
  generated test fixture. No production credentials or agent calls are used.
- Live Chrome verification: PET control at the PA sidebar bottom, Biggy preview,
  on/off and popup controls. Unauthorized catalog/sprite requests return 401.

Rollback: remove the pet loader from `applyShell` in `biggy-brand.js` and the
two `/api/biggy/pets` GET branches. Local sprite files and chat sessions need not
be removed. No changes to speech, routing, electrical calculations or review state.
