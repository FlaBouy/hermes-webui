# Jarvis II PA Core — Baseline POC Contract

**Status:** active Biggy PA path; controlled tool acceptance complete; browser acceptance in progress

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

The PA exposes `Jarvis II RAG Delegation` as a bounded Execute-Workflow Tool. It calls the separate inactive workflow `Jarvis II — RAG Delegation Tool POC` (`TIEU7dGs4fzf3wU1`). That workflow validates an engineering-document request, calls the authenticated `Jarvis II — Generic RAG Core VNext` contract, and normalizes only verified evidence back to the agent.

VNext performs a fresh corpus lookup and actual PDF-page verification for every request. Durable memory may eventually retain retrieval strategy outcomes, but cannot cache an answer or bypass that verification.

**Acceptance result:** the separate inactive acceptance workflow `Jarvis II — RAG Delegation VNext Acceptance` executed the same PA delegation path for an Allen-Bradley 1756-IB32 wiring-schematic request. It returned `jarvis.rag_delegation.v2`, provider `jarvis_ii_generic_rag_core_vnext`, natural spoken text, and a verified `1756-UM058` citation at PDF page 102. The delegation workflows remain inactive.

## Biggy PA Core cutover — 2026-08-20

`Jarvis II — PA Core POC` is active and Biggy's explicit Ask-Jarvis handoff now uses it as the single governed path. Biggy's former direct-document shortcut is disabled. The active path is:

`Biggy → PA Core → local 120B decision agent → RAG Delegation → Generic RAG Core VNext → one Jarvis response`

The PA ingress requires the internal bearer token; an owner-labelled request alone is not accepted. The final response assembly accepts an engineering citation only when the agent selected `rag_core` and returned a valid VNext local-library citation. Otherwise it fails closed as `NO_VERIFIED_EVIDENCE`.

The final Biggy-side adapter acceptance returned `ok = true`, transport `jarvis_ii_pa_core`, one verified `1756-IB32`/`1756-UM058` PDF page 102 citation, and RAG evidence. Smedley, its GUI route, and its port 5004 production RAG service were not changed. The remaining acceptance is owner-visible: one Biggy chat turn, correct Jarvis identity/voice, and a working source link.

## Implemented POC milestone: durable-memory write denial

Durable context remains read-only. The governed response contract now detects explicit durable-memory requests and marks the requested action as denied until the owner approves retention, redaction, scope, and explicit write authority. No memory store is called and no durable write is attempted on this path.

**Acceptance result:** a harmless controlled request to remember a coffee preference returned `write_denied`. The normal lodging fixture was restored immediately. The PA remained inactive with 22 nodes before and after the test.

## Biggy/Jarvis presentation repair — pending browser acceptance

The shared Biggy and Smedley renderers now use a durable response field, `assistant_identity = "jarvis"`, in addition to the existing Ask-Jarvis route flags. This ensures that a Jarvis response retains its own label even when it is displayed inside another assistant's shell. The client also recognizes the server's final-TTS queue marker, preventing a second browser-side read after the server has already queued Jarvis voice output.

Focused regression coverage passed (18 checks). Both local WebUI services were restarted: Smedley on port 8787 and Biggy on port 8790. A live browser handoff still needs owner acceptance before the presentation repair is marked complete.

## Smedley document-link origin repair

The failed 1756-IB32 link was ultimately traced to an obsolete public origin
that incorrectly included Smedley's internal WebUI listener port (`:8787`).
The public Tailnet endpoint is `https://smedley.tail061f03.ts.net` with no
port suffix. Both Smedley and Biggy LaunchAgents now use that canonical origin,
and the Smedley formatter defensively strips the local port even if an old
caller provides it. The public `rag-document` PDF route was verified with HTTP
200. Existing transcript links remain historical text; newly generated Jarvis
citations use the canonical origin.

The focused document-link test shard also reports four unrelated pre-existing source/test drift failures: one stale extension string expectation and three references to retired spoken-output helper functions. They do not affect this public-origin repair and remain tracked separately.

## Ask-Jarvis engineering-route precedence repair

An explicit Ask-Jarvis schematic request was being intercepted by the legacy direct-document shortcut before the two-stage PA handoff. That bypass explained the missing immediate acknowledgement and the older index-first response. The shortcut is now disabled by default and available only through the explicit operator environment flag `HERMES_WEBUI_ASK_JARVIS_DOCUMENT_FAST_PATH`.

The two interfaces now deliberately differ: Biggy leaves that flag unset and uses the PA hard-bind/governed RAG delegation path; Smedley sets it true and retains its proven direct engineering-document/RAG route. Both services use the same canonical Smedley public origin, with no local listener port in user-facing URLs. The service definitions were reloaded through `launchctl unload/load` after it was discovered that a simple process restart does not apply edited LaunchAgent environment variables. Focused route/identity/voice regression coverage passed (19 checks).

## Current workflow inventory and activation state

## Durable strategy learning — owner-approved 2026-08-20

The PA now has a narrow persistent learning loop. The active `Load Durable
Context` node reads a `strategy` section from Biggy on port 8790 and supplies
its aggregate-only summary directly to the local 120B decision agent. After a
completed PA response, the Biggy adapter records a sanitized outcome for each
approved selected tool.

The policy is **strategy-only, 30-day retention**. A record contains only the
approved tool name, provider label, outcome (`verified`, `unverified`,
`not_found`, or `transport_error`), evidence-status label, and automatic expiry
time. It never stores an objective, user prompt, spoken response, source URL,
page, document text, credentials, raw evidence, or cached answer. Expired rows
are pruned whenever the store is read or written. Strategy context can guide
selection among already-approved tools but may never skip a fresh tool call and
fresh evidence verification.

**Acceptance result:** a synthetic `rag_core` result created one strategy row;
the next authenticated context read returned only its aggregate count and the
30-day policy. No user content was present in the stored or returned data.

## Mapbox trip-planning cutover — 2026-08-20

Biggy was already rendering map panels with Mapbox GL JS, but the prior PA
travel adapter incorrectly used OpenStreetMap/Nominatim and OSRM for its data.
It now uses the existing Biggy Mapbox subscription for all trip data:

- Geocoding v6 resolves origin and destination.
- Directions v5 returns the driving route and GeoJSON line used by the existing
  Mapbox panel.
- Search Box category calls return temporary public POI cards for lodging,
  meals, entertainment, and midpoint-area fuel planning.

Mapbox results are temporary display evidence, not retained as answers or
durable memory. The PA makes no rate, availability, reservation, purchase,
traffic, fuel-open, or autonomous-navigation claim.

**Acceptance result:** an authenticated end-to-end PA request from Atlanta,
Georgia to Auburn, Alabama returned a 108.4-mile Mapbox route with geometry,
five cards in each of the four categories, one source citation, and a single
natural Jarvis response. The Biggy adapter preserves both the route and the
four-category card bundle for the existing display rails.

## Trip-planning loop — 2026-08-20

The active PA Core now handles a single read-only trip request as one governed
tool path:

`Biggy → PA Core → local 120B planner → Biggy PA travel adapter → existing Biggy route/cards display → one Jarvis response/TTS`

The planner extracts an origin and destination. If the origin is absent, it
returns `ORIGIN_REQUIRED`; it does not claim a route. With both endpoints, the
adapter obtains a driving estimate and public POIs from Mapbox. Each category is
bounded and isolated: a provider failure leaves that category empty but never
removes an otherwise verified route. The UI receives the existing
`jarvis.map_view_model.v1` plus a `jarvis.trip_plan_view_model.v1`; lodging is
the initial card rail, and the existing Lodging, Meals, Entertainment, and Fuel
rails can switch to their retained category models.

There are no hotel rates, room availability, reservations, bookings, purchases,
traffic guarantees, fuel-availability claims, or autonomous navigation/app
launches. Card links are public map listings only.

The PA's internal travel and durable-context calls were corrected from Smedley's
port 8787 to Biggy's port 8790. Smedley production, port 5004, and the Smedley
GUI route were not modified.

## Travel and calendar live-path repair — 2026-08-20

The active PA Core travel path was repaired after a Biggy acceptance request
showed three defects: an invented Pequest, New Jersey origin; a stale
OpenStreetMap/Google source label despite Mapbox evidence; and dropped
multi-category card models in the Biggy client. The PA now requires an origin
explicitly supplied in the current request. It does not infer or retain a home
location. Biggy preserves the `trip_plan_view_model` through its final-message
handoff, allowing the existing Lodging, Meals, Entertainment, and Fuel rails to
render the Mapbox-backed category models.

Calendar reads now run in a separate bounded, read-only lane before travel.
The lane invokes the existing Google Calendar read workflow for the requested
date window and returns only its outcome and count to the PA response; it never
writes calendar data or durable memory.

Two authenticated checks passed: a request without an origin returned
`ORIGIN_REQUIRED` after the calendar check and created no map; a request with
an explicit origin verified Mapbox route evidence and all four category models.
That second check also exposed an unverified sports-event destination being
treated as a Mapbox place. The PA now fails closed with
`DESTINATION_EVIDENCE_REQUIRED` for team/date event requests until a future
bounded schedule/venue-evidence tool verifies the venue. It will not route to a
model-invented location.

| Workflow | ID | State | Role |
| --- | --- | --- | --- |
| Jarvis II — PA Core POC | `cD6uUqpzXQl3n3iU` | Active | Biggy's local-120B governed decision path with bounded tools |
| Jarvis II — Production RAG Core | `JarvisIIProdRAG001` | Active | Verified engineering evidence retrieval |
| Jarvis II — Calendar Read Tool POC | `pPRdrWBRJCIhga7g` | Inactive | Bounded Google Calendar read tool |
| Jarvis II — Gmail Read Tool POC | `7ORc6ERMVy3tC4st` | Inactive | Bounded Gmail read tool |
| Jarvis II — Firecrawl Research Tool POC | `w2WJmXeU873L8wwa` | Inactive | Bounded public-research evidence tool |
| Jarvis II — RAG Delegation Tool POC | `TIEU7dGs4fzf3wU1` | Inactive | Validates and delegates engineering requests to Generic RAG Core VNext |
| Jarvis II — RAG Delegation VNext Acceptance | `JarvisIIRAGVNextAccept1` | Inactive | Synthetic IB32 acceptance fixture for the PA delegation path |

Biggy now uses PA Core for explicit Ask-Jarvis handoffs. Existing behavior outside that handoff remains outside this cutover scope.

## Engineering-RAG evidence gate repair — 2026-08-20

The active PA workflow now has a deterministic engineering-evidence gate after
the local-120B decision agent. The agent still classifies the request and
selects approved tools, but a manual, schematic, wiring, datasheet, or
vendor-library request cannot rely on the model to remember to invoke RAG.
When `rag_core` is selected (or the request has an engineering-evidence
signature), the workflow makes a fresh read-only call to the Generic RAG Core
VNext service and only then assembles the PA response.

The response formatter accepts both verified service contracts:

- `VERIFIED_EVIDENCE` requires a verified PDF page for wiring/schematic-style
  requests.
- `VERIFIED_MANUAL` permits a document citation without inventing a page.

This preserves the no-evidence fail-closed behavior and does not use a
pre-written vendor, manual, or page lookup. Every request performs a fresh
corpus and PDF verification.

Live read-only acceptance through the active PA webhook passed:

- Honeywell Process Manager I/O Installation manual for TDC3000 returned
  `COMPLETED`, `pm20520.pdf`, and the verified library citation.
- Allen-Bradley 1756-IA16 wiring request returned `COMPLETED`,
  `1756-um058_-en-p.pdf`, and verified PDF page 97.

At that repair point the PA graph had 25 nodes. Subsequent calendar and
destination-evidence work expanded the active graph; the live count is
recorded in the later sections. Smedley production and its GUI route were not
changed.

## Short-term follow-up context — 2026-08-20

Jarvis PA now receives a bounded, session-scoped conversation window from
Biggy. It exists solely to resolve a same-chat continuation such as “yes, dig
deeper,” “pull that figure,” or “the previous manual.” The window retains at
most ten completed PA turns, expires after one hour of inactivity, is held only
in the Biggy process, and has no disk backing or cross-chat visibility.

This is intentionally separate from the 30-day durable strategy aggregate.
Short-term context may identify the prior target and unresolved next step; it
is never evidence and cannot provide a manual, page number, citation, or
technical answer. Every engineering continuation must select the approved RAG
tool again and perform fresh corpus/PDF verification before it states results.

The native n8n Simple Memory node was evaluated but removed: its chat-history
message format is incompatible with the current LM Studio Engine Protocol model
endpoint and caused malformed-model-output failures. The compatible path injects
the bounded Biggy context directly into the Decision Agent prompt, preserving
the same session and turn limits without changing durable-memory policy.

**Acceptance result:** a two-turn synthetic request (“find 1756-IB32” then
“yes, dig deeper”) retained the prior target and selected `rag_core` again on
the follow-up. The first retrieval had no verified evidence, and the follow-up
did not emit a page or citation from context alone.

### Biggy continuation binding repair — 2026-08-20

Biggy now recognizes bounded Jarvis continuations in the same chat when the
latest completed assistant turn belongs to Jarvis. This covers affirmative
replies, numbered choices, and retrieval instructions such as “take a look,”
“look in,” “search,” “pull,” and “dig deeper.” Those turns are hard-bound back
to PA Core with the same chat ID instead of falling through to Biggy’s ordinary
model. An explicit address to Biggy or Smedley, or a message outside this
continuation language, releases the binding.

**Regression coverage:** the Honeywell/TDC3000 folder instruction and
“Selection 1” are both asserted to route to Jarvis; “Hey Biggy, change
subjects” is asserted not to do so.

## Next implementation sequence

1. Owner-visible Biggy acceptance: one trip request with an explicit origin, correct Jarvis identity/voice, one response, route panel, and category rails.
2. Improve the public-POI source only through an approved, evidence-preserving fallback if the current OpenStreetMap provider remains sparse or slow; do not invent listings.
3. Add an owner-reviewed acceptance matrix for weather, calendar, Gmail, travel, Firecrawl, RAG delegation, and durable-memory denial.
4. Propose durable-memory write contracts only after the owner approves retention, redaction, scope, and explicit write authority.

## Generic destination evidence and Lynn Haven default — 2026-08-20

The active PA Core now has a generic destination-evidence lane before any
travel route or trip cards are created. It has no event, stadium, plant, city,
or address lookup table.

- A named plant site, attraction, venue, or ordinary destination is resolved
  fresh through Mapbox.
- An event or ambiguous destination first receives a bounded Firecrawl public
  source lookup. The local 120B extracts a supported candidate, and Mapbox
  must verify that candidate before routing proceeds.
- If the exact venue is absent from the source snippet but the event host
  locality is supported, the PA may route to that locality; it does not call
  the locality a stadium or invent a venue name.
- An unresolved destination ends with `NO_VERIFIED_DESTINATION`; it never
  sends a speculative route, lodging list, or travel cards.
- The default PA origin is now **Lynn Haven, Florida**. An explicit user
  starting point overrides it.

The PA route node now consumes the verified destination branch item rather
than the original planner candidate. This prevents a verified event location
from being lost before Mapbox routing.

**Controlled active-workflow acceptance:** “Sept 19th Auburn vs Florida game,
lodging, and calendar conflicts” completed with Lynn Haven as origin; public
event evidence (`auburntigers.com`) plus Mapbox verified Auburn, Alabama;
Mapbox returned the route; and the UI contract received lodging, meals,
entertainment, and fuel card models. The read-only calendar result was empty
for the requested date window. No rates, availability, bookings, or private
event details were returned.

### Exact-venue travel-path repair — 2026-08-20

The active PA Core now has 45 nodes. A branch defect was found during the
controlled trip acceptance: direct-destination handling referenced the
calendar merge node even though that node is correctly skipped when the
planner does not request Calendar. That could terminate a legitimate travel
request early with the intermediate `TOOL_PENDING` response.

The destination branch now uses its current branch item for the Mapbox request,
and the named-destination assembly uses the common pre-branch item rather than
the optional calendar merge. This keeps calendar optional without weakening
destination verification.

**Re-acceptance:** the Auburn–Florida request returned `COMPLETED` with
Jordan-Hare Stadium as the verified destination, a Mapbox route from Lynn
Haven, four public card categories (lodging, meals, entertainment, fuel), and
a clear read-only calendar result. Visible citations contained the public
event source and Mapbox only; the generic Google Calendar URL is intentionally
removed from the travel response. The map model retains the full verified
address for routing while spoken output uses the concise venue-and-city form.

### Active same-chat target recovery — 2026-08-20

The owner-approved retention policy has two separate scopes:

- **Thirty-day durable strategy learning:** aggregated, tool-selection-only
  outcomes. It contains no user prompts, answers, citations, source text, or
  cached retrieval results.
- **One-hour short-term conversation context:** at most ten completed turns,
  scoped to one Biggy chat and held only in the Biggy process. It is not
  persistent storage.

Biggy already supplied that short-term window to PA ingress, but the live
120B planner had been bypassing it. The planner now receives the bounded
window explicitly. For a recognizable same-chat follow-up it may recover only
the prior engineering target and pass that target to a new RAG request. The
prompt and workflow both prohibit context from supplying facts, manual titles,
pages, citations, or results; fresh tool invocation and fresh verification are
mandatory.

**Controlled acceptance:** a previous 1756-IB32 wiring request followed by
“Yes, dig deeper and pull the wiring figure” produced a new `rag_core` call,
recorded `short_term_context: target_recovered`, and returned freshly verified
1756-UM058 evidence on PDF page 102. No prior answer or citation was replayed.
