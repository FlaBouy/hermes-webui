# A.R.G.U.S. cockpit-pet POC

## Production boundary

The POC is a standalone custom element and preview page. Production does not
import it, the local pet catalog does not list it, and none of its twelve menu
events call a live Hermes control. The existing Orb, menu, readout, prompt, and
dialog remain the production owners until an explicit accepted cutover.

Preview: `http://127.0.0.1:8790/static/argus-cockpit-pet-poc.html`

Files:

- `static/argus-cockpit-pet-poc.js` — portable `<argus-cockpit-pet>` entity
- `static/argus-cockpit-pet-poc.html` — isolated visual/interaction preview
- `tests/test_argus_cockpit_pet_poc.py` — isolation and contract guards
- `tests/browser_argus_cockpit_pet_poc.cjs` — optional isolated browser harness

## Current POC behavior

The entity reuses the accepted transparent Orb artwork and preserves the current
twelve-button geometry, A.R.G.U.S. label, model label, and online/state indicator.
The red bulb and its two red halo layers form one bounded “eye.” Pointer movement
anywhere in the document moves only that eye toward the pointer, up to 14 pixels
horizontally and 10 pixels vertically, with eased motion. The blue rings, outer
shell, lamps, menu buttons, and readout do not move. Mouse exit or window blur
returns the eye to center.

The sample sheet at
`Build Docs/Argus V1.0/Graphics/Orb/Codex Image Sep 4, 2026, 06_17_48 AM.png`
is a useful reference for future state vocabulary—idle, listening/PTT, thinking,
speaking, tool active, fleet dispatch, success, warning, error, sleep, cursor
awareness, and expanded interaction. It is an RGB reference image with its
checkerboard baked into the pixels, so it is not used as production transparency
or as a runtime sprite source.

## Future wiring contract

`model`, `status`, and `tracking` are attributes. `setActiveActions()` paints an
allowlisted set of active menu buttons. A menu press emits one
`argus-cockpit-action` event whose detail contains only the stable lower-case
action ID. The POC never interprets or executes that ID.

After visual acceptance, the integration sequence is:

1. Add a dedicated cockpit-object adapter to the multi-object manager.
2. Map the twelve emitted action IDs to the existing Hermes-owned controls.
3. Map the existing model, online, thinking, speaking, tool, and error state to
   the entity attributes without creating a second state owner.
4. Move the existing response dialog into the same object geometry and verify
   drag/resize behavior at the physical display sizes.
5. Run parity tests for every button, active line, indicator, dialog, pulse, and
   mutual-exclusion rule.
6. Only after parity acceptance, remove the existing Orb/menu/readout DOM.

Rollback during POC development is simply closing the preview page or removing
the standalone files; production has no dependency on them.
