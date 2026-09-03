# Hermes worker — Project Review MCP activation

Status: **LIVE registered** (Turing). Deps in hermes-agent venv; MCP block in Smedley profile; Biggy WebUI restarted. External producer/watch patches remain staged.

## Operational update (2026-09-02)

- Turing installed **11 pinned missing deps** into live hermes-agent venv; main verified **`pip check` clean** + versions.
- Turing registered `smedley_project_review` in `/Users/rick/.hermes/profiles/smedley/config.yaml` (was absent):
  - `command`: `/Users/rick/hermes-webui/.venv/bin/python`
  - `args`: `/Users/rick/hermes-webui/scripts/smedley_project_review_mcp.py`
  - `env.HERMES_WEBUI_STATE_DIR`: `/Users/rick/.hermes/profiles/biggy/webui-state`
  - `enabled: true`, `connect_timeout: 45.0`
  - model / provider / personality **untouched**
- Turing restarted **only** `ai.biggy.webui` after `/health` showed zero active runs.
- Post-restart `:8790` `/health`: `status=ok`, `server_started_at=1788350261.069769`, `active_runs=0`.

## Live verification (stdio MCP; HTTP 401 without session)

Bounded live tests used the **actual registered** command/env (no monkeypatch). Project `bdd341b152a4`. See `docs/smedley-dxf-verified-ocr.md` for paths/counts/times.

HTTP GET `/api/biggy/projects/reviews/extract/capabilities` → **401** (`Authentication required`); auth not disabled; no cookie available in that pass.

## Still staged / not claimed

- External producer/watch patches under `runtime/argus-rag/patches/` — **not deployed**
- Automatic DXF watcher ingestion — **not claimed**
- Table/`cells_verified` engineering verification — **not claimed** while `structure_unverified`

## `12-1-0104.pdf`

**TEST ONLY** — leave exactly where placed under 26HOS-006; do not move/rewrite; do not publish as production Hosford findings.
