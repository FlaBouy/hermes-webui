# Biggy Workspace embed — Atlas deployment handoff

**Task:** `smedley-whiteboard-wiring-20260911`  
**Scope:** Authenticated same-origin Open Workspace (no separate owner login in GUI iframe)  
**Deploy/restart PLATO:** **not authorized for Cursor** — Atlas deploys after review.

**Ops facts (current):**
- Owner Biggy GUI origin: `http://127.0.0.1:8790`
- Workspace upstream: `https://plato.tail061f03.ts.net`
- PLATO container name: `biggy-workspace-poc-biggy-workspace-1`
- Atlas has SSH to PLATO

## What shipped (code only)

### biggy-workspace
- `POST /api/v1/session/hermes-bridge` — S2S owner-session mint (bridge secret only)
- `BIGGY_WORKSPACE_HERMES_EMBED_ORIGINS` accepts exact `https://host[:port]` **and** exact loopback `http://127.0.0.1:port` / `http://localhost:port` (no other http hosts)
- Relative static assets + embed API prefix for `/biggy-workspace/` mount

### hermes-webui
- Same-origin `/biggy-workspace/*` proxy after Hermes `check_auth` (not public; not `/static/` bypass)
- Injects minted owner session Cookie upstream; never puts secrets in browser URLs
- **Refuses to follow upstream redirects** so session Cookie / bridge Bearer cannot leave the configured upstream origin
- Open Workspace iframe → `/biggy-workspace/`

## Required configuration (never commit secrets)

| Where | Variable | Value / rule |
| --- | --- | --- |
| PLATO container | `BIGGY_WORKSPACE_HERMES_BRIDGE_SECRET_FILE` | Shared ≥16-char secret file (`chmod 600`) |
| PLATO container | `BIGGY_WORKSPACE_HERMES_EMBED_ORIGINS` | `http://127.0.0.1:8790` |
| Smedley Hermes | `HERMES_WEBUI_BIGGY_WORKSPACE_BRIDGE_SECRET_FILE` | **Same** secret bytes |
| Smedley Hermes | `HERMES_WEBUI_BIGGY_WORKSPACE_UPSTREAM` | `https://plato.tail061f03.ts.net` |

Owner password on direct PLATO URL remains. Bridge does not disable Workspace or Hermes auth.

## Atlas deploy order (not performed by Cursor)

1. Update env on `biggy-workspace-poc-biggy-workspace-1` (bridge secret + embed origin). Preserve DB/state.
2. Recreate/restart **only** that container after env is set.
3. Set Hermes env on Smedley; restart Hermes/Biggy GUI only.
4. Smoke from already-authenticated GUI at `http://127.0.0.1:8790`: Open Workspace → planner, no Owner sign-in; View whiteboard unchanged.

## Rollback

- Unset Hermes upstream/bridge → `/biggy-workspace/` 503 fail-closed.
- Unset Workspace bridge secret → mint `bridge_not_configured`; direct owner login unchanged.
- Backups: `hermes-webui/backups/workspace-session-embed-*`, `workspace-embed-origin-fix-*`

## Non-claims

No deploy/restart performed by Cursor. No production state mutation. No owner-facing login steps generated.


## Atlas execution (deterministic script)

Script: `hermes-webui/scripts/deploy_biggy_workspace_session_bridge.py`

```bash
# 1) Preflight only (no mutation)
python3 /Users/rick/hermes-webui/scripts/deploy_biggy_workspace_session_bridge.py --preflight-only

# 2) Apply after preflight OK (Atlas only)
python3 /Users/rick/hermes-webui/scripts/deploy_biggy_workspace_session_bridge.py --apply
```

If preflight reports `owner_session_state=setup_required`, stop — owner password must already exist on Workspace DB before apply.
