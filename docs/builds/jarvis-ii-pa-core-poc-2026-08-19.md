# Jarvis II PA Core — Baseline POC Contract

**Status:** build in progress; inactive until acceptance testing

## Boundary

Jarvis II PA Core is separate from Jarvis II RAG Core. The PA is responsible for intent planning, owner context, tool selection, compliance, and response assembly. RAG Core remains an evidence tool for engineering-document questions.

## Local inference

The planner uses LM Studio's local `openai/gpt-oss-120b` through its OpenAI-compatible endpoint. The model classifies and plans; it does not fabricate tool results or write durable memory directly.

## Modules

| Module | POC behavior | Expansion path |
| --- | --- | --- |
| Ingress and identity | Authenticated request, correlation and idempotency fields | PTT, GUI, and scheduled adapters |
| Local planner | Structured intent/tool plan from local 120B | Per-intent prompts and evaluation fixtures |
| Durable memory | Read context contract; no autonomous writes | Explicitly approved, versioned memory writes with retention policy |
| Research | Structured research-plan contract | Grounded multi-source retrieval with citations and source snapshots |
| Tools | Allowlist and parameter contract | Calendar, weather, maps, lodging POI, tasks, and approved skills |
| Engineering evidence | Delegates to RAG Core | Existing verified document resolver |
| Compliance | Tool allowlist, approval requirements, audit envelope | Policy decision service and immutable audit chain |

## Non-negotiable POC rules

- No tool result may be invented by the planner.
- Calendar, weather, maps, lodging, research, and RAG outputs must carry source/tool evidence before they are displayed as facts.
- Long-term memory is read-only until the owner approves retention, redaction, scope, and write authority.
- The PA may return a research or tool plan, but it must not claim the plan has executed.
- GUI cards are rendered only from structured, source-backed view models.
- RAG Core is invoked as a tool; its engineering citations remain intact.

## First acceptance set

1. A general PA request produces a valid structured plan from local 120B.
2. An engineering request is delegated to RAG Core and retains the evidence response.
3. A travel request returns a tool plan, not invented weather, routes, or hotels.
4. A durable-memory write attempt is denied pending retention approval.
5. Every response has correlation, operation, policy, and audit fields.

## Implemented POC milestone: durable-context read

The PA now calls `POST /api/jarvis-ii/pa-context` before local planning. The endpoint is reachable only through the internal Jarvis II bearer credential and returns bounded, redacted Biggy `MEMORY.md`, `USER.md`, and `SOUL.md` context with a hash for each section. It excludes browser transcripts and all write actions.

The current PA workflow is `Jarvis II — PA Core POC` (`cD6uUqpzXQl3n3iU`), remains inactive, and now contains eight nodes. The n8n container-to-adapter check passed with the `jarvis.pa.durable_context.v1` contract and the write policy `DISABLED_PENDING_OWNER_RETENTION_POLICY`.

## Implemented POC milestone: travel evidence

`POST /api/jarvis-ii/pa-travel` is a read-only tool adapter backed by the installed local maps skill and OpenStreetMap/Nominatim. It resolves a canonical destination and returns nearby hotel/guest-house POIs as structured cards. It does not return or imply rates, availability, booking status, tickets, or calendar status. The Biggy card renderer accepts the dedicated `Jarvis II PA Tool` producer identity for this source-backed contract.

The inactive PA workflow now has an 11-node travel branch: local plan → policy → travel-tool selection → travel evidence → evidence-only response. It has not been cut over to Biggy.

**Acceptance result:** the controlled travel fixture completed through the local 120B planner and returned the canonical `Mercedes-Benz Stadium` with five source-backed OpenStreetMap lodging cards. Natural-language destination input is normalized at the adapter boundary before geocoding; unresolved destinations fail closed without cards.

## Deliberately deferred

Live calendar writes, bookings, purchases, persistent-memory writes, and automatic skill installation are outside the baseline POC. They require their own approved capability contracts and tests.
