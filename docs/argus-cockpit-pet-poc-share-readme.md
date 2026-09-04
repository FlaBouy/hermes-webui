# A.R.G.U.S. cockpit-Orb test package

This package is a standalone visual proof of concept. It does not connect to a
Biggy, Hermes, RAG, calendar, messaging, or tool service.

Open `argus-cockpit-pet-poc.html` in a modern browser. Use **ORB NAME** to give
the Orb a local name; the browser remembers that choice. Move the pointer around
the page to test the eye, select menu buttons to test their paths, and use the
state buttons to inspect each animation. Size scales the Orb/menu/readout entity
from 60–140 percent without changing its proportions. The **Message Biggy…** bar
is a separate fixed page anchor: it neither moves nor resizes with the Orb, but it
does reflect state changes in place. Its field and controls are inert layout
tests; they do not send, record, attach, or invoke a service. Drag
**DRAG TO MOVE** to reposition the entity and use **CENTER** to restore its
default size and location. The browser remembers the tester's layout.

The state strip includes Idle, Listening, Thinking, Speaking, Dispatch, Working,
Success, Warning, Error, and Sleep. Listening highlights the fixed microphone;
Dispatch demonstrates fleet activity; Sleep pauses and dims the Orb without
changing its placement.

Use the **RESPONSE** controls to inspect the independent conversation surface in
hidden, concise, expanded, and interrupted/error presentations. The sample text
is fixed demonstration content and does not come from an assistant service.

Keep the HTML, JavaScript, and PNG files together. They use relative paths so the
folder can be hosted by any ordinary static web server. Some browsers restrict
local `file://` pages; if direct opening is blocked, serve the folder locally or
upload its contents to a static host.

**PARITY PASS · 12/12 · 10/10** means all twelve inert menu structures, all ten
authored state controls, and all six fixed composer controls are present in the
standalone adapter. Selecting a button appends its active ID to that readout.
This is a POC parity check, not a live Hermes connection.

Record recommendations in `FEEDBACK.md`. Do not treat this POC as production
software or as evidence that any displayed action has run.
