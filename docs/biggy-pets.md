# Biggy animated Objects

The **ANI** button sits at the bottom of the PA right sidebar. Open PA, then ANI.
Closing PA hides the settings popup and ANI button, not the enabled object. The popup
is outside the rail's clipping area. The Orb and prompt axis are unchanged.

The A.R.G.U.S. Orb is always mounted on glass as the protected first Object.
Selecting it exposes size, drag placement, and **Center Orb**. Its visibility
toggle reads **Always on**, and both that toggle and **Remove selected** are
disabled. Global show/hide controls never affect the Orb.

Open ANI to add any number of other local Object instances. The control separates the
available catalog from the **On-screen objects** list, so two copies of the same
object can remain visible and still have independent size, placement, visibility,
and animation timing. **Show all** and **Hide all** are global display controls;
**Show/Hide selected** and **Remove selected** affect only the chosen instance.
State persists in this browser's `biggy:pets:v2` local storage independently of
chat sessions. Existing `biggy:pets:v1` single-object state migrates once into one
object instance. A missing catalog entry is retained but hidden and returns when
that catalog entry becomes available again; it is never replaced silently.

Drag any visible object with a mouse or touch to place it anywhere on screen. Clicking
or focusing an object selects that exact instance in the controls. Its position persists
as viewport-relative coordinates and remains inside the viewport after resizing.
With the object focused, arrow keys move it 8 pixels (Shift: 24).
Escape during a drag cancels that movement. **Place above Message Biggy** resets
Bones to the default spot just above the left edge of the typing field. Biggy's
**Place right of dialog** defaults to the right of the visible conversation lane,
bottom-aligned; with no dialog, it falls back to the right of the message prompt.
Each instance saves its own size, position, visibility, and animation controls. Biggy defaults to
256px tall; the initial 128px Biggy setting is doubled once during migration.
Opening ANI
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
persist per instance and add no model or voice calls.

## Production Orb Object

The rebuilt Orb, menu buttons, label, and model/online indicators are one
composite **cockpit Object**, not unrelated controls and not a passive sprite.
The control vocabulary therefore uses **Add Object** and **On-screen Objects**:

- one object identity owns the Orb, its menu buttons, and its dialog geometry;
- moving or resizing the object preserves their authored relationships;
- interactive hit regions expose stable action IDs that relay to the existing
  Hermes controls after the POC is accepted;
- the cockpit Object is selectable, movable, and resizable, but permanently
  mounted and protected from every hide/remove command;
- each other animated Object retains independent selection, visibility, removal,
  position, size, speed, pause, and random-timing controls;
- the accepted Object is wired to the existing production function owners, and
  the legacy Orb/menu/readout DOM has been retired.

The renderer is code-backed (HTML/SVG with an allowlisted
action map), even if its artwork arrives as a raster asset. A bitmap manifest
alone will never be allowed to invent or execute menu actions.

Manifest example:

```json
{
  "id": "bones",
  "displayName": "Bones",
  "spriteVersionNumber": 2,
  "spritesheetPath": "spritesheet.webp"
}
```

Object directory names and IDs must match and use lowercase letters, digits,
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
Each instance uses its own frame-specific timer only while enabled and the page
is visible. Reduced-motion preferences stop every animation. Disabled Objects have no
animation timer. Each sprite accepts pointer input only within its own bounding
box for dragging; place it clear of controls you need to click. Its default position
clears the prompt and it moves clear of the open resize/settings panel. Unmount releases timers,
observers, pending catalog requests and listeners.

## Verification

- `./scripts/test.sh tests/test_biggy_pets.py`: catalog, multiple pets, missing
  files, version/path/symlink guards, replacement invalidation.
- `node tests/browser_biggy_pets.cjs` with Playwright available: multiple copies
  of one Object, independent selection/visibility/sizing/timing, show/hide-all,
  drag/keyboard movement, saved position, v1 migration, unchanged composer geometry,
  reduced motion, missing selected Object, empty/error recovery and teardown.
  Isolated harness widths: 1920, 1366 and 390. This is responsive coverage of the
  Object component, not a claim that every existing Biggy panel is mobile-ready.
- Set `BIGGY_TEST_CHROMIUM` to an installed Chromium executable if necessary;
  `BIGGY_PET_TEST_SPRITE` optionally uses a supplied local sprite instead of the
  generated test fixture. No production credentials or agent calls are used.
- Live Chrome verification: ANI control at the PA sidebar bottom, Biggy preview,
  on/off and popup controls. Unauthorized catalog/sprite requests return 401.

Rollback: remove the Object loader from `applyShell` in `biggy-brand.js` and the
two `/api/biggy/pets` GET branches. Local sprite files and chat sessions need not
be removed. No changes to speech, routing, electrical calculations or review state.
