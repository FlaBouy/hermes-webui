# Smedley Project Review — Tool Execution and Follow-through

Task: `smedley-review-followthrough-20260902` (HAL glass confirmed).

## Problem class

Established Project Review dialog sessions could finish **execution** requests as
warm V6 text-only replies (`project_review_fast_route=true`, no tools). Root
causes included:

1. Broad “question mark ⇒ fast” classification (and earlier AND-gate pairing), so
   siblings like `Can you do that?`, `Please proceed?`, `Could you run it again?`,
   and multi-clause `What … and please run it?` never entered the tool loop.
2. Fast lane could append / clear streaming while a governed run was live.
3. Endpoint tests that stubbed `start_session_turn` and fabricated tool+final rows
   proved **routing only**, not tool-loop completion.

## Fix (shared dispatch contract — not a larger keyword pile)

Single contract: `plan_project_review_turn(text) → {lane, reason}`.

| Lane | Eligibility |
| --- | --- |
| **fast** (default) | Capability / hypothetical / future-dependent / discussion-only / informational / remaining ambiguity — answer or clarify; **no tool loop** |
| **governed** | Explicit *current* execute or continuation directive in any clause (`Continue` / `Go ahead` / `OK proceed` / present imperative / mixed discussion + `But run … now`); command prefix |
| **status** | Prior-results inquiry only (no fresh execute order) |

- Question marks alone never select governed.
- Mentioned, negated, hypothetical, and future-dependent work verbs do **not** authorize execution.
- Deferred worksheet/workbook planning (“parameters I will give you”) is **fast dialogue**.
- Fast replies must not claim pending extract/re-run/tool work (Smedley V6 prompt + compact `build_dialogue_project_context`; capability/deferred planning adds explicit no-inventory directives and a short history window).
- Governed turns still use full `build_canonical_project_context` (MCP/path/execution policy).
- Fast-lane failure returns **retryable 503** and must **not** silently escalate into the heavy tool loop.
- Session ownership lock + busy check (`is_streaming` / `active_stream_id`) runs
  **before both** fast and governed paths → concurrent → **409**.
- Every governed turn prepends refreshed `project_context` (project_id, readiness,
  MCP `project_review_extract*`, server `smedley_project_review`).
- Review dialog UI keeps ordinary conversation + simple working/error status visible;
  raw tool activity lives in optional **closed** details (owner expand preserved across poll).

## Verification classes (do not conflate)

### ROUTING SIMULATION

`tests/test_biggy_project_review_lifecycle.py`, voice/typed-fast suites:

- Prove lane selection, refreshed context, concurrency 409, and that stubbed
  `start_session_turn` is entered for governed messages.
- Explicitly labeled **ROUTING SIMULATION** — they do **not** prove MCP tool
  selection or final persistence through the Hermes runner.

### ACTUAL tool-loop (deterministic)

`tests/test_smedley_review_followthrough_tool_loop.py::test_start_session_turn_real_mcp_capabilities_tool_loop`

- Real `start_session_turn` → streaming runner → Hermes agent tool selection →
  real MCP `project_review_extract_capabilities` → assistant final persistence.
- Model transport is **scripted** (local OpenAI-compatible server) for
  deterministic regression only.
- Does **not** stub the dispatcher/runner.
- MCP tools restricted via `tools.include: [project_review_extract_capabilities]`;
  toolset id is server name `smedley_project_review` (not bare `"mcp"`).

### BOUNDED local-model smoke

`tests/test_smedley_review_followthrough_tool_loop.py::test_local_model_smoke_capabilities_or_report_blocker`

- **Opt-in only:** set `HERMES_WEBUI_LOCAL_MODEL_SMOKE=1` (optional
  `HERMES_WEBUI_LOCAL_MODEL_BASE_URL`, default `http://127.0.0.1:1234/v1`).
  Normal CI must not opportunistically invoke local LMs.
- Pinned to the live review model **`qwen/qwen3.8-27b`** with
  **`provider=lmstudio`** — no alternate-model fallback for a green result.
- Isolated `HERMES_HOME` / WebUI state — no production session mutation.
- Capabilities-only MCP (`tools.include` + `resources/prompts: false`).
- Requires successful `role=tool` capabilities result **and** a final assistant
  message **after** that result.
- Shared resolver guard: empty profile `model.provider` must not invent
  OpenRouter for HF-style ids such as `qwen/…`.
- Captured functional proof (not a latency target): ~**104 s** wall time on
  local `qwen/qwen3.8-27b` / `lmstudio` / `http://127.0.0.1:1234/v1` with
  `tool_ok=true`. Treat as capability verification, not low-latency UX.

Related presentation lifecycle (STREAMS/ACTIVE_RUNS ownership vs interim prose /
stale journal): `docs/smedley-review-active-lifecycle.md`.

Runaway turn / missing progress / status-vs-action / sample-only exclusion:
`docs/smedley-review-runaway-repair.md`.

```bash
./scripts/test.sh \
  tests/test_biggy_voice_route.py \
  tests/test_biggy_typed_fast_lane.py \
  tests/test_biggy_project_review_dialog.py \
  tests/test_biggy_project_review_lifecycle.py \
  tests/test_smedley_review_active_lifecycle.py \
  tests/test_smedley_review_followthrough_tool_loop.py \
  tests/test_minimax_provider.py \
  tests/test_smedley_project_review_dxf_ocr.py
```

## Remaining live / deploy needs (not done in this pass)

- No service restart; no real session/config mutation; no commit/push by this agent.
- **Safe config remediation required before treating live review as local-ready:**
  session `a09c02f318be` has `model=qwen/qwen3.8-27b`, `model_provider=null`,
  `profile=smedley`, while `~/.hermes/profiles/smedley/config.yaml` has **no**
  `model.provider` / `base_url`. Under that empty profile block, the pre-fix
  resolver selected **openrouter** for the slash id. After the shared guard fix,
  empty provider no longer invents OpenRouter, but the intended local endpoint
  still needs an explicit smedley model block (mirror biggy):

```yaml
model:
  provider: lmstudio
  default: qwen/qwen3.8-27b
  base_url: http://127.0.0.1:1234/v1
```

  Optionally stamp `model_provider: lmstudio` on the review session after
  deploy. Do not paste API keys into the profile file.
- After WebUI runs this code + remediation, owner re-sends the re-run request on
  live Biggy review dialog for `bdd341b152a4` / session `a09c02f318be` and
  confirms a governed turn (tools visible; not `project_review_fast_route`).
- Readiness still blocks engineering signoff; discussion/extraction allowed.
- `12-1-0104.pdf` and `SK-26BR-102-03 Interconnects.dxf` remain **test samples**
  in place — not production evidence.
