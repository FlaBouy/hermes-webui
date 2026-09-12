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

Implementation done. **Production citation acceptance blocked** — readiness registry has no READY library source under `library_only` + verified active generation. No bypass/promotion. See Workspace `docs/releases/2026-09-12-workspace-rag.md` and Codex handoff `outputs/WORKSPACE_RAG_RETRIEVE_DIAGNOSIS_20260912.md`.

## Tests (Cursor)

`tests/test_biggy_workspace_embed.py` + `tests/test_biggy_rag_ingest_proxy.py` (incl. ai_assist): **29 passed**.
