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

## Implemented POC milestone: owner-approved read tools

The inactive PA workflow now contains the following read-only agent tools, all connected as `ai_tool` inputs to the local 120B decision agent:

| Tool | Contract boundary | Verification result |
| --- | --- | --- |
| Weather Underground current conditions | Existing owner Weather Underground subscription; current conditions only | Controlled tool-call smoke passed with a natural-language briefing and no travel run |
| Weather Underground five-day forecast | Existing owner Weather Underground subscription; five-day outlook only | Agent tool-call metadata verified; returned a bounded Lynn Haven forecast briefing |
| Google Calendar read | Existing `jarvis_google_calendar_readonly` credential; bounded date window and result count; no mutations | Credential reconnected by owner; controlled smoke returned calendar items without exposing them in the build record |
| Gmail read | Existing `jarvis_gmail_readonly` credential; at most ten sender/subject/date/snippet summaries; no bodies, attachments, or mutations | Credential reconnected by owner; controlled smoke returned bounded header/snippet evidence |
| Public lodging/map evidence | OpenStreetMap/Nominatim via the PA travel adapter; source-backed POI cards only | Controlled Mercedes-Benz Stadium test returned five lodging cards; no invented rates, availability, or booking state |

The weather lane produces a structured optional visual action for the existing MyRadar experience. The UI is user-click only: Jarvis can offer a radar view or the existing broad-coverage MyRadar action, but cannot open a display, purchase, book, write to a calendar, or launch software autonomously.

## RAG Core status

Engineering-document retrieval is now serviceable through the separate active workflow `Jarvis II — Production RAG Core` (`JarvisIIProdRAG001`). It receives `POST /webhook/jarvis-ii` and remains the evidence authority for technical manuals, exact printed/PDF page references, and schematic links. The PA must delegate engineering-document requests to this core; it must not synthesize engineering evidence.

Recent fixes established vendor-neutral schematic resolution and verified a Honeywell ControlEdge HC900 page result. The associated source changes are committed as `7b2657e5`, `cd48a5e0`, and `5fe994c3`.

## Research lane decision — Google/Chrome

The earlier DuckDuckGo-based public-research draft is not accepted and must not be used as the PA's production research surface. The owner selected Google/Chrome for consistency with the broader Google environment and for future Chrome-extension capabilities.

On 2026-08-19, the local Chrome bridge was verified: Google Chrome is running, the Codex browser extension is installed and enabled on the Default profile, the native-messaging manifest is correct, and a fresh Chrome window established the live connection. This bridge is a live interactive Codex capability, not an n8n runtime service. It may be used for operator-assisted Google research and validation, but must not be represented as an unattended PA tool.

The production replacement therefore needs a durable, separately governed Google-backed research connector with source evidence returned to the PA. Until that connector is implemented and tested, research requests fail closed rather than producing uncited web claims. The PA POC remains inactive.

## Implemented POC milestone: Firecrawl public-research tool

The DuckDuckGo Code Tool draft has been retired from the PA graph and replaced with the read-only workflow tool `Jarvis II Firecrawl Research`. It invokes the separate inactive workflow `Jarvis II — Firecrawl Research Tool POC` (`w2WJmXeU873L8wwa`) through an Execute-Workflow Tool binding.

The sub-workflow has four linear nodes: workflow input → bounded query validation → Firecrawl search → normalized evidence. It uses an existing encrypted n8n Header Auth credential by reference only; no credential value appears in the workflow definition, test output, or build record. The Firecrawl request is limited to a short text query, at most five web results, and the Firecrawl search endpoint. It rejects URLs, file paths, private-network targets, control characters, and overlong input. The normalizer returns only title, public URL, source host, and shortened summary records; raw provider payloads are not passed to the PA agent.

**Acceptance result:** a controlled local-120B fixture requested verification of the National Air and Space Museum location. The Decision Agent invoked the Firecrawl workflow, received normalized evidence from five public sources, and emitted a governed response with `status = COMPLETED` and audit stage `research_evidence = agent_tool_completed`. The test fixture was immediately restored to the normal Mercedes-Benz Stadium lodging objective afterward. Both the PA POC and the Firecrawl sub-workflow remain inactive.

## Implemented POC milestone: governed RAG delegation

The PA now exposes `Jarvis II RAG Delegation` as a bounded Execute-Workflow Tool. It calls the separate inactive workflow `Jarvis II — RAG Delegation Tool POC` (`TIEU7dGs4fzf3wU1`), which validates an engineering-document request, calls the existing production RAG Core with its internal authorization boundary, and normalizes only the returned verified evidence.

**Acceptance result:** the controlled local-120B request for an Allen-Bradley 1756-IB32 wiring schematic invoked the RAG delegation tool and returned the verified `1756-UM058` evidence with the cited PDF page and wiring-page link. The normal lodging fixture was restored afterward. The PA and RAG-delegation tool remain inactive; the already-approved Production RAG Core remains active as the evidence service.

## Implemented POC milestone: durable-memory write denial

Durable context remains read-only. The governed response contract now detects explicit durable-memory requests and marks the requested action as denied until the owner approves retention, redaction, scope, and explicit write authority. No memory store is called and no durable write is attempted on this path.

**Acceptance result:** a harmless controlled request to remember a coffee preference returned `write_denied`. The normal lodging fixture was restored immediately. The PA remained inactive with 22 nodes before and after the test.

## Biggy/Jarvis presentation repair — pending browser acceptance

The shared Biggy and Smedley renderers now use a durable response field, `assistant_identity = "jarvis"`, in addition to the existing Ask-Jarvis route flags. This ensures that a Jarvis response retains its own label even when it is displayed inside another assistant's shell. The client also recognizes the server's final-TTS queue marker, preventing a second browser-side read after the server has already queued Jarvis voice output.

Focused regression coverage passed (18 checks). Both local WebUI services were restarted: Smedley on port 8787 and Biggy on port 8790. A live browser handoff still needs owner acceptance before the presentation repair is marked complete.

## Smedley document-link origin repair

The failed 1756-IB32 link was traced to an incomplete configured public origin: it omitted Smedley's required port 8787. The unported Tailscale URL returned HTTP 404 before reaching Smedley; the corrected ported route reaches the Smedley WebUI and returns its expected authenticated response. The Smedley and Biggy LaunchAgents now both use `https://smedley.tail061f03.ts.net:8787`; both services were restarted. Existing transcript links remain historical text; a new Jarvis request generates the corrected URL.

The focused document-link test shard also reports four unrelated pre-existing source/test drift failures: one stale extension string expectation and three references to retired spoken-output helper functions. They do not affect this public-origin repair and remain tracked separately.

## Ask-Jarvis engineering-route precedence repair

An explicit Ask-Jarvis schematic request was being intercepted by the legacy direct-document shortcut before the two-stage PA handoff. That bypass explained the missing immediate acknowledgement and the older index-first response. The shortcut is now disabled by default and available only through the explicit operator environment flag `HERMES_WEBUI_ASK_JARVIS_DOCUMENT_FAST_PATH`.

The two interfaces now deliberately differ: Biggy leaves that flag unset and uses the PA hard-bind/governed RAG delegation path; Smedley sets it true and retains its proven direct engineering-document/RAG route. Both services use the same ported Smedley public origin. The service definitions were reloaded through `launchctl unload/load` after it was discovered that a simple process restart does not apply edited LaunchAgent environment variables. Focused route/identity/voice regression coverage passed (19 checks).

## Current workflow inventory and activation state

| Workflow | ID | State | Role |
| --- | --- | --- | --- |
| Jarvis II — PA Core POC | `cD6uUqpzXQl3n3iU` | Inactive | Local 120B decision agent with weather, calendar, Gmail, travel, durable-context, and research-contract lanes |
| Jarvis II — Production RAG Core | `JarvisIIProdRAG001` | Active | Verified engineering evidence retrieval |
| Jarvis II — Calendar Read Tool POC | `pPRdrWBRJCIhga7g` | Inactive | Bounded Google Calendar read tool |
| Jarvis II — Gmail Read Tool POC | `7ORc6ERMVy3tC4st` | Inactive | Bounded Gmail read tool |
| Jarvis II — Firecrawl Research Tool POC | `w2WJmXeU873L8wwa` | Inactive | Bounded public-research evidence tool |
| Jarvis II — RAG Delegation Tool POC | `TIEU7dGs4fzf3wU1` | Inactive | Validates and delegates engineering requests to Production RAG Core |

No PA cutover to Biggy has occurred. Existing Biggy/Jarvis behavior is not proof that this POC is ready for activation.

## Next implementation sequence

1. Resolve the remaining Biggy GUI identity/voice-label and duplicate-response defects before any PA cutover.
2. Add an owner-reviewed acceptance matrix for the completed weather, calendar, Gmail, travel, Firecrawl, RAG-delegation, and durable-memory denial fixtures.
3. Verify the agent uses each tool rather than merely describing a plan; require evidence before factual responses and cards are rendered.
4. Propose durable-memory write contracts only after the owner approves retention, redaction, scope, and explicit write authority.
