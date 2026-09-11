# Closeout — Cursor whiteboard / Workspace embed (2026-09-11)

**Task:** `smedley-whiteboard-wiring-20260911`  
**Component branch:** `fix/v6-embed-console-cleanup` → remote `private` (`FlaBouy/hermes-webui-smedley`, private).  
**Companion:** `biggy-workspace` `inception/local-foundation` → `origin` (`FlaBouy/biggy-workspace`, private).

## Final source checkpoint

Whiteboard/office-planner wiring, Hermes↔Workspace authenticated embed bridge, and pre-existing legitimate source dependencies on this branch (PA/office planner modules, continuity/review shims, sentinel host, deploy helpers, related tests).

Focused tests at checkpoint: **75 Hermes** / **51 Workspace**. Wider backlog is checkpointed in this commit and **not fully retested**.

## Earlier Smedley GUI observation — 2026-09-11

Deployed GUI observed:

- Workspace day calendar — no extra login; duplicate badge removed
- Separate **View whiteboard** revision2 — seven Waiting Office Planner tasks
- Workspace — two unscheduled tasks; AI / ARGUS / RAG unconfigured

Current deployed static release: `static-update-20260911-135526`. **This push performs no deployment.**

## Not in this repo commit lane

- **NAS Build Docs / Fleet Registry** — Atlas updates separately under `/Users/rick/Mounts/Z/DATA/Build Docs/`. This file is the component-repo closeout pointer only.
- Secrets, runtime state, screenshots, `backups/`, `*.orig`, `runtime/argus-rag/staging/`, `:memory:.ses`, Windows-path agent-feed artifacts, private raw project-review fixtures, local PDF audit scratch.

## Ops (no secrets)

- Embed: same-origin `/biggy-workspace/*` after Hermes auth; S2S bridge secret via `*_SECRET_FILE` only.
- Deploy/restart PLATO and Hermes runtime remain Atlas after review — not performed by this push.

## Final coordinator review — September 11, 2026

The follow-up review opened the existing authenticated Biggy browser session on Smedley, then PA → Planner → Open Workspace. Workspace opened through `/biggy-workspace/` without a second owner login. Today’s day grid, mini calendar and two unscheduled synthetic tasks loaded. The removed uppercase duplicate badge remains absent; the outer panel title and inner page heading remain.

Closing Workspace returned to Office Planner. Visual Planning → View opened the separate full-width Local Visual Planner with the seven-step Smedley Cursor plan restored at revision 5. This supersedes the revision 2 observation above. Screenshots were visually inspected in the coordinator task; these were Smedley GUI observations, not captures of HAL’s physical display.

The authenticated bridge works. Later unauthenticated 302/401 probes did not demonstrate a deployment failure. No bridge redeployment, credential change or service restart was required. The source checkpoints reviewed were Hermes `0e784a19` and Workspace `84a0a56`; the previously recorded static release was not redeployed in this follow-up.

The 75 Hermes / 51 Workspace focused test counts above are historical checkpoint evidence, not tests rerun during this GUI review. Workspace AI/local inference and ARGUS/RAG remain unconfigured, and no successful offline-worker tick was observed. These are outside this GUI closeout.
