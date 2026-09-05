# Astra operational release gate — 2026-09-05

Production component: `/Users/rick/hermes-webui`, branch
`fix/v6-embed-console-cleanup`, private remote `private`. Authority:
`/Users/rick/argus-v1/manifests/argus-v1.json`. The baseline tag is historical;
use the authority component SHA and runtime inventory for recovery.

## Local gate

Run from this repository:

```sh
ASTRA_TOOLS_SOURCE='/Users/rick/Mounts/Z/DATA/n8n_share/Staging/RAG-build/jarvis_tools_api.py' \
SMEDLEY_OFFLINE_SERVICE_SOURCE='/Users/rick/Mounts/Z/DATA/n8n_share/Staging/RAG-build/jarvis_tools_api.py' \
bash scripts/astra_release_gate.sh
```

This isolates test homes/state. It covers affected logic, critical Project
Review lifecycle, electrical contracts and JavaScript syntax. Commit locally,
then rerun the line-scoped lint gate: its comparison uses committed HEAD.
No full-repository-green claim is implied. Preserve unrelated untracked files.

Before restarting, GET `/health` on 8790 and 8787 and require zero active runs
and streams. Back up changed LaunchAgents/external sources. Reload a changed
LaunchAgent with launchctl bootout/bootstrap; kickstart unchanged definitions.
Verify `/health` again, tools `/health`, expected listeners and source hashes.
Refresh the authenticated Biggy browser, inspect the Orb, ANI controls and one
electrical tool; close the test card. HAL task visibility is separately
confirmed by Rick, never inferred from a feed or DOM. Do not auto-dispose it.
Push the component only after checks, then pin that SHA in the authority repo.

## Runtime capture and restoration

`python3 scripts/astra_runtime_inventory.py /absolute/path/runtime.json`
captures allowlisted launch commands, artifact hashes and installed package
versions, not credentials/environment values. Keep credentials in existing
local protected files. Preserve the inventory beside the authority manifest.
Restore matching source/artifacts and Python environments before starting the
recorded services. NAS execution remains a documented recovery dependency,
not silently migrated. Exact artifact hashes must match; missing files fail
reproduction rather than being treated as optional success.

Biggy stdout is bounded by `scripts/bounded_process_log.py` to five 32 MiB
generations plus current. Its old log and separate stderr remain preserved.
To roll back this wrapper, restore the backed-up Biggy LaunchAgent and reload
it; do not delete logs. Electrical HTTP remains serial because its adapter
temporarily installs calculation functions: concurrency needs separate work.
The bounded 64 KiB body/10-second incomplete-read guard does not authenticate
LAN callers. Tools 8801, RAG 5004 and LM Studio 1234 retain required fleet access.

## Timing and acceptance limits

Fast replies carry a `voice_timing` request identity and relative model-start,
first-delta (streaming only) and final-text timestamps. Stored with the reply,
these distinguish model time from subsequent delivery. Acceptance starts at
the fast-model helper, not microphone capture. Synthesis/playback stages are
not measured by this metadata; end-to-end latency remains a residual gap.
No latency improvement is claimed from synthetic tests. Ingestion is not
engineering verification. Unsupported aluminum conductor calculations remain
fail-closed; aluminum tray material is a separate installation property.
