# A.R.G.U.S. cockpit-Orb test package

This package is a standalone visual proof of concept. It does not connect to a
Biggy, Hermes, RAG, calendar, messaging, or tool service.

Open `argus-cockpit-pet-poc.html` in a modern browser. Use **ORB NAME** to give
the Orb a local name; the browser remembers that choice. Move the pointer around
the page to test the eye, select menu buttons to test their paths, and use the
state buttons to inspect each animation. Size scales the entire Orb/menu/readout
entity from 60–140 percent without changing the button-to-Orb proportions. Drag
**DRAG TO MOVE** to reposition the entity and use **CENTER** to restore its
default size and location. The browser remembers the tester's layout.

Keep the HTML, JavaScript, and PNG files together. They use relative paths so the
folder can be hosted by any ordinary static web server. Some browsers restrict
local `file://` pages; if direct opening is blocked, serve the folder locally or
upload its contents to a static host.

Record recommendations in `FEEDBACK.md`. Do not treat this POC as production
software or as evidence that any displayed action has run.
