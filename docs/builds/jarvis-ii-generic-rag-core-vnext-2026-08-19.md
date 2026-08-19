# Jarvis II Generic RAG Core VNext — Build Record

**Date:** 2026-08-19  
**Status:** separate service and inactive n8n wrapper validated; no GUI cutover  
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
| `Jarvis II — Generic RAG Core VNext` | Inactive | n8n wrapper `qKn2WOJLhNGhZAdA`, 7 nodes |
| Existing Smedley RAG service | Unchanged | Current production path on port 5004 |

## Acceptance baseline

| Request | Result | Evidence outcome |
| --- | --- | --- |
| `1756-IA16` wiring schematic | Pass | `1756-UM058`, PDF page 97 |
| `1756-IB32` wiring schematic | Pass | `1756-UM058`, PDF page 102 |
| Honeywell Edge `900A16-0103` schematic | Safe fail | `NO_VERIFIED_EVIDENCE`; generic core rejected broad specifications pages rather than inventing a schematic page |

The Edge safe-fail is intentional. It is evidence that VNext will not make the
same error as the legacy path. The actual schematic source/page must be found by
retrieval and verified from its PDF before Edge can be marked accepted.

## Durable-memory design boundary

After owner approval of retention and write authority, the decision agent may
persist a **retrieval outcome record**: request shape, tool/query strategy,
source fingerprint, page-verification result, confidence, and timestamp. Future
requests can use successful records as ranked tool-selection hints and failed
records as negative evidence. Every request must still perform fresh corpus and
PDF verification; memory must never return a stored answer or bypass retrieval.

## Cutover gate

No Smedley or Biggy GUI route points to VNext. Cutover requires:

1. A verified Edge `900A16-0103` schematic fixture.
2. Broader multi-vendor acceptance fixtures.
3. A direct n8n wrapper execution test with the production authentication
   contract.
4. Owner approval of the GUI adapter change.
