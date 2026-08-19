# Jarvis II RAG Core — Build Record

**Date:** 2026-08-19
**Status:** operational for governed engineering-document retrieval
**Scope:** Smedley / Jarvis engineering RAG only

## Delivered production path

Jarvis II now has a small, dedicated RAG path for engineering-document questions.  It is separate from the legacy personal-assistant workflow and returns both a detailed on-screen answer and a short, natural spoken handoff.

| Component | Production role |
| --- | --- |
| n8n workflow | `Jarvis II — Production RAG Core` (`JarvisIIProdRAG001`), active |
| n8n ingress | `POST /webhook/jarvis-ii` on the Jarvis n8n service |
| Smedley resolver | `POST /api/jarvis-ii/document-resolve` on port 8787, bearer-token protected |
| Biggy bridge | Routes engineering-document questions to Jarvis II; travel and calendar requests remain on the legacy route temporarily |
| Web UI | Displays Jarvis identity and preserves a concise `spoken_reply` for the Jarvis voice profile |

The resolver is read-only: it locates a supported document, extracts relevant evidence, and returns citations and a page-qualified document link. It does not invoke tools that modify external systems.

## Response contract

Each supported engineering response supplies:

- a full, evidence-grounded answer for the screen;
- `spoken_reply` / `spoken_text` suitable for natural voice delivery;
- Jarvis response metadata and the James Michael Jarvis voice profile;
- citations, document identity, and a page-qualified link; and
- the public Smedley origin when a request is served locally.

The public origin is configured as `https://smedley.tail061f03.ts.net`, preventing generated document links from intentionally targeting `localhost` for remote use.

## Verified retrieval fixtures

| Request | Bound source | Verified PDF page | Supporting pages |
| --- | --- | ---: | --- |
| Allen-Bradley 1756-IB32 wiring schematic | `1756-UM058` | 102 | 101, 103 |
| Allen-Bradley 1756-IA16 wiring schematic | `1756-UM058` | 97 | 96, 98 |
| Allen-Bradley 1756-OW16I wiring schematic | `1756-UM058` | 119 | 117, 118 |
| Honeywell Process Manager I/O Installation Manual | `PM20-520` | Document resolution verified | Page selection remains request-specific |

The `1756-IA16` mapping was explicitly corrected from an IFM selection-table page to the wiring-diagram page.

## Validation completed

- Direct Jarvis II n8n ingress returned a grounded 1756-IB32 result with the correct page and a concise speaking sentence.
- The authenticated resolver returned the 1756-IA16 schematic on PDF page 97.
- A remote Smedley voice request for 1756-OW16I returned the correct manual, page 119, associated wiring context, and a Jarvis handoff.
- Document links are stored with the Tailscale public origin by the server.

## Explicit boundaries and known follow-up work

- The legacy active `Jarvis PA` workflow (`qEvgreDPwJLZcdCm`) remains only as a temporary fallback for calendar, weather, maps, and lodging. It is not the engineering RAG path.
- Weather, maps, lodging, and calendar are **not** part of the new RAG core and require a clean, verified Biggy travel/PA replacement. No invented hotel availability, rates, or scheduling status may be displayed.
- Some remote clients have displayed a stale `localhost:8787` document URL even though the stored server response contains the public Tailscale URL. Treat that as a frontend presentation issue if it recurs; do not change the evidence resolver mapping to work around it.
- Electrical calculator/tool remediation is separate from document retrieval and remains open.

## Rollback and safety

The RAG workflow and resolver are isolated from the legacy PA chain. If the new ingress must be bypassed, the Biggy bridge can route engineering requests back to the legacy behavior without deleting workflows or altering the document corpus. No credentials or sensitive values are recorded in this document.
