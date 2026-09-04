# A.R.G.U.S. cockpit Object

## Production cut-in

The accepted custom Orb is now mounted in production as one composite Object.
It owns the Orb artwork, eye, menu geometry, tie-ins, editable name, model label,
and online/state indicator. The existing hidden Hermes controls remain the sole
function owners; the Object relays its twelve allowlisted action IDs to those
controls and reflects their active state. The independent Biggy prompt remains a
fixed page anchor outside the Object.

The Orb is permanently mounted on glass. ANI may select, move, resize, or center
it, but cannot hide or remove it. **Show all**, **Hide all**, and **Remove
selected** apply only to the other animated Objects.

Preview: `http://127.0.0.1:8790/static/argus-cockpit-pet-poc.html`

Files:

- `static/argus-cockpit-pet-poc.js` — portable `<argus-cockpit-pet>` entity
- `static/argus-cockpit-pet-poc-adapter.js` — isolated pre-wiring contract adapter
- `static/argus-cockpit-pet-poc.html` — isolated visual/interaction preview
- `tests/test_argus_cockpit_pet_poc.py` — isolation and contract guards
- `tests/browser_argus_cockpit_pet_poc.cjs` — optional isolated browser harness
- `scripts/package_argus_cockpit_pet_poc.py` — builds a portable reviewer ZIP

## Current Object behavior

The entity reuses the accepted transparent Orb artwork and preserves the current
twelve-button geometry, A.R.G.U.S. label, model label, and online/state indicator.
The center is a glass sensor eye rather than a concentric illuminated button. A
fixed dark aperture and faint breathing rim contain a mobile textured red iris,
vertical pupil, and asymmetric lens highlights. Pointer movement anywhere in the
document moves only the iris/pupil toward the pointer, up to 11 pixels horizontally
and 8 pixels vertically, with eased motion. The aperture, blue rings, outer shell,
lamps, menu buttons, and readout do not move. Mouse exit or window blur returns the
gaze to center.

The first accepted motion vocabulary is implemented without adding decorative
radar effects. Idle uses a slow clockwise solid ring, slower counter-clockwise
dashed ring, restrained eye breathing, and low outer-lamp activity. Hovering a
menu button brightens only that button, its node, and its existing tie-in. An
active menu selection turns the button green and changes the carrier into a bold
white solid connection. Thinking increases the two ring cadences and changes the
status indicator to amber. Speaking uses an irregular red-eye and authored blue
lamp pulse while leaving menu geometry fixed. The preview state simulator can
switch between Idle, Thinking, and Speaking; menu selection is exclusive.

Only the two centered mechanical ring layers rotate continuously. Reduced-motion
mode stops rotations, pulses, and traveling tie-in effects while preserving every
color and state indication.

The second motion pass adds bounded operational outcomes. Working advances the
clockwise ring in twelve measured steps while leaving the slower opposing layer
alone. Success draws one temporary teal confirmation sweep and settles the active
path green. Warning keeps its path and text steady while the amber aperture ring
flashes on a slow 1.8-second cadence. Error keeps its path and text steady while
the red aperture ring flashes faster at 0.72 seconds. These signals are driven by
`status` and do not infer completion, severity, or tool progress inside the
component.

The remaining authored modes complete the POC state vocabulary. Listening/PTT
holds a calm teal aperture pulse, measured lamp cadence, and an illuminated
microphone control on the fixed Biggy bar. Fleet Dispatch accelerates the two
existing opposed rings and shifts only the active connection, lamps, indicator,
and fixed bar glow toward a restrained periwinkle signal. Sleep pauses the ring
layers and dims the shell, eye, menu, tie-ins, indicator, and fixed bar without
moving or hiding any control. None of these modes add radar sweeps or alter the
accepted geometry.

The `label` attribute owns the displayed Orb name. The standalone preview exposes
an **ORB NAME** field, limits the value to 20 characters, updates the entity
without reloading, and remembers the tester's choice only in that browser. The
default remains `A.R.G.U.S.`. Artwork and script references are relative so the
three runtime files can be moved together without depending on Biggy's `/static`
route.

The packaging script combines the HTML, JavaScript, Orb PNG, reviewer README, and
feedback worksheet into one uploadable ZIP. The package remains inert: menu and
composer events are visible demonstrations only and call no external service.

The preview treats the Orb, menu buttons, tie-ins, name, and model/state readout
as one scalable object. The Size control supports 60–140 percent; button boxes,
labels, borders, glows, and readout geometry use the component's own width as
their scale reference, so they retain their relationship to the Orb. **Drag to
Move** repositions the complete Orb entity while keeping it inside the viewport,
and **Center** restores its 100-percent default position. Layout is saved only in
the tester's browser. These preview controls are not the future production
controls; the production multi-object manager remains the eventual state owner.

The production-shaped **Message Biggy…** bar remains an independent, fixed page
anchor. It does not move or resize with the Orb. Its PA, attachment, bookmark,
microphone, voice, and send controls retain fixed dimensions while its border and
glow react in place to the state simulator. The field is editable for layout
testing, but Enter, Send, and every companion control emit inert page events only.
Nothing is submitted, recorded, uploaded, or sent to Biggy from the POC.

The response layer is also an independent fixed surface rather than part of the
Orb transform. Its simulator demonstrates hidden, concise, expanded technical,
and interrupted states. Concise keeps the conversational answer prominent;
expanded reveals supporting detail without changing the Biggy bar; interrupted
uses an explicit recoverable status. These are presentation fixtures only and do
not create, replay, cancel, or retry a real turn.

An isolated adapter now owns the preview's event choreography. It allowlists all
twelve stable action IDs, enforces one active menu action at a time, records only
the name of a composer control and the length of submitted test text, and emits a
read-only versioned contract snapshot. The visible **PARITY PASS · 12/12 ·
10/10** readout confirms that all twelve action structures and all ten authored
state controls loaded, the six fixed composer controls are present, and the
production-wired flag remains false. It does not claim that any production
service is connected.

The editable name uses an optical offset rather than ordinary whole-string
centering: the center of the `G` in the default `A.R.G.U.S.` label aligns to the
Orb centerline without moving the model/status readout below it.

Menu feedback is deliberately restrained. A quiet dotted carrier terminates at
an exposed connector node outside each button—no linework runs beneath a button.
The two button banks sit far enough outside the Orb to leave the carrier and its
traveling signal legible at every supported scale while remaining mirrored. Tie
paths originate at the artwork's visible illuminated outer perimeter rather than
the PNG's transparent image boundary, so the full enlarged carrier remains
visible between the Orb and connector. Each elbow sits halfway toward its button,
softening the indexed break angle and shortening the final horizontal approach.
Hover repeatedly sends a bright, tapered energy pulse from the Orb to the button
for as long as pointer hover or keyboard focus is maintained. Once selected, the
complete carrier becomes a solid highlighted line and breathes slowly with its
green button and connector node, so a live connection cannot be mistaken for an
idle dotted path; it does not repeatedly fire a projectile.
Working breathes cyan;
success sends one green
confirmation; warning flashes orange slowly; and error flashes red more urgently.
Deactivation retracts the path toward the Orb. Only selected paths animate
continuously, warning/error override hover, and reduced-motion preferences stop
all nonessential movement while retaining the state colors.

The sample sheet at
`Build Docs/Argus V1.0/Graphics/Orb/Codex Image Sep 4, 2026, 06_17_48 AM.png`
is a useful reference for future state vocabulary—idle, listening/PTT, thinking,
speaking, tool active, fleet dispatch, success, warning, error, sleep, cursor
awareness, and expanded interaction. It is an RGB reference image with its
checkerboard baked into the pixels, so it is not used as production transparency
or as a runtime sprite source.

## Production wiring contract

`model`, `status`, and `tracking` are attributes. `setActiveActions()` paints an
allowlisted set of active menu buttons. A menu press emits one
`argus-cockpit-action` event whose detail contains only the stable lower-case
action ID. The independent composer emits `argus-cockpit-control`; Enter and Send
emit `argus-cockpit-submit` with the current field text. The POC never interprets
or executes any of those events.

The accepted integration is:

1. Load the shared Object renderer in the production shell.
   The PA right-rail entry is labeled **ANI**, and all user-facing cutover
   documentation and labels use **Objects** throughout.
2. Relay the twelve action IDs to the existing Hermes-owned controls.
3. Feed model, online, thinking, speaking, tool, and error state into Object
   attributes without creating a second state owner.
4. Keep the existing prompt as an independent static anchor.
5. Let ANI control permanent Orb position and size while disabling removal and
   visibility controls for that Object.
6. Keep the retired Orb iframe, cloned menu, external name, and external readout
   out of production.

The standalone preview and adapter remain inert reviewer fixtures. Compatibility
filenames and the internal custom-element tag retain their original identifiers;
all visible controls and product documentation call the feature **Objects**.
