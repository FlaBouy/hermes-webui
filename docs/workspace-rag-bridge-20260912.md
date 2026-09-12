# Workspace Library search bridge — Hermes (2026-09-12)

**Task:** `workspace-rag-cursor-20260912` (bridge) · Atlas apply `workspace-rag-atlas-20260912`
**Branch:** `fix/v6-embed-console-cleanup` → remote **`private`** only (`FlaBouy/hermes-webui-smedley`). Never push `origin`.

## Deployed integration

Atlas applied companion Workspace release `workspace-rag-20260912-131842` and restarted `ai.biggy.webui`. Hermes embed:

- Intercepts `POST …/api/v1/commands` with `command=rag_search`
- Fulfills on Smedley: `POST http://127.0.0.1:5004/rag/retrieve` (`library_only`), concurrency=1 + connect/read wall
- Does **not** forward `rag_search` to PLATO
- Does **not** allowlist `/api/biggy/rag/retrieve` (no gate bypass)
- Owner health probes: `/api/biggy/rag/health`, `/api/biggy/v6/health`

Owner check: existing session opens `/biggy-workspace/` with Library search; task counts 2/0/2 unchanged.

## Remaining blocker

**Fixed in package (pending Atlas apply):** Project Review readiness was incorrectly gating general library retrieve. Restored `library_qdrant_filter` (`is_empty(project)` + exclude failed). See `outputs/WORKSPACE_RAG_COMPLETION_CURSOR.md`.

Atlas must restart `com.flabo.smedley.rag-api` and `ai.biggy.webui`, then run bounded multi-doc acceptance.

## Tests (Cursor)

`tests/test_biggy_workspace_embed.py` + `tests/test_biggy_rag_ingest_proxy.py` (incl. ai_assist): **29 passed**.

### Original-source route correction
Workspace citations use the authenticated `/api/biggy/rag/doc/` and `/api/biggy/rag/preview/` routes to the fixed local corpus service. They no longer depend on the retired extension registration. Safe relative paths, same-origin browser provenance, existing owner authentication and bounded streaming remain enforced. Regression evidence: original routing tests failed before correction; Workspace 11 tests passed; Hermes retrieval/embed/navigation 47 passed; proxy and neighboring extension security tests 63 passed. Live browser acceptance is recorded separately after deployment.

Final browser acceptance: release `workspace-rag-20260912-142041`; ControlLogix and Honeywell returned five real excerpts each. Their original PDFs opened in the owner Chrome session (196 and28 pages respectively). Counts2/0/2 unchanged. Anonymous source request denied401.

## In-GUI document windows and Clear sources
Rick's default across modules: open documents inside the GUI in a draggable, resizable window with Close document, preserving fullscreen. Shared BiggyDocumentViewer handles first-party document links, same-origin module frames, and RAG galaxy document opens. Explicit downloads and intentionally external navigation may opt out with data-document-external. Workspace embed loads the same component; same-origin corpus framing is scoped to document routes, with owner authentication preserved. Clear sources clears query/results/status and suppresses a late response without changing tasks/date.

Release workspace-rag-20260912-144240 deployed by Atlas, retaining prior142041 and rollback workspace-rag-rollback-20260912-144240. New additive viewer asset recorded before apply so baseline entry-point rollback retains it dormant. Focused browser/bridge/proxy43, Workspace11 and helper8 checks passed. Browser test verifies drag, resize, close, fullscreen, no extra page, cross-module iframe links and late-response clearing. Live owner Chrome acceptance passed: the196-page ControlLogix manual rendered inside the draggable/resizable Document viewer. Close document and Clear sources restored the planner; date2026-09-12 and counts2/0/2 unchanged.
