# Project review request and storage contract

## Readiness boundary

The review dialog determines the request lane before calling recursive folder
readiness. Fast conversation, deterministic electrical tools, and prior-result
status replies do not invoke that walk. Their readiness value is unknown, not
implicitly verified. Governed document work still obtains current readiness and
retains its existing evidence gates. No verification cache was introduced.

## Synchronous review turns

Fast, electrical, and status turns use the existing session transcript as their
durable source of truth. The owner row is saved with `review_request_id`,
`review_lane`, and `review_turn_state: pending` before execution. A completed
result and one assistant row are saved together afterward. Failed execution
leaves a saved failed owner row rather than dropping the request.

The browser supplies a per-project request ID retained in sessionStorage until
it observes completion, failure, or interruption. An ambiguous network failure
restores the draft and retains that ID. Retrying a completed ID returns its saved
result without another model/tool call or assistant row. Reusing an ID with a
different message is rejected. Clients which omit an ID remain compatible but
cannot obtain retry deduplication across separate HTTP submissions.

Pending records without live process ownership are shown as interrupted, never
silently re-executed. A new attempt requires a new request ID after the owner
has inspected the terminal state. Lightweight synchronous calls cannot be
cancelled in flight: their dialog has no Cancel stream ID and says so while
running. The existing governed stream/journal lifecycle is unchanged.

State layer: session JSON/transcript, plus a process-local live ownership set.
The existing per-session execution lock serializes lightweight execution. This
does not introduce distributed session-worker ownership or a new runner.

## Project storage

The on-disk schema remains a JSON list of project objects, including unknown
metadata. `load_projects()` returns a list-compatible snapshot carrying an
in-memory content revision. Mutate that snapshot in place and pass it to
`save_projects()`. Do not discard the revision with a new list comprehension;
use slice assignment for filtering. Blind replacement of an existing file is
rejected.

Saving acquires a thread lock and a cross-process file lock, checks the revision,
flushes a same-directory temporary file, and atomically replaces the target.
A stale snapshot raises a recoverable HTTP 409: reload and repeat the intended
mutation. Malformed data raises HTTP 503 with a recovery explanation; it is not
treated as an empty list and is never overwritten by the save helper. Restore a
validated copy of the original data to recover. No automatic data deletion or
database migration is performed.

## Regression checks

Run through `./scripts/test.sh` with isolated state:

- `tests/test_biggy_project_review_lifecycle.py`
- `tests/test_project_review_durable_turns.py`
- `tests/test_review_request_browser_contract.py`
- `tests/test_project_store_integrity.py`

These prove routing, saved acceptance before execution, replay without duplicate
completion, visible interruption/failure, atomic-write failure preservation,
and stale-writer rejection across processes. JS callback tests are not claims
about physical-display appearance or measured production latency.
