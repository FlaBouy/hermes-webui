# Smedley interactive electrical tools — 2026-09-03

## Owner workflow

- Project Review has **SMEDLEY VOICE**: record, stop, review/edit the transcribed prompt, then Send. It never auto-submits. Closing or changing the review cancels capture. Transcription is local-only; Jarnathan output voice is unchanged.
- Named requests for any of the eleven electrical calculators open the existing GUI tool. Voltage-drop follow-ups with known circuit inputs call the deterministic service directly, without an agent loop or model arithmetic, then open Voltage Drop populated with those inputs.
- **BACK TO SMEDLEY** saves the form's circuit parameters into that review's conversation context. It restores the conversation without overlapping the calculator. No calculation changes source drawings, OCR evidence, or project files.
- Voltage-drop target defaults to **2.5% maximum**; an explicit target takes precedence. A later follow-up retains the owner's circuit inputs rather than copying numbers from previous assistant estimates.

## Electrical installation profile

All eleven forms expose the shared installation category: aluminum ladder tray, nine-inch rungs, no cover / ventilated cover / solid cover, and TC-ER construction. Solid cover requires its continuous covered length. The adapter applies the 95% ampacity factor when an unventilated solid cover exceeds six feet under the retained NEC 2014 basis.

The initial supported manufacturer catalog is Southwire SPEC45253 copper 3C XHHW-2/CPE plus ground. OD, 75°C AC resistance, 60 Hz reactance and ampacity limits come from the product tables. Outdoor/wet/sunlight/direct-burial suitability is product-specific, not a blanket denial of TC-ER. Verify ordered cable markings.

Sources:
- [Southwire SPEC45253](https://www.southwire.com/wire-cable/power-control/cu-600-1000v-xlpe-insulation-thermoplastic-cpe-tp-jacket-xhhw-2-ct-rated-sunlight-resistant-for-direct-burial-silicone-free/p/SPEC45253)
- [Eaton NEC 2014 cable tray manual](https://www.eaton.com/content/dam/eaton/products/support-systems/cable-management/ct-manual.pdf)

Allied remains selectable but requires an exact part datasheet; it does not silently borrow Southwire dimensions. Generic SPEC45253 is not validated as a VFD-output cable; that selection returns an actionable limitation. Mixed tray size groups and extra conductors alongside jacketed cables require their appropriate fill methods. Running VD results do not approve starting voltage, EGC upsizing, bonding, supports or complete installation compliance.

## Runtime and checks

- Shared GUI assets: `extensions/smedley-engineering/`; loaded by Biggy under `/static/smedley-tools/`.
- Project Review dispatcher: `api/project_review_electrical.py`; source of known inputs is owner messages and explicit calculator edits, not prior model answers.
- External electrical service: `/Users/rick/Mounts/Z/DATA/n8n_share/Staging/RAG-build/jarvis_tools_api.py`, port 8801. Its installation adapter is deployed from `api/smedley_cable_tray.py` to the same directory. Context-local lookup overrides prevent cross-request contamination.
- Launch agents: `ai.biggy.webui` and `com.flabo.smedley.jarvis-tools-api`. Restart only after checking active review runs; reload the GUI for asset changes.
- Regression tests: `test_review_dictation_and_circuit_context.py`, `test_smedley_cable_tray.py`, existing review lifecycle/voice/voltage-drop suites.
- Live service checks: all eleven legacy tool requests returned successfully. Ten TC-ER tool checks returned successfully, including whole-cable raceway fill; VFD TC-ER correctly refused an unverified cable selection.
- Live screen check: the saved 480 V / 10 HP / 1,200 ft question with a 2.5% target opened Voltage Drop with 14 A table current, Southwire TC-ER, aluminum tray and the target populated. Service-only response was approximately 10 ms. This is not an end-to-end voice latency claim.
- A second live screen check opened Conductor Sets from the review. Changing installation to aluminum tray and selecting Back to Smedley saved the inputs in the project session; a subsequent context check retained the circuit and honored an explicit 2% target. The owner's pre-existing unsent draft was restored without submission.
- Final targeted regression run: 78 passed. JavaScript syntax, Python compilation and diff whitespace checks passed.
- Local speech test transcribed an existing audio clip successfully in 3.51 seconds, without cloud STT. Microphone permission/capture still depends on the browser and device.

Earlier conversational cable-size tables in the project transcript are retained for audit only and superseded by the tool result. They are not verified design values.

## Final handoff regression pass — 2026-09-03

- Natural action/subject requests such as "Size the feeder" and "Calculate the fill for this conduit" now select the matching calculator without requiring literal menu labels. Deferred, negated and explanatory requests do not open a tool.
- Owner shorthand `3P`, tray installation and copper conductor inputs survive the handoff. Aluminum tray material does not change conductor material. New circuits reset prior design values; follow-ups retain the active circuit.
- Stream sentence limits no longer clip decimal values or stop at `approx.` when a token chunk ends there. Split-character and split-decimal streams are covered.
- Live browser test of the owner's exact 480 V / 3P / 10 HP / 750 ft feeder request opened Feeder Size and populated its inputs in approximately 380 ms (click through snapshot). The initial result visibly failed the 2.5% constraint rather than being represented as an approved size.
- Back to Smedley saved the circuit. "Re-run that shooting for 2% VD" opened Voltage Drop with the retained 750 ft circuit and the changed 2% target in approximately 343 ms. These measurements are UI handoff checks, not speech-latency guarantees or design approval.
- A failed/unavailable calculation still opens Conductor Sets with retained inputs and an explicit no-result message. No guessed replacement or heavy agent is started.
- Clean staged-tree regression run: **239 passed, 1 optional live-model test skipped**. The two warnings are from the installed Hermes MCP child watcher, not calculation failures. The staged snapshot excludes unrelated travel/calendar/pet edits. OCR disagreement and structure gates remain enforced; these tests do not certify vendor drawing values.
