# Biggy / A.R.G.U.S. / Smedley session continuity

Last verified: 2026-09-04 (America/Chicago)

## Start here

- Repository: `/Users/rick/hermes-webui`
- Branch: `fix/v6-embed-console-cleanup`
- Project Review checkpoint: `f66069f5` — `Fix Project Review tool handoff, context, voice and verified extraction`
- Biggy integration checkpoint: `7d7c2993` — `Finish Biggy pet, conversation, travel and reconnect paths`
- The private branch is the only authorized push destination unless Rick explicitly changes it.
- Do not reset, clean, checkout, or bulk-stage the working tree. It contains unrelated evidence and staging artifacts belonging to Rick.
- Treat `tests/fixtures/project_review/native_table_evidence/` as evidence/test output, not verified engineering data.

## What is complete at the checkpoint

- Project Review has date/time and canonical RAG-directory awareness.
- Smedley review voice uses Jarnathan. General dialogue may be spoken naturally; heavy document/design returns speak only the conversational summary.
- Review dictation is local and editable before submission.
- DXF parsing and two-engine PDF OCR evidence paths are present. OCR disagreements and uncertain table structure fail closed; they are not represented as verified values.
- The review lifecycle prevents overlapping turns, reports progress, exposes cancellation/recovery, and avoids claiming work that was not run.
- Natural electrical requests open the matching calculator rather than sending the question to a model for improvised arithmetic.
- Circuit context carries owner-provided voltage, phase, HP/amps, distance, conductor material, tray/TC-ER profile, and explicit calculator edits into follow-ups.
- Owner default voltage-drop target is 2.5% maximum unless explicitly changed.
- TC-ER profile: aluminum ladder tray, 9-inch rungs; Southwire SPEC45253 is the initial supported catalog. Allied requires part-specific data.
- Sentence streaming no longer clips a reply at a split decimal or at `approx.`.

## Final verification evidence

- Clean staged-tree suite: 239 passed, 1 optional local-model smoke skipped.
- Broader working-tree suite before commit: 152 passed, 1 optional local-model smoke skipped.
- The two observed warnings came from the installed Hermes MCP child watcher and were not test failures.
- Live browser, exact owner request: `We have a 480V 3P 10HP motor sitting 750 ft from the bucket and feeder will be ran in cable tray. Size the feeder for that motor using copper conductors`.
  - Feeder Size opened in about 380 ms.
  - Populated: 480 V, 3-phase, 10 HP, 750 ft, copper, aluminum tray, TC-ER, Southwire, 9-inch rungs, 2.5% target.
  - The first result visibly failed the target; it was not presented as an approved conductor size.
- Live follow-up: `Re-run that shooting for 2% VD`.
  - Voltage Drop opened in about 343 ms.
  - Retained the active 750 ft circuit and changed only the target to 2%.
  - The test then restored the saved target to 2.5%.
- These are routing/UI checks and provisional tool results, not engineering approval of the installation.

## Biggy integration completed after the Project Review checkpoint

- Local Biggy pets are selectable from a PET control at the bottom of the PA right rail. They support on/off, resizing, dragging, keyboard movement, per-pet saved placement, slow/random animation, and reduced-motion behavior without an LLM, voice call, or network polling.
- Bones and Biggy assets are served through a path-safe local catalog/sprite API. Biggy defaults to the right of the prompt; Bones defaults above it.
- The stock center transcript is visually suppressed in the Biggy cockpit so the branded left LIVE lane is the single response presentation. HOME hides that lane without deleting its retained turns.
- Ordinary typed conversation and PTT opinion/story requests stay on Biggy's local V6 fast path. They no longer inherit a prior travel card or wake the heavy A.R.G.U.S. workflow merely because a previous route exists.
- A.R.G.U.S. travel setup now parallelizes independent geocoding, route, and point-of-interest reads and uses tighter bounded timeouts. Compact travel speech accepts a verified map model without requiring the full card schema.
- Google Calendar/Gmail revoked-token handling now presents a reconnect action. The browser preserves the full OAuth callback URL, including state and scopes, and uses the styled in-app prompt instead of a native browser prompt. The unsafe localhost callback page may be copied in full and pasted into this completion dialog.
- A clean staged-index checkout passed 189 affected regression tests. The isolated real-Chrome pet/layout exercise passed selection, on/off, resize, persistence, dragging/keyboard behavior, reduced motion, empty/error recovery, teardown, and 1920/1366/390 viewport checks.
- A broader repository sweep exposed unrelated legacy/global-state failures, including pre-existing native confirms and older stream-order assumptions. It must not be represented as an all-green full repository suite; the staged release suite is the authoritative verification for `7d7c2993`.

## Live runtime state at handoff

- Biggy: `http://127.0.0.1:8790/health` — healthy, no active runs or streams.
- Electrical tools: `http://127.0.0.1:8801/health` — version 4.0.0; all 11 tools active.
- Biggy LaunchAgent: `ai.biggy.webui`; the managed listener was restarted after deployment and reports a HEAD-derived build in its HTTP `Server` header. Its PID is ephemeral; verify ownership with LaunchAgent state and port 8790 before any process action.
- A second non-listening `server.py` process was observed earlier. Diagnose before terminating; do not assume it is safe merely because it is not listening.
- LM Studio, Hermes gateway/MCP services, Cursor IDE worker, and the fleet coordination services were running.
- Local CLIs available: `/Users/rick/.local/bin/cursor`, `/Users/rick/.local/bin/hermes`, `/Users/rick/.local/bin/agent`.

## Working tree after the Biggy integration checkpoint

The Biggy pet, conversation, travel, calendar/reconnect, and related regression files are committed in `7d7c2993`. The tree remains intentionally dirty only because unrelated owner evidence and staging artifacts were preserved.

Important untracked groups still include:

- OCR investigation evidence: `tests/fixtures/project_review/native_probe/` and `native_table_evidence/`.
- RAG producer/watch patch-test staging under `runtime/argus-rag/staging/`.
- Local audit helpers and screenshots.
- A malformed Windows-style `P:\\...` artifact path and `:memory:.ses`; inspect before deciding whether either may be removed.

Before any new commit, use selective staging and verify the staged snapshot. Never run a blanket `git add .` here.

## Known limitations / next work

1. Vendor PDF extraction is improved but not equivalent to precise engineering review. The WB3339 material still contains OCR disagreements/structure uncertainty that require a native source or owner verification.
2. Automatic DXF/PDF watcher integration remains staged, not deployed. Do not claim that merely dropping every new file will invoke the verified Project Review extraction path.
3. Review arithmetic should continue to open the deterministic GUI tool. A service error/no-solution result now opens Conductor Sets with retained inputs and must not fall back to model arithmetic.
4. Investigate the non-listening duplicate `server.py` process without interrupting the managed Biggy listener or an active review.

## Safe continuation procedure

1. Read this file and the repository `AGENTS.md`, `GUIDELINES.md`, `CONTRIBUTING.md`, and `CONTRACTS.md` before changing code.
2. Recheck `git status --short`; preserve every unrelated edit.
3. Confirm Biggy and tools health and confirm zero active runs/streams before restarting services.
4. Run tests through `./scripts/test.sh`, never bare system `pytest`.
5. For Project Review regression, include:
   - `tests/test_review_tool_handoff_regressions.py`
   - `tests/test_review_dictation_and_circuit_context.py`
   - `tests/test_smedley_cable_tray.py`
   - Project Review awareness, speech, lifecycle, follow-through, runaway, and DXF/OCR suites
6. For a commit, build and test a clean checkout of the staged index so uncommitted working-tree code cannot mask missing dependencies.
7. Push Project Review work only to the private remote unless Rick explicitly changes the destination.

## Resource snapshot

- Codex weekly/general window: 63% used, 37% remaining; reset reported for 2026-09-07 03:21 CDT.
- Two unused full-reset credits were available. Do not redeem either without Rick explicitly asking.
- GPT-5.3-Codex-Spark: 0% used in both the five-hour and weekly windows at the check.
- No Cursor quota figure was available from the local inventory. Preserve its allocation as scarce; Cursor had previously been reported at 6% remaining.
- Local execution capacity is strong: LM Studio, Hermes MCP/gateway, Cursor worker, Biggy, RAG services, and all electrical tools were online.

## Bottom line

The Project Review and Biggy integration checkpoints are safe, selectively staged, tested, and committed. The account still has usable Codex headroom and two emergency reset credits, while local model and Hermes capacity are available. This session can safely finish deployment and documentation; a later fresh session should start from this file and preserve the remaining unrelated dirty-tree evidence.

## External records updated

- Build Docs: `Z/DATA/Build Docs/Argus V1.0/PROJECT_STATUS.md`
- Build Docs synopsis: `Z/DATA/Build Docs/Argus V1.0/SYNOPSIS.md`
- Build Docs handoff: `Z/DATA/Build Docs/Argus V1.0/SESSION_CONTINUITY_2026-09-04.md`
- Fleet Registry: `Z/DATA/n8n_share/fleet-coordination/registry/PROJECT_REGISTRY.md`

The fleet coordinator rule was reconciled with `registry/machines.json`: `codex@SMEDLEY` is authoritative; the stale `claude@THUNDERDOME` rule was removed.
