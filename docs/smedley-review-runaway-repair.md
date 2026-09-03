# Smedley Project Review — Runaway Turn and Missing Progress

## September 3 — conversation latency repair and acceptance

The deferred worksheet capability question incorrectly entered governed execution:
live run `a93ef11858954f4dbd2a740c1597e261` took 715 seconds to finish.
Completion of that run was not a productive-conversation acceptance test.

The shared dispatch boundary now requires current execution/continuation intent;
hypothetical, negated, deferred-input, and ambiguous conversation stays in the
dialogue lane. A failed dialogue request returns a retryable error and cannot
silently launch a tool loop. Explicit present imperatives still route to execution.

Dialogue uses compact project context in the model's single system message,
separate from owner text and without extraction/path/budget instructions. It
distinguishes provisional drafting with uncertainty flags from final approval;
verification is not a prerequisite for accepting worksheet parameters.
Normal tool names are behind closed-by-default activity details (explicit opening
survives polling). Failures and stalls remain visible.

Verification, with no source files, workbooks or ingestion records changed:

- Real Chrome UI, same review: original question shown within 279 ms of click;
  HTTP request completed in 1.564 seconds with a persisted conversational reply,
  rather than a new extraction run.
- A live follow-up remained conversational. It exposed an old verification-gate
  claim, prompting the final context correction rather than acceptance by speed alone.
- Final context correction, actual local model with isolated pre-test review
  context: original question 1.50 seconds; parameter follow-up 0.91 seconds.
  Both answers asked for the specification and allowed a provisional draft with
  uncertain values flagged. No tools were offered or invoked.
- 60 focused routing, lifecycle, error, context, and presentation tests passed
  in 4.72 seconds. Normal tool-status regression was observed failing before its fix.
- Original browser draft was not replaced/reloaded. Further live test messages
  stopped when the owner continued using the review; final model probes did not
  append to the live transcript.

These tests validate the conversation repair, not a complete engineering review,
OCR cell approval, or a promised runtime for every governed review operation.
The existing OCR disagreements remain unapproved. No commit or push performed.

Task: `smedley-review-runaway-20260902` (HAL glass confirmed; remains active).

## Cause evidence (live journal metadata only)

Session `a09c02f318be` / run `cc854bc7…` showed library-relative path double-join failures
(`ok:false` preview / `is_error:false`), scratch terminal bypass, sample fixtures treated as
production, interim events invisible in GUI, and status questions re-entering governed turns.

## Repair contracts (this revision)

| Area | Contract |
| --- | --- |
| Agent context | Historical tool-call blocks → labeled **plain evidence summaries only**. Outbound never includes `role=tool` or `tool_calls` protocol (avoids parallel-ID mismatch / truncated invalid JSON). Reasoning/internal fields stripped. Total serialized char budget. Full saved `messages` untouched. Scope + retained owner decisions included. Binding is **process-local** (`set_project_review_turn_binding` / pop in streaming) so durable `context_messages` are not poisoned. |
| Progress | Incremental byte-offset scan; cache keyed by **resolved journal path + sid + rid** with bounded eviction. Real `args`/`is_error`/`preview`. Failures labeled Failed. |
| Status | Readable basename / state / unverified / `cells_verified` / sample-only / evidence basename — deterministic, no LLM. Unknown/errors ≠ success. |
| Cancel | Client **must** send `stream_id`. Narrow coordinator auth: active profile `biggy` or `smedley`, project profile `biggy`, `review_owner=smedley`, session bound to that project with `session.profile=smedley`, stream owner = that session. Exact-profile `_session_id_visible_to_request_profile` is **not** used (would 404 Biggy GUI → Smedley session). Live-stream expected-id lock/race guards unchanged. Global session/stream guards unchanged. |
| Paths / sample | Library-relative normalize; MCP response carries `sample_only` / `production_findings_allowed` / warnings. |
| Budget | Soft tool-complete / path-fail stall + `project_review_max_iterations` cap on new review turns. Spinner stays while process-live. |

## Verification

```bash
./scripts/test.sh \
  tests/test_smedley_review_runaway_repair.py \
  tests/test_smedley_review_followthrough_tool_loop.py \
  tests/test_biggy_project_review_lifecycle.py \
  tests/test_smedley_review_active_lifecycle.py \
  tests/test_biggy_voice_route.py \
  tests/test_biggy_typed_fast_lane.py \
  tests/test_biggy_project_review_dialog.py \
  tests/test_smedley_project_review_dxf_ocr.py
```

### Test labels (do not conflate)

| Class | What it proves |
| --- | --- |
| Unit / HTTP | Context budget, parallel-tool→summary, cancel 409 races, path normalize, readable digest, MCP decorated function with patched extractor |
| Node UI | `biggyProjectReviewCancelButtonState` hidden/disabled/recommended (isolated; not full Chromium glass) |
| ACTUAL scripted streaming | `start_session_turn` + runner + scripted model + MCP capabilities; long-history outbound evidence on scripted transport (`test_start_session_turn_review_context_budget_on_scripted_transport`) |
| Untested here | Live production cancel/restart; physical HAL glass click; unpaid external providers; opt-in local LM smoke unless `HERMES_WEBUI_LOCAL_MODEL_SMOKE=1`; **elapsed live acceptance of deferred-parameter worksheet dialogue** (coordinator owns the live dialog retest after deploy) |

## Deployment / recovery (owner approval required — not performed by this lane)

1. Deploy code only when approved.
2. Open dialog; if a turn is live, **CANCEL TURN** with the dialog’s current `cancel_stream_id` (server rejects stale ids).
3. Restart WebUI only after targeted cancel settles (or confirmed no live stream).
4. Status questions → deterministic digest; re-run only on explicit order.

No live cancellation/restart from the coding agent. Smedley model profile remediation from the prior follow-through turn remains as previously applied — not re-litigated here.
# Live acceptance — September 2, 2026, afternoon

The reopened task `smedley-review-runaway-20260902` was confirmed on HAL by Rick.
No additional glass confirmation is needed for this repair. Earlier handoff
notes asking Rick to resend the request are superseded by this live test.

- Live project `bdd341b152a4`, session `a09c02f318be`, local
  `qwen/qwen3.8-27b` / LM Studio: actual capabilities call, actual WB3339-014
  extraction, then a persisted final assistant reply. Run
  `dd357fa080064f3e9d71e690ae8f644e` settled with no active stream or pending
  message. The extraction took 42.2 seconds; the full turn took 318.8 seconds.
  This proves follow-through, **not acceptable conversational latency**.
- The narrative incorrectly called the eight-column BOM a nine-column grid.
  The MCP envelope now supplies measured per-table dimensions explicitly;
  regression coverage requires 21 rows including header and 8 columns for
  that fixture. Generated prose is not independent engineering evidence.
- Final OCR pass uses embedded native-resolution table images, oriented
  cell crops, direct recognition for single-line ink, detector fallback for
  multiline cells, real subprocess timeouts, and preserved partial evidence.
  Only zero-ink cells are blank. Literal ellipses are not discarded as debris.
- Six source PDFs completed in 270.4 seconds in the final isolated pass.
  They contain 429 engine disagreements, including 240 ellipsis readings.
  All remain `cells_verified=false`; no engineering approval or ledger
  promotion was performed. A higher disagreement count after retaining
  punctuation is not an extraction failure and must not be hidden.
- Final preserved evidence and human-readable source-crop packet:
  `/Users/rick/.jarvis_rag_status/project_review_evidence_runs/smedley-wb3339-cellocr-inkbands-20260902/Review-results.html`.
  All 473 linked crop files were checked for existence. The HTML packet was
  structurally checked, not browser-rendered (local-file browser policy).
- Biggy's duplicate native transcript is visually suppressed only within
  the Biggy cockpit, while its flex layout and saved history remain intact.
  Browser acceptance at 1920×1080 covered single left response presentation,
  HOME hiding both presentations, and a new reply restoring the left lane
  only. Composer remained at the bottom. Other Hermes profiles are not scoped.
- Final combined extraction, MCP-envelope, cockpit, voice and fast-routing
  tests: **109 passed**. Active-lifecycle tests passed separately. No commit
  or push was performed in this pass; unrelated dirty changes were preserved.
