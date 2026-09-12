# Vision core — Hermes bridge closeout (2026-09-12)

**Card:** `vision-core-cursor-20260912`  
**Live release:** `vision-core-20260912-164059` (Workspace schema6)  
**Hermes private destination:** `FlaBouy/hermes-webui-smedley` branch `fix/v6-embed-console-cleanup`  
**Public `origin` (nesquena/hermes-webui):** must not receive this Vision push

## What shipped (Hermes)

| Path | Role |
| --- | --- |
| `api/biggy_workspace_embed.py` | Smedley vision capability/analyze fulfill; `display-capture=(self)` Permissions-Policy |
| `static/biggy-brand.js` / `static/biggy-brand.css` | Cockpit VISION → Visual Capture in-place capture embed |
| `static/biggy-document-viewer.js` | Evidence original + analysis reopen allowlist |
| `tests/test_vision_core_chromium.py` | Isolated Workspace Vision E2E |
| `tests/test_vision_cockpit_entry_chromium.py` | Real Workspace iframe cockpit entry + startup wiring |
| `tests/test_biggy_workspace_embed.py` | Fulfill + embed header regressions |

## Tests (evidence, not owner acceptance)

- Workspace: 275 unittest discover (prior full run); focused Vision adapter/UI slices green at Rev E.
- Hermes: focused embed vision fulfill + Permissions-Policy; Vision E2E **1 passed**; cockpit iframe **2 passed**.
- Helper: `work/vision/test_deploy_vision_core.py` **15 OK** (handoff packaging; not a Hermes tree test).
- Perceptual local model proof (synthetic WREN / shapes) recorded earlier; not re-run at closeout.

## Owner path (verified by coordinator, not owner-accepted)

`http://127.0.0.1:8790/` → VISION → Visual Capture → capture-only iframe. No Planner/password in that path. Close Vision returns to Message Biggy. Owner capture→analyze→save/reopen remains pending when Rick is available.

## Data-preserving backups

| Item | Path / note |
| --- | --- |
| Pre-cutover Workspace SQLite | `/mnt/DATA_Hot/Biggy_Workspace/backups/vision/20260912-164059-pre-vision-core/workspace.sqlite3` |
| Prior Workspace release retained | `vision-core-20260912-163142` |
| Hermes bridge snapshot | handoff `work/vision/hermes-bridge-backups/20260912-164059/{baseline,candidate}/` |
| Failure policy | After candidate start: retain current DB6; never auto-restore pre-backup over later writes; never `migrate_down`; RAG not restarted |

## Explicit limits / next

- No recording; gestures and machine control remain disabled in this increment.
- Focus / Screen Guidance standalone cockpit modes are follow-on.
- **Next increment:** TD camera streaming and virtual backdrop (not implemented here).
- No claim of owner production capture acceptance in this closeout.
