# Jarvis II Generic RAG Core VNext — Build Record

**Date:** 2026-08-19  
**Status:** service and authenticated n8n contract accepted; PA Core integration accepted; no GUI cutover
**Production boundary:** Smedley’s active document path remains unchanged.

## Purpose

VNext replaces the index-first, resolver-dependent evidence path with a generic
retrieval contract. It contains no vendor-specific manual binding or part-to-page
map. Each wiring request follows the same sequence:

1. Extract catalog-shaped terms from the request.
2. Perform an exact catalog-term read against the corpus index.
3. Exclude indexes from candidate answers.
4. Read candidate manual PDFs and require part-specific diagram evidence on a
   real PDF page.
5. Return the strongest verified page, or `NO_VERIFIED_EVIDENCE`.

The response is evidence-only. It does not invoke a model, alter the corpus,
write memory, or modify tools/credentials.

## Components

| Component | State | Role |
| --- | --- | --- |
| `api/jarvis_ii_generic_retrieval.py` | Tested | Generic catalog retrieval, source classification, PDF verification |
| `scripts/jarvis_ii_rag_core_service.py` | Running locally | Loopback-only read-only service on `127.0.0.1:5014` |
| `Jarvis II — Generic RAG Core VNext` | Active | Authenticated n8n evidence endpoint `qKn2WOJLhNGhZAdA`, 7 nodes; it is a read-only tool service, not a GUI route |
| Existing Smedley RAG service | Unchanged | Current production path on port 5004 |
| `Jarvis II — Generic RAG Core VNext Authenticated Acceptance Driver` | Inactive | n8n test driver `LmRewqh8RHa5PKqm`, used because inactive webhook workflows cannot be invoked by the n8n CLI |
| `Jarvis II — Generic RAG Core VNext No-Evidence Acceptance Driver` | Inactive | n8n test driver `zAuZFnLHvjgGVxr1`, validates the authenticated fail-closed response contract |

## Acceptance baseline

| Request | Result | Evidence outcome |
| --- | --- | --- |
| `1756-IA16` wiring schematic | Pass | `1756-UM058`, PDF page 97 |
| `1756-IB32` wiring schematic | Pass | `1756-UM058`, PDF page 102 |
| Honeywell Edge `900A16-0103` schematic | Pass | Hardware Planning and Installation Guide, PDF page 159; the PDF identifies the `900A16` family heading and contains the High Level Analog Input wiring diagram |

The initial Edge pass safely rejected broad specifications pages. The final pass
used the request's exact configuration plus a generic derived family token,
inspected the retrieved source PDF once, and verified the page from its OCR
evidence. No Honeywell-specific source or page mapping was added.

The same live loopback service was rechecked during the inactive wrapper
acceptance pass: `900A16-0103` resolved through generic family evidence
(`matched_catalog_term: 900A16`) to the Honeywell ControlEdge 900 Hardware
Planning and Installation Guide, PDF page 159.

## Inactive n8n acceptance — 2026-08-19

The VNext wrapper itself remains inactive and its Webhook trigger cannot be
executed through `n8n execute --id`: that CLI accepts only workflows whose entry
node is an **Execute Workflow Trigger**. This is an n8n execution limitation,
not an authentication failure. Activating the wrapper merely to test it was not
acceptable.

An inactive, seven-node authenticated driver was therefore imported. It uses a
short-lived runtime read of `GPT_BIGGY_PROPOSE_TOKEN` (not exported or written
to source) and executes byte-for-byte copies of VNext's validation, retrieval,
and rendering logic against the loopback VNext service. Its first acceptance
fixture passed:

| Check | Result |
| --- | --- |
| Authenticated request validation | Pass |
| `1756-IB32` verified result | Pass — `COMPLETED` |
| Natural spoken text | Pass — “I found verified wiring evidence … PDF page 102.” |
| Citation URL | Pass — `1756-um058_-en-p.pdf#page=102` |
| n8n response envelope | Pass — exactly one output item; all spoken-text aliases match |

A separate authenticated negative driver was also imported and executed. Its
nonexistent `9999-ZZ99` request passed the required fail-closed contract:

| Check | Result |
| --- | --- |
| Authenticated request validation | Pass |
| Result status | Pass — `NO_VERIFIED_EVIDENCE` |
| Natural spoken text | Pass — concise verified-evidence failure wording |
| Citations and evidence object | Pass — zero citations and `rag_evidence: null` |
| n8n response envelope | Pass — exactly one output item; all spoken-text aliases match |

Focused regression tests also pass: `6 passed` for
`test_jarvis_ii_generic_retrieval.py` and
`test_jarvis_ii_rag_core_service.py`.

This verifies the inactive n8n processing contract. It does **not** prove GUI
rendering or TTS behavior; neither GUI adapter has been pointed at VNext, so a
duplicate-message/TTS acceptance test belongs to the owner-approved cutover
fixture.

## Durable-memory design boundary

After owner approval of retention and write authority, the decision agent may
persist a **retrieval outcome record**: request shape, tool/query strategy,
source fingerprint, page-verification result, confidence, and timestamp. Future
requests can use successful records as ranked tool-selection hints and failed
records as negative evidence. Every request must still perform fresh corpus and
PDF verification; memory must never return a stored answer or bypass retrieval.

## PA Core integration — 2026-08-20

VNext is now the backend for the existing inactive PA Core RAG tool. The path is
`Jarvis II PA Core POC → Jarvis II RAG Delegation Tool POC → Generic RAG Core VNext`.
No GUI adapter points to that path yet, and no GUI cutover is claimed.

The separate inactive `Jarvis II — RAG Delegation VNext Acceptance` fixture
executed the exact PA delegation workflow with an Allen-Bradley `1756-IB32`
request. It returned the normalized `jarvis.rag_delegation.v2` contract,
natural spoken text, and the verified `1756-UM058` PDF page 102 citation.
The PA Core, delegation tool, and acceptance fixture all remain inactive.

A cross-vendor false positive was discovered during this fixture: an
Allen-Bradley `1756-OW16I` request could rank a Honeywell manual that mentioned
the part number. The generic resolver now derives vendor cues from the current
candidate corpus folders and, only when the request explicitly names a vendor,
keeps candidates from that vendor. No vendor/manual/page mapping was added.
The repaired direct service and live n8n contract both return:

| Request | Result |
| --- | --- |
| Allen-Bradley `1756-OW16I` wiring schematic | `1756-UM058`, PDF page 119 |

Biggy’s old Smedley-sidecar document URL was not usable in Biggy’s separate
authenticated session. VNext now provides a narrow same-GUI endpoint,
`/api/jarvis-ii/rag-document/...`, which serves only PDF paths contained beneath
the configured library root and `Vendor Data/`. This route does not proxy port
5004 and serves documents inline with the current GUI session.

GUI rendering, one-response behavior, TTS, and link click-through remain
cutover acceptance work. They have not been used as evidence that PA Core is
ready for activation.

## Smedley shared-core cutover — 2026-08-20

Smedley's engineering-document adapter now sends manual, datasheet, and
wiring/schematic requests to the same active Generic RAG Core VNext wrapper
used by Biggy. The previous Smedley legacy ranker remains only for document
requests outside this verified engineering-evidence contract.

The adapter distinguishes the verified result type at render time: a verified
manual has an **Open manual** citation without inventing a PDF page number; a
verified wiring result keeps its **Open wiring page** citation. Both paths use
the original request, fresh VNext corpus/PDF verification, and one natural
spoken reply. `NO_VERIFIED_EVIDENCE` still fails closed with no citation.

Focused adapter tests passed for wiring evidence, manual evidence, and the
no-evidence contract. The Smedley web adapter was reloaded without restarting
the Smedley RAG service or n8n. The exact TDC3000 request then completed through
the protected live authentication contract with `pm20520.pdf`, one natural
spoken reply, and the Smedley-session URL
`/api/jarvis-ii/rag-document/Vendor%20Data/Honeywell/Experian%20PKS/TDC3000/pm20520.pdf`.

The full legacy document-route suite currently has one unrelated fixture
failure (`test_index_only_document_route_clears_manual_binding`); its mocked
index-only input resolved a real `1756-UM058` manual rather than the fixture's
expected index-only reply. The three VNext contract tests pass, and the live
PM20-520 acceptance above is the evidence for this cutover.

## Shared resolver regression repair — 2026-08-20

Two production regressions were repaired without adding vendor/document/page
mappings. First, an absolute loopback citation returned by a wrapper is now
reduced to its safe route and rebound to Smedley's configured public origin;
the UI can no longer emit a `127.0.0.1` document link. Second, vendor aliases
are derived from each current corpus vendor-folder label. A folder named
`Allen Bradley` therefore supplies the request alias `AB`, so an `AB
1756-OW16I` request excludes coincidental Honeywell matches before PDF-page
verification.

Focused regression coverage passed (`14 passed`). Protected live acceptance
confirmed Honeywell Edge `900A16-0103` at PDF page 159 and `AB 1756-OW16I` in
Allen-Bradley `1756-UM058` at PDF page 119.

### Public citation-origin correction — 2026-08-20

The service definitions had retained an obsolete public Smedley origin with
the local WebUI listener port appended (`:8787`). That produced broken
browser-facing citations despite correct retrieval evidence. Both the
formatter and the two relevant LaunchAgent settings now normalize the Smedley
public origin to `https://smedley.tail061f03.ts.net` (HTTPS default port only).
The VNext citation route was verified reachable at that public origin with
HTTP 200 for a `1756-UM058` PDF. Focused formatter coverage passed for both a
ported Tailnet origin and an absolute loopback citation, proving neither form
can be emitted to the user.
