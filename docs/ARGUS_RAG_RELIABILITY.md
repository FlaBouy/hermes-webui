# Argus RAG reliability and autopsy runbook

## Operational contract

Biggy and Smedley share one evidence plane:

- Smedley direct retrieval: `http://127.0.0.1:5004/rag/retrieve`
- Argus bounded resolver: `http://127.0.0.1:5014/resolve`
- Argus PA workflow: `cD6uUqpzXQl3n3iU` on local n8n `:5680`
- Biggy adapter: `api.argus_route.try_argus_pa_core`

Clear map, travel, calendar, weather, mail, research, manual, schematic, and
part-number requests use the deterministic n8n fast lane. Ambiguous requests
may still use the local 120B planner. Both lanes converge on the same policy,
evidence, card, and terminal-response nodes.

Successful n8n executions are retained for correlation autopsy. An empty
webhook body is never blindly replayed: Biggy recovers the already-completed
terminal result by correlation ID or takes the governed transport fallback.

## Runtime isolation

Executable RAG Python is local:

- tracked runtime: `runtime/argus-rag/`
- Smedley API entry point: `/Users/rick/bin/smedley-rag-api.py`
- Argus core entry point: `scripts/jarvis_ii_rag_core_service.py`

The corpus may remain on shared storage, but no long-lived Python service or
imported module may execute directly from a removable/network mount. This is
the guard against the macOS SIGBUS crashes caused by force-unmounted mapped
Python pages.

## Release gates

Run the independent black-box gate:

```bash
.venv/bin/python evaluations/argus-rag/blackbox.py --repeat 5 --live-pa --json
```

It verifies repeated health, Smedley direct retrieval, Argus manual retrieval,
the live PA map contract, and the Biggy-to-Argus adapter including spoken text.

Run the third-party semantic contract gate:

```bash
PROMPTFOO_DISABLE_TELEMETRY=1 \
GPT_BIGGY_PROPOSE_TOKEN="$(< /Users/rick/.jarvis-ptt/gpt-biggy-propose-token)" \
npx promptfoo@0.122.2 eval -c evaluations/argus-rag/promptfooconfig.yaml --no-cache
```

Deploy the canonical PA workflow only after its graph tests pass:

```bash
.venv/bin/python scripts/deploy_argus_pa_workflow.py
.venv/bin/python scripts/deploy_argus_pa_workflow.py --apply
```

The deployer pins the live workflow identity, refuses a mismatched graph, does
not accept a credential on the command line, and verifies that deployment did
not change activation.

## Correlation autopsy

Every Biggy/Argus handoff emits redacted JSONL events under:

`~/.argus-v1/observability/flight-recorder/`

Phoenix runs locally at `http://127.0.0.1:6006`. The independent exporter is a
LaunchAgent named `ai.argus.observability`; tracing failure cannot block Biggy,
Smedley, n8n, or RAG.

For a saved n8n execution:

```bash
.venv/bin/python scripts/argus_n8n_autopsy.py --correlation-id CORRELATION_ID
```

The report identifies the planner lane, total node time, and slowest nodes
without printing request bodies, tokens, or retrieved document text.

## 2026-08-28 accepted measurements

- Previous map baseline: 74.46 seconds; 70.69 seconds in `Local 120B Plan`.
- Deterministic direct PA map: 3.28 seconds.
- Biggy-to-Argus adapter map: 3.22 seconds with spoken response.
- Smedley direct retrieval: 89 milliseconds.
- Argus verified-manual resolver: 79 milliseconds.
- Repeated black-box suite: 14/14 passed.
- Promptfoo semantic suite: 2/2 passed.
- Focused Python suite: 198 passed.

The physical glass remains the final UI authority, but glass is no longer the
only diagnostic source: every accepted turn must now be explainable by its
correlation trace and repeatable release gate.
