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

## Deliberately deferred

Live calendar writes, bookings, purchases, persistent-memory writes, and automatic skill installation are outside the baseline POC. They require their own approved capability contracts and tests.
