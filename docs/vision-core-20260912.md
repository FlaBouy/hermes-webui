# Vision core — Hermes bridge closeout (2026-09-12)

**Card:** `vision-core-cursor-20260912`  
**Live release:** `vision-core-20260912-172218` (Workspace schema6; tablet intake/session correction)  
**Prior live:** `vision-core-20260912-164059`  
**Hermes private destination:** `FlaBouy/hermes-webui-smedley` branch `fix/v6-embed-console-cleanup`  
**Public `origin` (nesquena/hermes-webui):** must not receive this Vision push

## What shipped (Hermes)

| Path | Role |
| --- | --- |
| `api/biggy_workspace_embed.py` | Smedley vision capability/analyze fulfill (no mint gate); minimal single-flight mint for proxy routes; `display-capture=(self)` Permissions-Policy |
| `static/biggy-brand.js` / `static/biggy-brand.css` | Cockpit VISION → Visual Capture in-place capture embed |
| `static/biggy-document-viewer.js` | Evidence original + analysis reopen allowlist |
| `tests/test_vision_core_chromium.py` | Isolated Workspace Vision E2E + tablet intake/session harness |
| `tests/test_vision_cockpit_entry_chromium.py` | Real Workspace iframe cockpit entry + startup wiring |
| `tests/test_biggy_workspace_embed.py` | Fulfill + mint-skip + auth gate + single-flight failure share |

## Tablet correction (`vision-core-20260912-172218`)

- Vision capability/analyze fulfill on Smedley without Workspace owner-session mint (Hermes GUI auth still required).
- Mint: no generic `bridge_mint_failed` retry; single-flight with shared failure for waiters; RAG mint-before-fulfill semantics unchanged.
- Focused tests before private closeout: embed **26 passed**; Vision Chromium + cockpit **4 passed**.
- Atlas deploy: DB6 integrity/data unchanged. Coordinator cockpit: intake enabled, local capability, no session error. Owner tablet recheck pending. Original mint HTTP failure status remains unknown (later mint probe observed 200 / ttl 43200).

## Tests (evidence, not owner acceptance)

- Workspace: focused Vision UI contracts **3 passed** at tablet closeout.
- Hermes: focused embed vision fulfill + mint independence + Permissions-Policy; Vision E2E + tablet session harness + cockpit iframe **4 passed**.
- Helper: `work/vision/test_deploy_vision_core.py` **15 OK** (handoff packaging; not a Hermes tree test).
- Perceptual local model proof (synthetic WREN / shapes) recorded earlier; not re-run at closeout.

## Owner path (verified by coordinator, not owner-accepted)

`http://127.0.0.1:8790/` → VISION → Visual Capture → capture-only iframe. No Planner/password in that path. Close Vision returns to Message Biggy. Owner tablet intake→analyze→save/reopen remains pending when Rick is available.

## Data-preserving backups

| Item | Path / note |
| --- | --- |
| Pre-cutover Workspace SQLite (164059) | `/mnt/DATA_Hot/Biggy_Workspace/backups/vision/20260912-164059-pre-vision-core/workspace.sqlite3` |
| Live release | `vision-core-20260912-172218` (tablet correction) |
| Prior Workspace release retained | `vision-core-20260912-164059` |
| Hermes bridge snapshot | handoff `work/vision/hermes-bridge-backups/` (Atlas apply stamp for 172218) |
| Failure policy | After candidate start: retain current DB6; never auto-restore pre-backup over later writes; never `migrate_down`; RAG not restarted |

## Explicit limits / next

- No recording; gestures and machine control remain disabled in this increment.
- Focus / Screen Guidance standalone cockpit modes are follow-on.
- **Next increment:** TD camera streaming and virtual backdrop (not implemented here).
- No claim of owner production capture acceptance in this closeout.
