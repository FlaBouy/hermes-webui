# Smedley Project Review — Active Dialog Lifecycle

Task: `smedley-review-followthrough-20260902` (bounded lifecycle presentation).

## Problem

`_biggy_project_review_dialog_payload` could report `status=completed` while a
governed turn was still live:

1. Any assistant prose newer than the latest `worker_started` journal event
   triggered `visible_reply_supersedes_journal`, including interim "I will run…"
   text while `session.is_streaming` was still true — dialog polling stopped.
2. A prior turn's `completed` journal could win as the global latest event and
   settle the payload even when a different `active_stream_id` was process-live.

Persisted `is_streaming` / `active_stream_id` alone are not ownership after
restart; STREAMS / ACTIVE_RUNS are.

## Contract (presentation only)

| Condition | Dialog lifecycle |
| --- | --- |
| Claimed stream live in STREAMS or ACTIVE_RUNS (or live ACTIVE_RUNS for session) | `running` — keep polling |
| Journal `completed` / `interrupted` for the **current** claimed stream (no live worker) | settle matching terminal |
| Nonstreaming later visible reply after stale nonterminal journal | `completed` (fast supersede) |
| Nonterminal journal predating `SERVER_START_TIME`, or persisted claim with no live worker | `interrupted` (fail closed) |

Layer: project-review dialog presentation over turn journal + live stream
ownership. Does not change dispatch classification or tool-loop execution.

## Tests

```bash
./scripts/test.sh \
  tests/test_smedley_review_active_lifecycle.py \
  tests/test_biggy_project_review_lifecycle.py
```

Dispatch / tool-loop / resolver / DXF coverage lives under
`docs/smedley-review-followthrough.md` (combined integrated suite). Local 27B
smoke (~104 s) is functional proof only, opt-in, and is not part of this
presentation-lifecycle suite.
